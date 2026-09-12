import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes
import pd_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, *_args):
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

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply_update(doc, query, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def update_many(self, query, update):
        modified = 0
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply_update(doc, query, update)
                modified += 1
        return SimpleNamespace(matched_count=modified, modified_count=modified)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def _matches(self, doc, query):
        for key, expected in query.items():
            current = self._get_path(doc, key)
            if isinstance(expected, dict):
                if "$in" in expected and current not in expected["$in"]:
                    return False
                continue
            if isinstance(current, list):
                if expected not in current:
                    return False
                continue
            if current != expected:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    def _get_path(self, doc, key):
        current = doc
        parts = str(key).split(".")
        for idx, part in enumerate(parts):
            if isinstance(current, list):
                if part == "id":
                    return [item.get("id") for item in current]
                return None
            if not isinstance(current, dict):
                return None
            if idx + 1 < len(parts) and isinstance(current.get(part), list) and parts[idx + 1] == "id":
                return [item.get("id") for item in current.get(part, [])]
            current = current.get(part)
        return current

    def _set_path(self, doc, key, value, query):
        parts = str(key).split(".")
        current = doc
        idx = 0
        while idx < len(parts):
            part = parts[idx]
            if part == "$":
                array_name = parts[idx - 1]
                wanted = query.get(f"{array_name}.id")
                if not isinstance(current, list):
                    return
                current = next((item for item in current if item.get("id") == wanted), None)
                if current is None:
                    return
                idx += 1
                continue
            if idx == len(parts) - 1:
                current[part] = value
                return
            next_value = current.get(part)
            if isinstance(next_value, list):
                current = next_value
            else:
                current = current.setdefault(part, {})
            idx += 1

    def _apply_update(self, doc, query, update):
        for key, value in update.get("$set", {}).items():
            self._set_path(doc, key, value, query)


async def _crm_user(_request):
    return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}


async def _pd_user(_request):
    return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}


def _crm_db(feature_enabled=True, sample=None):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {crm_routes.CARD_GOVERNANCE_FLAG: feature_enabled},
        }]),
        crm_projects=FakeCollection([{
            "id": "project-1",
            "tenant_id": "tenant-1",
            "stage": "em_negociacao",
        }]),
        crm_samples=FakeCollection([sample or {
            "id": "sample-1",
            "tenant_id": "tenant-1",
            "projeto_id": "project-1",
            "stage": "enviada",
            "variacoes": [
                {"id": "var-1", "status": "enviada", "codigo": "A"},
                {"id": "var-2", "status": "retrabalho", "codigo": "B"},
            ],
        }]),
        skus=FakeCollection([]),
    )


def _pd_db(feature_enabled=True, status="IN_PROGRESS", deleted=False):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {pd_routes.CARD_GOVERNANCE_FLAG: feature_enabled},
        }]),
        pd_requests=FakeCollection([{
            "id": "req-1",
            "tenant_id": "tenant-1",
            "status": status,
            "is_deleted": deleted,
        }]),
        pd_cards=FakeCollection([{
            "id": "card-1",
            "tenant_id": "tenant-1",
            "pd_request_id": "req-1",
        }]),
    )


def setup_function():
    crm_routes.db = _crm_db()
    crm_routes._get_current_user = _crm_user
    crm_routes._now_iso = lambda: "2026-09-12T10:00:00-03:00"

    pd_routes.db = _pd_db()
    pd_routes.get_current_user = _pd_user
    pd_routes.now_iso_func = lambda: "2026-09-12T10:00:00-03:00"


def test_crm_card_governance_requires_feature(monkeypatch):
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    crm_routes.db = _crm_db(feature_enabled=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(crm_routes.archive_sample(
            "sample-1",
            crm_routes.GovernanceArchiveRequest(reason="Projeto duplicado"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 403


def test_crm_archive_variacao_blocks_approved_variation(monkeypatch):
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    sample = {
        "id": "sample-1",
        "tenant_id": "tenant-1",
        "stage": "enviada",
        "variacoes": [
            {"id": "var-1", "status": "aprovada", "resultado": "aprovada"},
            {"id": "var-2", "status": "retrabalho"},
        ],
    }
    crm_routes.db = _crm_db(sample=sample)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(crm_routes.archive_variacao(
            "sample-1",
            "var-1",
            crm_routes.GovernanceArchiveRequest(reason="Nao seguir com variante"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 409


def test_crm_archive_and_restore_variacao(monkeypatch):
    audit_calls = []

    async def fake_audit_log(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)

    archived = asyncio.run(crm_routes.archive_variacao(
        "sample-1",
        "var-1",
        crm_routes.GovernanceArchiveRequest(reason="Cliente descartou esta variacao"),
        SimpleNamespace(),
    ))

    stored_variacao = crm_routes.db.crm_samples.docs[0]["variacoes"][0]
    assert archived["is_deleted"] is True
    assert stored_variacao["is_deleted"] is True
    assert stored_variacao["delete_reason"] == "Cliente descartou esta variacao"

    restored = asyncio.run(crm_routes.restore_variacao(
        "sample-1",
        "var-1",
        crm_routes.GovernanceRestoreRequest(reason="Reativar para nova avaliacao"),
        SimpleNamespace(),
    ))

    assert restored["is_deleted"] is False
    assert crm_routes.db.crm_samples.docs[0]["variacoes"][0]["restore_reason"] == "Reativar para nova avaliacao"
    assert [call["action"] for call in audit_calls] == ["crm_variacao_archived", "crm_variacao_restored"]


def test_pd_archive_request_blocks_approved(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _pd_db(status="APPROVED")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.archive_pd_request(
            "req-1",
            pd_routes.GovernanceArchiveRequest(reason="Teste cancelado"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 409


def test_pd_archive_and_restore_request_updates_card(monkeypatch):
    audit_calls = []

    async def fake_audit_log(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)

    archived = asyncio.run(pd_routes.archive_pd_request(
        "req-1",
        pd_routes.GovernanceArchiveRequest(reason="Solicitacao aberta por engano"),
        SimpleNamespace(),
    ))

    assert archived["is_deleted"] is True
    assert pd_routes.db.pd_requests.docs[0]["is_deleted"] is True
    assert pd_routes.db.pd_cards.docs[0]["is_deleted"] is True

    restored = asyncio.run(pd_routes.restore_pd_request(
        "req-1",
        pd_routes.GovernanceRestoreRequest(reason="Retomar desenvolvimento"),
        SimpleNamespace(),
    ))

    assert restored["is_deleted"] is False
    assert pd_routes.db.pd_requests.docs[0]["restore_reason"] == "Retomar desenvolvimento"
    assert pd_routes.db.pd_cards.docs[0]["is_deleted"] is False
    assert [call["action"] for call in audit_calls] == ["pd_request_archived", "pd_request_restored"]
