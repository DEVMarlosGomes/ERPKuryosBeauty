from datetime import date, datetime

from backend import pcp_routes


def test_import_helpers_normalize_headers_and_dates():
    assert pcp_routes._norm_header("Previsão Envase / Linha") == "previsao_envase_linha"
    assert pcp_routes._norm_header("CÓDIGO KURYOS") == "codigo_kuryos"
    assert pcp_routes._as_ymd("17/08/2026") == "2026-08-17"
    assert pcp_routes._as_ymd(datetime(2026, 8, 17, 7, 30)) == "2026-08-17"
    assert pcp_routes._as_ymd(date(2026, 8, 17)) == "2026-08-17"
    assert pcp_routes._as_hhmm("7h30", "07:00") == "07:30"
    assert pcp_routes._as_hhmm("8", "07:00") == "08:00"


def test_op_technical_blocks_require_revision_and_not_apt():
    op = {
        "tecnico": {
            "revisao_obrigatoria": True,
            "apto_operacao": False,
            "bloqueios": ["Ficha tecnica pendente", "Aprovacao comercial pendente"],
        }
    }
    assert pcp_routes._op_technical_blocks(op) == ["Ficha tecnica pendente", "Aprovacao comercial pendente"]


def test_op_technical_blocks_release_when_apt_or_no_revision():
    assert pcp_routes._op_technical_blocks({"tecnico": {"revisao_obrigatoria": False}}) == []
    assert pcp_routes._op_technical_blocks({"tecnico": {"revisao_obrigatoria": True, "apto_operacao": True}}) == []
