import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import materiais_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def create_index(self, *args, **kwargs):
        return None

    def _matches(self, doc, query):
        for key, expected in query.items():
            if doc.get(key) != expected:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


async def _fake_current_user(_request):
    return {"id": "user-1", "tenant_id": "tenant-1", "role": "admin", "name": "Admin"}


def _db(feature_enabled=True, materiais=None):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {materiais_routes.MATERIAL_TAX_DEFAULTS_FLAG: feature_enabled},
        }]),
        materiais=FakeCollection(materiais or []),
        graneis=FakeCollection([]),
    )


def setup_function():
    materiais_routes.db = _db()
    materiais_routes._get_current_user = _fake_current_user
    materiais_routes._new_id = lambda: "mat-id-1"
    materiais_routes._now_iso = lambda: "2026-09-12T10:00:00-03:00"


def test_create_material_without_fiscal_defaults_still_works_when_flag_off(monkeypatch):
    materiais_routes.db = _db(feature_enabled=False)

    async def fake_next_seq(_tenant_id, tipo2):
        return f"{tipo2}-00001"

    monkeypatch.setattr(materiais_routes, "_next_material_seq", fake_next_seq)

    created = asyncio.run(materiais_routes.create_material(
        materiais_routes.MaterialCreate(tipo2="MP", subtipo="Geral", nome="Agua"),
        request=SimpleNamespace(),
    ))

    assert created["codigo_interno"] == "MP-00001"
    assert "ncm" not in created
    assert "ipi_default" not in created


def test_create_material_with_fiscal_defaults_requires_flag(monkeypatch):
    materiais_routes.db = _db(feature_enabled=False)

    async def fake_next_seq(_tenant_id, tipo2):
        return f"{tipo2}-00001"

    monkeypatch.setattr(materiais_routes, "_next_material_seq", fake_next_seq)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(materiais_routes.create_material(
            materiais_routes.MaterialCreate(
                tipo2="MP",
                subtipo="Geral",
                nome="Agua",
                fiscal_defaults=materiais_routes.MaterialFiscalDefaults(ncm="3304.99.10"),
            ),
            request=SimpleNamespace(),
        ))

    assert exc.value.status_code == 403
    assert materiais_routes.MATERIAL_TAX_DEFAULTS_FLAG in str(exc.value.detail)


def test_update_material_fiscal_defaults_normalizes_and_audits():
    materiais_routes.db = _db(materiais=[{
        "id": "mat-1",
        "tenant_id": "tenant-1",
        "codigo_interno": "MP-00001",
        "tipo2": "MP",
        "subtipo": "Geral",
        "nome": "Agua",
        "status": "ativo",
    }])

    updated = asyncio.run(materiais_routes.update_material_fiscal_defaults(
        "mp-00001",
        materiais_routes.MaterialFiscalDefaults(
            ncm="3304.99.10",
            cest="28.064.00",
            ipi_default=3.25,
            icms_st_default=12,
            origem_fiscal="0",
            observacoes_fiscais="Padrao fiscal validado",
        ),
        request=SimpleNamespace(),
    ))

    assert updated["ncm"] == "33049910"
    assert updated["cest"] == "2806400"
    assert updated["ipi_default"] == 3.25
    assert updated["icms_st_default"] == 12
    assert updated["origem_fiscal"] == "0"
    assert updated["material_tax_defaults_v2"] is True
    assert updated["fiscal_updated_by"] == "user-1"


def test_invalid_fiscal_defaults_are_rejected():
    with pytest.raises(HTTPException) as exc:
        materiais_routes._fiscal_defaults_payload(
            materiais_routes.MaterialFiscalDefaults(ncm="123", ipi_default=101)
        )

    assert exc.value.status_code == 422
