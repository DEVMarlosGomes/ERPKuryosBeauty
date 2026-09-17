import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import contratos_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                for key, value in update.get("$push", {}).items():
                    doc.setdefault(key, []).append(value)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def update_many(self, query, update):
        matched = 0
        for doc in self.docs:
            if self._matches(doc, query):
                matched += 1
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
        return SimpleNamespace(matched_count=matched, modified_count=matched)

    def _matches(self, doc, query):
        for key, value in query.items():
            if isinstance(value, dict) and "$ne" in value:
                if doc.get(key) == value["$ne"]:
                    return False
            elif isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
            elif doc.get(key) != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and all(value == 0 for value in projection.values()):
            return {key: value for key, value in doc.items() if key not in projection}
        return dict(doc)


def test_assinar_contrato_transiciona_por_api_oficial(monkeypatch):
    audit_entries = []

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit_log(**kwargs):
        audit_entries.append(kwargs)

    monkeypatch.setattr(contratos_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(contratos_routes, "now_iso", lambda: "2026-08-25T10:00:00+00:00")
    monkeypatch.setattr(contratos_routes, "audit_log", fake_audit_log)
    contratos_routes.db = SimpleNamespace(
        contratos=FakeCollection([{
            "id": "contrato-1",
            "tenant_id": "tenant-1",
            "status": "gerado",
            "kickoff_id": "kickoff-1",
            "projeto_id": "proj-1",
            "client_id": "cli-1",
            "pdf_data": b"%PDF",
        }])
    )

    result = asyncio.run(contratos_routes.assinar_contrato(
        "contrato-1",
        contratos_routes.ContratoAssinarInput(observacoes="Assinado pelo comercial"),
        SimpleNamespace(),
    ))

    assert result["status"] == "assinado"
    assert result["signed_by"] == "user-1"
    assert result["assinatura"]["assinado_em"] == "2026-08-25T10:00:00+00:00"
    assert result["status_history"][-1]["to"] == "assinado"
    assert "pdf_data" not in result
    assert audit_entries[0]["action"] == "contrato_assinado"
    assert audit_entries[0]["metadata"]["projeto_id"] == "proj-1"


def test_assinar_cgi_gera_sku_e_libera_pedido(monkeypatch):
    import crm_routes

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit_log(**_kwargs):
        return None

    async def fake_generate_skus(project_id, user):
        assert project_id == "proj-1"
        assert user["tenant_id"] == "tenant-1"
        return [{"variacao_id": "var-1", "sku": {"codigo_interno": "SKU-0001"}}]

    monkeypatch.setattr(contratos_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(contratos_routes, "now_iso", lambda: "2026-09-17T10:00:00+00:00")
    monkeypatch.setattr(contratos_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "_generate_skus_for_project_approved_variations", fake_generate_skus)

    orders = FakeCollection([{
        "id": "order-1",
        "tenant_id": "tenant-1",
        "kickoff_id": "kickoff-1",
        "cgi_status": "gerado",
    }])
    contratos_routes.db = SimpleNamespace(
        contratos=FakeCollection([{
            "id": "contrato-1",
            "tenant_id": "tenant-1",
            "status": "gerado",
            "kickoff_id": "kickoff-1",
            "projeto_id": "proj-1",
            "client_id": "cli-1",
        }]),
        orders=orders,
        crm_samples=FakeCollection(),
        crm_clients=FakeCollection(),
        crm_projects=FakeCollection(),
        skus=FakeCollection(),
    )

    result = asyncio.run(contratos_routes.assinar_contrato(
        "contrato-1",
        contratos_routes.ContratoAssinarInput(),
        SimpleNamespace(),
    ))

    assert result["skus_gerados"][0]["sku"]["codigo_interno"] == "SKU-0001"
    assert result["pedido_liberado_para_emissao"] is True
    assert result["pedido_id"] == "order-1"
    assert orders.docs[0]["cgi_status"] == "assinado"
    assert orders.docs[0]["liberado_para_emissao"] is True
    assert orders.docs[0]["skus_gerados_cgi"][0]["variacao_id"] == "var-1"


def test_assinar_cgi_ja_assinado_reprocessa_sku_e_repara_pedido(monkeypatch):
    import crm_routes

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit_log(**_kwargs):
        return None

    async def fake_generate_skus(_project_id, _user):
        return [{"variacao_id": "var-1", "sku": {"id": "sku-1", "codigo_interno": "PFM-PURE-0001"}}]

    monkeypatch.setattr(contratos_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(contratos_routes, "now_iso", lambda: "2026-09-17T11:00:00+00:00")
    monkeypatch.setattr(contratos_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "_generate_skus_for_project_approved_variations", fake_generate_skus)

    orders = FakeCollection([{
        "id": "order-1",
        "tenant_id": "tenant-1",
        "kickoff_id": "kickoff-1",
        "cgi_status": "assinado",
        "liberado_para_emissao": False,
    }])
    contratos_routes.db = SimpleNamespace(
        contratos=FakeCollection([{
            "id": "contrato-1",
            "tenant_id": "tenant-1",
            "status": "assinado",
            "signed_at": "2026-09-17T10:00:00+00:00",
            "assinatura": {"assinado_por_nome": "Admin"},
            "kickoff_id": "kickoff-1",
            "projeto_id": "proj-1",
        }]),
        orders=orders,
        crm_samples=FakeCollection(),
        crm_clients=FakeCollection(),
        crm_projects=FakeCollection(),
        skus=FakeCollection(),
    )

    result = asyncio.run(contratos_routes.assinar_contrato(
        "contrato-1", contratos_routes.ContratoAssinarInput(), SimpleNamespace()
    ))

    assert result["status"] == "assinado"
    assert result["pedido_liberado_para_emissao"] is True
    assert result["pedido_id"] == "order-1"
    assert orders.docs[0]["liberado_para_emissao"] is True
    assert orders.docs[0]["items.0.sku_id"] == "sku-1"


def test_assinar_cgi_nao_libera_pedido_quando_sku_bloqueado(monkeypatch):
    import crm_routes

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit_log(**_kwargs):
        return None

    async def fake_generate_skus(_project_id, _user):
        return [{"variacao_id": "var-1", "sku": {"blocked": True, "reason": "Categoria sem CAT3."}}]

    monkeypatch.setattr(contratos_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(contratos_routes, "now_iso", lambda: "2026-09-17T11:00:00+00:00")
    monkeypatch.setattr(contratos_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "_generate_skus_for_project_approved_variations", fake_generate_skus)

    orders = FakeCollection([{"tenant_id": "tenant-1", "kickoff_id": "kickoff-1"}])
    contratos_routes.db = SimpleNamespace(
        contratos=FakeCollection([{
            "id": "contrato-1", "tenant_id": "tenant-1", "status": "gerado",
            "kickoff_id": "kickoff-1", "projeto_id": "proj-1",
        }]),
        orders=orders,
        crm_samples=FakeCollection(), crm_clients=FakeCollection(),
        crm_projects=FakeCollection(), skus=FakeCollection(),
    )

    result = asyncio.run(contratos_routes.assinar_contrato(
        "contrato-1", contratos_routes.ContratoAssinarInput(), SimpleNamespace()
    ))

    assert result["status"] == "assinado"
    assert result["pedido_liberado_para_emissao"] is False
    assert result["sku_bloqueios"] == ["Categoria sem CAT3."]
    assert orders.docs[0]["liberado_para_emissao"] is False
