import asyncio
import os
import sys
from itertools import count
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import orders_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, key, direction):
        reverse = direction < 0
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=reverse)
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    self._set_path(doc, key, value)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def _matches(self, doc, query):
        for key, value in query.items():
            current = self._get_path(doc, key)
            if isinstance(value, dict):
                if "$nin" in value and current in value["$nin"]:
                    return False
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$gte" in value and current < value["$gte"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    def _get_path(self, doc, key):
        current = doc
        for part in str(key).split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _set_path(self, doc, key, value):
        current = doc
        parts = str(key).split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value


def setup_module():
    orders_routes.now_iso_func = lambda: "2026-09-11T10:00:00-03:00"


def _user():
    return {"id": "user-1", "tenant_id": "tenant-1", "name": "PCP", "role": "pcp"}


async def _fake_get_current_user(_request):
    return _user()


def _db(feature_enabled=True, order=None, allocations=None):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {
                orders_routes.PCP_QUANTITY_PLANNING_FLAG: feature_enabled,
                orders_routes.PCP_MATERIAL_PICKING_FLAG: feature_enabled,
            },
        }]),
        orders=FakeCollection([order or {
            "id": "order-1",
            "tenant_id": "tenant-1",
            "numero_pedido": "09_01",
            "status": "confirmado",
            "cliente": {"nome": "Cliente Teste"},
            "items": [{
                "item": "Produto A",
                "codigo_kuryos": "SKU-001",
                "sku_id": "sku-1",
                "qtd": 100,
                "prazo_entrega": "2026-09-30",
            }],
            "op_id": None,
        }]),
        pcp_allocations=FakeCollection(allocations or []),
        ops=FakeCollection([]),
        skus=FakeCollection([]),
        bom_items=FakeCollection([]),
        estoque_saldos_lote=FakeCollection([]),
        wms_enderecos=FakeCollection([]),
        wms_separacoes=FakeCollection([]),
        production_order_events=FakeCollection([]),
    )


def test_quantity_planning_flag_starts_off(monkeypatch):
    orders_routes.db = _db(feature_enabled=False)
    monkeypatch.setattr(orders_routes, "get_current_user", _fake_get_current_user)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orders_routes.list_order_pcp_allocations("order-1", SimpleNamespace()))

    assert exc.value.status_code == 403
    assert orders_routes.PCP_QUANTITY_PLANNING_FLAG in str(exc.value.detail)


