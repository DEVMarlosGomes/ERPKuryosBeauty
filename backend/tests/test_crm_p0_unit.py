import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes


class FakeResult:
    def __init__(self, matched_count=1, deleted_count=0):
        self.matched_count = matched_count
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self, _length):
        return list(self.docs)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query, projection=None):
        matched = [self._project(doc, projection) for doc in self.docs if self._matches(doc, query)]
        return FakeCursor(matched)

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return FakeResult()

    async def update_one(self, query, update):
        matched = 0
        for doc in self.docs:
            if not self._matches(doc, query):
                continue
            matched = 1
            for key, value in (update.get("$set") or {}).items():
                doc[key] = value
            for key, value in (update.get("$push") or {}).items():
                if isinstance(value, dict) and "$each" in value:
                    doc.setdefault(key, [])
                    doc[key].extend(value["$each"])
                else:
                    doc.setdefault(key, [])
                    doc[key].append(value)
            break
        return FakeResult(matched_count=matched)

    async def delete_many(self, query):
        kept = []
        deleted = 0
        for doc in self.docs:
            if self._matches(doc, query):
                deleted += 1
            else:
                kept.append(doc)
        self.docs = kept
        return FakeResult(deleted_count=deleted)

    def _matches(self, doc, query):
        for key, value in query.items():
            if isinstance(value, dict):
                if "$in" in value and doc.get(key) not in value["$in"]:
                    return False
                if "$ne" in value and doc.get(key) == value["$ne"]:
                    return False
                continue
            if doc.get(key) != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection is None:
            return dict(doc)
        if projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


class FakeDB:
    def __init__(self):
        self.crm_clients = FakeCollection()
        self.users = FakeCollection([
            {"id": "user-1", "tenant_id": "tenant-1", "name": "Tester"}
        ])
        self.lead_sources = FakeCollection()
        self.crm_projects = FakeCollection()
        self.crm_samples = FakeCollection()
        self.workflow_tasks = FakeCollection()
        self.audit_logs = FakeCollection()


def _base_client_payload(canal_origem):
    return {
        "nome_empresa": "Cliente Teste",
        "cnpj": "",
        "contato_principal": {
            "nome": "Contato Teste",
            "whatsapp": "11999999999",
            "email": "contato@example.com",
        },
        "contatos_adicionais": [],
        "canal_origem": canal_origem,
        "categoria_interesse": ["hidratante_facial"],
        "origem_lead": "site",
        "temperatura_lead": "morno",
        "responsavel_comercial": "user-1",
        "segmento": "outro",
        "porte": "medio",
        "regiao": "SP",
        "site": "",
        "instagram": "",
        "observacoes": "",
    }


def test_validate_client_payload_accepts_all_canal_origem_values():
    fake_db = FakeDB()
    crm_routes.db = fake_db

    for option in crm_routes.CANAL_ORIGEM_OPTIONS:
        payload = _base_client_payload(option)
        validated = asyncio.run(
            crm_routes._validate_client_payload("tenant-1", payload)
        )
        assert validated["canal_origem"] == option


def test_validate_client_payload_allows_minimal_lead_on_initial_create():
    fake_db = FakeDB()
    crm_routes.db = fake_db

    validated = asyncio.run(
        crm_routes._validate_client_payload(
            "tenant-1",
            {
                "nome_empresa": "Lead Inicial",
                "cnpj": "",
                "contato_principal": None,
                "contatos_adicionais": [],
                "canal_origem": "",
                "categoria_interesse": [],
                "origem_lead": "",
                "temperatura_lead": "morno",
                "responsavel_comercial": "user-1",
                "segmento": "",
                "porte": "",
                "regiao": "",
                "site": "",
                "instagram": "",
                "observacoes": "",
            },
            require_required_fields=True,
        )
    )

    assert validated["nome_empresa"] == "Lead Inicial"
    assert validated["cnpj"] == ""
    assert validated["contato_principal"] == {"nome": "", "whatsapp": "", "email": ""}
    assert validated["contatos_adicionais"] == []


