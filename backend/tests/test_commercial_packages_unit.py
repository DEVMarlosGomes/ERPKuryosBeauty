import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, key, direction):
        self.docs.sort(key=lambda doc: doc.get(key) or 0, reverse=direction < 0)
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


async def _current_user(_request):
    return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}


def _approved_sample():
    return {
        "id": "sample-1",
        "tenant_id": "tenant-1",
        "numero_amostra": "2026-1001",
        "nome_produto": "Serum Delta",
        "categoria": "Skin Care",
        "projeto_id": "project-1",
        "projeto_nome": "Projeto Delta",
        "cliente_id": "client-1",
        "cliente_nome": "Cliente Delta",
        "variacoes": [{
            "id": "var-1",
            "codigo": "2026-1001-A",
            "descricao_aplicacao": "Pump 30 ml",
            "status": "aprovada",
            "resultado": "aprovada",
            "aprovacao_externa": True,
            "aprovado_cliente_em": "2026-09-12T09:00:00-03:00",
            "sku_id": "sku-1",
        }],
    }


def _db(feature_enabled=True, sample=None, packages=None):
    return SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {crm_routes.COMMERCIAL_PACKAGE_FLAG: feature_enabled},
        }]),
        crm_samples=FakeCollection([sample or _approved_sample()]),
        crm_projects=FakeCollection([{
            "id": "project-1",
            "tenant_id": "tenant-1",
            "nome_projeto": "Projeto Delta",
            "stage": "em_negociacao",
            "volume_estimado_pedido": 5000,
            "faixa_preco_venda": 42.9,
        }]),
        crm_clients=FakeCollection([{
            "id": "client-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Delta",
            "cnpj": "11222333000144",
            "condicao_pagamento": "030/060/090",
            "moq_negociado": "5000",
        }]),
        skus=FakeCollection([{
            "id": "sku-1",
            "tenant_id": "tenant-1",
            "codigo_interno": "SKN-CLID-0001",
            "nome_produto": "Serum Delta",
            "preco_unitario": 35.5,
            "preco_unitario_currency": "BRL",
            "moq": 5000,
        }]),
        commercial_packages=FakeCollection(packages or []),
    )


def setup_function():
    seq = {"value": 0}

    def new_id():
        seq["value"] += 1
        return f"id-{seq['value']}"

    crm_routes.db = _db()
    crm_routes._get_current_user = _current_user
    crm_routes._new_id = new_id
    crm_routes._now_iso = lambda: "2026-09-12T10:00:00-03:00"


def test_commercial_package_requires_feature_flag():
    crm_routes.db = _db(feature_enabled=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(crm_routes.list_commercial_packages_for_variacao("sample-1", "var-1", SimpleNamespace()))

    assert exc.value.status_code == 403
    assert crm_routes.COMMERCIAL_PACKAGE_FLAG in str(exc.value.detail)


def test_commercial_package_requires_approved_variation():
    sample = _approved_sample()
    sample["variacoes"][0]["status"] = "enviada"
    sample["variacoes"][0]["resultado"] = ""
    sample["variacoes"][0]["aprovacao_externa"] = False
    crm_routes.db = _db(sample=sample)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(crm_routes.create_commercial_package_for_variacao(
            "sample-1",
            "var-1",
            crm_routes.CommercialPackageCreate(),
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 409


def test_create_commercial_package_versions_and_snapshots(monkeypatch):
    audit_calls = []

    async def fake_audit_log(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)

    payload = crm_routes.CommercialPackageCreate(
        idempotency_key="pkg-req-1",
        pedido_cliente_ref="PO-123",
        frete=crm_routes.CommercialPackageFreight(tipo="CIF", valor=120.5, endereco="Rua 1", cidade_uf="SP/SP"),
        condicoes=crm_routes.CommercialPackageTerms(
            percentual_nf=80,
            condicao_pagamento="030/060/090",
            prazo_entrega_dias=25,
            preco_unitario=36.9,
        ),
        anexos=[crm_routes.CommercialPackageAttachment(original_filename="aprovacao.pdf", url="/files/aprovacao.pdf")],
    )

    created = asyncio.run(crm_routes.create_commercial_package_for_variacao(
        "sample-1",
        "var-1",
        payload,
        SimpleNamespace(),
    ))

    assert created["package_version"] == 1
    assert created["status"] == "ativo"
    assert created["source"] == "aprovacao_amostra"
    assert created["frete"]["tipo"] == "CIF"
    assert created["condicoes"]["percentual_nf"] == 80
    assert created["snapshot"]["sample"]["numero_amostra"] == "2026-1001"
    assert created["snapshot"]["variacao"]["codigo"] == "2026-1001-A"
    assert created["snapshot"]["client"]["nome_empresa"] == "Cliente Delta"
    assert created["snapshot"]["sku"]["codigo_interno"] == "SKN-CLID-0001"
    assert created["anexos"][0]["id"] == "id-2"
    assert audit_calls[0]["action"] == "commercial_package_created"

    listed = asyncio.run(crm_routes.list_commercial_packages_for_variacao("sample-1", "var-1", SimpleNamespace()))
    assert listed["count"] == 1
    assert listed["packages"][0]["id"] == created["id"]


def test_commercial_package_idempotency_replays_existing(monkeypatch):
    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)
    payload = crm_routes.CommercialPackageCreate(idempotency_key="pkg-req-1")

    first = asyncio.run(crm_routes.create_commercial_package_for_variacao(
        "sample-1", "var-1", payload, SimpleNamespace()
    ))
    second = asyncio.run(crm_routes.create_commercial_package_for_variacao(
        "sample-1", "var-1", payload, SimpleNamespace()
    ))

    assert second["id"] == first["id"]
    assert second["idempotent_replay"] is True
    assert len(crm_routes.db.commercial_packages.docs) == 1


def test_commercial_package_validates_terms():
    payload = crm_routes.CommercialPackageCreate(
        condicoes=crm_routes.CommercialPackageTerms(percentual_nf=101, condicao_pagamento="30/60/90")
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(crm_routes.create_commercial_package_for_variacao(
            "sample-1",
            "var-1",
            payload,
            SimpleNamespace(),
        ))

    assert exc.value.status_code == 422