def test_create_allocation_backfills_item_id_and_respects_remaining(monkeypatch):
    ids = count(1)
    orders_routes.new_id_func = lambda: f"id-{next(ids)}"
    orders_routes.db = _db()
    monkeypatch.setattr(orders_routes, "get_current_user", _fake_get_current_user)

    allocation = asyncio.run(orders_routes.create_order_item_pcp_allocation(
        "order-1",
        "item-1",
        orders_routes.PCPAllocationCreate(planned_quantity=60),
        SimpleNamespace(),
    ))

    assert allocation["sales_order_item_id"] == "item-1"
    assert allocation["planned_quantity"] == 60
    assert allocation["remaining_quantity"] == 60
    assert orders_routes.db.orders.docs[0]["items"][0]["id"] == "item-1"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orders_routes.create_order_item_pcp_allocation(
            "order-1",
            "item-1",
            orders_routes.PCPAllocationCreate(planned_quantity=50),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 422
    assert "excede saldo" in str(exc.value.detail)


def test_create_op_from_allocation_consumes_balance_and_preserves_order_link(monkeypatch):
    ids = count(1)
    orders_routes.new_id_func = lambda: f"id-{next(ids)}"
    orders_routes.db = _db(allocations=[{
        "id": "alloc-1",
        "tenant_id": "tenant-1",
        "sales_order_id": "order-1",
        "sales_order_item_id": "item-1",
        "sku_id": "sku-1",
        "planned_quantity": 100,
        "consumed_quantity": 0,
        "remaining_quantity": 100,
        "production_order_ids": [],
        "line_id": "linha-1",
        "status": "planejado",
    }])
    monkeypatch.setattr(orders_routes, "get_current_user", _fake_get_current_user)
    reviewed_item_counts = []

    async def fake_snapshot(order, _tenant_id):
        reviewed_item_counts.append(len(order.get("items") or []))
        return {
            "apto_operacao": True,
            "revisao_obrigatoria": False,
            "bloqueios": [],
            "alertas": [],
            "items": [],
            "snapshot_at": "2026-09-11T10:00:00-03:00",
        }

    monkeypatch.setattr(orders_routes, "_build_op_technical_snapshot", fake_snapshot)

    op = asyncio.run(orders_routes.create_op_from_pcp_allocation(
        "order-1",
        "alloc-1",
        orders_routes.PCPAllocationOPCreate(quantity=40, observacoes="Primeiro lote"),
        SimpleNamespace(),
    ))

    assert op["allocation_id"] == "alloc-1"
    assert op["sales_order_item_id"] == "item-1"
    assert op["items"][0]["order_item_id"] == "item-1"
    assert op["items"][0]["qtd_planejada"] == 40
    assert op["pcp_origem"] == "pedido_comercial_item"
    assert reviewed_item_counts == [1]

    allocation = orders_routes.db.pcp_allocations.docs[0]
    assert allocation["consumed_quantity"] == 40
    assert allocation["remaining_quantity"] == 60
    assert allocation["status"] == "parcial"
    assert allocation["production_order_ids"] == [op["id"]]

    order = orders_routes.db.orders.docs[0]
    assert order["status"] == "em_producao"
    assert order["op_id"] == op["id"]
    assert order["pcp_allocation_ids"] == ["alloc-1"]
    assert orders_routes.db.production_order_events.docs[0]["action"] == "create_op_from_allocation"


def _db_for_picking(feature_enabled=True):
    db = _db(feature_enabled=feature_enabled)
    db.ops.docs = [{
        "id": "op-1",
        "tenant_id": "tenant-1",
        "numero_op": "OP-2026-001",
        "pedido_id": "order-1",
        "allocation_id": "alloc-1",
        "sales_order_item_id": "item-1",
        "sku_id": "sku-1",
        "status": "aberta",
        "items": [{
            "item": "Produto A",
            "codigo_kuryos": "SKU-001",
            "sku_id": "sku-1",
            "qtd_planejada": 10,
        }],
    }]
    db.skus.docs = [{
        "id": "sku-1",
        "tenant_id": "tenant-1",
        "codigo_interno": "SKU-001",
        "produto_pai_id": "pai-1",
        "apresentacao": {"qtd_envase": 1},
    }]
    db.bom_items.docs = [{
        "id": "bom-1",
        "tenant_id": "tenant-1",
        "produto_pai_id": "pai-1",
        "sku_id": None,
        "camada": "bulk",
        "vigente": True,
        "codigo_material": "MP-001",
        "nome_material": "Materia Prima 1",
        "percentual": 50,
        "unidade": "kg",
    }, {
        "id": "bom-2",
        "tenant_id": "tenant-1",
        "produto_pai_id": "pai-1",
        "sku_id": "sku-1",
        "camada": "embalagem",
        "vigente": True,
        "codigo_material": "EP-001",
        "nome_material": "Frasco",
        "quantidade_por_unidade": 1,
        "unidade_consumo": "un",
    }]
    db.wms_enderecos.docs = [
        {"id": "end-1", "tenant_id": "tenant-1", "codigo": "P01-A-01-01", "status": "livre", "setor": "MANIPULACAO"},
        {"id": "end-2", "tenant_id": "tenant-1", "codigo": "P01-A-01-02", "status": "livre", "setor": "MANIPULACAO"},
        {"id": "end-3", "tenant_id": "tenant-1", "codigo": "P01-B-01-01", "status": "bloqueado", "setor": "LOGISTICA"},
    ]
    db.estoque_saldos_lote.docs = [
        {
            "id": "saldo-new",
            "tenant_id": "tenant-1",
            "item_id": "mat-1",
            "codigo_item": "MP-001",
            "item_nome": "Materia Prima 1",
            "lote": "L2",
            "validade": "2026-12-31",
            "endereco_id": "end-2",
            "endereco_codigo": "P01-A-01-02",
            "quantidade": 10,
            "posicao_cq": "aprovado",
            "status": "ok",
            "unidade": "kg",
        },
        {
            "id": "saldo-old",
            "tenant_id": "tenant-1",
            "item_id": "mat-1",
            "codigo_item": "MP-001",
            "item_nome": "Materia Prima 1",
            "lote": "L1",
            "validade": "2026-10-31",
            "endereco_id": "end-1",
            "endereco_codigo": "P01-A-01-01",
            "quantidade": 2,
            "posicao_cq": "aprovado",
            "status": "ok",
            "unidade": "kg",
        },
        {
            "id": "saldo-quarantine",
            "tenant_id": "tenant-1",
            "item_id": "mat-1",
            "codigo_item": "MP-001",
            "item_nome": "Materia Prima 1",
            "lote": "L0",
            "validade": "2026-01-31",
            "endereco_id": "end-1",
            "endereco_codigo": "P01-A-01-01",
            "quantidade": 99,
            "posicao_cq": "quarentena",
            "status": "ok",
            "unidade": "kg",
        },
        {
            "id": "saldo-blocked-address",
            "tenant_id": "tenant-1",
            "item_id": "mat-2",
            "codigo_item": "EP-001",
            "item_nome": "Frasco",
            "lote": "E1",
            "validade": "2026-10-01",
            "endereco_id": "end-3",
            "endereco_codigo": "P01-B-01-01",
            "quantidade": 20,
            "posicao_cq": "aprovado",
            "status": "ok",
            "unidade": "un",
        },
        {
            "id": "saldo-embalagem",
            "tenant_id": "tenant-1",
            "item_id": "mat-2",
            "codigo_item": "EP-001",
            "item_nome": "Frasco",
            "lote": "E2",
            "validade": "2026-11-01",
            "endereco_id": "end-2",
            "endereco_codigo": "P01-A-01-02",
            "quantidade": 10,
            "posicao_cq": "aprovado",
            "status": "ok",
            "unidade": "un",
        },
        {
            "id": "saldo-other-tenant",
            "tenant_id": "tenant-2",
            "item_id": "mat-1",
            "codigo_item": "MP-001",
            "item_nome": "Materia Prima 1",
            "lote": "T2",
            "validade": "2026-01-01",
            "endereco_id": "end-x",
            "quantidade": 100,
            "posicao_cq": "aprovado",
            "status": "ok",
        },
    ]
    return db


def test_material_picking_flag_starts_off(monkeypatch):
    orders_routes.db = _db_for_picking(feature_enabled=False)
    monkeypatch.setattr(orders_routes, "get_current_user", _fake_get_current_user)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orders_routes.suggest_wms_picking_for_op("op-1", SimpleNamespace()))

    assert exc.value.status_code == 403
    assert orders_routes.PCP_MATERIAL_PICKING_FLAG in str(exc.value.detail)


