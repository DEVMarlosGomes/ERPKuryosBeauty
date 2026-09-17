import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes
import kickoff_routes
import pd_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def update_one(self, query, update):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                for key, value in update.get("$push", {}).items():
                    doc.setdefault(key, []).append(value)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


class SampleDecisionCollection:
    def __init__(self, sample):
        self.sample = sample

    async def find_one(self, query, projection=None):
        if self.sample.get("id") == query.get("id") and self.sample.get("tenant_id") == query.get("tenant_id"):
            return self.sample
        return None

    async def update_one(self, query, update):
        variation_id = query.get("variacoes.id")
        variation = next(item for item in self.sample["variacoes"] if item["id"] == variation_id)
        for key, value in update.get("$set", {}).items():
            prefix = "variacoes.$."
            if key.startswith(prefix):
                variation[key[len(prefix):]] = value
            else:
                self.sample[key] = value
        for key, value in update.get("$push", {}).items():
            if key == "variacoes.$.historico_status":
                variation.setdefault("historico_status", []).append(value)
        return SimpleNamespace(matched_count=1, modified_count=1)


class EmptyCollection:
    async def find_one(self, query, projection=None):
        return None


class BoolUnsafeDatabase:
    def __init__(self):
        self.pd_formulas = EmptyCollection()

    def __bool__(self):
        raise NotImplementedError("Database objects do not implement truth value testing")


def _user():
    return {"id": "u1", "name": "Comercial", "tenant_id": "t1", "role": "sales_ops"}


def test_crm2_marcos_espelham_negociacao_fechado_e_perdido():
    clients = FakeCollection([{
        "id": "c1",
        "tenant_id": "t1",
        "stage": "projeto_em_discussao",
        "historico_movimentacoes": [],
    }])
    crm_routes.db = SimpleNamespace(crm_clients=clients)
    crm_routes._now_iso = lambda: "2026-09-17T12:00:00+00:00"
    project = {"id": "p1", "cliente_id": "c1"}

    asyncio.run(crm_routes._mirror_client_stage_to_negociacao(project, _user()))
    assert clients.docs[0]["stage"] == "negociacao"

    asyncio.run(crm_routes._mirror_client_stage_from_project(
        project, _user(), "cliente_fechado", source="pedido_fechado"
    ))
    assert clients.docs[0]["stage"] == "cliente_fechado"

    asyncio.run(crm_routes._mirror_client_stage_from_project(
        project,
        _user(),
        "cliente_perdido",
        source="projeto_arquivado",
        motivo_perda="Cliente cancelou o lançamento",
    ))
    assert clients.docs[0]["stage"] == "cliente_perdido"
    assert clients.docs[0]["motivo_perda"] == "Cliente cancelou o lançamento"
    assert clients.docs[0]["historico_movimentacoes"][-1]["automatico"] is True


def test_aprovacao_pd_nao_cria_kickoff_pedido_ou_sku():
    pd_routes.db = SimpleNamespace(
        crm_samples=FakeCollection([{
            "id": "s1", "tenant_id": "t1", "projeto_id": "p1",
        }])
    )
    result = asyncio.run(pd_routes._ensure_project_kickoff_after_pd_approval(
        {"id": "req1", "linked_amostra_id": "s1"},
        _user(),
    ))

    assert result["project_id"] == "p1"
    assert result["waiting_for"] == "aprovacao_comercial_e_orcamento"
    assert "kickoff_id" not in result
    assert "skus_gerados" not in result


def test_selo_verde_exige_aprovacao_pd_e_comercial():
    samples = FakeCollection([{
        "id": "s1",
        "tenant_id": "t1",
        "projeto_id": "p1",
        "variacoes": [{
            "id": "v1",
            "aprovacao_pd": True,
            "aprovacao_externa": True,
            "resultado": "aprovada",
        }],
    }])
    projects = FakeCollection([{"id": "p1", "tenant_id": "t1", "stage": "amostra_enviada"}])
    crm_routes.db = SimpleNamespace(crm_samples=samples, crm_projects=projects)
    crm_routes._now_iso = lambda: "2026-09-17T12:00:00+00:00"

    result = asyncio.run(crm_routes._refresh_sample_project_approval_summary("s1", _user()))

    assert result == {"approved_variations": 1, "ready_for_quote": True}
    assert samples.docs[0]["stage"] == "aprovada"
    assert projects.docs[0]["stage"] == "amostra_enviada"
    assert projects.docs[0]["amostra_aprovada"] is True


def test_comercial_aprova_cliente_antes_do_pd(monkeypatch):
    sample = {
        "id": "s1",
        "tenant_id": "t1",
        "projeto_id": "p1",
        "stage": "enviada",
        "variacoes": [{
            "id": "v1",
            "status": "enviada",
            "aprovacao_pd": False,
            "aprovacao_externa": False,
        }],
    }
    crm_routes.db = SimpleNamespace(
        crm_samples=SampleDecisionCollection(sample),
        crm_projects=FakeCollection([{"id": "p1", "tenant_id": "t1", "stage": "amostra_enviada"}]),
        pd_cards=EmptyCollection(),
    )

    async def fake_current_user(_request):
        return _user()

    async def no_op(**_kwargs):
        return None

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_current_user)
    monkeypatch.setattr(crm_routes, "_sync_pd_cards_from_crm_stage", no_op)
    monkeypatch.setattr(crm_routes, "audit_log", no_op)
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-09-17T13:00:00+00:00")

    result = asyncio.run(crm_routes.resultado_cliente(
        "s1",
        "v1",
        crm_routes.ResultadoClienteRequest(resultado="aprovada"),
        SimpleNamespace(),
    ))

    variation = sample["variacoes"][0]
    assert result["ready_for_quote"] is False
    assert variation["status"] == "enviada"
    assert variation["resultado"] == "aprovada"
    assert variation["aprovacao_externa"] is True
    assert variation["aprovacao_pd"] is False
    assert variation["status_pd_label"] == "Cliente aprovou - aguardando P&D"


def test_formula_resolver_accepts_real_mongo_database_object():
    result = asyncio.run(kickoff_routes._find_formula_context(
        "formula-inexistente",
        "t1",
        database=BoolUnsafeDatabase(),
    ))

    assert result is None
