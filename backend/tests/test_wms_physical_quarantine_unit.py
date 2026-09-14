import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import estoque_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, key, direction):
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None, sort=None):
        docs = [doc for doc in self.docs if self._matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        if not docs:
            return None
        return self._project(docs[0], projection)

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update, upsert=False):
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs[idx] = self._apply_update(doc, update)
                return SimpleNamespace(modified_count=1)
        if upsert:
            doc = dict(query)
            doc = self._apply_update(doc, update)
            self.docs.append(doc)
            return SimpleNamespace(modified_count=1, upserted_id=doc.get("id"))
        return SimpleNamespace(modified_count=0)

    def _matches(self, doc, query):
        for key, expected in query.items():
            value = self._get(doc, key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                continue
            if value != expected:
                return False
        return True

    def _get(self, doc, key):
        cur = doc
        for part in key.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _set(self, doc, key, value):
        cur = doc
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {k: v for k, v in doc.items() if k != "_id"}
        return dict(doc)

    def _apply_update(self, doc, update):
        doc = dict(doc)
        for key, value in update.get("$set", {}).items():
            self._set(doc, key, value)
        for key, value in update.get("$push", {}).items():
            arr = self._get(doc, key)
            if arr is None:
                self._set(doc, key, [])
                arr = self._get(doc, key)
            arr.append(value)
        return doc


def _install_db(feature_enabled=True):
    seq = {"n": 0}

    def new_id():
        seq["n"] += 1
        return f"id-{seq['n']}"

    async def fake_user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}

    estoque_routes._new_id = new_id
    estoque_routes._now_iso = lambda: "2026-09-14T10:00:00+00:00"
    estoque_routes._get_current_user = fake_user
    estoque_routes.db = SimpleNamespace(
        tenant_settings=FakeCollection([
            {"tenant_id": "t1", "features": {"wms_physical_quarantine_v2": feature_enabled}}
        ]),
        wms_enderecos=FakeCollection([
            {
                "id": "end-a",
                "tenant_id": "t1",
                "codigo": "P01-A-01-01",
                "setor": "LOGISTICA",
                "status": "ocupado",
            },
            {
                "id": "end-q",
                "tenant_id": "t1",
                "codigo": "QAR-Q-01-01",
                "setor": "DEVOLUCAO",
                "status": "livre",
                "physical_quarantine_enabled": True,
            },
        ]),
        estoque_items=FakeCollection([
            {
                "id": "item-1",
                "tenant_id": "t1",
                "tipo_item": "mp",
                "setor": "LOGISTICA",
                "nome": "Frasco 200ml",
                "codigo": "FR200",
                "quantidade_atual": 100,
                "unidade": "un",
                "posicao_cq": "quarentena",
                "cq_status": "quarentena",
            }
        ]),
        estoque_saldos_lote=FakeCollection([
            {
                "id": "saldo-1",
                "tenant_id": "t1",
                "item_id": "item-1",
                "item_nome": "Frasco 200ml",
                "codigo_item": "FR200",
                "tipo_item": "mp",
                "lote": "L-001",
                "endereco_id": "end-a",
                "endereco_codigo": "P01-A-01-01",
                "setor": "LOGISTICA",
                "quantidade": 100,
                "quantidade_atual": 100,
                "unidade": "un",
                "posicao_cq": "quarentena",
                "status": "quarentena",
            }
        ]),
        estoque_movimentos_lote=FakeCollection([]),
        wms_quarantine_movements=FakeCollection([]),
        cq_status_lote=FakeCollection([]),
    )


def _missing_route_contract():
    required = [
        "obter_wms_quarentena_policy",
        "atualizar_wms_quarentena_policy",
        "movimentar_wms_quarentena",
    ]
    missing = [name for name in required if not hasattr(estoque_routes, name)]
    if missing:
        pytest.xfail(f"wms_physical_quarantine_v2 ainda sem contrato funcional: {', '.join(missing)}")


def test_current_wms_transfer_still_blocks_logical_cq_quarantine():
    _install_db()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(estoque_routes.transferir_lote_endereco(
            estoque_routes.TransferenciaLoteCreate(
                item_id="item-1",
                lote="L-001",
                endereco_origem_id="end-a",
                endereco_destino_id="end-q",
                quantidade=10,
                motivo="Movimento fisico para quarentena",
            ),
            request=SimpleNamespace(),
        ))

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "hard_stop_estoque_sem_liberacao_cq"
    assert estoque_routes.db.estoque_saldos_lote.docs[0]["quantidade"] == 100
    assert estoque_routes.db.estoque_movimentos_lote.docs == []


