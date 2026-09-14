import asyncio
import os
import sys
from itertools import count
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import expedicao_routes
import orders_routes


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
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def count_documents(self, query):
        return len([doc for doc in self.docs if self._matches(doc, query)])

    def _matches(self, doc, query):
        for key, expected in query.items():
            value = self._get(doc, key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                if "$nin" in expected and value in expected["$nin"]:
                    return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                continue
            if value != expected:
                return False
        return True

    def _get(self, doc, key):
        cur = doc
        for part in str(key).split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _set(self, doc, key, value):
        cur = doc
        parts = str(key).split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    def _apply_update(self, doc, update):
        doc = dict(doc)
        for key, value in update.get("$set", {}).items():
            self._set(doc, key, value)
        for key, value in update.get("$push", {}).items():
            current = self._get(doc, key) or []
            current.append(value)
            self._set(doc, key, current)
        return doc


async def _fake_user(_request):
    return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}


def _install(feature_enabled=True):
    ids = count(1)
    db = SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "t1",
            "features": {
                orders_routes.COMMERCIAL_PARTIAL_FULFILLMENT_FLAG: feature_enabled,
                expedicao_routes.COMMERCIAL_PARTIAL_FULFILLMENT_FLAG: feature_enabled,
            },
        }]),
        orders=FakeCollection([{
            "id": "order-1",
            "tenant_id": "t1",
            "numero_pedido": "09_001",
            "status": "em_producao",
            "cliente_id": "cli-1",
            "cliente": {"nome": "Cliente A", "razao_social": "Cliente A Ltda"},
            "frete": {"tipo": "FOB", "endereco": "Rua 1", "cidade_uf": "SP"},
            "total_pedido": 1000,
            "aditivos": [{"id": "ad-1", "status": "aprovado"}],
            "items": [{
                "id": "item-1",
                "sku_id": "sku-1",
                "codigo_kuryos": "SKU-001",
                "item": "Creme 200ml",
                "qtd": 100,
                "valor_total": 1000,
            }],
        }]),
        ops=FakeCollection([{
            "id": "op-1",
            "tenant_id": "t1",
            "pedido_id": "order-1",
            "numero_op": "OP-001",
            "status": "concluida",
            "sales_order_item_id": "item-1",
            "items": [{
                "order_item_id": "item-1",
                "item": "Creme 200ml",
                "codigo_kuryos": "SKU-001",
                "qtd_planejada": 60,
                "qtd_produzida": 60,
            }],
        }]),
        expedicao_ordens=FakeCollection([
            {
                "id": "exp-1",
                "tenant_id": "t1",
                "order_id": "order-1",
                "numero_exp": "EXP-00001",
                "status": "expedido",
                "numero_nf_saida": "NF-001",
                "items": [{"order_item_id": "item-1", "produto_nome": "Creme 200ml", "sku": "SKU-001", "quantidade": 10}],
            },
            {
                "id": "exp-2",
                "tenant_id": "t1",
                "order_id": "order-1",
                "numero_exp": "EXP-00002",
                "status": "pendente",
                "items": [{"order_item_id": "item-1", "produto_nome": "Creme 200ml", "sku": "SKU-001", "quantidade": 20}],
            },
        ]),
        faturamento_notas=FakeCollection([{
            "id": "nf-1",
            "tenant_id": "t1",
            "order_id": "order-1",
            "status": "emitida",
            "valor_produtos": 500,
            "valor_total": 500,
        }]),
        estoque_items=FakeCollection([]),
        estoque_movimentos=FakeCollection([]),
    )
    orders_routes.db = db
    orders_routes.get_current_user = _fake_user
    orders_routes.new_id_func = lambda: f"id-{next(ids)}"
    orders_routes.now_iso_func = lambda: "2026-09-14T10:00:00-03:00"
    expedicao_routes.db = db
    expedicao_routes.get_current_user = _fake_user
    expedicao_routes.new_id_func = lambda: f"id-{next(ids)}"
    expedicao_routes.now_iso_func = lambda: "2026-09-14T10:00:00-03:00"
    return db


def test_fulfillment_summary_flag_starts_off():
    _install(feature_enabled=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orders_routes.get_order_fulfillment_summary("order-1", SimpleNamespace()))

    assert exc.value.status_code == 403
    assert orders_routes.COMMERCIAL_PARTIAL_FULFILLMENT_FLAG in str(exc.value.detail)


def test_fulfillment_summary_calculates_produced_shipped_nf_and_freight():
    _install()

    summary = asyncio.run(orders_routes.get_order_fulfillment_summary("order-1", SimpleNamespace()))
    item = summary["items"][0]

    assert item["qtd_pedido"] == 100
    assert item["qtd_produzida"] == 60
    assert item["qtd_expedicao_planejada"] == 30
    assert item["qtd_expedida"] == 10
    assert item["saldo_produzido_disponivel"] == 30
    assert item["saldo_pedido_a_expedir"] == 90
    assert summary["operational_snapshot"]["percentual_nf"] == 50
    assert summary["operational_snapshot"]["frete_cif_fob"] == "FOB"
    assert summary["operational_snapshot"]["aditivos_count"] == 1


def test_create_partial_expedition_from_order_items_respects_available_produced_balance():
    db = _install()

    exp = asyncio.run(expedicao_routes.create_ordem_from_order_items(
        expedicao_routes.ExpFromOrderItemsCreate(
            order_id="order-1",
            items=[expedicao_routes.ExpOrderItemPartial(order_item_id="item-1", quantidade=30, lote="L-001")],
            observacoes="Entrega parcial",
        ),
        SimpleNamespace(),
    ))

    assert exp["delivery_mode"] == "partial_order_items"
    assert exp["partial_delivery_v2"] is True
    assert exp["items"][0]["order_item_id"] == "item-1"
    assert exp["items"][0]["qtd_produzida_snapshot"] == 60
    assert exp["items"][0]["saldo_produzido_disponivel_antes"] == 30
    assert exp["operational_snapshot"]["frete_cif_fob"] == "FOB"
    assert db.orders.docs[0]["last_exp_id"] == exp["id"]
    assert exp["id"] in db.orders.docs[0]["expedicao_ids"]


def test_create_partial_expedition_blocks_quantity_above_produced_balance():
    _install()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(expedicao_routes.create_ordem_from_order_items(
            expedicao_routes.ExpFromOrderItemsCreate(
                order_id="order-1",
                items=[expedicao_routes.ExpOrderItemPartial(order_item_id="item-1", quantidade=31)],
            ),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 422
    assert exc.value.detail["available"] == 30