def test_move_project_supports_crm2_quote_and_complete_budget_stages(monkeypatch):
    fake_db = FakeDB()
    fake_db.crm_clients.docs = [{
        "id": "client-1",
        "tenant_id": "tenant-1",
        "stage": "projeto_em_discussao",
        "historico_movimentacoes": [],
    }]
    fake_db.crm_projects.docs = [{
        "id": "project-1",
        "tenant_id": "tenant-1",
        "cliente_id": "client-1",
        "nome_projeto": "Projeto Teste",
        "categoria": "skin_care",
        "responsavel_comercial": "user-1",
        "ideia_conceito": "Briefing completo",
        "posicionamento": "premium",
        "volume_estimado_pedido": 1000,
        "tipo_servico": "full_service",
        "prazo_desejado_amostra": "2026-10-01",
        "stage": "amostra_enviada",
        "historico_movimentacoes": [],
    }]
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {
            "id": "user-1",
            "name": "Tester",
            "tenant_id": "tenant-1",
            "role": "admin",
        }

    generated_tasks = []

    async def fake_trigger_tasks_for_transition(**kwargs):
        generated_tasks.append((kwargs["old_stage"], kwargs["new_stage"]))
        return [{"id": f"task-{len(generated_tasks)}"}]

    audit_entries = []

    async def fake_audit_log(**kwargs):
        audit_entries.append(kwargs)

    async def fake_assert_no_blocking_tasks(**_kwargs):
        return None

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(crm_routes, "assert_no_blocking_tasks", fake_assert_no_blocking_tasks)
    monkeypatch.setattr(crm_routes, "trigger_tasks_for_transition", fake_trigger_tasks_for_transition)
    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-09-14T12:00:00+00:00")

    quote_result = asyncio.run(
        crm_routes.move_project(
            "project-1",
            crm_routes.ProjectMove(stage="cotacao"),
            SimpleNamespace(),
        )
    )
    budget_result = asyncio.run(
        crm_routes.move_project(
            "project-1",
            crm_routes.ProjectMove(stage="orcamento_completo"),
            SimpleNamespace(),
        )
    )

    assert quote_result["project"]["stage"] == "cotacao"
    assert quote_result["to_stage"] == crm_routes.STAGE_LABELS["cotacao"]
    assert budget_result["project"]["stage"] == "orcamento_completo"
    assert budget_result["to_stage"] == crm_routes.STAGE_LABELS["orcamento_completo"]
    assert generated_tasks == [
        ("amostra_enviada", "cotacao"),
        ("cotacao", "orcamento_completo"),
    ]
    assert [entry["after"]["stage"] for entry in audit_entries] == ["cotacao", "orcamento_completo"]
    assert fake_db.crm_clients.docs[0]["stage"] == "negociacao"
    assert fake_db.crm_clients.docs[0]["historico_movimentacoes"][0]["origem"] == "espelho_crm2_em_negociacao"


def test_validate_client_payload_rejects_invalid_canal_origem():
    fake_db = FakeDB()
    crm_routes.db = fake_db

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            crm_routes._validate_client_payload(
                "tenant-1",
                _base_client_payload("instagram"),
            )
        )

    assert exc_info.value.status_code == 400
    assert "Canal de origem" in str(exc_info.value.detail)


