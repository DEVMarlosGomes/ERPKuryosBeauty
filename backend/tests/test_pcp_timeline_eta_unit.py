import asyncio
import os
import sys
from itertools import count
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import pcp_routes


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
                    doc[key] = value
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def _matches(self, doc, query):
        for key, value in query.items():
            current = doc.get(key)
            if isinstance(value, dict):
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$nin" in value and current in value["$nin"]:
                    return False
                if "$gte" in value and current < value["$gte"]:
                    return False
                if "$lte" in value and current > value["$lte"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


def _user():
    return {"id": "user-1", "tenant_id": "tenant-1", "name": "PCP Senior", "role": "pcp"}


async def _fake_get_current_user(_request):
    return _user()


def _op():
    return {
        "id": "op-1",
        "tenant_id": "tenant-1",
        "numero_op": "OP-001",
        "pedido_id": "order-1",
        "numero_pedido": "09_001",
        "sales_order_item_id": "item-1",
        "allocation_id": "alloc-1",
        "status": "em_processo",
        "pcp_status": "em_execucao",
        "created_at": "2026-09-11T07:00:00+00:00",
        "updated_at": "2026-09-11T10:00:00+00:00",
        "items": [{
            "order_item_id": "item-1",
            "item": "Creme Teste",
            "codigo_kuryos": "SKU-001",
            "qtd_planejada": 100,
            "qtd_produzida": 40,
        }],
        "apontamentos": [
            {"id": "ap-1", "item_idx": 0, "qtd_produzida": 20, "horario": "2026-09-11T08:00:00+00:00"},
            {"id": "ap-2", "item_idx": 0, "qtd_produzida": 20, "horario": "2026-09-11T09:00:00+00:00"},
        ],
        "pausas": [{
            "id": "pause-1",
            "tipo": "manutencao",
            "motivo": "Ajuste",
            "horario_inicio": "2026-09-11T09:00:00+00:00",
            "horario_fim": "2026-09-11T09:30:00+00:00",
            "duracao_min": 30,
        }],
        "perdas": [{
            "id": "loss-1",
            "item_idx": 0,
            "tipo": "processo",
            "quantidade": 2,
            "em": "2026-09-11T09:40:00+00:00",
        }],
    }


def _db(feature_enabled=True, closings=None, events=None):
    default_events = [{
        "id": "evt-1",
        "tenant_id": "tenant-1",
        "op_id": "op-1",
        "event_type": "setup_end",
        "action": "setup_end",
        "started_at": "2026-09-11T07:10:00+00:00",
        "ended_at": "2026-09-11T07:25:00+00:00",
        "created_at": "2026-09-11T07:25:00+00:00",
        "payload": {"setup_type": "assepsia"},
    }]
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {pcp_routes.PCP_TIMELINE_ETA_FLAG: feature_enabled},
        }]),
        ops=FakeCollection([_op()]),
        pcp_programacao=FakeCollection([
            {
                "id": "slot-1",
                "tenant_id": "tenant-1",
                "op_id": "op-1",
                "tipo": "producao",
                "status": "em_execucao",
                "data": "2026-09-11",
                "data_inicio": "2026-09-11",
                "hora_inicio": "07:30",
                "hora_fim": "11:00",
                "linha_id": "linha-1",
                "linha_nome": "Linha 1",
            },
            {
                "id": "slot-setup",
                "tenant_id": "tenant-1",
                "op_id": "op-1",
                "tipo": "setup",
                "status": "concluido",
                "data": "2026-09-11",
                "data_inicio": "2026-09-11",
                "setup_tempo_min": 15,
                "linha_id": "linha-1",
                "linha_nome": "Linha 1",
            },
        ]),
        pcp_allocations=FakeCollection([{
            "id": "alloc-1",
            "tenant_id": "tenant-1",
            "sales_order_id": "order-1",
            "sales_order_item_id": "item-1",
            "planned_quantity": 100,
            "consumed_quantity": 100,
            "remaining_quantity": 0,
            "created_at": "2026-09-11T07:05:00+00:00",
        }]),
        orders=FakeCollection([{
            "id": "order-1",
            "tenant_id": "tenant-1",
            "numero_pedido": "09_001",
            "created_at": "2026-09-10T12:00:00+00:00",
            "items": [{"id": "item-1", "item": "Creme Teste", "qtd": 100, "prazo_entrega": "2026-09-20"}],
        }]),
        wms_separacoes=FakeCollection([{
            "id": "sep-1",
            "tenant_id": "tenant-1",
            "op_id": "op-1",
            "status": "confirmada",
            "linhas": [{"saldo_id": "saldo-1", "quantidade": 1}],
            "faltas": [],
            "created_at": "2026-09-11T07:20:00+00:00",
        }]),
        production_order_events=FakeCollection(default_events if events is None else events),
        pcp_day_closings=FakeCollection([] if closings is None else closings),
    )


