import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import pd_routes


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

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                for key in update.get("$unset", {}):
                    doc.pop(key, None)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def _matches(self, doc, query):
        for key, expected in query.items():
            current = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and current not in expected["$in"]:
                    return False
                continue
            if current != expected:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


async def _current_user(_request):
    return {"id": "user-1", "tenant_id": "tenant-1", "role": "admin", "name": "Admin"}


def _db(feature_enabled=True, links=None, formula_locked=True, approved_by_client=True, approved_by_internal=True):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {pd_routes.FORMULA_CLIENT_LINKS_FLAG: feature_enabled},
        }]),
        pd_formulas=FakeCollection([{
            "id": "formula-1",
            "tenant_id": "tenant-1",
            "development_id": "dev-1",
            "name": "Formula Base",
            "version": 2,
            "locked": formula_locked,
            "created_at": "2026-09-12T09:00:00-03:00",
        }]),
        pd_developments=FakeCollection([{
            "id": "dev-1",
            "tenant_id": "tenant-1",
            "pd_request_id": "req-1",
        }]),
        pd_requests=FakeCollection([{
            "id": "req-1",
            "tenant_id": "tenant-1",
            "project_name": "Projeto Original",
            "client_name": "Cliente Original",
            "status": "APPROVED",
        }]),
        pd_approvals=FakeCollection([{
            "id": "approval-1",
            "tenant_id": "tenant-1",
            "development_id": "dev-1",
            "approved_by_client": approved_by_client,
            "approved_by_internal": approved_by_internal,
        }]),
        crm_clients=FakeCollection([{
            "id": "client-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Delta",
        }]),
        crm_projects=FakeCollection([{
            "id": "project-1",
            "tenant_id": "tenant-1",
            "cliente_id": "client-1",
        }]),
        skus=FakeCollection([{
            "id": "sku-1",
            "tenant_id": "tenant-1",
            "cliente_id": "client-1",
        }]),
        produtos_pai=FakeCollection([{
            "id": "pai-1",
            "tenant_id": "tenant-1",
            "cliente_id": "client-1",
        }]),
        formula_client_links=FakeCollection(links or []),
    )


def setup_function():
    pd_routes.db = _db()
    pd_routes.get_current_user = _current_user
    pd_routes.new_id_func = lambda: "link-1"
    pd_routes.now_iso_func = lambda: "2026-09-12T10:00:00-03:00"


