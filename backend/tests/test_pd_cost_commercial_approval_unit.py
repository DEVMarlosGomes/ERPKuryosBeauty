import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import pd_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.update_calls = []

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                if projection and projection.get("_id") == 0:
                    return {k: v for k, v in doc.items() if k != "_id"}
                return dict(doc)
        return None

    async def update_one(self, query, update):
        self.update_calls.append((dict(query), dict(update)))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                for key, value in (update.get("$set") or {}).items():
                    parts = key.split(".")
                    target = doc
                    for part in parts[:-1]:
                        target = target.setdefault(part, {})
                    target[parts[-1]] = value
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)


def setup_cost_db():
    pd_routes.db = SimpleNamespace(
        pd_developments=FakeCollection([{"id": "dev-1", "tenant_id": "tenant-1"}]),
        pd_cost_versions=FakeCollection([
            {
                "development_id": "dev-1",
                "tenant_id": "tenant-1",
                "v1": {"status": "enviado", "total": 10.0},
                "v2": {"status": "rascunho", "total": 2.0},
                "total_final": 12.0,
            }
        ]),
    )
    pd_routes.now_iso_func = lambda: "2026-08-18T10:00:00+00:00"


def patch_user(monkeypatch, role):
    async def fake_get_current_user(_request):
        return {"id": f"user-{role}", "name": role.title(), "tenant_id": "tenant-1", "role": role}

    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(pd_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)


def test_compras_cannot_finalize_v2_cost(monkeypatch):
    setup_cost_db()
    patch_user(monkeypatch, "compras")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.finalize_cost_v2("dev-1", SimpleNamespace()))

    assert exc.value.status_code == 403


def test_comercial_can_finalize_v2_cost_and_marks_approval(monkeypatch):
    setup_cost_db()
    patch_user(monkeypatch, "sales_ops")

    result = asyncio.run(pd_routes.finalize_cost_v2("dev-1", SimpleNamespace()))

    assert result["v2"]["status"] == "finalizado"
    assert result["v2"]["approved_by_commercial"] is True
    assert result["v2"]["finalized_by_role"] == "sales_ops"
