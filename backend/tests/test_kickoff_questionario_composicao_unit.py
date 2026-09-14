import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import kickoff_routes


class FakeResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self, _length):
        return [dict(doc) for doc in self.docs]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    async def find_one(self, query, projection=None, *args, **kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return FakeResult()

    async def update_one(self, query, update, *args, **kwargs):
        for doc in self.docs:
            if not self._matches(doc, query):
                continue
            for key, value in (update.get("$set") or {}).items():
                doc[key] = value
            for key, value in (update.get("$push") or {}).items():
                doc.setdefault(key, [])
                if isinstance(value, dict) and "$each" in value:
                    doc[key].extend(value["$each"])
                else:
                    doc[key].append(value)
            return FakeResult(1)
        return FakeResult(0)

    def _matches(self, doc, query):
        for key, value in query.items():
            current = self._get(doc, key)
            if isinstance(value, dict):
                if "$in" in value and current not in value["$in"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _get(self, doc, dotted_key):
        current = doc
        for part in dotted_key.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


def _complete_questionario():
    q = kickoff_routes._questionario_template()
    q["bloco0"].update({
        "cliente": "Cliente",
        "nome_produto": "Produto",
        "categoria": "skin_care",
        "forma_fisica": "liquido",
        "volume_gramatura": "200 ml",
        "numero_skus_variacoes": "1",
        "modelo_servico": "full_service_marca_propria",
    })
    q["bloco1"].update({
        "formula": "desenvolvida_kuryos",
        "cliente_fornece": ["nada"],
        "tem_cor": "nao",
        "tem_brilho_mica_glitter": "nao",
        "viscosidade": "1500 cP",
        "densidade": "1.01",
        "compra_fragrancia_por": "kuryos",
    })
    for section in ("bloco2", "bloco4"):
        for row in q[section]["componentes"]:
            row.update({"aplicavel": "nao"})
    for row in q["bloco3"]["componentes"]:
        row.update({"aplicavel": "nao"})
    q["bloco2"]["componentes"][0].update({
        "aplicavel": "sim",
        "definido": "sim",
        "fornecido_por": "Kuryos",
        "especificacao_fornecedor_codigo": "Frasco PET 200 ml",
    })
    q["bloco3"]["componentes"][0].update({
        "aplicavel": "sim",
        "definido": "sim",
        "fornecido_por": "Cliente",
        "arte_cria_aprova": "Cliente / Kuryos",
        "arte_aprovada": "sim",
    })
    q["bloco4"]["componentes"][1].update({
        "aplicavel": "sim",
        "definido": "sim",
        "fornecido_por": "Kuryos",
        "especificacao_fornecedor_codigo": "Caixa master 24 un",
    })
    q["bloco5"].update({
        "especificacoes_cq_componentes": "Inspecao visual e dimensional",
        "testes_aprovacoes_obrigatorios": "Aprovacao de arte antes da producao",
        "amostra_referencia_fornecida_cliente": "sim",
    })
    q["fechamento"].update({
        "data_prevista_inicio_producao": "2026-10-01",
        "volume_primeiro_lote": "1000",
        "responsavel_kuryos": "user-1",
        "responsavel_cliente": "Cliente Resp",
        "data_preenchimento": "2026-09-14",
    })
    return q


def test_questionario_template_matches_doc_component_tables():
    template = kickoff_routes._questionario_template()

    assert template["schema_version"] == kickoff_routes.QUESTIONARIO_COMPOSICAO_VERSION
    assert len(template["bloco2"]["componentes"]) == 10
    assert len(template["bloco3"]["componentes"]) == 6
    assert len(template["bloco4"]["componentes"]) == 5
    assert template["bloco2"]["componentes"][0]["componente"] == "Frasco / pote / bisnaga"
    assert template["bloco3"]["componentes"][0]["componente"] == "Rotulo (frontal / contra)"
    assert template["bloco4"]["componentes"][1]["componente"] == "Caixa de embarque (master)"


def test_questionario_autopopulates_from_system_sources():
    kickoff_routes.db = SimpleNamespace(
        propostas_comerciais=FakeCollection([{
            "tenant_id": "tenant-1",
            "projeto_id": "proj-1",
            "tipo_produto": "Serum facial",
            "items_pedido": [{"item": "Serum 30ml", "qtd": 500, "prazo_entrega": "2026-10-10"}],
            "observacoes_proposta": "Condicao especial",
        }]),
        crm_samples=FakeCollection([{
            "tenant_id": "tenant-1",
            "projeto_id": "proj-1",
            "nome_produto": "Serum facial",
            "categoria": "skin_care",
            "parametro_variacao": "fragrancia",
            "variacoes": [{"id": "var-1", "status": "aprovada", "codigo": "2026-1001-a", "referencia_fragrancia": "CASA X F123"}],
        }]),
        pd_formula_items=FakeCollection([{"formula_id": "formula-1", "ingredient_name": "Fragrancia F123", "phase": "Fragrancia"}]),
    )

    questionario = asyncio.run(kickoff_routes._build_questionario_composicao(
        {"id": "proj-1", "tenant_id": "tenant-1", "cliente_nome": "Cliente A", "nome_projeto": "Projeto A", "categoria": "skin_care", "tipo_servico": "full_service_marca_propria", "responsavel_comercial": "user-1"},
        {"id": "client-1", "tenant_id": "tenant-1", "nome_empresa": "Cliente A", "contato_principal": {"nome": "Comprador"}},
        {"formula": {"id": "formula-1", "name": "Formula A", "volume": 30, "volume_unit": "ml"}},
        {"responsavel_comercial": "user-1"},
    ))

    assert questionario["bloco0"]["cliente"] == "Cliente A"
    assert questionario["bloco0"]["nome_produto"] == "Serum facial"
    assert questionario["bloco0"]["numero_skus_variacoes"] == "1"
    assert questionario["bloco1"]["formula"] == "desenvolvida_kuryos"
    assert questionario["bloco1"]["fragrancia_essencia"] == "Fragrancia F123"
    assert "propostas_comerciais" in questionario["autopopulated_from"]


def test_update_questionario_syncs_legacy_blocks_and_status(monkeypatch):
    q = _complete_questionario()
    audit_entries = []
    created_tasks = []

    async def fake_user(_request):
        return {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit(**kwargs):
        audit_entries.append(kwargs)

    async def fake_task(**kwargs):
        created_tasks.append(kwargs)
        return {"id": "task-1"}

    monkeypatch.setattr(kickoff_routes, "get_current_user", fake_user)
    monkeypatch.setattr(kickoff_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kickoff_routes, "audit_log", fake_audit)
    monkeypatch.setattr(kickoff_routes, "create_workflow_task", fake_task)
    monkeypatch.setattr(kickoff_routes, "now_iso", lambda: "2026-09-14T12:00:00+00:00")
    kickoff_routes.db = SimpleNamespace(
        kickoffs=FakeCollection([{
            "id": "kickoff-1",
            "tenant_id": "tenant-1",
            "projeto_id": "proj-1",
            "formula_id": "formula-1",
            "kickoff_group_id": "kg-1",
            "numero_kickoff": "KO-2026-0001",
            "status": "em_preenchimento",
            "versao": "v1",
            "versao_numero": 1,
            "aprovacoes": kickoff_routes._approval_template(),
            "bloco2": {},
            "bloco3": {},
            "bloco4": {},
            "log_auditoria": [],
        }]),
        crm_projects=FakeCollection([{"id": "proj-1", "tenant_id": "tenant-1"}]),
        workflow_tasks=FakeCollection(),
        users=FakeCollection([{"id": "lider-1", "tenant_id": "tenant-1", "role": "lider_pd", "name": "Lider"}]),
        pd_formulas=FakeCollection(),
        pd_formula_items=FakeCollection(),
        homologacao_fornecedores=FakeCollection(),
        homologacao_mps=FakeCollection(),
    )

    result = asyncio.run(kickoff_routes.update_kickoff_questionario(
        "kickoff-1",
        kickoff_routes.KickoffQuestionarioInput(questionario=q),
        SimpleNamespace(),
    ))

    assert result["status"] == "aguardando_aprovacao"
    assert result["questionario_composicao"]["bloco0"]["nome_produto"] == "Produto"
    assert result["bloco2"]["volume_primeiro_pedido"] == 1000.0
    assert result["bloco4"]["embalagem_primaria_tipo"] == "Frasco / pote / bisnaga"
    assert created_tasks[0]["metadata"]["kickoff_task_code"] == "aprovar_kickoff_lider_pd"
    assert audit_entries[0]["action"] == "kickoff_questionario_composicao_updated"


def test_archive_and_restore_kickoff_are_soft_delete(monkeypatch):
    async def fake_user(_request):
        return {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit(**_kwargs):
        return None

    monkeypatch.setattr(kickoff_routes, "get_current_user", fake_user)
    monkeypatch.setattr(kickoff_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kickoff_routes, "audit_log", fake_audit)
    monkeypatch.setattr(kickoff_routes, "now_iso", lambda: "2026-09-14T12:00:00+00:00")
    kickoff_routes.db = SimpleNamespace(
        kickoffs=FakeCollection([{
            "id": "kickoff-1",
            "tenant_id": "tenant-1",
            "projeto_id": "proj-1",
            "formula_id": "formula-1",
            "kickoff_group_id": "kg-1",
            "numero_kickoff": "KO-2026-0001",
            "status": "em_preenchimento",
            "versao": "v1",
            "versao_numero": 1,
            "aprovacoes": kickoff_routes._approval_template(),
            "questionario_composicao": kickoff_routes._questionario_template(),
            "bloco2": {},
            "bloco3": {},
            "bloco4": {},
            "log_auditoria": [],
        }]),
        crm_projects=FakeCollection([{"id": "proj-1", "tenant_id": "tenant-1"}]),
        pd_formulas=FakeCollection(),
        pd_formula_items=FakeCollection(),
        homologacao_fornecedores=FakeCollection(),
        homologacao_mps=FakeCollection(),
    )

    archived = asyncio.run(kickoff_routes.archive_kickoff(
        "kickoff-1",
        kickoff_routes.KickoffDeleteInput(motivo="Projeto cancelado"),
        SimpleNamespace(),
    ))
    restored = asyncio.run(kickoff_routes.restore_kickoff("kickoff-1", SimpleNamespace()))

    assert archived["status"] == "arquivado"
    assert archived["archive_reason"] == "Projeto cancelado"
    assert restored["status"] == "em_preenchimento"
    assert restored["restored_by"] == "user-1"
