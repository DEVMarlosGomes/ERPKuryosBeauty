import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import cadastros_master_routes as cad


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.inserted = []
        self.updated = []

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        stored = dict(doc)
        self.docs.append(stored)
        self.inserted.append(stored)
        return SimpleNamespace(inserted_id=stored.get("id"))

    async def update_one(self, query, update):
        self.updated.append((query, update))
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    def _matches(self, doc, query):
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                continue
            if value != expected:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {k: v for k, v in doc.items() if k != "_id"}
        return dict(doc)


def setup_module(module):
    cad._new_id = lambda: "new-id"
    cad._now_iso = lambda: "2026-08-18T12:00:00+00:00"

    async def fake_current_user(request):
        return {
            "id": "user-1",
            "tenant_id": "tenant-1",
            "role": "admin",
            "name": "Admin",
        }

    cad._get_current_user = fake_current_user


def test_validate_catmp3_accepts_three_alphanumeric_chars():
    assert cad._validate_catmp3("fra") == "FRA"
    assert cad._validate_catmp3("e01") == "E01"


def test_validate_catmp3_rejects_invalid_codes():
    with pytest.raises(HTTPException) as exc:
        cad._validate_catmp3("fragrance")
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    ("raw", "tipo2"),
    [
        ("mp", "MP"),
        ("materia-prima", "MP"),
        ("insumo", "EP"),
        ("embalagem secundaria", "ES"),
        ("rotulo", "RT"),
    ],
)
def test_material_tipo_business_mapping(raw, tipo2):
    assert cad._material_tipo_from_business(raw) == tipo2


def test_create_produto_final_uses_cat3_cli4_sequence_and_freezes_client(monkeypatch):
    cad.db = SimpleNamespace(
        categorias=FakeCollection([
            {"tenant_id": "tenant-1", "cat3": "BSP", "status": "ativa", "nome": "Body Splash"}
        ]),
        crm_clients=FakeCollection([
            {"tenant_id": "tenant-1", "id": "cli-1", "nome_empresa": "Miss Rose", "cli4": "MISS"}
        ]),
        skus=FakeCollection([]),
    )

    async def fake_next_sku(tenant_id, cat3, cli4):
        assert (tenant_id, cat3, cli4) == ("tenant-1", "BSP", "MISS")
        return 7

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "next_sku_per_pair_v2", fake_next_sku)
    monkeypatch.setattr(cad, "_audit", fake_audit)

    result = asyncio.run(cad.create_produto_final(
        cad.ProdutoFinalCreate(
            nome_produto="Body Splash Flor",
            cliente_id="cli-1",
            cat3="BSP",
            pd_request_id="pd-1",
        ),
        request=SimpleNamespace(),
    ))

    assert result["codigo_interno"] == "BSP-MISS-0007"
    assert result["pd_concluido"] is True
    assert cad.db.skus.inserted[0]["codigo_interno"] == "BSP-MISS-0007"
    assert cad.db.crm_clients.updated[0][1]["$set"]["cli4_congelado"] is True