def test_wms_picking_suggestion_uses_fefo_and_filters_blocked_stock(monkeypatch):
    orders_routes.db = _db_for_picking()
    monkeypatch.setattr(orders_routes, "get_current_user", _fake_get_current_user)

    suggestion = asyncio.run(orders_routes.suggest_wms_picking_for_op("op-1", SimpleNamespace()))

    mp = next(item for item in suggestion["suggestions"] if item["material_key"] == "MP-001")
    assert mp["required_quantity"] == 5
    assert [line["saldo_lote_id"] for line in mp["separacoes"]] == ["saldo-old", "saldo-new"]
    assert [line["quantidade_sugerida"] for line in mp["separacoes"]] == [2, 3]
    assert all(line["saldo_lote_id"] != "saldo-quarantine" for line in mp["separacoes"])

    embalagem = next(item for item in suggestion["suggestions"] if item["material_key"] == "EP-001")
    assert embalagem["required_quantity"] == 10
    assert [line["saldo_lote_id"] for line in embalagem["separacoes"]] == ["saldo-embalagem"]
    assert suggestion["summary"]["materials_with_shortage"] == 0


def test_confirm_wms_picking_is_idempotent_and_does_not_decrement_stock(monkeypatch):
    ids = count(1)
    orders_routes.new_id_func = lambda: f"id-{next(ids)}"
    orders_routes.db = _db_for_picking()
    monkeypatch.setattr(orders_routes, "get_current_user", _fake_get_current_user)

    before_stock = {doc["id"]: doc["quantidade"] for doc in orders_routes.db.estoque_saldos_lote.docs}
    payload = orders_routes.WMSPickingConfirm(idempotency_key="op-1-sep")

    first = asyncio.run(orders_routes.confirm_wms_picking_for_op("op-1", payload, SimpleNamespace()))
    second = asyncio.run(orders_routes.confirm_wms_picking_for_op("op-1", payload, SimpleNamespace()))

    assert first["id"] == second["id"]
    assert first["status"] == "confirmada"
    assert first["estoque_baixado"] is False
    assert len(orders_routes.db.wms_separacoes.docs) == 1
    assert len(orders_routes.db.production_order_events.docs) == 1
    assert orders_routes.db.production_order_events.docs[0]["action"] == "confirm_wms_picking"
    assert {doc["id"]: doc["quantidade"] for doc in orders_routes.db.estoque_saldos_lote.docs} == before_stock
    assert orders_routes.db.ops.docs[0]["wms_separacao_id"] == first["id"]