def test_formula_client_links_requires_feature(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(feature_enabled=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.list_formula_client_links("formula-1", SimpleNamespace()))

    assert exc.value.status_code == 403


def test_create_formula_client_link_snapshots_formula_and_refs(monkeypatch):
    audit_calls = []

    async def fake_audit_log(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)

    created = asyncio.run(pd_routes.create_formula_client_link(
        "formula-1",
        pd_routes.FormulaClientLinkCreate(
            cliente_id="client-1",
            projeto_id="project-1",
            sku_id="sku-1",
            produto_pai_id="pai-1",
            uso_comercial="linha_derivada",
            observacoes="Uso permitido para derivacao comercial",
            idempotency_key="req-1",
        ),
        SimpleNamespace(),
    ))

    assert created["formula_id"] == "formula-1"
    assert created["cliente_id"] == "client-1"
    assert created["uso_comercial"] == "linha_derivada"
    assert created["formula_snapshot"]["version"] == 2
    assert created["formula_snapshot"]["is_registered"] is True
    assert created["status"] == "ativo"
    assert created["source_request_snapshot"]["project_name"] == "Projeto Original"
    assert created["feature"] == pd_routes.FORMULA_CLIENT_LINKS_FLAG
    assert audit_calls[0]["action"] == "formula_client_link_created"


def test_unregistered_formula_client_link_starts_in_validation(monkeypatch):
    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(formula_locked=False, approved_by_client=False, approved_by_internal=True)

    created = asyncio.run(pd_routes.create_formula_client_link(
        "formula-1",
        pd_routes.FormulaClientLinkCreate(cliente_id="client-1"),
        SimpleNamespace(),
    ))

    assert created["status"] == "em_validacao"
    assert created["formula_snapshot"]["is_registered"] is False


def test_create_formula_client_link_rejects_invalid_usage(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.create_formula_client_link(
            "formula-1",
            pd_routes.FormulaClientLinkCreate(cliente_id="client-1", uso_comercial="uso invalido"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 422


def test_create_formula_client_link_rejects_project_from_other_client(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.create_formula_client_link(
            "formula-1",
            pd_routes.FormulaClientLinkCreate(cliente_id="client-1", projeto_id="project-other"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 404


def test_formula_client_link_idempotency_replays_existing(monkeypatch):
    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    payload = pd_routes.FormulaClientLinkCreate(cliente_id="client-1", idempotency_key="same-call")

    first = asyncio.run(pd_routes.create_formula_client_link("formula-1", payload, SimpleNamespace()))
    second = asyncio.run(pd_routes.create_formula_client_link("formula-1", payload, SimpleNamespace()))

    assert second["id"] == first["id"]
    assert second["idempotent_replay"] is True
    assert len(pd_routes.db.formula_client_links.docs) == 1


def test_existing_active_formula_client_link_is_reused(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[{
        "id": "existing-1",
        "tenant_id": "tenant-1",
        "formula_id": "formula-1",
        "cliente_id": "client-1",
        "uso_comercial": "produto_cliente",
        "status": "ativo",
    }])

    result = asyncio.run(pd_routes.create_formula_client_link(
        "formula-1",
        pd_routes.FormulaClientLinkCreate(cliente_id="client-1"),
        SimpleNamespace(),
    ))

    assert result["id"] == "existing-1"
    assert result["already_exists"] is True


def test_list_formula_client_links_filters_inactive_by_default(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[
        {
            "id": "active-1",
            "tenant_id": "tenant-1",
            "formula_id": "formula-1",
            "cliente_id": "client-1",
            "uso_comercial": "produto_cliente",
            "status": "ativo",
            "created_at": "2026-09-12T10:00:00-03:00",
        },
        {
            "id": "inactive-1",
            "tenant_id": "tenant-1",
            "formula_id": "formula-1",
            "cliente_id": "client-1",
            "uso_comercial": "produto_cliente",
            "status": "inativo",
            "created_at": "2026-09-12T11:00:00-03:00",
        },
    ])

    result = asyncio.run(pd_routes.list_formula_client_links("formula-1", SimpleNamespace()))

    assert result["count"] == 1
    assert result["links"][0]["id"] == "active-1"


def test_update_formula_client_link_rejects_invalid_status(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[{
        "id": "link-1",
        "tenant_id": "tenant-1",
        "formula_id": "formula-1",
        "cliente_id": "client-1",
        "uso_comercial": "produto_cliente",
        "status": "ativo",
    }])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.update_formula_client_link(
            "formula-1",
            "link-1",
            pd_routes.FormulaClientLinkUpdate(status="arquivado"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 422


def test_reactivate_formula_client_link_blocks_duplicate_active(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[
        {
            "id": "link-inactive",
            "tenant_id": "tenant-1",
            "formula_id": "formula-1",
            "cliente_id": "client-1",
            "uso_comercial": "produto_cliente",
            "status": "inativo",
        },
        {
            "id": "link-active",
            "tenant_id": "tenant-1",
            "formula_id": "formula-1",
            "cliente_id": "client-1",
            "uso_comercial": "produto_cliente",
            "status": "ativo",
        },
    ])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.update_formula_client_link(
            "formula-1",
            "link-inactive",
            pd_routes.FormulaClientLinkUpdate(status="ativo"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 409


def test_reactivate_formula_client_link_clears_inactivation_fields(monkeypatch):
    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[{
        "id": "link-1",
        "tenant_id": "tenant-1",
        "formula_id": "formula-1",
        "cliente_id": "client-1",
        "uso_comercial": "produto_cliente",
        "status": "inativo",
        "inactivated_at": "2026-09-12T09:00:00-03:00",
        "inactivated_by": "user-1",
        "inactivated_by_name": "Admin",
        "inactivation_reason": "Cliente pausou uso",
    }])

    updated = asyncio.run(pd_routes.update_formula_client_link(
        "formula-1",
        "link-1",
        pd_routes.FormulaClientLinkUpdate(status="em_validacao"),
        SimpleNamespace(),
    ))

    assert updated["status"] == "em_validacao"
    assert "inactivation_reason" not in updated


def test_inactivate_formula_client_link_requires_reason(monkeypatch):
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[{
        "id": "link-1",
        "tenant_id": "tenant-1",
        "formula_id": "formula-1",
        "cliente_id": "client-1",
        "uso_comercial": "produto_cliente",
        "status": "ativo",
    }])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pd_routes.update_formula_client_link(
            "formula-1",
            "link-1",
            pd_routes.FormulaClientLinkUpdate(status="inativo"),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 422


def test_inactivate_formula_client_link_audits(monkeypatch):
    audit_calls = []

    async def fake_audit_log(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(pd_routes, "require_roles", lambda *_args, **_kwargs: None)
    pd_routes.db = _db(links=[{
        "id": "link-1",
        "tenant_id": "tenant-1",
        "formula_id": "formula-1",
        "cliente_id": "client-1",
        "uso_comercial": "produto_cliente",
        "status": "ativo",
    }])

    updated = asyncio.run(pd_routes.update_formula_client_link(
        "formula-1",
        "link-1",
        pd_routes.FormulaClientLinkUpdate(status="inativo", reason="Cliente encerrou uso comercial"),
        SimpleNamespace(),
    ))

    assert updated["status"] == "inativo"
    assert updated["inactivation_reason"] == "Cliente encerrou uso comercial"
    assert audit_calls[0]["action"] == "formula_client_link_updated"
