from datetime import date, datetime
from pathlib import Path

from backend import pcp_routes
from backend import orders_routes


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


def test_calendar_period_helpers_build_dynamic_shift_config():
    payload = pcp_routes.CalendarioPeriodoApply(
        data_inicio="2026-08-19",
        data_fim="2026-08-22",
        dias=["qua", "sab"],
        hora_inicio="7",
        hora_fim="18h30",
        turnos=[
            pcp_routes.TurnoDiaConfig(nome="Turno 1", hora_inicio="07:00", hora_fim="14:00", capacidade_pct=50),
            pcp_routes.TurnoDiaConfig(nome="Turno 2", hora_inicio="14:00", hora_fim="18:30", capacidade_pct=50),
        ],
    )

    dates = list(pcp_routes._iter_dates(
        pcp_routes._parse_date_ymd(payload.data_inicio, "data_inicio"),
        pcp_routes._parse_date_ymd(payload.data_fim, "data_fim"),
    ))
    assert [pcp_routes._dia_key_from_date(d) for d in dates] == ["qua", "qui", "sex", "sab"]

    config = pcp_routes._calendar_config_from_apply(payload)
    assert config["hora_inicio"] == "07:00"
    assert config["hora_fim"] == "18:30"
    assert len(config["turnos"]) == 2


def test_op_status_requires_pcp_confirmation_step():
    assert "aguardando_confirmacao_pcp" in orders_routes.OP_STATUSES

    root = Path(__file__).resolve().parents[2]
    production_page = root / "frontend" / "src" / "pages" / "PCPProductionPage.js"
    pcp_routes_file = root / "backend" / "pcp_routes.py"

    production_src = production_page.read_text(encoding="utf-8")
    assert 'setStatus(selected, "aguardando_confirmacao_pcp")' in production_src
    assert 'setStatus(selected, "concluida")' not in production_src

    pcp_src = pcp_routes_file.read_text(encoding="utf-8")
    assert '"status": "aguardando_confirmacao_pcp"' in pcp_src
    assert '"status": "concluida", "updated_at": now' not in pcp_src