def test_physical_quarantine_partial_helpers_keep_delta_shape():
    required = [
        "WMS_PHYSICAL_QUARANTINE_FLAG",
        "WMSQuarantinePolicyUpdate",
        "WMSQuarantineMoveCreate",
        "_quarantine_saldo_patch",
    ]
    missing = [name for name in required if not hasattr(estoque_routes, name)]
    if missing:
        pytest.xfail(f"helpers parciais de wms_physical_quarantine_v2 ainda ausentes: {', '.join(missing)}")

    assert estoque_routes.WMS_PHYSICAL_QUARANTINE_FLAG == "wms_physical_quarantine_v2"

    patch = estoque_routes._quarantine_saldo_patch(
        True,
        {"policy_version": 2},
        {"id": "end-q", "codigo": "QAR-Q-01-01"},
        "2026-09-14T10:00:00+00:00",
        "mov-1",
    )

    assert patch["wms_quarantine_physical"] is True
    assert patch["wms_quarantine_status"] == "em_quarentena"
    assert patch["wms_quarantine_address_id"] == "end-q"
    assert "posicao_cq" not in patch
    assert "cq_status" not in patch


def test_physical_quarantine_feature_flag_blocks_new_route_contract_when_disabled():
    _install_db(feature_enabled=False)
    _missing_route_contract()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(estoque_routes.obter_wms_quarentena_policy(request=SimpleNamespace()))

    assert exc.value.status_code == 403
    assert exc.value.detail["feature"] == "wms_physical_quarantine_v2"


def test_physical_quarantine_configures_area_and_address():
    _install_db()
    _missing_route_contract()

    config = asyncio.run(estoque_routes.atualizar_wms_quarentena_policy(
        estoque_routes.WMSQuarantinePolicyUpdate(
            endereco_id="end-q",
            motivo="Endereco padrao para material aguardando CQ",
        ),
        request=SimpleNamespace(),
    ))

    assert config["policy"]["endereco_id"] == "end-q"
    assert config["policy"]["endereco_codigo"] == "QAR-Q-01-01"
    assert config["policy"]["policy_version"] >= 1
    assert config["endereco"]["wms_role"] == "quarentena_fisica"


def test_physical_quarantine_moves_stock_without_changing_logical_cq_status():
    _install_db()
    _missing_route_contract()

    asyncio.run(estoque_routes.atualizar_wms_quarentena_policy(
        estoque_routes.WMSQuarantinePolicyUpdate(
            endereco_id="end-q",
            motivo="Endereco padrao para material aguardando CQ",
        ),
        request=SimpleNamespace(),
    ))
    moved = asyncio.run(estoque_routes.movimentar_wms_quarentena(
        estoque_routes.WMSQuarantineMoveCreate(
            saldo_lote_id="saldo-1",
            direcao="entrada",
            quantidade=40,
            motivo="Recebimento aguardando analise CQ",
            idempotency_key="q-in-L-001",
        ),
        request=SimpleNamespace(),
    ))
    replay = asyncio.run(estoque_routes.movimentar_wms_quarentena(
        estoque_routes.WMSQuarantineMoveCreate(
            saldo_lote_id="saldo-1",
            direcao="entrada",
            quantidade=40,
            motivo="Recebimento aguardando analise CQ",
            idempotency_key="q-in-L-001",
        ),
        request=SimpleNamespace(),
    ))

    assert replay["movement"]["id"] == moved["movement"]["id"]
    assert replay["idempotent"] is True
    assert moved["movement"]["direcao"] == "entrada"
    assert moved["movement"]["origem"]["endereco_id"] == "end-a"
    assert moved["movement"]["destino"]["endereco_id"] == "end-q"
    assert moved["destino"]["wms_quarantine_physical"] is True
    assert moved["destino"]["posicao_cq"] == "quarentena"
    assert moved["movement"]["cq_logico"] == "quarentena"
    assert moved["destino"]["status"] != "quarentena"
    assert len(estoque_routes.db.wms_quarantine_movements.docs) == 2


def test_physical_quarantine_exit_is_audited_and_does_not_release_cq():
    _install_db()
    _missing_route_contract()

    asyncio.run(estoque_routes.atualizar_wms_quarentena_policy(
        estoque_routes.WMSQuarantinePolicyUpdate(
            endereco_id="end-q",
            motivo="Endereco padrao para material aguardando CQ",
        ),
        request=SimpleNamespace(),
    ))
    estoque_routes.db.estoque_saldos_lote.docs[0].update({
        "endereco_id": "end-q",
        "endereco_codigo": "QAR-Q-01-01",
        "wms_quarantine_physical": True,
        "wms_quarantine_status": "em_quarentena",
    })
    moved = asyncio.run(estoque_routes.movimentar_wms_quarentena(
        estoque_routes.WMSQuarantineMoveCreate(
            saldo_lote_id="saldo-1",
            direcao="saida",
            endereco_destino_id="end-a",
            quantidade=25,
            motivo="Mover para area de inspecao mantendo bloqueio CQ",
            idempotency_key="q-out-L-001",
        ),
        request=SimpleNamespace(),
    ))

    assert moved["movement"]["direcao"] == "saida"
    assert moved["origem"]["wms_quarantine_physical"] is True
    assert moved["destino"]["wms_quarantine_physical"] is False
    assert moved["destino"]["posicao_cq"] == "quarentena"
    assert moved["movement"]["cq_logico"] == "quarentena"
    assert moved["movement"]["id"]

    with pytest.raises(HTTPException):
        asyncio.run(estoque_routes._assert_saida_liberada_por_cq(
            estoque_routes.db.estoque_items.docs[0],
            "SAIDA_CONSUMO_OP",
        ))
