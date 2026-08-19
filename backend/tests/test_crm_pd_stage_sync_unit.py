import os
import sys

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes


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
    assert "amostra_em_desenvolvimento" in crm_routes.PROJECT_TRANSITIONS["em_negociacao"]
