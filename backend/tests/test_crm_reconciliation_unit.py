import os
import sys

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes


def test_reconciliation_plan_repairs_stages_approvals_and_classifies_homonyms():
    clients = [
        {"id": "c1", "nome_empresa": "Cliente A", "stage": "qualificado", "cnpj": "11.111.111/0001-11"},
        {"id": "c2", "nome_empresa": "Marlos", "stage": "projeto_em_discussao", "cnpj": "22.222.222/0001-22"},
        {"id": "c3", "nome_empresa": "MARLOS", "stage": "negociacao", "cnpj": "33.333.333/0001-33"},
    ]
    projects = [
        {"id": "p1", "cliente_id": "c1", "stage": "pedido_aprovado"},
        {"id": "p2", "cliente_id": "c2", "stage": "em_negociacao"},
    ]
    samples = [{
        "id": "s1", "projeto_id": "p1", "stage": "aprovada",
        "variacoes": [{
            "id": "v1", "status": "aprovada", "resultado": "aprovada",
            "aprovacao_externa": True,
        }],
    }]

    plan = crm_routes.build_crm_reconciliation_plan(clients, projects, samples)

    changes = {item["client_id"]: item["to_stage"] for item in plan["client_stage_changes"]}
    assert changes == {"c1": "cliente_fechado", "c2": "negociacao"}
    assert plan["approval_repairs"][0]["variation_ids"] == ["v1"]
    assert plan["homonyms"][0]["client_ids"] == ["c2", "c3"]
    assert plan["homonyms"][0]["already_marked"] is False
    assert plan["duplicate_candidates"] == []


def test_reconciliation_does_not_regress_closed_client_and_flags_ambiguous_duplicate():
    clients = [
        {"id": "c1", "nome_empresa": "Mesmo Nome", "stage": "cliente_fechado", "cnpj": "11.111.111/0001-11"},
        {"id": "c2", "nome_empresa": "mesmo nome", "stage": "negociacao", "cnpj": "11.111.111/0001-11"},
    ]
    projects = [{"id": "p1", "cliente_id": "c1", "stage": "em_negociacao"}]

    plan = crm_routes.build_crm_reconciliation_plan(clients, projects, [])

    assert plan["client_stage_changes"] == []
    assert len(plan["duplicate_candidates"]) == 1
    assert plan["homonyms"] == []


def test_reconciliation_plan_is_empty_after_repairs_and_homonym_marking():
    marker = {"status": "homonimo_confirmado"}
    clients = [
        {"id": "c1", "nome_empresa": "Marlos", "stage": "cliente_fechado", "cnpj": "11.111.111/0001-11", "deduplicacao_nome": marker},
        {"id": "c2", "nome_empresa": "MARLOS", "stage": "negociacao", "cnpj": "22.222.222/0001-22", "deduplicacao_nome": marker},
    ]
    projects = [
        {"id": "p1", "cliente_id": "c1", "stage": "pedido_aprovado"},
        {"id": "p2", "cliente_id": "c2", "stage": "em_negociacao"},
    ]
    samples = [{
        "id": "s1", "stage": "aprovada", "aprovacao_pd": True, "aprovacao_interna": True,
        "aprovacao_externa": True, "aprovacao_comercial": True,
        "variacoes": [{
            "id": "v1", "status": "aprovada", "resultado": "aprovada", "aprovacao_pd": True,
            "aprovacao_interna": True, "aprovacao_externa": True, "aprovacao_comercial": True,
        }],
    }]

    plan = crm_routes.build_crm_reconciliation_plan(clients, projects, samples)

    assert plan["client_stage_changes"] == []
    assert plan["approval_repairs"] == []
    assert plan["homonyms"][0]["already_marked"] is True