def test_batch_create_projects_rolls_back_when_secondary_step_fails(monkeypatch):
    fake_db = FakeDB()
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {
            "id": "user-1",
            "name": "Tester",
            "tenant_id": "tenant-1",
            "role": "admin",
        }

    async def fake_assert_client_exists(_tenant_id, _client_id):
        return {
            "id": "client-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Teste",
            "responsavel_comercial": "user-1",
        }

    async def fake_create_workflow_task(**_kwargs):
        task = {"id": "task-1", "tenant_id": "tenant-1"}
        await fake_db.workflow_tasks.insert_one(task)
        return task

    async def failing_deadline_task(_project, _user):
        raise RuntimeError("deadline failed")

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(crm_routes, "assert_client_exists", fake_assert_client_exists)
    monkeypatch.setattr(crm_routes, "create_workflow_task", fake_create_workflow_task)
    monkeypatch.setattr(crm_routes, "_create_project_deadline_alert_task", failing_deadline_task)
    monkeypatch.setattr(crm_routes, "_new_id", lambda: "project-1")
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-05-22T12:00:00+00:00")

    payload = crm_routes.ProjectBatchCreate(
        cliente_id="client-1",
        projects=[crm_routes.ProjectBatchItem(nome_projeto="Projeto Teste")],
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(crm_routes.batch_create_projects(payload, SimpleNamespace()))

    assert exc_info.value.status_code == 500
    assert fake_db.crm_projects.docs == []
    assert fake_db.workflow_tasks.docs == []
    assert fake_db.audit_logs.docs == []


def test_batch_create_projects_blocks_prospect_without_qualification(monkeypatch):
    fake_db = FakeDB()
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {
            "id": "user-1",
            "name": "Tester",
            "tenant_id": "tenant-1",
            "role": "admin",
        }

    async def fake_assert_client_exists(_tenant_id, _client_id):
        return {
            "id": "client-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Prospect",
            "responsavel_comercial": "user-1",
            "stage": "prospeccao",
            "canal_origem": "",
            "categoria_interesse": [],
            "temperatura_lead": "morno",
            "segmento": "",
            "contato_principal": {"nome": "", "whatsapp": ""},
        }

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(crm_routes, "assert_client_exists", fake_assert_client_exists)

    payload = crm_routes.ProjectBatchCreate(
        cliente_id="client-1",
        projects=[crm_routes.ProjectBatchItem(nome_projeto="Projeto Bloqueado")],
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(crm_routes.batch_create_projects(payload, SimpleNamespace()))

    assert exc_info.value.status_code == 409
    assert "Preencha a qualifica" in str(exc_info.value.detail)
    assert "ANVISA" in str(exc_info.value.detail)
    assert "Fornecedor atual" in str(exc_info.value.detail)
    assert fake_db.crm_projects.docs == []


def test_batch_create_projects_blocks_qualified_client_without_project_gate(monkeypatch):
    fake_db = FakeDB()
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {
            "id": "user-1",
            "name": "Tester",
            "tenant_id": "tenant-1",
            "role": "admin",
        }

    async def fake_assert_client_exists(_tenant_id, _client_id):
        return {
            "id": "client-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Qualificado",
            "responsavel_comercial": "user-1",
            "stage": "qualificado",
            "canal_origem": "site",
            "categoria_interesse": ["hidratante_facial"],
            "temperatura_lead": "morno",
            "segmento": "outro",
            "contato_principal": {"nome": "Contato", "whatsapp": "11999999999"},
            "decisores": [],
            "tem_anvisa": "",
            "volume_estimado_mensal": "",
            "fornecedor_atual": None,
        }

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(crm_routes, "assert_client_exists", fake_assert_client_exists)

    payload = crm_routes.ProjectBatchCreate(
        cliente_id="client-1",
        projects=[crm_routes.ProjectBatchItem(nome_projeto="Projeto Bloqueado")],
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(crm_routes.batch_create_projects(payload, SimpleNamespace()))

    assert exc_info.value.status_code == 409
    assert "Preencha a qualifica" in str(exc_info.value.detail)
    assert "Decisores" in str(exc_info.value.detail)
    assert "ANVISA" in str(exc_info.value.detail)
    assert "Volume estimado mensal" in str(exc_info.value.detail)
    assert "Fornecedor atual" in str(exc_info.value.detail)
    assert fake_db.crm_projects.docs == []


def test_batch_create_samples_persists_fragrance_currency_and_internal_code(monkeypatch):
    fake_db = FakeDB()
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {
            "id": "user-1",
            "name": "Tester",
            "tenant_id": "tenant-1",
            "role": "admin",
        }

    async def fake_assert_project_exists(_tenant_id, _project_id):
        return {
            "id": "project-1",
            "tenant_id": "tenant-1",
            "cliente_id": "client-1",
            "cliente_nome": "Cliente Teste",
            "nome_projeto": "Projeto Teste",
            "stage": "projeto_em_discussao",
        }

    created_pd_cards = []

    async def fake_create_pd_card_for_variacao(sample, variacao, _user):
        created_pd_cards.append((sample["id"], variacao["id"]))

    async def fake_audit_log(**_kwargs):
        return None

    async def fake_advance_project_stage_if_needed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(crm_routes, "assert_project_exists", fake_assert_project_exists)
    monkeypatch.setattr(crm_routes, "_create_pd_card_for_variacao", fake_create_pd_card_for_variacao)
    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "_advance_project_stage_if_needed", fake_advance_project_stage_if_needed)
    monkeypatch.setattr(crm_routes, "_project_stage_rank", lambda *_args, **_kwargs: 0)

    async def fake_get_next_sample_code(*_args, **_kwargs):
        return "2026-1001"

    monkeypatch.setattr(crm_routes, "_get_next_sample_code", fake_get_next_sample_code)
    generated_ids = iter(["sample-1", "var-1"])
    monkeypatch.setattr(crm_routes, "_new_id", lambda: next(generated_ids))
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-07-15T12:00:00+00:00")
    monkeypatch.setattr(crm_routes, "inherit", lambda sample, _project, _fields: sample)

    payload = crm_routes.SampleBatchCreateV2(
        projeto_id="project-1",
        samples=[
            crm_routes.SampleBatchItemV2(
                nome_produto="Shampoo Teste",
                variacoes=[
                    crm_routes.VariacaoItem(
                        descricao_aplicacao="Versao premium",
                        referencia_fragrancia="FR-00001 - Citrus",
                        fr_codigo="fr-00001",
                        custo_fragrancia=12.5,
                        custo_fragrancia_currency="usd",
                    )
                ],
            )
        ],
    )

    result = asyncio.run(crm_routes.batch_create_samples_v2(payload, SimpleNamespace()))

    assert result["count"] == 1
    assert len(fake_db.crm_samples.docs) == 1
    variacao = fake_db.crm_samples.docs[0]["variacoes"][0]
    assert variacao["fr_codigo"] == "fr-00001"
    assert variacao["custo_fragrancia_currency"] == "USD"
    assert created_pd_cards == [("sample-1", "var-1")]


def test_add_variacoes_rolls_after_z_and_persists_usd_currency(monkeypatch):
    fake_db = FakeDB()
    existing_variacoes = [
        {
            "id": f"var-{index}",
            "codigo": f"2026-1001-{crm_routes.int_to_letters(index)}",
            "letra": crm_routes.int_to_letters(index),
        }
        for index in range(26)
    ]
    fake_db.crm_samples.docs.append({
        "id": "sample-1",
        "tenant_id": "tenant-1",
        "numero_amostra": "2026-1001",
        "variacoes": existing_variacoes,
        "tem_variacoes": True,
    })
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {
            "id": "user-1",
            "name": "Tester",
            "tenant_id": "tenant-1",
            "role": "admin",
        }

    async def fake_create_pd_card_for_variacao(_sample, _variacao, _user):
        return None

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "_create_pd_card_for_variacao", fake_create_pd_card_for_variacao)
    monkeypatch.setattr(crm_routes, "_new_id", lambda: "var-aa")
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-07-15T13:00:00+00:00")

    payload = crm_routes.AddVariacoesRequest(
        variacoes=[
            crm_routes.VariacaoItem(
                descricao_aplicacao="Continuacao pos-Z",
                referencia_fragrancia="FR-00999 - Amber",
                fr_codigo="fr-00999",
                custo_fragrancia=8.75,
                custo_fragrancia_currency="usd",
            )
        ]
    )

    result = asyncio.run(crm_routes.add_variacoes_to_sample("sample-1", payload, SimpleNamespace()))

    new_variacao = result["new_variacoes"][0]
    assert new_variacao["codigo"] == "2026-1001-aa"
    assert new_variacao["letra"] == "aa"
    assert new_variacao["fr_codigo"] == "fr-00999"
    assert new_variacao["custo_fragrancia_currency"] == "USD"
