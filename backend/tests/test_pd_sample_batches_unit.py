import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import pd_routes


class FakeResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class TrackingCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.insert_calls = []
        self.update_calls = []

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items() if "." not in key):
                if projection and projection.get("_id") == 0:
                    return {k: v for k, v in doc.items() if k != "_id"}
                return dict(doc)
        return None

    async def insert_one(self, doc):
        snapshot = dict(doc)
        self.insert_calls.append(snapshot)
        self.docs.append(snapshot)
        return FakeResult()

    async def update_one(self, query, update):
        self.update_calls.append((dict(query), dict(update)))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items() if "." not in key):
                for key, value in (update.get("$set") or {}).items():
                    doc[key] = value
                return FakeResult(matched_count=1)
        return FakeResult(matched_count=0)


def make_payload(**overrides):
    base = {
        "nome": "Base Floral",
        "formula_base_id": "formula-1",
        "volume_base_ml": 15,
        "base_total_volume_ml": 120,
        "max_derivacoes": 6,
        "perda_operacional_percent": 10,
        "validade_base": "2026-08-10",
        "condicoes_armazenamento": "25C protegido da luz",
        "status_base": "ativa",
        "status_qualidade": "aprovada",
        "variantes": [
            {"id": "var-1", "nome": "Rosa", "versao": 1, "overrides": [], "notas": ""},
            {"id": "var-2", "nome": "Lavanda", "versao": 1, "overrides": [], "notas": ""},
            {"id": "var-3", "nome": "Verbena", "versao": 1, "overrides": [], "notas": ""},
        ],
        "notas": "Teste",
    }
    base.update(overrides)
    return pd_routes.SampleBatchCreate.model_validate(base)


def test_build_sample_batch_payload_calculates_capacity_and_balance():
    payload = pd_routes._build_sample_batch_payload(
        make_payload(),
        tenant_id="tenant-1",
        dev_id="dev-1",
        existing_id="batch-1",
        current_now="2026-08-03T10:00:00+00:00",
    )

    assert payload["capacidade_maxima_derivacoes"] == 6
    assert payload["capacidade_restante_derivacoes"] == 3
    assert payload["volume_consumido_ml"] == 45
    assert payload["volume_disponivel_ml"] == 75
    assert payload["bloqueado_para_novas_derivacoes"] is False
    assert payload["motivos_bloqueio"] == []


def test_build_sample_batch_payload_marks_expired_base_as_blocked():
    payload = pd_routes._build_sample_batch_payload(
        make_payload(validade_base="2026-08-02"),
        tenant_id="tenant-1",
        dev_id="dev-1",
        existing_id="batch-1",
        current_now="2026-08-03T10:00:00+00:00",
    )

    assert payload["bloqueado_para_novas_derivacoes"] is True
    assert "validade_expirada" in payload["motivos_bloqueio"]


def test_build_sample_batch_payload_rejects_more_derivations_than_capacity():
    with pytest.raises(HTTPException) as exc_info:
        pd_routes._build_sample_batch_payload(
            make_payload(base_total_volume_ml=45, max_derivacoes=2),
            tenant_id="tenant-1",
            dev_id="dev-1",
            existing_id="batch-1",
            current_now="2026-08-03T10:00:00+00:00",
        )

    assert exc_info.value.status_code == 400
    assert "suporta no maximo" in exc_info.value.detail


def test_build_sample_batch_payload_rejects_non_allowed_base_change():
    payload = make_payload(
        variantes=[
            {
                "id": "var-1",
                "nome": "Base alterada",
                "versao": 1,
                "overrides": [
                    {
                        "ingredient_name_base": "Agua deionizada",
                        "ingredient_name": "Propilenoglicol",
                        "percentage": 10,
                        "fornecedor": "",
                    }
                ],
                "notas": "",
            }
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        pd_routes._build_sample_batch_payload(
            payload,
            tenant_id="tenant-1",
            dev_id="dev-1",
            existing_id="batch-1",
            current_now="2026-08-03T10:00:00+00:00",
        )

    assert exc_info.value.status_code == 400
    assert "Altere apenas" in exc_info.value.detail
    assert "Agua" in exc_info.value.detail


def test_build_sample_batch_payload_accepts_fragrance_change_scope():
    payload = pd_routes._build_sample_batch_payload(
        make_payload(
            variantes=[
                {
                    "id": "var-1",
                    "nome": "Floral",
                    "versao": 1,
                    "overrides": [
                        {
                            "ingredient_name_base": "Fragrancia padrao",
                            "ingredient_name": "Fragrancia Floral",
                            "percentage": 3,
                            "fornecedor": "Fornecedor A",
                        }
                    ],
                    "notas": "",
                }
            ]
        ),
        tenant_id="tenant-1",
        dev_id="dev-1",
        existing_id="batch-1",
        current_now="2026-08-03T10:00:00+00:00",
    )

    override = payload["variantes"][0]["overrides"][0]
    assert override["change_scope"] == "fragrancia"
    assert payload["allowed_change_scopes"] == ["cor", "ativo", "fragrancia"]


def test_create_sample_batch_persists_computed_fields(monkeypatch):
    fake_db = SimpleNamespace(
        pd_developments=TrackingCollection([{"id": "dev-1", "tenant_id": "tenant-1"}]),
        pd_formulas=TrackingCollection([{"id": "formula-1", "tenant_id": "tenant-1", "development_id": "dev-1"}]),
        pd_sample_batches=TrackingCollection(),
    )
    pd_routes.db = fake_db
    pd_routes.new_id_func = iter(["batch-1"]).__next__
    pd_routes.now_iso_func = lambda: "2026-08-03T10:00:00+00:00"

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1", "role": "formulador"}

    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(pd_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(pd_routes, "audit_log", fake_audit_log)

    created = asyncio.run(pd_routes.create_sample_batch("dev-1", make_payload(), SimpleNamespace()))

    assert created["id"] == "batch-1"
    assert created["capacidade_maxima_derivacoes"] == 6
    assert created["capacidade_restante_derivacoes"] == 3
    assert created["status_base"] == "ativa"
    assert fake_db.pd_sample_batches.insert_calls[0]["volume_disponivel_ml"] == 75
