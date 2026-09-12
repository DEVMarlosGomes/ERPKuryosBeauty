import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import server


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

    def _matches(self, doc, query):
        for key, expected in query.items():
            if doc.get(key) != expected:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


class FakeUploadFile:
    filename = "contrato.pdf"
    content_type = "application/pdf"

    async def read(self):
        return b"pdf-data"


async def _current_user(_request):
    return {"id": "user-1", "tenant_id": "tenant-1", "role": "admin", "name": "Admin"}


def _db(feature_enabled=True):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {server.UNIFIED_ATTACHMENTS_FLAG: feature_enabled},
        }]),
        files=FakeCollection([]),
        attachments=FakeCollection([]),
    )


def test_generic_upload_with_owner_creates_unified_attachment(monkeypatch):
    stored = {}

    def fake_put(path, data, content_type):
        stored["path"] = path
        stored["data"] = data
        stored["content_type"] = content_type
        return {"path": path, "size": len(data)}

    ids = iter(["file-1", "att-1"])
    monkeypatch.setattr(server, "db", _db(feature_enabled=True))
    monkeypatch.setattr(server, "get_current_user", _current_user)
    monkeypatch.setattr(server, "new_id", lambda: next(ids))
    monkeypatch.setattr(server, "now_iso", lambda: "2026-09-12T10:00:00-03:00")
    monkeypatch.setattr(server, "put_object", fake_put)

    created = asyncio.run(server.upload_file(
        SimpleNamespace(),
        FakeUploadFile(),
        owner_type="kickoff",
        owner_id="kickoff-1",
        relation="contrato_assinado",
    ))

    assert created["id"] == "file-1"
    assert created["attachment_id"] == "att-1"
    assert created["attachment"]["owner_type"] == "kickoff"
    assert created["attachment"]["owner_id"] == "kickoff-1"
    assert created["attachment"]["file_id"] == "file-1"
    assert "kuryos-crm/uploads/tenant-1/" in stored["path"]


def test_generic_upload_with_owner_requires_feature_before_storage(monkeypatch):
    called = {"put": False}

    def fake_put(*_args, **_kwargs):
        called["put"] = True
        return {"path": "x", "size": 1}

    monkeypatch.setattr(server, "db", _db(feature_enabled=False))
    monkeypatch.setattr(server, "get_current_user", _current_user)
    monkeypatch.setattr(server, "put_object", fake_put)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.upload_file(
            SimpleNamespace(),
            FakeUploadFile(),
            owner_type="kickoff",
            owner_id="kickoff-1",
        ))

    assert exc.value.status_code == 403
    assert called["put"] is False


def test_list_unified_attachments_filters_by_owner(monkeypatch):
    monkeypatch.setattr(server, "db", _db(feature_enabled=True))
    monkeypatch.setattr(server, "get_current_user", _current_user)
    server.db.attachments.docs.append({
        "id": "att-1",
        "tenant_id": "tenant-1",
        "owner_type": "kickoff",
        "owner_id": "kickoff-1",
        "relation": "contrato_assinado",
        "is_deleted": False,
        "uploaded_at": "2026-09-12T10:00:00-03:00",
    })

    result = asyncio.run(server.list_attachments(
        SimpleNamespace(),
        owner_type="kickoff",
        owner_id="kickoff-1",
    ))

    assert result["count"] == 1
    assert result["attachments"][0]["id"] == "att-1"