def setup_function():
    ids = count(1)
    pcp_routes.new_id_func = lambda: f"id-{next(ids)}"
    pcp_routes.now_iso_func = lambda: "2026-09-11T10:00:00+00:00"
    pcp_routes.get_current_user = _fake_get_current_user


def test_timeline_feature_flag_starts_off():
    pcp_routes.db = _db(feature_enabled=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pcp_routes.get_pcp_op_timeline("op-1", SimpleNamespace()))

    assert exc.value.status_code == 403
    assert pcp_routes.PCP_TIMELINE_ETA_FLAG in str(exc.value.detail)


def test_create_timeline_event_is_idempotent():
    pcp_routes.db = _db(events=[])

    payload = pcp_routes.PCPTimelineEventCreate(
        event_type="setup_start",
        started_at="2026-09-11T07:00:00+00:00",
        setup_type="assepsia",
        idempotency_key="setup-op-1",
    )
    created = asyncio.run(pcp_routes.create_pcp_timeline_event("op-1", payload, SimpleNamespace()))
    repeated = asyncio.run(pcp_routes.create_pcp_timeline_event("op-1", payload, SimpleNamespace()))

    assert created["id"] == repeated["id"]
    assert created["event_type"] == "setup_start"
    assert len(pcp_routes.db.production_order_events.docs) == 1


def test_timeline_aggregates_item_allocation_slot_wms_and_op_records():
    pcp_routes.db = _db()

    result = asyncio.run(pcp_routes.get_pcp_op_timeline("op-1", SimpleNamespace()))

    tipos = {row["tipo"] for row in result["rows"]}
    assert {"op_created", "allocation", "order_item", "slot_producao", "slot_setup", "setup_end", "apontamento", "perda", "pausa", "wms_separacao"} <= tipos
    assert result["context"]["planned_quantity"] == 100
    assert result["context"]["produced_quantity"] == 40
    assert result["context"]["remaining_quantity"] == 60
    assert result["context"]["allocation"]["id"] == "alloc-1"


def test_eta_considers_recent_rhythm_pause_and_setup():
    pcp_routes.db = _db()

    eta = asyncio.run(pcp_routes.get_pcp_op_eta("op-1", SimpleNamespace(), now="2026-09-11T10:00:00+00:00"))

    assert eta["status"] == "calculada"
    assert eta["remaining_quantity"] == 60
    assert eta["pause_minutes"] == 30
    assert eta["setup_minutes"] == 30
    assert eta["eta_minutes"] == 90
    assert eta["eta_at"] == "2026-09-11T11:30:00+00:00"


def test_day_closing_snapshots_kpis_reconciliation_and_reuses_existing():
    pcp_routes.db = _db()

    created = asyncio.run(pcp_routes.create_pcp_day_closing(
        pcp_routes.PCPDayClosingCreate(data="2026-09-11", idempotency_key="close-2026-09-11"),
        SimpleNamespace(),
    ))
    repeated = asyncio.run(pcp_routes.create_pcp_day_closing(
        pcp_routes.PCPDayClosingCreate(data="2026-09-11", idempotency_key="close-2026-09-11"),
        SimpleNamespace(),
    ))

    assert created["id"] == repeated["id"]
    assert created["kpis"]["ops_movimentadas"] == 1
    assert created["kpis"]["qtd_produzida"] == 40
    assert created["kpis"]["qtd_perdas"] == 2
    assert created["kpis"]["paradas_minutos"] == 30
    assert created["kpis"]["setup_minutos"] == 30
    assert created["reconciliacao"][0]["remaining_quantity"] == 60
    assert len(pcp_routes.db.pcp_day_closings.docs) == 1
