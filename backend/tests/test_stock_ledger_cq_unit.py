import asyncio
import os
import sys
from copy import deepcopy
from itertools import count
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import cq_routes
import orders_routes
from stock_ledger import (
    baixar_saldo_lote_expedicao,
    consumir_reserva_saldo_lote,
    estornar_consumo_saldo_lote,
    estornar_saida_expedicao,
    liberar_reserva_saldo_lote,
    reservar_saldo_lote,
    saldo_quantidade_disponivel,
)


class FakeCursor:
    def __init__(self, docs):
        self.docs = [deepcopy(doc) for doc in docs]

    def sort(self, *_args):
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [deepcopy(doc) for doc in (docs or [])]

    @staticmethod
    def _get(doc, path):
        value = doc
        for part in path.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    @staticmethod
    def _set(doc, path, value):
        target = doc
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    def _matches(self, doc, query):
        for key, expected in query.items():
            if key == "$expr":
                # Expressoes usadas pelo ledger: disponivel >= qtd ou reservado >= qtd.
                comparisons = expected.get("$and") or [expected]
                for comparison in comparisons:
                    threshold = float(comparison["$gte"][1])
                    left = comparison["$gte"][0]
                    if "$subtract" in left:
                        actual = float(doc.get("quantidade", doc.get("quantidade_atual", 0)) or 0) - float(doc.get("quantidade_reservada", 0) or 0)
                    elif isinstance(left, dict) and left.get("$ifNull", [None])[0] == "$quantidade_reservada":
                        actual = float(doc.get("quantidade_reservada", 0) or 0)
                    else:
                        actual = float(doc.get("quantidade", doc.get("quantidade_atual", 0)) or 0)
                    if actual < threshold:
                        return False
                continue
            current = self._get(doc, key)
            if isinstance(expected, dict) and "$ne" in expected:
                if current == expected["$ne"]:
                    return False
            elif isinstance(expected, dict) and "$gte" in expected:
                if current is None or current < expected["$gte"]:
                    return False
            elif isinstance(expected, dict) and "$in" in expected:
                if current not in expected["$in"]:
                    return False
            elif current != expected:
                return False
        return True

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                result = deepcopy(doc)
                result.pop("_id", None)
                return result
        return None

    def find(self, query, projection=None):
        return FakeCursor([doc for doc in self.docs if self._matches(doc, query)])

    async def insert_one(self, doc):
        self.docs.append(deepcopy(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    def _apply(self, doc, update):
        for key, value in update.get("$set", {}).items():
            self._set(doc, key, value)
        for key, value in update.get("$inc", {}).items():
            self._set(doc, key, float(self._get(doc, key) or 0) + float(value))

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def update_many(self, query, update):
        count_updated = 0
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, update)
                count_updated += 1
        return SimpleNamespace(matched_count=count_updated, modified_count=count_updated)

    async def find_one_and_update(self, query, update, **_kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, update)
                return deepcopy(doc)
        return None


def _id_factory():
    values = count(1)
    return lambda: f"event-{next(values)}"


def _user():
    return {"id": "u-1", "name": "PCP", "tenant_id": "t-1"}


def test_reserva_atomica_reduz_disponivel_e_impede_sobre_reserva():
    db = SimpleNamespace(
        estoque_saldos_lote=FakeCollection([{
            "id": "saldo-1", "tenant_id": "t-1", "item_id": "item-1",
            "lote": "L1", "quantidade": 100.0, "quantidade_reservada": 0.0,
        }]),
        estoque_movimentos_lote=FakeCollection([]),
    )
    new_id = _id_factory()
    now = lambda: "2026-09-22T10:00:00-03:00"

    asyncio.run(reservar_saldo_lote(
        db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1",
        saldo_lote_id="saldo-1", quantidade=70, op_id="op-1",
        wms_separacao_id="sep-1", usuario=_user(), material_key="mp-1",
    ))

    saldo = db.estoque_saldos_lote.docs[0]
    assert saldo["quantidade"] == 100.0
    assert saldo["quantidade_reservada"] == 70.0
    assert saldo_quantidade_disponivel(saldo) == 30.0
    assert db.estoque_movimentos_lote.docs[0]["evento"] == "RESERVA_CRIADA"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(reservar_saldo_lote(
            db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1",
            saldo_lote_id="saldo-1", quantidade=31, op_id="op-2",
            wms_separacao_id="sep-2", usuario=_user(), material_key="mp-1",
        ))
    assert exc.value.status_code == 409
    assert saldo["quantidade_reservada"] == 70.0

    asyncio.run(liberar_reserva_saldo_lote(
        db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1",
        saldo_lote_id="saldo-1", quantidade=70, op_id="op-1",
        wms_separacao_id="sep-1", usuario=_user(), motivo="OP cancelada", material_key="mp-1",
    ))
    assert saldo["quantidade_reservada"] == 0.0
    assert saldo["reserva_status"] == "livre"
    assert [event["evento"] for event in db.estoque_movimentos_lote.docs] == ["RESERVA_CRIADA", "RESERVA_LIBERADA"]


def test_decisao_cq_propaga_para_saldo_palete_e_ledger():
    cq_routes.db = SimpleNamespace(
        estoque_saldos_lote=FakeCollection([{
            "id": "saldo-1", "tenant_id": "t-1", "item_id": "item-1",
            "lote": "L1", "quantidade": 20, "status": "quarentena", "posicao_cq": "quarentena",
        }]),
        wms_paletes=FakeCollection([{
            "id": "pal-1", "tenant_id": "t-1", "estoque_item_id": "item-1",
            "status": "quarentena", "capa_palete": {"status_cq": "quarentena"},
        }]),
        estoque_movimentos_lote=FakeCollection([]),
    )
    cq_routes.new_id_func = _id_factory()
    cq_routes.now_iso_func = lambda: "2026-09-22T10:00:00-03:00"
    ra = {"id": "ra-1", "numero_ra": "RA-1", "item_id": "item-1", "lote_id": "lote-1"}

    asyncio.run(cq_routes._propagar_decisao_cq_wms(
        ra, "aprovado", "aprovado", _user(), "2026-09-22T10:00:00-03:00"
    ))

    saldo = cq_routes.db.estoque_saldos_lote.docs[0]
    palete = cq_routes.db.wms_paletes.docs[0]
    assert saldo["status"] == "disponivel"
    assert saldo["posicao_cq"] == "aprovado"
    assert saldo["cq_ra_id"] == "ra-1"
    assert palete["status"] == "aprovado"
    assert palete["capa_palete"]["status_cq"] == "aprovado"
    assert cq_routes.db.estoque_movimentos_lote.docs[0]["evento"] == "CQ_STATUS_ALTERADO"


def test_consumo_converte_empenho_em_baixa_fisica_e_permite_estorno():
    db = SimpleNamespace(
        estoque_saldos_lote=FakeCollection([{
            "id": "saldo-1", "tenant_id": "t-1", "item_id": "item-1", "lote": "L1",
            "quantidade": 100.0, "quantidade_atual": 100.0, "quantidade_reservada": 60.0,
            "status": "disponivel", "reserva_status": "reservado",
        }]),
        estoque_items=FakeCollection([{
            "id": "item-1", "tenant_id": "t-1", "quantidade_atual": 100.0,
        }]),
        estoque_movimentos_lote=FakeCollection([]),
    )
    new_id = _id_factory()
    now = lambda: "2026-09-22T11:00:00-03:00"

    asyncio.run(consumir_reserva_saldo_lote(
        db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1", saldo_lote_id="saldo-1",
        quantidade=25, op_id="op-1", wms_separacao_id="sep-1", apontamento_id="ap-1",
        usuario=_user(), material_key="mp-1", op_item_idx=0,
    ))
    saldo = db.estoque_saldos_lote.docs[0]
    assert saldo["quantidade"] == 75.0
    assert saldo["quantidade_atual"] == 75.0
    assert saldo["quantidade_reservada"] == 35.0
    assert db.estoque_items.docs[0]["quantidade_atual"] == 75.0
    assert db.estoque_movimentos_lote.docs[0]["evento"] == "CONSUMO_OP"

    asyncio.run(estornar_consumo_saldo_lote(
        db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1", saldo_lote_id="saldo-1",
        quantidade=25, op_id="op-1", wms_separacao_id="sep-1", apontamento_id="ap-1",
        usuario=_user(), motivo="Falha ao gravar apontamento", material_key="mp-1", op_item_idx=0,
    ))
    assert saldo["quantidade"] == 100.0
    assert saldo["quantidade_reservada"] == 60.0
    assert db.estoque_items.docs[0]["quantidade_atual"] == 100.0
    assert db.estoque_movimentos_lote.docs[-1]["evento"] == "ESTORNO_CONSUMO_OP"


def test_apontamento_planeja_consumo_proporcional_e_libera_sobra_da_op():
    op = {
        "id": "op-1", "tenant_id": "t-1",
        "items": [{"item": "Produto", "sku_id": "sku-1", "qtd_planejada": 100, "qtd_produzida": 0}],
    }
    orders_routes.db = SimpleNamespace(
        skus=FakeCollection([{"id": "sku-1", "tenant_id": "t-1", "codigo_interno": "SKU-1", "apresentacao": {"qtd_envase": 1}}]),
        bom_items=FakeCollection([{
            "id": "bom-1", "tenant_id": "t-1", "sku_id": "sku-1", "camada": "embalagem",
            "material_id": "mp-1", "nome_material": "Frasco", "quantidade_por_unidade": 2, "vigente": True,
        }]),
        wms_separacoes=FakeCollection([{
            "id": "sep-1", "tenant_id": "t-1", "op_id": "op-1", "reserva_aplicada": True,
            "reserva_liberada": False,
            "linhas": [{"saldo_lote_id": "saldo-1", "material_key": "mp-1", "quantidade": 200, "lote": "L1"}],
        }]),
        estoque_saldos_lote=FakeCollection([{
            "id": "saldo-1", "tenant_id": "t-1", "item_id": "item-1", "lote": "L1",
            "quantidade": 200.0, "quantidade_atual": 200.0, "quantidade_reservada": 200.0,
            "status": "disponivel", "reserva_status": "reservado",
        }]),
        estoque_items=FakeCollection([{"id": "item-1", "tenant_id": "t-1", "quantidade_atual": 200.0}]),
        estoque_movimentos_lote=FakeCollection([]),
    )
    orders_routes.new_id_func = _id_factory()
    orders_routes.now_iso_func = lambda: "2026-09-22T12:00:00-03:00"

    plan = asyncio.run(orders_routes._prepare_apontamento_consumption_plan(op, 0, 25, _user()))
    assert plan == [{
        "saldo_lote_id": "saldo-1", "wms_separacao_id": "sep-1", "material_key": "mp-1",
        "quantidade": 50.0, "lote": "L1",
    }]
    asyncio.run(orders_routes._consume_apontamento_plan(op, 0, "ap-1", plan, _user()))
    saldo = orders_routes.db.estoque_saldos_lote.docs[0]
    assert saldo["quantidade"] == 150.0
    assert saldo["quantidade_reservada"] == 150.0

    released = asyncio.run(orders_routes._release_op_picking_reservations(op, _user(), "OP concluida"))
    assert released == 1
    assert saldo["quantidade"] == 150.0
    assert saldo["quantidade_reservada"] == 0.0
    assert orders_routes.db.wms_separacoes.docs[0]["reserva_liberada"] is True


def test_expedicao_baixa_lote_exato_sem_duplicar_e_permite_compensacao():
    db = SimpleNamespace(
        estoque_saldos_lote=FakeCollection([{
            "id": "saldo-pa-1", "tenant_id": "t-1", "item_id": "pa-1", "lote": "PA-001",
            "quantidade": 80.0, "quantidade_atual": 80.0, "quantidade_reservada": 0.0,
            "status": "disponivel", "posicao_cq": "aprovado",
        }]),
        estoque_items=FakeCollection([{
            "id": "pa-1", "tenant_id": "t-1", "quantidade_atual": 80.0,
        }]),
        estoque_movimentos_lote=FakeCollection([]),
    )
    new_id = _id_factory()
    now = lambda: "2026-09-22T13:00:00-03:00"
    args = dict(
        database=db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1",
        saldo_lote_id="saldo-pa-1", quantidade=30, expedicao_id="exp-1",
        item_index=0, idempotency_key="dispatch-unique-1", usuario=_user(),
    )

    first = asyncio.run(baixar_saldo_lote_expedicao(**args))
    replay = asyncio.run(baixar_saldo_lote_expedicao(**args))
    assert first["id"] == replay["id"]
    assert db.estoque_saldos_lote.docs[0]["quantidade"] == 50.0
    assert db.estoque_items.docs[0]["quantidade_atual"] == 50.0
    assert [e["evento"] for e in db.estoque_movimentos_lote.docs] == ["SAIDA_EXPEDICAO"]

    asyncio.run(estornar_saida_expedicao(
        db, new_id_fn=new_id, now_iso_fn=now, tenant_id="t-1", saldo_lote_id="saldo-pa-1",
        quantidade=30, expedicao_id="exp-1", item_index=0, idempotency_key="dispatch-unique-1",
        usuario=_user(), motivo="Falha posterior no despacho",
    ))
    assert db.estoque_saldos_lote.docs[0]["quantidade"] == 80.0
    assert db.estoque_items.docs[0]["quantidade_atual"] == 80.0
    assert db.estoque_movimentos_lote.docs[-1]["evento"] == "ESTORNO_SAIDA_EXPEDICAO"
