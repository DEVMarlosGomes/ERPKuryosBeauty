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


def _db(feature_enabled=True, alerts=None):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {pcp_routes.PCP_ALERTS_FLAG: feature_enabled},
        }]),
        pcp_programacao=FakeCollection([
            {
                "id": "slot-start-late",
                "tenant_id": "tenant-1",
                "status": "planejado",
                "numero_prog": "PCP-00001",
                "op_id": "op-1",
                "op_numero": "OP-001",
                "linha_id": "linha-1",
                "linha_nome": "Linha 1",
                "produto_nome": "Produto A",
                "sku": "SKU-A",
                "data_inicio": "2026-09-11",
                "hora_inicio": "09:00",
            },
            {
                "id": "slot-running-late",
                "tenant_id": "tenant-1",
                "status": "em_execucao",
                "numero_prog": "PCP-00002",
                "op_id": "op-2",
                "op_numero": "OP-002",
                "linha_id": "linha-2",
                "linha_nome": "Linha 2",
                "produto_nome": "Produto B",
                "sku": "SKU-B",
                "data_fim": "2026-09-11",
                "hora_fim": "09:30",
            },
            {
                "id": "slot-future",
                "tenant_id": "tenant-1",
                "status": "planejado",
                "numero_prog": "PCP-00003",
                "op_id": "op-3",
                "data_inicio": "2026-09-11",
                "hora_inicio": "11:00",
            },
            {
                "id": "slot-done",
                "tenant_id": "tenant-1",
                "status": "concluido",
                "numero_prog": "PCP-00004",
                "op_id": "op-4",
                "data_inicio": "2026-09-11",
                "hora_inicio": "08:00",
            },
        ]),
        pcp_alerts=FakeCollection(alerts or []),
    )


def setup_function():
    ids = count(1)
    pcp_routes.new_id_func = lambda: f"id-{next(ids)}"
    pcp_routes.now_iso_func = lambda: "2026-09-11T10:00:00+00:00"
    pcp_routes.get_current_user = _fake_get_current_user


def test_pcp_alerts_flag_starts_off():
    pcp_routes.db = _db(feature_enabled=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pcp_routes.list_pcp_alerts(SimpleNamespace()))

    assert exc.value.status_code == 403
    assert pcp_routes.PCP_ALERTS_FLAG in str(exc.value.detail)


def test_check_pcp_alerts_creates_start_and_running_late_alerts():
    pcp_routes.db = _db()

    result = asyncio.run(pcp_routes.check_pcp_alerts(
        pcp_routes.PCPAlertsCheck(now="2026-09-11T10:00:00+00:00", tolerance_minutes=5, cooldown_minutes=10),
        SimpleNamespace(),
    ))

    assert result["checked"] == 3
    assert result["alerts_created"] == 2
    assert {alert["tipo"] for alert in result["alerts"]} == {"op_inicio_atrasado", "op_em_andamento_atrasada"}
    assert len(pcp_routes.db.pcp_alerts.docs) == 2
    assert all(alert["notificacao_externa_enviada"] is False for alert in pcp_routes.db.pcp_alerts.docs)


def test_check_pcp_alerts_respects_cooldown_and_repiques():
    pcp_routes.db = _db()
    first = asyncio.run(pcp_routes.check_pcp_alerts(
        pcp_routes.PCPAlertsCheck(now="2026-09-11T10:00:00+00:00", cooldown_minutes=10),
        SimpleNamespace(),
    ))
    assert first["alerts_created"] == 2

    second = asyncio.run(pcp_routes.check_pcp_alerts(
        pcp_routes.PCPAlertsCheck(now="2026-09-11T10:05:00+00:00", cooldown_minutes=10),
        SimpleNamespace(),
    ))
    assert second["alerts_created"] == 0
    assert second["skipped_by_cooldown"] == 2
    assert len(pcp_routes.db.pcp_alerts.docs) == 2

    third = asyncio.run(pcp_routes.check_pcp_alerts(
        pcp_routes.PCPAlertsCheck(now="2026-09-11T10:20:00+00:00", cooldown_minutes=10),
        SimpleNamespace(),
    ))
    assert third["alerts_repiqued"] == 2
    assert {alert["repiques"] for alert in pcp_routes.db.pcp_alerts.docs} == {1}


def test_resolve_pcp_alert_updates_status_without_deleting():
    pcp_routes.db = _db(alerts=[{
        "id": "alert-1",
        "tenant_id": "tenant-1",
        "alert_key": "tenant-1:op_inicio_atrasado:slot-1:2026-09-11T09:00:00+00:00",
        "tipo": "op_inicio_atrasado",
        "status": "aberto",
        "detected_at": "2026-09-11T10:00:00+00:00",
    }])

    resolved = asyncio.run(pcp_routes.resolve_pcp_alert("alert-1", SimpleNamespace()))

    assert resolved["status"] == "resolvido"
    assert resolved["resolved_by"] == "user-1"
    assert len(pcp_routes.db.pcp_alerts.docs) == 1
