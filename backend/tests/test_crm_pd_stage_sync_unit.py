import os
import sys

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes
import workflow_engine


def test_pd_rework_sync_moves_project_back_to_development():
    target = crm_routes._pd_status_to_project_stage_sync(
        "retrabalho_interno",
        "2026-08-18T12:00:00+00:00",
    )

    assert target is not None
    stage, source, extra = target
    assert stage == "amostra_em_desenvolvimento"
    assert source == "pd_card_rework"
    assert extra["data_inicio_desenvolvimento"] == "2026-08-18T12:00:00+00:00"


def test_project_transitions_allow_pd_rework_return_from_sent_or_negotiation():
    assert "amostra_em_desenvolvimento" in crm_routes.PROJECT_TRANSITIONS["amostra_enviada"]
    assert "amostra_em_desenvolvimento" in crm_routes.PROJECT_TRANSITIONS["cotacao"]
    assert "amostra_em_desenvolvimento" in crm_routes.PROJECT_TRANSITIONS["orcamento_completo"]
    assert "amostra_em_desenvolvimento" in crm_routes.PROJECT_TRANSITIONS["em_negociacao"]


def test_project_pipeline_has_commercial_quote_and_complete_budget_stages():
    assert crm_routes.PROJECT_STAGES.index("amostra_enviada") < crm_routes.PROJECT_STAGES.index("cotacao")
    assert crm_routes.PROJECT_STAGES.index("cotacao") < crm_routes.PROJECT_STAGES.index("orcamento_completo")
    assert crm_routes.PROJECT_STAGES.index("orcamento_completo") < crm_routes.PROJECT_STAGES.index("em_negociacao")
    assert "cotacao" in crm_routes.PROJECT_TRANSITIONS["amostra_enviada"]
    assert "orcamento_completo" in crm_routes.PROJECT_TRANSITIONS["cotacao"]
    assert "em_negociacao" in crm_routes.PROJECT_TRANSITIONS["orcamento_completo"]
    assert "pedido_aprovado" in crm_routes.PROJECT_TRANSITIONS["orcamento_completo"]
    assert crm_routes.STAGE_LABELS["cotacao"] == "Cotação"
    assert crm_routes.STAGE_LABELS["orcamento_completo"] == "Orçamento Completo"


def test_workflow_tasks_for_commercial_quote_and_complete_budget():
    quote_tasks = workflow_engine.tasks_for_project_transition("amostra_enviada", "cotacao")
    budget_tasks = workflow_engine.tasks_for_project_transition("cotacao", "orcamento_completo")

    assert quote_tasks[0]["category"] == "comercial"
    assert "cotacao" in quote_tasks[0]["title"].lower()
    assert budget_tasks[0]["category"] == "fechamento"
    assert "orcamento completo" in budget_tasks[0]["title"].lower()
