import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import server


class FakeTenantSettings:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if doc.get("tenant_id") == query.get("tenant_id"):
                return dict(doc)
        return None

    async def insert_one(self, document):
        self.docs.append(dict(document))
        return SimpleNamespace(inserted_id=document.get("tenant_id"))

    async def update_one(self, query, update):
        for doc in self.docs:
            if doc.get("tenant_id") != query.get("tenant_id"):
                continue
            for path, value in update.get("$set", {}).items():
                target = doc
                parts = path.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = value
            return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


def test_operational_defaults_enable_picking_and_planning_for_new_tenant(monkeypatch):
    settings = FakeTenantSettings()
    monkeypatch.setattr(server, "db", SimpleNamespace(tenant_settings=settings))
    monkeypatch.setattr(server, "now_iso", lambda: "2026-09-23T10:00:00+00:00")

    result = asyncio.run(server.ensure_tenant_operational_feature_defaults("tenant-1"))

    assert result["features"][server.PCP_MATERIAL_PICKING_FLAG] is True
    assert result["features"][server.PCP_QUANTITY_PLANNING_FLAG] is True
    assert len(settings.docs) == 1


def test_operational_defaults_preserve_explicit_false_and_fill_only_missing(monkeypatch):
    settings = FakeTenantSettings([{
        "tenant_id": "tenant-1",
        "features": {
            server.PCP_MATERIAL_PICKING_FLAG: False,
            "custom_flag": True,
        },
    }])
    monkeypatch.setattr(server, "db", SimpleNamespace(tenant_settings=settings))
    monkeypatch.setattr(server, "now_iso", lambda: "2026-09-23T10:00:00+00:00")

    result = asyncio.run(server.ensure_tenant_operational_feature_defaults("tenant-1"))

    assert result["features"][server.PCP_MATERIAL_PICKING_FLAG] is False
    assert result["features"][server.PCP_QUANTITY_PLANNING_FLAG] is True
    assert result["features"]["custom_flag"] is True
