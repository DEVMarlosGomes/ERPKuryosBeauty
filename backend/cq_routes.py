"""
CQ Module - Controle de Qualidade (Quality Control)

Collections (all immutable — no DELETE endpoints):
  cq_registros_analise  — RA (Registro de Análise / laudo)
  cq_checklists         — CK-1 a CK-8 (inspeção de campo)
  cq_rncs               — RNC (Não Conformidades)
  cq_retencoes          — Amostras de retenção
  cq_instrumentos       — Instrumentos de calibração
  cq_status_lote        — Trilha de auditoria de status de lote

Invariants:
  - lote_id obrigatório para criar RA
  - conforme calculado automaticamente pelo sistema (numérico: min <= resultado <= max)
  - ao aprovar/reprovar: status do lote registrado em cq_status_lote
  - reprovado → RNC criada automaticamente (disposicao_imediata obrigatória)
  - aprovado/concessao → RET criada automaticamente; data_limite_guarda calculada
  - concessao → justificativa_concessao obrigatória
  - erros corrigidos via campo observacao com log de quem corrigiu e quando
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from rbac import require_roles, has_role
from workflow_engine import audit_log, next_sequence, create_workflow_task

logger = logging.getLogger(__name__)

cq_router = APIRouter(prefix="/api/cq")

# ── Module state ───────────────────────────────────────────────────────────────
db = None
get_current_user = None
new_id_func = None
now_iso_func = None
_broadcast_event = None


def init_cq(database, auth_func, id_func, iso_func, broadcast_event_fn=None):
    global db, get_current_user, new_id_func, now_iso_func, _broadcast_event
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func
    _broadcast_event = broadcast_event_fn
    logger.info("CQ module initialized")


def new_id() -> str:
    return new_id_func()


def now_iso() -> str:
    return now_iso_func()


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 7 — HARD STOPS (importáveis por outros módulos)
# ══════════════════════════════════════════════════════════════════════════════

async def cq_verificar_assepsia_manipulacao(db, tenant_id: str, om_id: str):
    """Bloqueia início de OM sem CK-3 aprovado."""
    ok = await db.cq_checklists.find_one(
        {"op_id": om_id, "tipo": "CK-3", "status": "aprovado", "tenant_id": tenant_id}
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "hard_stop_assepsia_manipulacao",
                "message": "Ordem de Manipulação não pode iniciar sem CK-3 (Assépsia) aprovado pelo CQ.",
            },
        )


async def cq_verificar_assepsia_envase(db, tenant_id: str, op_id: str):
    """Bloqueia início de OP de envase sem CK-4 aprovado."""
    ok = await db.cq_checklists.find_one(
        {"op_id": op_id, "tipo": "CK-4", "status": "aprovado", "tenant_id": tenant_id}
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "hard_stop_assepsia_envase",
                "message": "Ordem de Produção não pode iniciar sem CK-4 (Assépsia de Linha) aprovado.",
            },
        )


async def cq_verificar_setup_linha(db, tenant_id: str, op_id: str):
    """Bloqueia início de produção em série sem CK-5 aprovado."""
    ok = await db.cq_checklists.find_one(
        {"op_id": op_id, "tipo": "CK-5", "status": "aprovado", "tenant_id": tenant_id}
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "hard_stop_setup_linha",
                "message": "Produção não pode iniciar sem CK-5 (Setup/First Article) aprovado.",
            },
        )


async def cq_verificar_lote_aprovado(db, tenant_id: str, lote_id: str):
    """Bloqueia movimentação de lote reprovado. Lote status=concessao passa normalmente."""
    if not lote_id:
        return  # Sem lote_id, sem bloqueio (campo opcional em movimentos legados)
    ultimo = await db.cq_status_lote.find_one(
        {"lote_id": lote_id, "tenant_id": tenant_id},
        sort=[("created_at", -1)],
    )
    if not ultimo or ultimo.get("status_novo") not in {"aprovado", "concessao"}:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "hard_stop_lote_sem_liberacao_cq",
                "message": "Lote sem liberacao de CQ. Movimentacao bloqueada ate aprovacao ou concessao registrada.",
            },
        )


async def cq_verificar_liberacao_palete(db, tenant_id: str, lote_id: str):
    """Bloqueia expedição sem CK-7 aprovado para o lote."""
    if not lote_id:
        return
    ok = await db.cq_checklists.find_one(
        {"lote_id": lote_id, "tipo": "CK-7", "status": "aprovado", "tenant_id": tenant_id}
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "hard_stop_liberacao_palete",
                "message": "Palete não pode ser expedido sem CK-7 (Liberação de Palete) aprovado pelo CQ.",
            },
        )


# ── RBAC ──────────────────────────────────────────────────────────────────────
# Acesso total CQ: criar/aprovar RA, gerir RNC, fechar instrumentos
CQ_FULL = {"admin", "qa", "lider_pd"}
# Analista: preencher resultados, criar RA, gerar CoA
CQ_ANALISTA = {"admin", "qa", "lider_pd", "formulador"}
# Leitura: visualizar RAs, checklists, RNCs
CQ_READ = {"admin", "qa", "lider_pd", "formulador", "engenharia_produto", "compras", "sales_ops"}


# ── Numbering ─────────────────────────────────────────────────────────────────
async def _next_number(tenant_id: str, prefix: str, counter_key: str) -> str:
    year = datetime.now(timezone.utc).year
    seq = await next_sequence(tenant_id, f"{counter_key}_{year}", start=0)
    return f"{prefix}-{year}-{seq:04d}"


async def _next_ra_number(tenant_id: str) -> str:
    return await _next_number(tenant_id, "RA", "cq_ra")


async def _next_rnc_number(tenant_id: str) -> str:
    return await _next_number(tenant_id, "RNC", "cq_rnc")


async def _next_ret_number(tenant_id: str) -> str:
    return await _next_number(tenant_id, "RET", "cq_ret")


async def _next_ck_number(tenant_id: str, tipo: str) -> str:
    # tipo = "CK-6" → tipo_num = "6"
    tipo_num = tipo.replace("CK-", "").strip() if tipo.upper().startswith("CK-") else tipo
    year = datetime.now(timezone.utc).year
    seq = await next_sequence(tenant_id, f"cq_ck_{year}", start=0)
    return f"CK-{tipo_num}-{year}-{seq:04d}"


# ── Date helpers ───────────────────────────────────────────────────────────────
def _add_days_iso(iso_date: Optional[str], days: int) -> str:
    """Return (iso_date + days) as an ISO date string, falling back to today."""
    if iso_date:
        try:
            base = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            base = datetime.now(timezone.utc)
    else:
        base = datetime.now(timezone.utc)
    return (base + timedelta(days=days)).date().isoformat()


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 1 — SCHEMAS (Pydantic models for all 6 collections)
# ══════════════════════════════════════════════════════════════════════════════

# ─── cq_registros_analise ────────────────────────────────────────────────────

class ParametroSchema(BaseModel):
    """Represents a single quality parameter in an RA."""
    id: str = ""
    nome: str
    unidade: Optional[str] = None
    metodo: Optional[str] = None
    especificacao_min: Optional[float] = None
    especificacao_max: Optional[float] = None
    resultado: Optional[Any] = None
    conforme: Optional[bool] = None      # calculated by the system
    observacao: Optional[str] = None


class RACreate(BaseModel):
    lote_id: str                          # REQUIRED — sem lote não cria RA
    lote_numero: str
    tipo: str                             # recepcao_mp | recepcao_embalagem | bulk_piloto | produto_acabado
    item_id: Optional[str] = None
    item_nome: Optional[str] = None
    item_tipo: Optional[str] = None
    fornecedor_id: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    nf_numero: Optional[str] = None
    nf_data: Optional[str] = None        # ISO date string
    quantidade_recebida: Optional[float] = None
    unidade: Optional[str] = None
    numero_lote_fornecedor: Optional[str] = None
    data_fabricacao_fornecedor: Optional[str] = None
    data_validade_fornecedor: Optional[str] = None
    # Optional override — if absent, parameters are fetched from Ficha Técnica
    parametros: Optional[List[ParametroSchema]] = None


class ParametroResultadoInput(BaseModel):
    id: str
    resultado: Optional[Any] = None
    observacao: Optional[str] = None


class RAParametrosUpdate(BaseModel):
    parametros: List[ParametroResultadoInput]


class AprovarInput(BaseModel):
    decisao: str                              # aprovado | reprovado | concessao
    observacoes: Optional[str] = None
    justificativa_concessao: Optional[str] = None   # required when decisao=concessao
    disposicao_imediata: Optional[str] = None       # required when decisao=reprovado
    instrumento_usado_id: Optional[str] = None
    # devolucao | descarte | reprocesso | concessao


class RegistrarEnvioCoAInput(BaseModel):
    cliente_id: Optional[str] = None
    cliente_nome: Optional[str] = None
    canal: Optional[str] = None           # email | whatsapp | portal
    observacoes: Optional[str] = None


# ─── cq_checklists ────────────────────────────────────────────────────────────

class ChecklistItemInput(BaseModel):
    id: Optional[str] = None
    secao: Optional[str] = None
    ordem: Optional[int] = None
    descricao: str
    tipo_resposta: str = "snna"           # snna | numerico | texto
    somente_cq: bool = False
    resposta: Optional[Any] = None        # S | N | NA | número | texto
    conforme: Optional[bool] = None
    observacao: Optional[str] = None
    foto_file_ids: Optional[List[str]] = None
    nc_classificacao: Optional[str] = None  # critica | maior | menor — quando resposta=N
    acao_imediata: Optional[str] = None


class ChecklistCreate(BaseModel):
    tipo: str                             # CK-1 a CK-8
    nome: Optional[str] = None           # título descritivo exibido na listagem
    op_id: Optional[str] = None          # OBRIGATÓRIO para CK-3 a CK-8
    op_numero: Optional[str] = None
    lote_id: Optional[str] = None
    linha: Optional[str] = None
    turno: Optional[str] = None
    subtipo_insumo: Optional[str] = None    # CK-1 only: frasco|tampa|valvula|rotulo|cartucho|caixa
    horario_previsto_ronda: Optional[str] = None  # CK-6 only
    ra_id: Optional[str] = None          # vínculo com Registro de Análise de origem
    itens: Optional[List[ChecklistItemInput]] = None


class ChecklistItemUpdate(BaseModel):
    resposta: Optional[Any] = None
    conforme: Optional[bool] = None
    observacao: Optional[str] = None
    foto_file_ids: Optional[List[str]] = None
    nc_classificacao: Optional[str] = None
    acao_imediata: Optional[str] = None
    instrumento_id: Optional[str] = None   # if set, calibration status is verified


# ─── cq_rncs ──────────────────────────────────────────────────────────────────

class RNCCreate(BaseModel):
    classificacao: str                    # critica | maior | menor
    origem: str                           # recepcao_mp | recepcao_embalagem | processo_manipulacao | processo_envase | produto_acabado
    descricao: str
    disposicao_imediata: str             # devolucao | descarte | reprocesso | concessao  — OBRIGATÓRIO
    ra_id: Optional[str] = None
    ck_id: Optional[str] = None
    lote_id: Optional[str] = None
    lote_numero: Optional[str] = None
    item_nome: Optional[str] = None
    fornecedor_id: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    quantidade_afetada: Optional[float] = None
    unidade: Optional[str] = None
    responsavel_id: Optional[str] = None
    responsavel_nome: Optional[str] = None
    prazo_resolucao: Optional[str] = None  # ISO date


class RNCEncerrarInput(BaseModel):
    capa_descricao: Optional[str] = None
    evidencia_resolucao: Optional[str] = None
    observacoes: Optional[str] = None
    status_final: str = "encerrada"       # encerrada | encerrada_concessao


# ─── cq_retencoes ─────────────────────────────────────────────────────────────

class RetencaoCreate(BaseModel):
    tipo: str                             # mp | fragrancia | produto_acabado
    ra_id: Optional[str] = None
    lote_id: Optional[str] = None
    lote_numero: Optional[str] = None
    item_nome: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    quantidade_retida: Optional[float] = None
    unidade: Optional[str] = None
    localizacao_fisica: Optional[str] = None
    data_coleta: Optional[str] = None     # ISO date; defaults to today
    # data_limite_guarda is CALCULATED — not accepted from client


# ─── cq_instrumentos ──────────────────────────────────────────────────────────

class InstrumentoCreate(BaseModel):
    nome: str
    codigo_interno: str
    tipo: str                             # phmetro | balanca | torquimetro | densimetro | termohigrometro
    localizacao: Optional[str] = None
    frequencia_calibracao_dias: int = 365
    ultima_calibracao: Optional[str] = None  # ISO date
    certificado_file_id: Optional[str] = None


class CalibraHistoricoEntry(BaseModel):
    data: str                             # ISO date
    laboratorio: Optional[str] = None
    certificado_numero: Optional[str] = None
    resultado: Optional[str] = None       # aprovado | reprovado


# ─── cq_status_lote ───────────────────────────────────────────────────────────
# This collection is immutable and written only by _registrar_status_lote().
# Valid lote statuses:
LOTE_STATUSES = {
    "quarentena", "em_analise", "aprovado", "reprovado",
    "concessao", "reprocesso", "devolvido", "descartado",
}


# ══════════════════════════════════════════════════════════════════════════════
#   INDEX CREATION (called from server.py startup)
# ══════════════════════════════════════════════════════════════════════════════

async def create_cq_indexes():
    """Create all CQ module indexes. Called once during server startup."""
    cq_collections = [
        "cq_registros_analise",
        "cq_checklists",
        "cq_rncs",
        "cq_retencoes",
        "cq_instrumentos",
        "cq_status_lote",
    ]
    for col_name in cq_collections:
        await db[col_name].create_index("tenant_id")
        await db[col_name].create_index([("tenant_id", 1), ("created_at", -1)])

    # RA-specific
    await db.cq_registros_analise.create_index(
        [("tenant_id", 1), ("numero_ra", 1)], unique=True, sparse=True
    )
    await db.cq_registros_analise.create_index([("tenant_id", 1), ("lote_id", 1)])
    await db.cq_registros_analise.create_index([("tenant_id", 1), ("status", 1)])
    await db.cq_registros_analise.create_index([("tenant_id", 1), ("tipo", 1)])

    # RNC-specific
    await db.cq_rncs.create_index(
        [("tenant_id", 1), ("numero_rnc", 1)], unique=True, sparse=True
    )
    await db.cq_rncs.create_index([("tenant_id", 1), ("status", 1)])
    await db.cq_rncs.create_index([("tenant_id", 1), ("classificacao", 1)])

    # Retenção-specific
    await db.cq_retencoes.create_index(
        [("tenant_id", 1), ("numero_ret", 1)], unique=True, sparse=True
    )
    await db.cq_retencoes.create_index([("tenant_id", 1), ("data_limite_guarda", 1)])
    await db.cq_retencoes.create_index([("tenant_id", 1), ("status", 1)])

    # Instrumento-specific
    await db.cq_instrumentos.create_index(
        [("tenant_id", 1), ("codigo_interno", 1)], unique=True, sparse=True
    )
    await db.cq_instrumentos.create_index([("tenant_id", 1), ("proxima_calibracao", 1)])
    await db.cq_instrumentos.create_index([("tenant_id", 1), ("status", 1)])

    # Status lote
    await db.cq_status_lote.create_index([("tenant_id", 1), ("lote_id", 1)])

    # Checklist
    await db.cq_checklists.create_index([("tenant_id", 1), ("op_id", 1)])
    await db.cq_checklists.create_index([("tenant_id", 1), ("tipo", 1)])

    logger.info("CQ module indexes created")


# ══════════════════════════════════════════════════════════════════════════════
#   INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _registrar_status_lote(
    *,
    tenant_id: str,
    lote_id: str,
    lote_numero: str,
    status_anterior: Optional[str],
    status_novo: str,
    motivo: Optional[str],
    user: dict,
    ra_id: Optional[str] = None,
    rnc_id: Optional[str] = None,
) -> dict:
    """Append an immutable lote-status-change record."""
    entry = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "lote_id": lote_id,
        "lote_numero": lote_numero,
        "status_anterior": status_anterior,
        "status_novo": status_novo,
        "motivo": motivo,
        "ra_id": ra_id,
        "rnc_id": rnc_id,
        "alterado_por_id": user["id"],
        "alterado_por_nome": user.get("name", ""),
        "created_at": now_iso(),
    }
    await db.cq_status_lote.insert_one(entry)
    return entry


async def _criar_ret_auto(tenant_id: str, ra: dict, user: dict) -> dict:
    """
    Auto-create a retention sample when an RA is approved.

    data_limite_guarda:
      recepcao_mp / recepcao_embalagem → nf_data + 180 days
      bulk_piloto / produto_acabado    → data_validade_fornecedor + 180 days
    """
    numero_ret = await _next_ret_number(tenant_id)

    if ra["tipo"] in ("recepcao_mp", "recepcao_embalagem"):
        tipo_ret = "mp"
        base_date = ra.get("nf_data") or ra.get("created_at")
    else:
        tipo_ret = "produto_acabado"
        base_date = ra.get("data_validade_fornecedor") or ra.get("created_at")

    ret = {
        "id": new_id(),
        "numero_ret": numero_ret,
        "tenant_id": tenant_id,
        "tipo": tipo_ret,
        "ra_id": ra["id"],
        "lote_id": ra.get("lote_id"),
        "lote_numero": ra.get("lote_numero"),
        "item_nome": ra.get("item_nome"),
        "fornecedor_nome": ra.get("fornecedor_nome"),
        "quantidade_retida": ra.get("quantidade_recebida"),
        "unidade": ra.get("unidade"),
        "localizacao_fisica": None,
        "data_coleta": now_iso()[:10],
        "data_limite_guarda": _add_days_iso(base_date, 180),
        "status": "em_guarda",
        "created_at": now_iso(),
    }
    await db.cq_retencoes.insert_one(ret)
    return ret


async def _criar_rnc_auto(
    tenant_id: str,
    ra: dict,
    disposicao_imediata: str,
    user: dict,
) -> dict:
    """Auto-create an RNC when an RA is rejected."""
    numero_rnc = await _next_rnc_number(tenant_id)

    rnc = {
        "id": new_id(),
        "numero_rnc": numero_rnc,
        "tenant_id": tenant_id,
        "status": "aberta",
        "classificacao": "maior",
        "origem": ra["tipo"],
        "descricao": (
            f"RA {ra['numero_ra']} reprovado — resultado geral não conforme. "
            f"Item: {ra.get('item_nome') or '—'}. Lote: {ra.get('lote_numero') or '—'}."
        ),
        "ra_id": ra["id"],
        "ck_id": None,
        "lote_id": ra.get("lote_id"),
        "lote_numero": ra.get("lote_numero"),
        "item_nome": ra.get("item_nome"),
        "fornecedor_id": ra.get("fornecedor_id"),
        "fornecedor_nome": ra.get("fornecedor_nome"),
        "quantidade_afetada": ra.get("quantidade_recebida"),
        "unidade": ra.get("unidade"),
        "fotos_file_ids": [],
        "disposicao_imediata": disposicao_imediata,
        "responsavel_id": user["id"],
        "responsavel_nome": user.get("name", ""),
        "prazo_resolucao": None,
        "comunicado_fornecedor_enviado": False,
        "comunicado_enviado_em": None,
        "resposta_fornecedor": None,
        "capa_descricao": None,
        "evidencia_resolucao": None,
        "encerrado_por_id": None,
        "encerrado_em": None,
        "created_at": now_iso(),
        "log_auditoria": [],
    }
    await db.cq_rncs.insert_one(rnc)
    return rnc


async def _buscar_parametros_ft(tenant_id: str, item_id: Optional[str]) -> List[dict]:
    """
    Try to load quality specs from the latest approved Ficha Técnica for item_id.
    Returns an empty list if the FT is not found — analyst fills manually.
    """
    if not item_id:
        return []

    docs = await db.pd_documents.find(
        {
            "tenant_id": tenant_id,
            "doc_type": "ficha_tecnica",
            "item_id": item_id,
            "status": "aprovado",
        },
        {"_id": 0},
    ).sort("created_at", -1).limit(1).to_list(1)

    if not docs:
        return []

    doc = docs[0]
    params: List[dict] = []

    # Walk known parameter containers in FT documents
    for field_name in ("parametros_in_process", "especificacoes_produto_acabado"):
        specs = doc.get(field_name)
        if not isinstance(specs, dict):
            continue
        for key, val in specs.items():
            if not isinstance(val, dict):
                continue
            params.append({
                "id": new_id(),
                "nome": val.get("label") or key,
                "unidade": val.get("unidade"),
                "metodo": val.get("metodo"),
                "especificacao_min": val.get("min") or val.get("especificacao_min"),
                "especificacao_max": val.get("max") or val.get("especificacao_max"),
                "resultado": None,
                "conforme": None,
                "observacao": None,
            })
        if params:
            break

    return params


# ══════════════════════════════════════════════════════════════════════════════
#   COA HTML / PDF GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _build_coa_html(ra: dict, tipo_coa: str, empresa: str) -> str:
    """Build a complete, self-contained HTML document for the CoA."""

    watermark_css = (
        """
        body::before {
            content: "DOCUMENTO CONTROLADO — não copiar";
            position: fixed;
            top: 42%; left: -18%; width: 140%;
            text-align: center;
            font-size: 2.2em; font-weight: bold;
            color: rgba(180, 0, 0, 0.10);
            transform: rotate(-32deg);
            z-index: 0; pointer-events: none;
            white-space: nowrap;
        }
        """
        if tipo_coa == "comercial"
        else ""
    )

    status_labels = {
        "aprovado": "APROVADO",
        "concessao": "APROVADO POR CONCESSÃO",
        "reprovado": "REPROVADO",
    }
    status_label = status_labels.get(ra.get("status", ""), (ra.get("status") or "").upper())

    resultado_geral = ra.get("resultado_geral") or "—"
    rg_color = (
        "#1a7f37" if resultado_geral == "conforme"
        else "#cf222e" if resultado_geral == "nao_conforme"
        else "#666"
    )
    rg_label = (
        "CONFORME" if resultado_geral == "conforme"
        else "NÃO CONFORME" if resultado_geral == "nao_conforme"
        else resultado_geral.upper()
    )

    params_rows = ""
    for p in ra.get("parametros", []):
        resultado = p.get("resultado")
        conforme = p.get("conforme")
        if conforme is True:
            cell_color, badge = "#1a7f37", "✓ CONFORME"
        elif conforme is False:
            cell_color, badge = "#cf222e", "✗ NÃO CONFORME"
        else:
            cell_color, badge = "#555", "—"

        mn = p.get("especificacao_min")
        mx = p.get("especificacao_max")
        if mn is not None and mx is not None:
            spec_range = f"{mn} – {mx}"
        elif mn is not None:
            spec_range = f"≥ {mn}"
        elif mx is not None:
            spec_range = f"≤ {mx}"
        else:
            spec_range = "—"

        params_rows += f"""
        <tr>
            <td>{p.get('nome') or '—'}</td>
            <td>{p.get('unidade') or '—'}</td>
            <td>{p.get('metodo') or '—'}</td>
            <td>{spec_range}</td>
            <td style="color:{cell_color};font-weight:600;">{resultado if resultado is not None else '—'}</td>
            <td style="color:{cell_color};font-weight:600;">{badge}</td>
        </tr>"""

    if not params_rows:
        params_rows = (
            '<tr><td colspan="6" style="text-align:center;color:#999;padding:16px;">'
            "Nenhum parâmetro registrado</td></tr>"
        )

    data_analise = ra.get("data_analise") or (ra.get("updated_at") or "")[:10]
    gerado_em = now_iso()[:10]

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<title>CoA — {ra.get('numero_ra', '')}</title>
<style>
{watermark_css}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11pt; color: #1c1c1e;
    padding: 36px 40px; position: relative; z-index: 1;
}}
h1 {{ font-size: 20pt; text-align: center; margin-bottom: 2px; }}
.subtitle {{ text-align: center; font-size: 10pt; color: #555; margin-bottom: 28px; }}
.section {{ margin-bottom: 22px; }}
.section h2 {{
    font-size: 10pt; text-transform: uppercase; letter-spacing: 0.6px;
    background: #f3f4f6; border-left: 4px solid #2563eb;
    padding: 4px 10px; margin-bottom: 10px;
}}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 24px; }}
.field-label {{ font-size: 8.5pt; color: #666; margin-bottom: 1px; }}
.field-value {{ font-size: 10pt; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
thead th {{
    background: #2563eb; color: #fff;
    padding: 6px 8px; text-align: left; font-size: 9pt;
}}
tbody td {{ border-bottom: 1px solid #e5e7eb; padding: 5px 8px; vertical-align: middle; }}
tbody tr:nth-child(even) td {{ background: #f9fafb; }}
.resultado-geral {{
    margin-top: 16px; padding: 12px;
    border: 2px solid {rg_color}; border-radius: 6px;
    font-size: 13pt; font-weight: bold; text-align: center;
    color: {rg_color};
}}
.footer {{
    margin-top: 48px; display: flex;
    justify-content: space-between; align-items: flex-end;
}}
.assinatura {{
    width: 220px; text-align: center;
    border-top: 1px solid #555; padding-top: 4px;
    font-size: 9pt;
}}
.meta {{ font-size: 8pt; color: #aaa; text-align: right; line-height: 1.6; }}
</style>
</head>
<body>
<h1>{empresa}</h1>
<div class="subtitle">Certificado de Análise (CoA) — {tipo_coa.upper()}</div>

<div class="section">
  <h2>Identificação do Registro</h2>
  <div class="grid">
    <div><div class="field-label">Número RA</div><div class="field-value">{ra.get('numero_ra') or '—'}</div></div>
    <div><div class="field-label">Status</div><div class="field-value">{status_label}</div></div>
    <div><div class="field-label">Tipo de Análise</div><div class="field-value">{(ra.get('tipo') or '').replace('_', ' ').title()}</div></div>
    <div><div class="field-label">Data da Análise</div><div class="field-value">{data_analise or '—'}</div></div>
    <div><div class="field-label">Analista</div><div class="field-value">{ra.get('analista_nome') or '—'}</div></div>
  </div>
</div>

<div class="section">
  <h2>Identificação do Item / Lote</h2>
  <div class="grid">
    <div><div class="field-label">Item</div><div class="field-value">{ra.get('item_nome') or '—'}</div></div>
    <div><div class="field-label">Lote Interno</div><div class="field-value">{ra.get('lote_numero') or '—'}</div></div>
    <div><div class="field-label">Fornecedor</div><div class="field-value">{ra.get('fornecedor_nome') or '—'}</div></div>
    <div><div class="field-label">Lote Fornecedor</div><div class="field-value">{ra.get('numero_lote_fornecedor') or '—'}</div></div>
    <div><div class="field-label">Qtd. Recebida</div><div class="field-value">{ra.get('quantidade_recebida') or '—'} {ra.get('unidade') or ''}</div></div>
    <div><div class="field-label">NF</div><div class="field-value">{ra.get('nf_numero') or '—'}</div></div>
    <div><div class="field-label">Fabricação (Forn.)</div><div class="field-value">{ra.get('data_fabricacao_fornecedor') or '—'}</div></div>
    <div><div class="field-label">Validade (Forn.)</div><div class="field-value">{ra.get('data_validade_fornecedor') or '—'}</div></div>
  </div>
</div>

<div class="section">
  <h2>Resultados de Análise</h2>
  <table>
    <thead>
      <tr>
        <th>Parâmetro</th><th>Unidade</th><th>Método</th>
        <th>Especificação</th><th>Resultado</th><th>Conformidade</th>
      </tr>
    </thead>
    <tbody>
      {params_rows}
    </tbody>
  </table>
  <div class="resultado-geral">Resultado Geral: {rg_label}</div>
</div>

<div class="footer">
  <div>
    <div class="assinatura">
      <div style="height:44px;"></div>
      {ra.get('analista_nome') or 'Analista CQ'}
    </div>
    <div class="field-label" style="margin-top:4px;">Analista Responsável</div>
  </div>
  <div class="meta">
    Gerado em {gerado_em}<br/>
    {ra.get('numero_ra') or ''} — uso interno controlado
  </div>
</div>
</body>
</html>"""


def _html_to_pdf(html: str) -> Optional[bytes]:
    """Try WeasyPrint; return None if not installed."""
    try:
        from weasyprint import HTML as _WP  # type: ignore
        return _WP(string=html).write_pdf()
    except ImportError:
        return None
    except Exception as exc:
        logger.warning("WeasyPrint failed: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 2 — ENDPOINTS: Registro de Análise (RA)
# ══════════════════════════════════════════════════════════════════════════════

# ─── POST /api/cq/registros-analise ───────────────────────────────────────────
@cq_router.post("/registros-analise", status_code=201)
async def criar_ra(data: RACreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_ANALISTA)
    tenant_id = user["tenant_id"]

    if not data.lote_id:
        raise HTTPException(status_code=400, detail="lote_id é obrigatório")

    TIPOS_VALIDOS = {"recepcao_mp", "recepcao_embalagem", "bulk_piloto", "produto_acabado"}
    if data.tipo not in TIPOS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"tipo inválido. Valores aceitos: {sorted(TIPOS_VALIDOS)}",
        )

    # Build parametros list: explicit override > FT lookup > empty
    if data.parametros is not None:
        parametros = [
            {
                "id": p.id or new_id(),
                "nome": p.nome,
                "unidade": p.unidade,
                "metodo": p.metodo,
                "especificacao_min": p.especificacao_min,
                "especificacao_max": p.especificacao_max,
                "resultado": p.resultado,
                "conforme": p.conforme,
                "observacao": p.observacao,
            }
            for p in data.parametros
        ]
    else:
        parametros = await _buscar_parametros_ft(tenant_id, data.item_id)

    ra_id = new_id()
    numero_ra = await _next_ra_number(tenant_id)

    ra = {
        "id": ra_id,
        "numero_ra": numero_ra,
        "tenant_id": tenant_id,
        "tipo": data.tipo,
        "status": "rascunho",
        "lote_id": data.lote_id,
        "lote_numero": data.lote_numero,
        "item_id": data.item_id,
        "item_nome": data.item_nome,
        "item_tipo": data.item_tipo,
        "fornecedor_id": data.fornecedor_id,
        "fornecedor_nome": data.fornecedor_nome,
        "nf_numero": data.nf_numero,
        "nf_data": data.nf_data,
        "quantidade_recebida": data.quantidade_recebida,
        "unidade": data.unidade,
        "numero_lote_fornecedor": data.numero_lote_fornecedor,
        "data_fabricacao_fornecedor": data.data_fabricacao_fornecedor,
        "data_validade_fornecedor": data.data_validade_fornecedor,
        "parametros": parametros,
        "resultado_geral": None,
        "analista_id": user["id"],
        "analista_nome": user.get("name", ""),
        "data_analise": None,
        "fotos_file_ids": [],
        "amostra_retencao_id": None,
        "rnc_id": None,
        "coa_gerado": False,
        "coa_enviado_cliente": False,
        "coa_enviado_em": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "log_auditoria": [],
    }

    await db.cq_registros_analise.insert_one(ra)

    # Register lote entering quarantine/analysis
    await _registrar_status_lote(
        tenant_id=tenant_id,
        lote_id=data.lote_id,
        lote_numero=data.lote_numero,
        status_anterior=None,
        status_novo="em_analise",
        motivo=f"RA {numero_ra} criado",
        user=user,
        ra_id=ra_id,
    )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="create",
        entity_type="cq_ra",
        entity_id=ra_id,
        after=ra,
    )

    if _broadcast_event:
        await _broadcast_event(
            tenant_id, "cq_ra_created", {"ra_id": ra_id, "numero_ra": numero_ra}
        )

    # CQ-01 / CQ-02 — notify QC analyst of new reception RA
    _RECEPCAO_TO_CQ: Dict[str, tuple] = {
        "recepcao_mp":        ("CQ-01", "Analisar recebimento MP/Fragrância"),
        "recepcao_embalagem": ("CQ-02", "Inspecionar recebimento de Embalagem"),
    }
    if data.tipo in _RECEPCAO_TO_CQ:
        cq_code, cq_titulo = _RECEPCAO_TO_CQ[data.tipo]
        await create_workflow_task(
            tenant_id=tenant_id,
            entity_type="cq_ra",
            entity_id=ra_id,
            title=f"{cq_code} {cq_titulo} — {numero_ra}",
            description=(
                f"RA {numero_ra} criado. "
                f"Item: {data.item_nome or '—'}. "
                f"Fornecedor: {data.fornecedor_nome or '—'}. "
                f"Qtd: {data.quantidade_recebida or '—'} {data.unidade or ''}."
            ),
            category="qa",
            blocking=False,
            due_in_days=1,
            created_by=user,
        )

    ra.pop("_id", None)
    return ra


# ─── GET /api/cq/registros-analise ────────────────────────────────────────────
@cq_router.get("/registros-analise")
async def listar_ras(
    request: Request,
    status: Optional[str] = Query(None),
    tipo: Optional[str] = Query(None),
    lote_id: Optional[str] = Query(None),
    fornecedor_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        query["status"] = status
    if tipo:
        query["tipo"] = tipo
    if lote_id:
        query["lote_id"] = lote_id
    if fornecedor_id:
        query["fornecedor_id"] = fornecedor_id

    cursor = (
        db.cq_registros_analise.find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    total = await db.cq_registros_analise.count_documents(query)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ─── GET /api/cq/registros-analise/{ra_id} ────────────────────────────────────
@cq_router.get("/registros-analise/{ra_id}")
async def detalhe_ra(ra_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)

    ra = await db.cq_registros_analise.find_one(
        {"id": ra_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not ra:
        raise HTTPException(status_code=404, detail="Registro de Análise não encontrado")
    return ra


# ─── PUT /api/cq/registros-analise/{ra_id}/parametros ─────────────────────────
@cq_router.put("/registros-analise/{ra_id}/parametros")
async def salvar_parametros(ra_id: str, data: RAParametrosUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_ANALISTA)
    tenant_id = user["tenant_id"]

    ra = await db.cq_registros_analise.find_one(
        {"id": ra_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not ra:
        raise HTTPException(status_code=404, detail="Registro de Análise não encontrado")
    if ra["status"] in ("aprovado", "reprovado", "concessao"):
        raise HTTPException(
            status_code=409,
            detail=f"RA já encerrado com status '{ra['status']}' — use o campo observacao para registrar correções",
        )

    resultado_map = {p.id: p for p in data.parametros}

    updated_params = []
    for p in ra.get("parametros", []):
        upd = resultado_map.get(p["id"])
        if upd is None:
            updated_params.append(p)
            continue

        resultado = upd.resultado
        conforme: Optional[bool] = None

        if resultado is not None:
            # Numeric conformity check
            try:
                resultado_num = float(resultado)
                mn = p.get("especificacao_min")
                mx = p.get("especificacao_max")
                if mn is not None and mx is not None:
                    conforme = mn <= resultado_num <= mx
                elif mn is not None:
                    conforme = resultado_num >= mn
                elif mx is not None:
                    conforme = resultado_num <= mx
            except (TypeError, ValueError):
                pass  # Non-numeric → system cannot auto-calculate conforme

        updated_params.append({
            **p,
            "resultado": resultado,
            "conforme": conforme,
            "observacao": (
                upd.observacao if upd.observacao is not None else p.get("observacao")
            ),
        })

    # Auto-calculate resultado_geral
    checked = [p for p in updated_params if p.get("conforme") is not None]
    if checked:
        resultado_geral: Optional[str] = (
            "conforme" if all(p["conforme"] for p in checked) else "nao_conforme"
        )
    else:
        resultado_geral = None

    now = now_iso()
    await db.cq_registros_analise.update_one(
        {"id": ra_id},
        {
            "$set": {
                "parametros": updated_params,
                "resultado_geral": resultado_geral,
                "status": "em_analise",
                "data_analise": now[:10],
                "updated_at": now,
            }
        },
    )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="update_parametros",
        entity_type="cq_ra",
        entity_id=ra_id,
        before={"resultado_geral": ra.get("resultado_geral")},
        after={"resultado_geral": resultado_geral},
    )

    ra_updated = await db.cq_registros_analise.find_one({"id": ra_id}, {"_id": 0})
    return ra_updated


# ─── POST /api/cq/registros-analise/{ra_id}/aprovar ───────────────────────────
@cq_router.post("/registros-analise/{ra_id}/aprovar")
async def aprovar_ra(ra_id: str, data: AprovarInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    ra = await db.cq_registros_analise.find_one(
        {"id": ra_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not ra:
        raise HTTPException(status_code=404, detail="Registro de Análise não encontrado")
    if ra["status"] in ("aprovado", "reprovado", "concessao"):
        raise HTTPException(
            status_code=409,
            detail=f"RA já encerrado com status '{ra['status']}'",
        )

    DECISOES_VALIDAS = {"aprovado", "reprovado", "concessao"}
    if data.decisao not in DECISOES_VALIDAS:
        raise HTTPException(
            status_code=422,
            detail=f"decisao inválida. Valores aceitos: {sorted(DECISOES_VALIDAS)}",
        )

    if data.decisao == "concessao" and not data.justificativa_concessao:
        raise HTTPException(
            status_code=422,
            detail="justificativa_concessao é obrigatória quando decisao='concessao'",
        )

    if data.decisao == "reprovado":
        if not data.disposicao_imediata:
            raise HTTPException(
                status_code=422,
                detail="disposicao_imediata é obrigatória quando decisao='reprovado'",
            )
        DISPOSICOES_VALIDAS = {"devolucao", "descarte", "reprocesso", "concessao"}
        if data.disposicao_imediata not in DISPOSICOES_VALIDAS:
            raise HTTPException(
                status_code=422,
                detail=f"disposicao_imediata inválida. Valores aceitos: {sorted(DISPOSICOES_VALIDAS)}",
            )

    if data.instrumento_usado_id:
        instrumento = await db.cq_instrumentos.find_one(
            {"id": data.instrumento_usado_id, "tenant_id": tenant_id},
            {"_id": 0},
        )
        if not instrumento:
            raise HTTPException(status_code=404, detail="Instrumento usado na analise nao encontrado")
        status_real = _calc_instrumento_status(instrumento)
        if status_real != "calibrado":
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "hard_stop_instrumento_nao_calibrado",
                    "message": f"Instrumento '{instrumento.get('nome', data.instrumento_usado_id)}' esta com status '{status_real}'. Calibracao valida e obrigatoria para liberar RA.",
                },
            )

    now = now_iso()
    status_anterior = ra["status"]
    status_novo = data.decisao

    log_entry: Dict[str, Any] = {
        "campo": "status",
        "de": status_anterior,
        "para": status_novo,
        "usuario_id": user["id"],
        "usuario_nome": user.get("name", ""),
        "datetime": now,
    }
    if data.observacoes:
        log_entry["observacoes"] = data.observacoes
    if data.justificativa_concessao:
        log_entry["justificativa_concessao"] = data.justificativa_concessao

    await db.cq_registros_analise.update_one(
        {"id": ra_id},
        {
            "$set": {
                "status": status_novo,
                "instrumento_usado_id": data.instrumento_usado_id,
                "updated_at": now,
            },
            "$push": {"log_auditoria": log_entry},
        },
    )

    # Audit lote status change
    lote_status_map = {
        "aprovado": "aprovado",
        "reprovado": "reprovado",
        "concessao": "concessao",
    }
    await _registrar_status_lote(
        tenant_id=tenant_id,
        lote_id=ra["lote_id"],
        lote_numero=ra.get("lote_numero", ""),
        status_anterior="em_analise",
        status_novo=lote_status_map[data.decisao],
        motivo=data.observacoes or f"Decisão CQ: {data.decisao}",
        user=user,
        ra_id=ra_id,
    )

    posicao_cq = "aprovado" if data.decisao in ("aprovado", "concessao") else "reprovado"
    if ra.get("item_id"):
        await db.estoque_items.update_one(
            {"id": ra["item_id"], "tenant_id": tenant_id},
            {
                "$set": {
                    "posicao_cq": posicao_cq,
                    "cq_status": data.decisao,
                    "cq_lote_id": ra.get("lote_id"),
                    "cq_ra_id": ra_id,
                    "cq_decidido_em": now,
                    "updated_at": now,
                }
            },
        )

    if ra.get("recebimento_id"):
        await db.recebimentos.update_one(
            {
                "id": ra["recebimento_id"],
                "tenant_id": tenant_id,
                "items.ra_id": ra_id,
            },
            {
                "$set": {
                    "items.$.ra_status": data.decisao,
                    "items.$.cq_decidido_em": now,
                    "updated_at": now,
                }
            },
        )

    ret_id: Optional[str] = None
    rnc_id: Optional[str] = None

    if data.decisao in ("aprovado", "concessao"):
        # Auto-create retention sample
        ret = await _criar_ret_auto(tenant_id, ra, user)
        ret_id = ret["id"]
        await db.cq_registros_analise.update_one(
            {"id": ra_id}, {"$set": {"amostra_retencao_id": ret_id}}
        )

        # Create CQ-12 task if any client in the tenant requires CoA delivery
        coa_client = await db.crm_clients.find_one(
            {"tenant_id": tenant_id, "requer_coa": True},
            {"_id": 0, "id": 1, "nome_empresa": 1},
        )
        if coa_client:
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_ra",
                entity_id=ra_id,
                title=f"CQ-12 Enviar CoA — {ra.get('numero_ra')}",
                description=(
                    f"CoA do RA {ra.get('numero_ra')} deve ser enviado ao cliente "
                    f"{coa_client.get('nome_empresa', '')} (requer_coa=true)."
                ),
                category="qa",
                blocking=False,
                due_in_days=2,
                created_by=user,
            )

    elif data.decisao == "reprovado":
        # Auto-create RNC
        rnc = await _criar_rnc_auto(tenant_id, ra, data.disposicao_imediata, user)
        rnc_id = rnc["id"]
        await db.cq_registros_analise.update_one(
            {"id": ra_id}, {"$set": {"rnc_id": rnc_id}}
        )

        # Create CQ-11 task for RNC treatment
        await create_workflow_task(
            tenant_id=tenant_id,
            entity_type="cq_ra",
            entity_id=ra_id,
            title=f"CQ-11 Tratar RNC — {rnc['numero_rnc']}",
            description=(
                f"RA {ra.get('numero_ra')} reprovado. RNC {rnc['numero_rnc']} aberta. "
                f"Disposição imediata: {data.disposicao_imediata}. "
                f"Item: {ra.get('item_nome') or '—'}."
            ),
            category="qa",
            blocking=True,
            due_in_days=3,
            created_by=user,
        )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="aprovar",
        entity_type="cq_ra",
        entity_id=ra_id,
        before={"status": status_anterior},
        after={"status": status_novo, "ret_id": ret_id, "rnc_id": rnc_id},
    )

    if _broadcast_event:
        await _broadcast_event(
            tenant_id,
            "cq_ra_aprovado",
            {"ra_id": ra_id, "status": status_novo, "rnc_id": rnc_id, "ret_id": ret_id},
        )

    ra_updated = await db.cq_registros_analise.find_one({"id": ra_id}, {"_id": 0})
    return ra_updated


# ─── GET /api/cq/registros-analise/{ra_id}/coa ────────────────────────────────
@cq_router.get("/registros-analise/{ra_id}/coa")
async def gerar_coa(
    ra_id: str,
    request: Request,
    tipo_coa: str = Query("interno", description="interno | comercial"),
):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    tenant_id = user["tenant_id"]

    ra = await db.cq_registros_analise.find_one(
        {"id": ra_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not ra:
        raise HTTPException(status_code=404, detail="Registro de Análise não encontrado")

    if ra["status"] not in ("aprovado", "concessao"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"CoA só pode ser gerado para RA com status 'aprovado' ou 'concessao' "
                f"(status atual: '{ra['status']}')"
            ),
        )

    if tipo_coa not in ("interno", "comercial"):
        raise HTTPException(
            status_code=400,
            detail="tipo_coa deve ser 'interno' ou 'comercial'",
        )

    # Fetch company name from tenant
    tenant_doc = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "nome": 1, "name": 1}
    )
    empresa = ""
    if tenant_doc:
        empresa = tenant_doc.get("nome") or tenant_doc.get("name") or ""
    if not empresa:
        empresa = "Laboratório CQ"

    html_content = _build_coa_html(ra, tipo_coa, empresa)

    # Mark CoA as generated (best-effort — do not block response on failure)
    await db.cq_registros_analise.update_one(
        {"id": ra_id}, {"$set": {"coa_gerado": True, "updated_at": now_iso()}}
    )

    pdf_bytes = _html_to_pdf(html_content)
    if pdf_bytes:
        filename = f"CoA-{ra['numero_ra']}-{tipo_coa}.pdf"
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # WeasyPrint not installed → return HTML (fully functional in browser)
    return HTMLResponse(content=html_content, status_code=200)


# ─── POST /api/cq/registros-analise/{ra_id}/registrar-envio-coa ───────────────
@cq_router.post("/registros-analise/{ra_id}/registrar-envio-coa")
async def registrar_envio_coa(
    ra_id: str, data: RegistrarEnvioCoAInput, request: Request
):
    user = await get_current_user(request)
    require_roles(user, CQ_ANALISTA)
    tenant_id = user["tenant_id"]

    ra = await db.cq_registros_analise.find_one(
        {"id": ra_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not ra:
        raise HTTPException(status_code=404, detail="Registro de Análise não encontrado")
    if ra["status"] not in ("aprovado", "concessao"):
        raise HTTPException(
            status_code=400,
            detail="CoA só pode ser registrado para RA aprovado ou aprovado por concessão",
        )

    now = now_iso()
    log_entry = {
        "campo": "coa_enviado_cliente",
        "de": ra.get("coa_enviado_cliente", False),
        "para": True,
        "usuario_id": user["id"],
        "usuario_nome": user.get("name", ""),
        "datetime": now,
        "cliente_id": data.cliente_id,
        "cliente_nome": data.cliente_nome,
        "canal": data.canal,
        "observacoes": data.observacoes,
    }

    await db.cq_registros_analise.update_one(
        {"id": ra_id},
        {
            "$set": {
                "coa_enviado_cliente": True,
                "coa_enviado_em": now,
                "updated_at": now,
            },
            "$push": {"log_auditoria": log_entry},
        },
    )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="registrar_envio_coa",
        entity_type="cq_ra",
        entity_id=ra_id,
        after={"coa_enviado_cliente": True, "coa_enviado_em": now},
    )

    ra_updated = await db.cq_registros_analise.find_one({"id": ra_id}, {"_id": 0})
    return ra_updated


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 3 — CHECKLISTS CK-1 A CK-8 (modelos + helpers + endpoints)
# ══════════════════════════════════════════════════════════════════════════════

# ─── Additional Pydantic models ────────────────────────────────────────────────

class AprovarChecklistInput(BaseModel):
    decisao: str                              # aprovado | reprovado
    observacoes: Optional[str] = None


class RNCUpdate(BaseModel):
    classificacao: Optional[str] = None
    descricao: Optional[str] = None
    responsavel_id: Optional[str] = None
    responsavel_nome: Optional[str] = None
    prazo_resolucao: Optional[str] = None
    capa_descricao: Optional[str] = None
    observacao: Optional[str] = None


class RNCEncerrarPayload(BaseModel):
    evidencia_resolucao: str                  # REQUIRED — 422 if missing
    com_concessao: bool = False
    autorizacao_concessao: Optional[str] = None  # required if com_concessao=True
    observacoes: Optional[str] = None


class ComunicarFornecedorInput(BaseModel):
    email_destinatario: Optional[str] = None
    observacoes: Optional[str] = None


# ─── Date helper ──────────────────────────────────────────────────────────────

def _add_business_days(base: datetime, days: int) -> str:
    """Add N business days skipping weekends (no public holiday calendar)."""
    result = base
    added = 0
    while added < days:
        result += timedelta(days=1)
        if result.weekday() < 5:
            added += 1
    return result.date().isoformat()


# ─── CK helpers ────────────────────────────────────────────────────────────────

def _ck_tipo_to_origem(tipo: str) -> str:
    return {
        "CK-1": "recepcao_embalagem",
        "CK-2": "recepcao_mp",
        "CK-3": "processo_manipulacao",
        "CK-4": "processo_envase",
        "CK-5": "processo_envase",
        "CK-6": "processo_envase",
        "CK-7": "produto_acabado",
        "CK-8": "processo_manipulacao",
    }.get(tipo, "processo_manipulacao")


def _make_item(
    secao: str,
    ordem: int,
    descricao: str,
    tipo_resposta: str = "snna",
    somente_cq: bool = False,
) -> dict:
    return {
        "id": new_id(),
        "secao": secao,
        "ordem": ordem,
        "descricao": descricao,
        "tipo_resposta": tipo_resposta,
        "somente_cq": somente_cq,
        "resposta": None,
        "conforme": None,
        "observacao": None,
        "foto_file_ids": [],
        "nc_classificacao": None,
        "acao_imediata": None,
    }


# ─── CK-1 template (adaptive seção 4 by subtipo) ──────────────────────────────

_CK1_SECAO4_LABEL = {
    "frasco":   "4. Frascos",
    "tampa":    "4. Tampas",
    "rotulo":   "4. Rótulos",
    "valvula":  "4. Válvulas",
    "cartucho": "4. Cartuchos",
    "caixa":    "4. Caixas Master",
}
_CK1_SECAO4_ITENS: Dict[str, List[tuple]] = {
    "frasco": [
        ("Volume nominal confere com a especificação", "snna"),
        ("Cor/transparência confere com o padrão aprovado", "snna"),
        ("Pescoço e encaixe compatíveis com a tampa especificada", "snna"),
        ("Ausência de defeitos visuais (bolhas, manchas, deformidades)", "snna"),
        ("Peso do frasco vazio dentro da tolerância (g)", "numerico"),
    ],
    "tampa": [
        ("Rosca compatível com o frasco especificado", "snna"),
        ("Torque de abertura dentro do especificado (N.m)", "numerico"),
        ("Ausência de defeitos visuais (rebarbas, rachaduras, cor incorreta)", "snna"),
        ("Vedação adequada — sem vazamento ao pressionar", "snna"),
    ],
    "rotulo": [
        ("Texto INCI correto conforme aprovação ANVISA", "snna"),
        ("CNPJ e razão social da empresa corretos", "snna"),
        ("Código de barras legível (verificado com scanner)", "snna"),
        ("Cor e layout conformes com a arte aprovada", "snna"),
        ("Informações obrigatórias presentes (lote, validade, modo de uso)", "snna"),
    ],
    "valvula": [
        ("Pressão de spray conforme especificação", "snna"),
        ("Vedação sem vazamento ao pressionar", "snna"),
        ("Compatibilidade dimensional com o frasco", "snna"),
    ],
    "cartucho": [
        ("Dimensões conferem com o frasco especificado", "snna"),
        ("Impressão correta (layout, textos, cores)", "snna"),
        ("Sem amassados, rasgos ou danos na impressão", "snna"),
        ("Janela de visualização posicionada corretamente (se aplicável)", "snna"),
    ],
    "caixa": [
        ("Dimensões corretas para unitização no palete", "snna"),
        ("Impressão e identificação corretas", "snna"),
        ("Resistência e integridade da caixa adequadas", "snna"),
        ("Quantidade por caixa confere com a especificação", "snna"),
    ],
}


def _itens_ck1(subtipo: str) -> List[dict]:
    itens = [
        _make_item("1. Documentação",  1, "NF presente e conferida com o pedido de compra"),
        _make_item("1. Documentação",  2, "Dados da NF corretos (CNPJ, produto, quantidade)"),
        _make_item("1. Documentação",  3, "Laudo ou CoA do fornecedor disponível"),
        _make_item("2. Transporte",    4, "Veículo em condições adequadas de higiene"),
        _make_item("2. Transporte",    5, "Embalagens sem danos causados pelo transporte"),
        _make_item("2. Transporte",    6, "Sem odores ou evidências de contaminação"),
        _make_item("3. AQL NBR 5426", 7, "Plano de amostragem definido conforme NBR 5426"),
        _make_item("3. AQL NBR 5426", 8, "Tamanho de amostra confere com o plano"),
        _make_item("3. AQL NBR 5426", 9, "Critério de aceitação aplicado corretamente"),
        _make_item("3. AQL NBR 5426",10, "Resultado AQL: lote aceito?"),
    ]
    secao4 = _CK1_SECAO4_LABEL.get(subtipo, f"4. {subtipo.capitalize()}")
    for i, (desc, tipo_r) in enumerate(_CK1_SECAO4_ITENS.get(subtipo, []), start=11):
        itens.append(_make_item(secao4, i, desc, tipo_resposta=tipo_r))
    return itens


def _itens_ck2() -> List[dict]:
    return [
        _make_item("1. Recebimento", 1, "Nota Fiscal presente e conferida"),
        _make_item("1. Recebimento", 2, "Laudo do fornecedor (CoA) disponível"),
        _make_item("1. Recebimento", 3, "FISPQ (ficha de segurança) disponível"),
        _make_item("1. Recebimento", 4, "Embalagem íntegra — sem vazamentos ou danos"),
        _make_item("1. Recebimento", 5, "Identificação do produto visível e correta"),
        _make_item("1. Recebimento", 6, "Dentro do prazo de validade do fornecedor"),
        _make_item("1. Recebimento", 7, "Quantidade recebida confere com o pedido"),
        _make_item("1. Recebimento", 8, "Contraprova coletada e devidamente identificada"),
    ]


def _itens_ck3() -> List[dict]:
    return [
        _make_item("1. Higienização dos Tachos", 1, "Tacho lavado com água quente e detergente neutro"),
        _make_item("1. Higienização dos Tachos", 2, "Tacho enxaguado com água purificada"),
        _make_item("1. Higienização dos Tachos", 3, "Tacho sanitizado com álcool 70°"),
        _make_item("1. Higienização dos Tachos", 4, "Tacho seco — sem resíduos de umidade"),
        _make_item("2. Utensílios e Área",       5, "Utensílios (espátulas, batedores) higienizados"),
        _make_item("2. Utensílios e Área",       6, "Balança verificada e zerada"),
        _make_item("2. Utensílios e Área",       7, "Bancada e área de manipulação limpas e desinfetadas"),
        _make_item("2. Utensílios e Área",       8, "Sem materiais ou resíduos de outros produtos na área"),
        _make_item("3. Aprovação CQ",            9, "CQ verificou e aprova as condições para iniciar a manipulação?", somente_cq=True),
    ]


def _itens_ck4() -> List[dict]:
    return [
        _make_item("1. Limpeza de Equipamentos",   1, "Esteira de envase limpa e desinfetada"),
        _make_item("1. Limpeza de Equipamentos",   2, "Bico dosador limpo e sem resíduos do produto anterior"),
        _make_item("1. Limpeza de Equipamentos",   3, "Tampadora limpa e regulada"),
        _make_item("1. Limpeza de Equipamentos",   4, "Rotuladora limpa e sem resíduos de cola/rótulos anteriores"),
        _make_item("2. Calibração e Ferramentas",  5, "Dosadora calibrada e zerada para o produto"),
        _make_item("2. Calibração e Ferramentas",  6, "Torquímetro disponível e com calibração vigente"),
        _make_item("3. Aprovação CQ",              7, "CQ aprova as condições de higiene e setup para iniciar o envase?", somente_cq=True),
    ]


def _itens_ck5() -> List[dict]:
    return [
        # Setup checks
        _make_item("1. Setup",                  1,  "OP afixada na linha e conferida pelo operador"),
        _make_item("1. Setup",                  2,  "Produto e número de lote corretos conforme OP"),
        _make_item("1. Setup",                  3,  "Frasco correto conforme OP e especificação"),
        _make_item("1. Setup",                  4,  "Tampa correta conforme OP e especificação"),
        _make_item("1. Setup",                  5,  "Rótulo correto conforme OP e arte aprovada"),
        _make_item("1. Setup",                  6,  "Quantidade de insumos separados confere com a OP"),
        # 3 samples × 3 measurements
        _make_item("2. Medições — Amostra 1",   7,  "Amostra 1 — Peso (g)",     "numerico"),
        _make_item("2. Medições — Amostra 1",   8,  "Amostra 1 — Volume (mL)",  "numerico"),
        _make_item("2. Medições — Amostra 1",   9,  "Amostra 1 — Torque (N.m)", "numerico"),
        _make_item("3. Medições — Amostra 2",   10, "Amostra 2 — Peso (g)",     "numerico"),
        _make_item("3. Medições — Amostra 2",   11, "Amostra 2 — Volume (mL)",  "numerico"),
        _make_item("3. Medições — Amostra 2",   12, "Amostra 2 — Torque (N.m)", "numerico"),
        _make_item("4. Medições — Amostra 3",   13, "Amostra 3 — Peso (g)",     "numerico"),
        _make_item("4. Medições — Amostra 3",   14, "Amostra 3 — Volume (mL)",  "numerico"),
        _make_item("4. Medições — Amostra 3",   15, "Amostra 3 — Torque (N.m)", "numerico"),
        # CQ sign-off
        _make_item("5. Aprovação CQ",           16, "CQ aprova o First Article e libera a linha para produção?", somente_cq=True),
    ]


def _itens_ck6() -> List[dict]:
    return [
        _make_item("1. Identificação",        1,  "Linha identificada conforme OP (produto e lote visíveis)"),
        _make_item("1. Identificação",        2,  "Horário da ronda registrado conforme cronograma"),
        _make_item("2. Operadores / EPI",     3,  "Operadores com EPIs completos (touca, jaleco, luvas)"),
        _make_item("2. Operadores / EPI",     4,  "Não há operadores não autorizados na linha"),
        _make_item("3. Área",                 5,  "Área limpa e organizada"),
        _make_item("3. Área",                 6,  "Sem resíduos de produto ou material no chão"),
        _make_item("3. Área",                 7,  "Corredores desobstruídos e acesso à emergência livre"),
        _make_item("4. Documentos",           8,  "OP visível, atualizada e preenchida corretamente"),
        _make_item("4. Documentos",           9,  "CK-5 (First Article) aprovado e afixado na linha"),
        _make_item("5. Insumos",              10, "Insumos identificados com número de lote correto"),
        _make_item("5. Insumos",              11, "Sem insumos com prazo vencido na linha"),
        _make_item("5. Insumos",              12, "Sem mistura de lotes sem autorização"),
        _make_item("6. Produto em Processo",  13, "Peso do produto (g)",          "numerico"),
        _make_item("6. Produto em Processo",  14, "Volume do produto (mL)",       "numerico"),
        _make_item("6. Produto em Processo",  15, "Torque de fechamento (N.m)",   "numerico"),
        _make_item("6. Produto em Processo",  16, "Aspecto visual conforme padrão aprovado"),
        _make_item("7. Equipamentos",         17, "Dosadora operando sem falhas ou alarmes"),
        _make_item("7. Equipamentos",         18, "Tampadora operando corretamente"),
        _make_item("7. Equipamentos",         19, "Rotuladora operando corretamente"),
        _make_item("8. NCs Observadas",       20, "Há não conformidades identificadas nesta ronda?"),
    ]


def _itens_ck7() -> List[dict]:
    return [
        _make_item("1. Documentação",              1, "RA de produto acabado aprovado para este lote", somente_cq=True),
        _make_item("1. Documentação",              2, "Palete corretamente identificado (produto, lote, quantidade)"),
        _make_item("1. Documentação",              3, "Etiqueta 'APROVADO CQ' afixada visivelmente no palete"),
        _make_item("2. Integridade das Embalagens",4, "Embalagens sem amassados, rasgos ou danos visíveis"),
        _make_item("2. Integridade das Embalagens",5, "Rótulos aplicados corretamente e sem defeitos"),
        _make_item("2. Integridade das Embalagens",6, "Caixas master fechadas e identificadas"),
        _make_item("3. Conformidade da Unitização",7, "Quantidade de unidades confere com a OP"),
        _make_item("3. Conformidade da Unitização",8, "Palete filmado corretamente para transporte"),
        _make_item("3. Conformidade da Unitização",9, "Separação conforme pedido de expedição"),
    ]


def _itens_ck8() -> List[dict]:
    return [
        _make_item("1. Higiene das Instalações",     1,  "Instalações sanitárias limpas e abastecidas"),
        _make_item("1. Higiene das Instalações",     2,  "Vestiários organizados e limpos"),
        _make_item("1. Higiene das Instalações",     3,  "Almoxarifado organizado — sem materiais fora do lugar"),
        _make_item("2. Condições Ambientais",        4,  "Temperatura sala de envase (°C)",       "numerico"),
        _make_item("2. Condições Ambientais",        5,  "Umidade relativa sala de envase (%)",   "numerico"),
        _make_item("2. Condições Ambientais",        6,  "Temperatura sala de fragrâncias (°C)",  "numerico"),
        _make_item("3. Controle de Pragas",          7,  "Sem evidências de pragas (insetos, roedores)"),
        _make_item("3. Controle de Pragas",          8,  "Iscas e armadilhas presentes e íntegras"),
        _make_item("4. Verificação de Instrumentos", 9,  "Balança verificada com peso padrão — dentro da tolerância"),
        _make_item("4. Verificação de Instrumentos", 10, "pHmetro calibrado (buffers 4,00 e 7,00)"),
        _make_item("4. Verificação de Instrumentos", 11, "Termohigrômetro calibrado e funcionando"),
    ]


def _build_itens_para_checklist(tipo: str, subtipo_insumo: Optional[str] = None) -> List[dict]:
    builders = {
        "CK-2": _itens_ck2, "CK-3": _itens_ck3, "CK-4": _itens_ck4,
        "CK-5": _itens_ck5, "CK-6": _itens_ck6, "CK-7": _itens_ck7,
        "CK-8": _itens_ck8,
    }
    if tipo == "CK-1":
        return _itens_ck1(subtipo_insumo or "frasco")
    fn = builders.get(tipo)
    return fn() if fn else []


def _calc_ck5_averages(itens: List[dict]) -> dict:
    """Recalculate peso/volume/torque averages from all numeric CK-5 items."""
    pesos: List[float] = []
    volumes: List[float] = []
    torques: List[float] = []
    for item in itens:
        if item.get("tipo_resposta") != "numerico" or item.get("resposta") is None:
            continue
        try:
            val = float(item["resposta"])
        except (TypeError, ValueError):
            continue
        lower = (item.get("descricao") or "").lower()
        if "peso" in lower:
            pesos.append(val)
        elif "volume" in lower:
            volumes.append(val)
        elif "torque" in lower:
            torques.append(val)
    result: dict = {}
    if pesos:
        result["media_peso_g"] = round(sum(pesos) / len(pesos), 3)
    if volumes:
        result["media_volume_ml"] = round(sum(volumes) / len(volumes), 3)
    if torques:
        result["media_torque_nm"] = round(sum(torques) / len(torques), 3)
    return result


# ─── Supplier notification HTML ────────────────────────────────────────────────

def _build_comunicado_fornecedor_html(rnc: dict, empresa: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<title>Comunicado NC — {rnc.get('numero_rnc', '')}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:Arial,Helvetica,sans-serif; font-size:11pt; color:#1c1c1e; padding:36px 40px; }}
h1 {{ font-size:18pt; text-align:center; margin-bottom:4px; }}
.subtitle {{ text-align:center; color:#555; font-size:10pt; margin-bottom:28px; }}
.section {{ margin-bottom:20px; }}
.section h2 {{ font-size:10pt; text-transform:uppercase; background:#fef2f2; border-left:4px solid #dc2626; padding:4px 10px; margin-bottom:10px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 24px; }}
.fl {{ font-size:8.5pt; color:#666; }}
.fv {{ font-size:10pt; font-weight:600; }}
.box {{ border-radius:4px; padding:10px; font-size:10pt; margin-top:4px; }}
.desc  {{ background:#fef9ec; border:1px solid #fcd34d; }}
.disp  {{ background:#fff1f2; border:1px solid #fca5a5; color:#dc2626; font-weight:bold; }}
.capa  {{ background:#f0fdf4; border:1px solid #86efac; }}
.foot  {{ margin-top:48px; border-top:1px solid #e5e7eb; padding-top:12px; font-size:8pt; color:#888; }}
</style>
</head>
<body>
<h1>{empresa}</h1>
<div class="subtitle">COMUNICADO DE NÃO CONFORMIDADE AO FORNECEDOR</div>

<div class="section">
  <h2>Identificação da RNC</h2>
  <div class="grid">
    <div><div class="fl">Número RNC</div><div class="fv">{rnc.get('numero_rnc') or '—'}</div></div>
    <div><div class="fl">Classificação</div><div class="fv">{(rnc.get('classificacao') or '').upper()}</div></div>
    <div><div class="fl">Data de Abertura</div><div class="fv">{(rnc.get('created_at') or '')[:10]}</div></div>
    <div><div class="fl">Prazo para CAPA</div><div class="fv">{rnc.get('prazo_resolucao') or '—'}</div></div>
  </div>
</div>

<div class="section">
  <h2>Material e Fornecedor</h2>
  <div class="grid">
    <div><div class="fl">Material / Item</div><div class="fv">{rnc.get('item_nome') or '—'}</div></div>
    <div><div class="fl">Fornecedor</div><div class="fv">{rnc.get('fornecedor_nome') or '—'}</div></div>
    <div><div class="fl">Lote</div><div class="fv">{rnc.get('lote_numero') or '—'}</div></div>
    <div><div class="fl">Quantidade Afetada</div><div class="fv">{rnc.get('quantidade_afetada') or '—'} {rnc.get('unidade') or ''}</div></div>
  </div>
</div>

<div class="section">
  <h2>Descrição da Não Conformidade</h2>
  <div class="box desc">{rnc.get('descricao') or '—'}</div>
</div>

<div class="section">
  <h2>Disposição Imediata</h2>
  <div class="box disp">{(rnc.get('disposicao_imediata') or '—').upper().replace('_', ' ')}</div>
</div>

<div class="section">
  <h2>Ação Corretiva e Preventiva (CAPA) Solicitada</h2>
  <div class="box capa">
    Solicitamos que V.Sa. encaminhe no prazo indicado um plano de ação contendo:<br/>
    1. Análise de causa raiz (5 Porquês ou Ishikawa);<br/>
    2. Ações corretivas implementadas;<br/>
    3. Ações preventivas para evitar recorrência;<br/>
    4. Evidências objetivas da implementação.
  </div>
</div>

<div class="foot">
  Comunicado gerado em {now_iso()[:10]} — {empresa} — Sistema de Gestão da Qualidade
</div>
</body>
</html>"""


# ─── Constants ─────────────────────────────────────────────────────────────────

TIPOS_CK_VALIDOS = {"CK-1", "CK-2", "CK-3", "CK-4", "CK-5", "CK-6", "CK-7", "CK-8"}
# CK-3 to CK-8 are linked to a production order
TIPOS_CK_REQUEREM_OP = {"CK-3", "CK-4", "CK-5", "CK-6", "CK-7", "CK-8"}
SUBTIPOS_CK1_VALIDOS = {"frasco", "tampa", "valvula", "rotulo", "cartucho", "caixa"}


# ─── POST /api/cq/checklists ──────────────────────────────────────────────────

@cq_router.post("/checklists", status_code=201)
async def criar_checklist(data: ChecklistCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_ANALISTA)
    tenant_id = user["tenant_id"]

    tipo_upper = (data.tipo or "").upper()
    if tipo_upper not in TIPOS_CK_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"tipo inválido. Valores aceitos: {sorted(TIPOS_CK_VALIDOS)}",
        )

    if tipo_upper in TIPOS_CK_REQUEREM_OP and not data.op_id:
        raise HTTPException(
            status_code=400,
            detail=f"{tipo_upper} exige op_id — informe a Ordem de Produção associada",
        )

    if tipo_upper == "CK-1":
        if not data.subtipo_insumo:
            raise HTTPException(
                status_code=400,
                detail="CK-1 exige subtipo_insumo (frasco|tampa|valvula|rotulo|cartucho|caixa)",
            )
        if data.subtipo_insumo not in SUBTIPOS_CK1_VALIDOS:
            raise HTTPException(
                status_code=422,
                detail=f"subtipo_insumo inválido. Valores aceitos: {sorted(SUBTIPOS_CK1_VALIDOS)}",
            )

    # CK-7: PRÉ-REQUISITO BLOQUEANTE — RA de produto_acabado aprovado para o lote
    if tipo_upper == "CK-7":
        if not data.lote_id:
            raise HTTPException(
                status_code=400,
                detail="CK-7 exige lote_id para verificar o pré-requisito de RA aprovado",
            )
        ra_pa = await db.cq_registros_analise.find_one(
            {
                "tenant_id": tenant_id,
                "tipo": "produto_acabado",
                "status": {"$in": ["aprovado", "concessao"]},
                "lote_id": data.lote_id,
            },
            {"_id": 0, "id": 1},
        )
        if not ra_pa:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "prerequisito_nao_atendido",
                    "message": "RA de Produto Acabado aprovado é pré-requisito para CK-7",
                },
            )

    ck_id = new_id()
    numero_ck = await _next_ck_number(tenant_id, tipo_upper)

    # Fixed template — caller-supplied itens are ignored
    itens = _build_itens_para_checklist(tipo_upper, data.subtipo_insumo)

    ck: Dict[str, Any] = {
        "id": ck_id,
        "numero_ck": numero_ck,
        "tipo": tipo_upper,
        "tenant_id": tenant_id,
        "status": "em_preenchimento",
        "op_id": data.op_id,
        "op_numero": data.op_numero,
        "lote_id": data.lote_id,
        "linha": data.linha,
        "turno": data.turno,
        "nome": data.nome,
        "subtipo_insumo": data.subtipo_insumo,
        "horario_previsto_ronda": data.horario_previsto_ronda,
        "ra_id": data.ra_id,
        "itens": itens,
        "ncs_identificadas": 0,
        "rncs_geradas": [],
        "preenchido_por_id": user["id"],
        "preenchido_por_nome": user.get("name", ""),
        "aprovado_por_id": None,
        "aprovado_por_nome": None,
        "aprovado_em": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "log_auditoria": [],
    }

    await db.cq_checklists.insert_one(ck)

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="create",
        entity_type="cq_checklist",
        entity_id=ck_id,
        after=ck,
    )

    if _broadcast_event:
        await _broadcast_event(
            tenant_id, "cq_checklist_created", {"ck_id": ck_id, "numero_ck": numero_ck}
        )

    ck.pop("_id", None)
    return ck


# ─── GET /api/cq/checklists ────────────────────────────────────────────────────

@cq_router.get("/checklists")
async def listar_checklists(
    request: Request,
    tipo: Optional[str] = Query(None),
    op_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    lote_id: Optional[str] = Query(None),
    ra_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if tipo:
        query["tipo"] = tipo.upper()
    if op_id:
        query["op_id"] = op_id
    if status:
        query["status"] = status
    if lote_id:
        query["lote_id"] = lote_id
    if ra_id:
        query["ra_id"] = ra_id

    cursor = (
        db.cq_checklists.find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    total = await db.cq_checklists.count_documents(query)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ─── GET /api/cq/checklists/{ck_id} ───────────────────────────────────────────

@cq_router.get("/checklists/{ck_id}")
async def detalhe_checklist(ck_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    ck = await db.cq_checklists.find_one(
        {"id": ck_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not ck:
        raise HTTPException(status_code=404, detail="Checklist não encontrado")
    return ck


# ─── PUT /api/cq/checklists/{ck_id}/itens/{item_id} ───────────────────────────

@cq_router.put("/checklists/{ck_id}/itens/{item_id}")
async def preencher_item(
    ck_id: str, item_id: str, data: ChecklistItemUpdate, request: Request
):
    user = await get_current_user(request)
    require_roles(user, CQ_ANALISTA)
    tenant_id = user["tenant_id"]

    ck = await db.cq_checklists.find_one(
        {"id": ck_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not ck:
        raise HTTPException(status_code=404, detail="Checklist não encontrado")
    if ck["status"] in ("aprovado", "reprovado"):
        raise HTTPException(
            status_code=409,
            detail=f"Checklist já encerrado com status '{ck['status']}'",
        )

    item_atual = next((i for i in ck.get("itens", []) if i["id"] == item_id), None)
    if not item_atual:
        raise HTTPException(status_code=404, detail="Item não encontrado neste checklist")

    # somente_cq guard
    if item_atual.get("somente_cq") and not has_role(user, CQ_FULL):
        raise HTTPException(
            status_code=403,
            detail="Este item é de preenchimento exclusivo do CQ (qa / lider_pd / admin)",
        )

    resposta = data.resposta
    conforme = data.conforme

    # Auto-calculate conforme for snna responses
    if item_atual.get("tipo_resposta") == "snna" and resposta is not None:
        conforme = resposta in ("S", "NA")

    # Build positional-operator update
    fields: Dict[str, Any] = {"updated_at": now_iso()}
    if data.resposta is not None:
        fields["itens.$.resposta"] = resposta
        fields["itens.$.conforme"] = conforme
    if data.observacao is not None:
        fields["itens.$.observacao"] = data.observacao
    if data.nc_classificacao is not None:
        fields["itens.$.nc_classificacao"] = data.nc_classificacao
    if data.acao_imediata is not None:
        fields["itens.$.acao_imediata"] = data.acao_imediata
    if data.foto_file_ids is not None:
        fields["itens.$.foto_file_ids"] = data.foto_file_ids

    await db.cq_checklists.update_one(
        {"id": ck_id, "tenant_id": tenant_id, "itens.id": item_id},
        {"$set": fields},
    )

    # Re-fetch for post-processing
    ck_upd = await db.cq_checklists.find_one({"id": ck_id}, {"_id": 0})

    # CK-5: recalculate peso/volume/torque averages after any numeric save
    if ck["tipo"] == "CK-5" and item_atual.get("tipo_resposta") == "numerico":
        avgs = _calc_ck5_averages(ck_upd.get("itens", []))
        if avgs:
            await db.cq_checklists.update_one({"id": ck_id}, {"$set": avgs})

    # Auto-create RNC when resposta=N and nc_classificacao=critica
    if resposta == "N" and data.nc_classificacao == "critica":
        numero_rnc = await _next_rnc_number(tenant_id)
        rnc_auto: Dict[str, Any] = {
            "id": new_id(),
            "numero_rnc": numero_rnc,
            "tenant_id": tenant_id,
            "status": "aberta",
            "classificacao": "critica",
            "origem": _ck_tipo_to_origem(ck["tipo"]),
            "descricao": (
                f"NC crítica identificada no {ck['numero_ck']} — "
                f"seção '{item_atual.get('secao', '—')}': \"{item_atual['descricao']}\"."
            ),
            "ra_id": None,
            "ck_id": ck_id,
            "lote_id": ck.get("lote_id"),
            "lote_numero": None,
            "item_nome": None,
            "fornecedor_id": None,
            "fornecedor_nome": None,
            "quantidade_afetada": None,
            "unidade": None,
            "fotos_file_ids": data.foto_file_ids or [],
            "disposicao_imediata": "descarte",
            "responsavel_id": user["id"],
            "responsavel_nome": user.get("name", ""),
            "prazo_resolucao": None,
            "comunicado_fornecedor_enviado": False,
            "comunicado_enviado_em": None,
            "resposta_fornecedor": None,
            "capa_descricao": None,
            "evidencia_resolucao": None,
            "encerrado_por_id": None,
            "encerrado_em": None,
            "created_at": now_iso(),
            "log_auditoria": [],
        }
        await db.cq_rncs.insert_one(rnc_auto)

        await db.cq_checklists.update_one(
            {"id": ck_id},
            {
                "$push": {"rncs_geradas": rnc_auto["id"]},
                "$inc":  {"ncs_identificadas": 1},
            },
        )

        # CK-6 ronda: alerta de parada se mesma seção teve NC crítica na ronda anterior
        if ck["tipo"] == "CK-6" and ck.get("op_id"):
            secao_atual = item_atual.get("secao", "")
            prev_rounds = (
                await db.cq_checklists.find(
                    {
                        "tenant_id": tenant_id,
                        "tipo": "CK-6",
                        "op_id": ck["op_id"],
                        "id": {"$ne": ck_id},
                    },
                    {"_id": 0, "itens": 1},
                )
                .sort("created_at", -1)
                .limit(1)
                .to_list(1)
            )
            if prev_rounds:
                prev_nc_critica = any(
                    i.get("resposta") == "N"
                    and i.get("nc_classificacao") == "critica"
                    and i.get("secao") == secao_atual
                    for i in prev_rounds[0].get("itens", [])
                )
                if prev_nc_critica:
                    op_ref = ck.get("op_numero") or ck.get("op_id") or "—"
                    await create_workflow_task(
                        tenant_id=tenant_id,
                        entity_type="cq_checklist",
                        entity_id=ck_id,
                        title=f"CQ-13 ALERTA PARADA DE LINHA — {ck['numero_ck']}",
                        description=(
                            f"NC crítica repetida na seção '{secao_atual}' em duas rondas "
                            f"consecutivas (OP {op_ref}). Verificar necessidade de parada imediata."
                        ),
                        category="qa",
                        blocking=True,
                        due_in_days=0,
                        created_by=user,
                    )

    # Instrument calibration alert — checked when instrumento_id is supplied with the item
    if data.instrumento_id:
        instr_check = await db.cq_instrumentos.find_one(
            {"id": data.instrumento_id, "tenant_id": tenant_id}, {"_id": 0}
        )
        if instr_check and _calc_instrumento_status(instr_check) in ("vencido", "bloqueado"):
            alerta = "[ALERTA: instrumento com calibração vencida]"
            new_obs = f"{alerta} {data.observacao or ''}".strip()
            await db.cq_checklists.update_one(
                {"id": ck_id, "itens.id": item_id},
                {
                    "$set": {"itens.$.observacao": new_obs},
                    "$push": {
                        "log_auditoria": {
                            "tipo": "instrumento_alerta",
                            "instrumento_id": data.instrumento_id,
                            "instrumento_nome": instr_check.get("nome"),
                            "alerta": alerta,
                            "usuario_id": user["id"],
                            "usuario_nome": user.get("name", ""),
                            "datetime": now_iso(),
                        }
                    },
                },
            )

    # CQ-03/04: when all operator-facing items are filled, notify CQ to approve
    if ck["tipo"] in ("CK-3", "CK-4"):
        ck_for_cq = await db.cq_checklists.find_one({"id": ck_id}, {"_id": 0})
        itens_op = [i for i in (ck_for_cq or {}).get("itens", []) if not i.get("somente_cq")]
        if itens_op and all(i.get("resposta") is not None for i in itens_op):
            cq_code = "CQ-03" if ck["tipo"] == "CK-3" else "CQ-04"
            cq_titulo = (
                "Liberar assépsia de manipulação"
                if ck["tipo"] == "CK-3"
                else "Liberar assépsia de linha"
            )
            # Idempotent — only create if no pending task already exists
            exists_task = await db.workflow_tasks.find_one(
                {
                    "tenant_id": tenant_id,
                    "entity_id": ck_id,
                    "title": {"$regex": f"^{cq_code}"},
                    "status": "pendente",
                },
                {"_id": 0, "id": 1},
            )
            if not exists_task:
                await create_workflow_task(
                    tenant_id=tenant_id,
                    entity_type="cq_checklist",
                    entity_id=ck_id,
                    title=f"{cq_code} {cq_titulo} — {ck['numero_ck']}",
                    description=(
                        f"Todos os itens do operador no {ck['numero_ck']} foram preenchidos. "
                        f"CQ deve verificar in loco e aprovar as condições."
                    ),
                    category="qa",
                    blocking=True,
                    due_in_days=0,
                    created_by=user,
                )

    ck_final = await db.cq_checklists.find_one({"id": ck_id}, {"_id": 0})
    return ck_final


# ─── POST /api/cq/checklists/{ck_id}/aprovar ─────────────────────────────────

@cq_router.post("/checklists/{ck_id}/aprovar")
async def aprovar_checklist(
    ck_id: str, data: AprovarChecklistInput, request: Request
):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    ck = await db.cq_checklists.find_one(
        {"id": ck_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not ck:
        raise HTTPException(status_code=404, detail="Checklist não encontrado")
    if ck["status"] in ("aprovado", "reprovado"):
        raise HTTPException(
            status_code=409, detail=f"Checklist já encerrado com status '{ck['status']}'"
        )

    if data.decisao not in ("aprovado", "reprovado"):
        raise HTTPException(
            status_code=422, detail="decisao deve ser 'aprovado' ou 'reprovado'"
        )

    now = now_iso()
    await db.cq_checklists.update_one(
        {"id": ck_id},
        {
            "$set": {
                "status": data.decisao,
                "aprovado_por_id": user["id"],
                "aprovado_por_nome": user.get("name", ""),
                "aprovado_em": now,
                "updated_at": now,
            },
            "$push": {
                "log_auditoria": {
                    "campo": "status",
                    "de": ck["status"],
                    "para": data.decisao,
                    "usuario_id": user["id"],
                    "usuario_nome": user.get("name", ""),
                    "datetime": now,
                    "observacoes": data.observacoes,
                }
            },
        },
    )

    tipo = ck["tipo"]
    op_ref = ck.get("op_numero") or ck.get("op_id") or "—"

    if data.decisao == "aprovado":
        if tipo == "CK-3":
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_checklist",
                entity_id=ck_id,
                title=f"CK-3 Aprovado — Iniciar Manipulação (OP {op_ref})",
                description=f"Assépsia de manipulação {ck['numero_ck']} aprovada pelo CQ. Linha liberada para manipulação.",
                category="operacional",
                blocking=False,
                due_in_days=0,
                created_by=user,
            )

        elif tipo == "CK-4":
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_checklist",
                entity_id=ck_id,
                title=f"CK-4 Aprovado — Iniciar Envase (OP {op_ref})",
                description=f"Assépsia de envase {ck['numero_ck']} aprovada pelo CQ. Linha liberada para envase.",
                category="operacional",
                blocking=False,
                due_in_days=0,
                created_by=user,
            )
            # CQ-05: first article must be done before serial production starts
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_checklist",
                entity_id=ck_id,
                title=f"CQ-05 Realizar setup / First Article — OP {op_ref}",
                description=(
                    f"Linha liberada ({ck['numero_ck']}). "
                    f"Realizar inspeção de primeiro artigo (CK-5) antes de iniciar produção em série."
                ),
                category="qa",
                blocking=True,
                due_in_days=0,
                created_by=user,
            )

        elif tipo == "CK-5":
            prazo_ronda = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_checklist",
                entity_id=ck_id,
                title=f"CQ-06 Primeira Ronda de Linha — OP {op_ref}",
                description=(
                    f"First Article {ck['numero_ck']} aprovado. "
                    f"Realizar primeira ronda CK-6 até {prazo_ronda[:16].replace('T', ' ')} UTC."
                ),
                category="qa",
                blocking=False,
                due_in_days=0,
                created_by=user,
                metadata={"prazo_primeira_ronda_iso": prazo_ronda},
            )

        elif tipo == "CK-7":
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_checklist",
                entity_id=ck_id,
                title=f"CK-7 Aprovado — Liberar Palete para Expedição (OP {op_ref})",
                description=f"Palete inspecionado e aprovado pelo CQ ({ck['numero_ck']}). Expedição autorizada.",
                category="operacional",
                blocking=False,
                due_in_days=0,
                created_by=user,
            )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="aprovar",
        entity_type="cq_checklist",
        entity_id=ck_id,
        before={"status": ck["status"]},
        after={"status": data.decisao},
    )

    if _broadcast_event:
        await _broadcast_event(
            tenant_id, "cq_checklist_aprovado", {"ck_id": ck_id, "status": data.decisao}
        )

    ck_updated = await db.cq_checklists.find_one({"id": ck_id}, {"_id": 0})
    return ck_updated


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 4 — RNCs
# ══════════════════════════════════════════════════════════════════════════════

# ─── GET /api/cq/rncs ─────────────────────────────────────────────────────────

@cq_router.get("/rncs")
async def listar_rncs(
    request: Request,
    status: Optional[str] = Query(None),
    origem: Optional[str] = Query(None),
    fornecedor_id: Optional[str] = Query(None),
    classificacao: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        query["status"] = status
    if origem:
        query["origem"] = origem
    if fornecedor_id:
        query["fornecedor_id"] = fornecedor_id
    if classificacao:
        query["classificacao"] = classificacao

    cursor = (
        db.cq_rncs.find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    total = await db.cq_rncs.count_documents(query)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ─── GET /api/cq/rncs/{rnc_id} ────────────────────────────────────────────────

@cq_router.get("/rncs/{rnc_id}")
async def detalhe_rnc(rnc_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    rnc = await db.cq_rncs.find_one(
        {"id": rnc_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not rnc:
        raise HTTPException(status_code=404, detail="RNC não encontrada")
    return rnc


# ─── PUT /api/cq/rncs/{rnc_id} ────────────────────────────────────────────────

@cq_router.put("/rncs/{rnc_id}")
async def atualizar_rnc(rnc_id: str, data: RNCUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_ANALISTA)
    tenant_id = user["tenant_id"]

    rnc = await db.cq_rncs.find_one(
        {"id": rnc_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not rnc:
        raise HTTPException(status_code=404, detail="RNC não encontrada")
    if rnc["status"] in ("encerrada", "encerrada_concessao"):
        raise HTTPException(
            status_code=400,
            detail=f"RNC encerrada com status '{rnc['status']}' — não pode ser editada",
        )

    update_fields: Dict[str, Any] = {"updated_at": now_iso()}
    payload = data.model_dump(exclude_none=True)
    for field in ("classificacao", "descricao", "responsavel_id", "responsavel_nome",
                  "prazo_resolucao", "capa_descricao"):
        if field in payload:
            update_fields[field] = payload[field]

    # Add observacao to log if provided
    if data.observacao:
        log_entry = {
            "campo": "observacao",
            "de": None,
            "para": data.observacao,
            "usuario_id": user["id"],
            "usuario_nome": user.get("name", ""),
            "datetime": now_iso(),
        }
        await db.cq_rncs.update_one(
            {"id": rnc_id}, {"$push": {"log_auditoria": log_entry}}
        )

    # Auto-transition to em_investigacao when both responsavel and prazo are set
    responsavel_id_final = payload.get("responsavel_id") or rnc.get("responsavel_id")
    prazo_final = payload.get("prazo_resolucao") or rnc.get("prazo_resolucao")
    if (
        responsavel_id_final
        and prazo_final
        and rnc["status"] == "aberta"
    ):
        update_fields["status"] = "em_investigacao"

    if update_fields:
        await db.cq_rncs.update_one({"id": rnc_id}, {"$set": update_fields})

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="update",
        entity_type="cq_rnc",
        entity_id=rnc_id,
        before={k: rnc.get(k) for k in update_fields if k != "updated_at"},
        after=update_fields,
    )

    rnc_updated = await db.cq_rncs.find_one({"id": rnc_id}, {"_id": 0})
    return rnc_updated


# ─── POST /api/cq/rncs/{rnc_id}/encerrar ─────────────────────────────────────

@cq_router.post("/rncs/{rnc_id}/encerrar")
async def encerrar_rnc(rnc_id: str, data: RNCEncerrarPayload, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    rnc = await db.cq_rncs.find_one(
        {"id": rnc_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not rnc:
        raise HTTPException(status_code=404, detail="RNC não encontrada")
    if rnc["status"] in ("encerrada", "encerrada_concessao"):
        raise HTTPException(
            status_code=409,
            detail=f"RNC já encerrada com status '{rnc['status']}'",
        )

    # evidencia_resolucao is required (enforced here; also required by Pydantic)
    if not data.evidencia_resolucao or not data.evidencia_resolucao.strip():
        raise HTTPException(
            status_code=422,
            detail="evidencia_resolucao é obrigatória para encerrar a RNC",
        )

    if data.com_concessao and not data.autorizacao_concessao:
        raise HTTPException(
            status_code=422,
            detail="autorizacao_concessao é obrigatória quando com_concessao=true",
        )

    status_final = "encerrada_concessao" if data.com_concessao else "encerrada"
    now = now_iso()

    update: Dict[str, Any] = {
        "status": status_final,
        "evidencia_resolucao": data.evidencia_resolucao,
        "encerrado_por_id": user["id"],
        "encerrado_em": now,
        "updated_at": now,
    }
    if data.autorizacao_concessao:
        update["autorizacao_concessao"] = data.autorizacao_concessao

    log_entry: Dict[str, Any] = {
        "campo": "status",
        "de": rnc["status"],
        "para": status_final,
        "usuario_id": user["id"],
        "usuario_nome": user.get("name", ""),
        "datetime": now,
        "observacoes": data.observacoes,
    }

    await db.cq_rncs.update_one(
        {"id": rnc_id},
        {"$set": update, "$push": {"log_auditoria": log_entry}},
    )

    # Supplier RNC threshold check (≥3 RNCs in 90 days → alert for Compras)
    if rnc.get("fornecedor_id"):
        ninety_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).isoformat()
        count_90d = await db.cq_rncs.count_documents(
            {
                "tenant_id": tenant_id,
                "fornecedor_id": rnc["fornecedor_id"],
                "created_at": {"$gte": ninety_days_ago},
            }
        )
        if count_90d >= 3:
            await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_rnc",
                entity_id=rnc_id,
                title=f"ALERTA — Fornecedor com {count_90d} RNCs em 90 dias",
                description=(
                    f"Fornecedor '{rnc.get('fornecedor_nome') or rnc.get('fornecedor_id')}' "
                    f"acumula {count_90d} RNCs nos últimos 90 dias. "
                    f"Revisar homologação e histórico de não conformidades."
                ),
                category="compras",
                blocking=False,
                due_in_days=5,
                created_by=user,
            )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="encerrar",
        entity_type="cq_rnc",
        entity_id=rnc_id,
        before={"status": rnc["status"]},
        after={"status": status_final},
    )

    if _broadcast_event:
        await _broadcast_event(
            tenant_id, "cq_rnc_encerrada", {"rnc_id": rnc_id, "status": status_final}
        )

    rnc_updated = await db.cq_rncs.find_one({"id": rnc_id}, {"_id": 0})
    return rnc_updated


# ─── POST /api/cq/rncs/{rnc_id}/comunicar-fornecedor ─────────────────────────

@cq_router.post("/rncs/{rnc_id}/comunicar-fornecedor")
async def comunicar_fornecedor(
    rnc_id: str, data: ComunicarFornecedorInput, request: Request
):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    rnc = await db.cq_rncs.find_one(
        {"id": rnc_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not rnc:
        raise HTTPException(status_code=404, detail="RNC não encontrada")
    if rnc["status"] in ("encerrada", "encerrada_concessao"):
        raise HTTPException(
            status_code=400,
            detail="Não é possível comunicar fornecedor em RNC encerrada",
        )

    # Only supply-chain origins can notify a supplier
    ORIGENS_FORNECEDOR = {"recepcao_mp", "recepcao_embalagem"}
    if rnc.get("origem") not in ORIGENS_FORNECEDOR:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Comunicado ao fornecedor só é aplicável para RNCs de origem "
                f"'recepcao_mp' ou 'recepcao_embalagem' (origem atual: '{rnc.get('origem')}')."
            ),
        )

    # Fetch company name
    tenant_doc = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "nome": 1, "name": 1}
    )
    empresa = ""
    if tenant_doc:
        empresa = tenant_doc.get("nome") or tenant_doc.get("name") or ""
    if not empresa:
        empresa = "Laboratório CQ"

    now = now_iso()

    # Mark as sent before building PDF so timestamp appears in the doc
    await db.cq_rncs.update_one(
        {"id": rnc_id},
        {
            "$set": {
                "comunicado_fornecedor_enviado": True,
                "comunicado_enviado_em": now,
                "status": "aguardando_fornecedor",
                "updated_at": now,
            },
            "$push": {
                "log_auditoria": {
                    "campo": "comunicado_fornecedor_enviado",
                    "de": False,
                    "para": True,
                    "usuario_id": user["id"],
                    "usuario_nome": user.get("name", ""),
                    "datetime": now,
                    "email_destinatario": data.email_destinatario,
                    "observacoes": data.observacoes,
                }
            },
        },
    )

    # Re-fetch so the HTML reflects the updated comunicado_enviado_em
    rnc_updated = await db.cq_rncs.find_one({"id": rnc_id}, {"_id": 0})

    html_content = _build_comunicado_fornecedor_html(rnc_updated, empresa)

    # Create CQ-14 follow-up task (3 business days = ~5 calendar days)
    prazo_cq14 = _add_business_days(datetime.now(timezone.utc), 3)
    await create_workflow_task(
        tenant_id=tenant_id,
        entity_type="cq_rnc",
        entity_id=rnc_id,
        title=f"CQ-14 Acompanhar resposta do fornecedor — {rnc_updated.get('numero_rnc')}",
        description=(
            f"Comunicado enviado ao fornecedor '{rnc.get('fornecedor_nome') or '—'}'. "
            f"Aguardar resposta da CAPA até {prazo_cq14}. "
            f"RNC: {rnc_updated.get('numero_rnc')}."
        ),
        category="qa",
        blocking=False,
        due_in_days=5,
        created_by=user,
        metadata={"prazo_capa_iso": prazo_cq14, "email_destinatario": data.email_destinatario},
    )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="comunicar_fornecedor",
        entity_type="cq_rnc",
        entity_id=rnc_id,
        after={"status": "aguardando_fornecedor", "comunicado_enviado_em": now},
    )

    pdf_bytes = _html_to_pdf(html_content)
    if pdf_bytes:
        filename = f"Comunicado-NC-{rnc_updated.get('numero_rnc', rnc_id)}.pdf"
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return HTMLResponse(content=html_content, status_code=200)


# ── GET /api/cq/retencoes ─────────────────────────────────────────────────────
@cq_router.get("/retencoes")
async def listar_retencoes(
    request: Request,
    status: Optional[str] = Query(None),
    ra_id: Optional[str] = Query(None),
    lote_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        query["status"] = status
    if ra_id:
        query["ra_id"] = ra_id
    if lote_id:
        query["lote_id"] = lote_id

    cursor = (
        db.cq_retencoes.find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    total = await db.cq_retencoes.count_documents(query)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ── GET /api/cq/retencoes/{ret_id} ────────────────────────────────────────────
@cq_router.get("/retencoes/{ret_id}")
async def detalhe_retencao(ret_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)

    ret = await db.cq_retencoes.find_one(
        {"id": ret_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not ret:
        raise HTTPException(status_code=404, detail="Amostra de retenção não encontrada")
    return ret


# ══════════════════════════════════════════════════════════════════════════════
#   405 GUARDS — no DELETE on any CQ collection
# ══════════════════════════════════════════════════════════════════════════════

_IMUTAVEL_MSG = "Documentos CQ são imutáveis. Exclusão não é permitida em nenhuma coleção CQ."


@cq_router.delete("/registros-analise/{ra_id}", status_code=405)
async def delete_ra_blocked(ra_id: str):
    raise HTTPException(status_code=405, detail=_IMUTAVEL_MSG)


@cq_router.delete("/checklists/{ck_id}", status_code=405)
async def delete_ck_blocked(ck_id: str):
    raise HTTPException(status_code=405, detail=_IMUTAVEL_MSG)


@cq_router.delete("/rncs/{rnc_id}", status_code=405)
async def delete_rnc_blocked(rnc_id: str):
    raise HTTPException(status_code=405, detail=_IMUTAVEL_MSG)


@cq_router.delete("/retencoes/{ret_id}", status_code=405)
async def delete_ret_blocked(ret_id: str):
    raise HTTPException(status_code=405, detail=_IMUTAVEL_MSG)


@cq_router.delete("/instrumentos/{instr_id}", status_code=405)
async def delete_instr_blocked(instr_id: str):
    raise HTTPException(status_code=405, detail=_IMUTAVEL_MSG)


@cq_router.delete("/status-lote/{entry_id}", status_code=405)
async def delete_status_lote_blocked(entry_id: str):
    raise HTTPException(status_code=405, detail=_IMUTAVEL_MSG)


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 5 — SCHEDULER + HELPER _calc_instrumento_status
# ══════════════════════════════════════════════════════════════════════════════

def _calc_instrumento_status(instr: dict) -> str:
    """Real-time status: vencido if proxima_calibracao < today (ignores bloqueado/em_calibracao)."""
    stored = instr.get("status", "calibrado")
    if stored in ("em_calibracao", "bloqueado"):
        return stored
    proxima = instr.get("proxima_calibracao")
    if proxima:
        today = datetime.now(timezone.utc).date().isoformat()
        if proxima < today:
            return "vencido"
    return stored


@cq_router.get("/scheduler/tick")
async def scheduler_tick(request: Request):
    """
    Manual trigger for time-based CQ checks.
    Recommended cadence: every 5 minutes via system cron.
    Checks: CQ-10 (RET vencendo), CQ-13 (ronda atrasada), CQ-14 (fornecedor sem resposta).
    """
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    now_dt = datetime.now(timezone.utc)
    today_str = now_dt.date().isoformat()
    created: List[dict] = []

    # ── CQ-09: CK-8 de higiene/ambiente/calibração ainda não criado hoje ─────
    ck8_hoje = await db.cq_checklists.find_one(
        {"tenant_id": tenant_id, "tipo": "CK-8", "created_at": {"$gte": today_str}},
        {"_id": 0, "id": 1},
    )
    if not ck8_hoje:
        exists_cq09 = await db.workflow_tasks.find_one(
            {
                "tenant_id": tenant_id,
                "title": {"$regex": "^CQ-09"},
                "created_at": {"$gte": today_str},
            },
            {"_id": 0, "id": 1},
        )
        if not exists_cq09:
            t = await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_turno",
                entity_id=f"ck8_{today_str}",
                title=f"CQ-09 CK-8 Higiene/Ambiente/Calibração — {today_str}",
                description=(
                    f"CK-8 de higiene, ambiente e calibração ainda não realizado hoje ({today_str}). "
                    f"Executar antes de qualquer CK-5 ou CK-6 do turno."
                ),
                category="qa",
                blocking=True,
                due_in_days=0,
                created_by=user,
            )
            created.append({"tipo": "CQ-09", "date": today_str, "task_id": t.get("id")})

    # ── CQ-10: amostras de retenção vencendo em ≤30 dias ─────────────────────
    window_30d = (now_dt + timedelta(days=30)).date().isoformat()
    async for ret in db.cq_retencoes.find(
        {
            "tenant_id": tenant_id,
            "status": "em_guarda",
            "data_limite_guarda": {"$lte": window_30d},
        },
        {"_id": 0},
    ):
        existing = await db.workflow_tasks.find_one(
            {
                "tenant_id": tenant_id,
                "entity_id": ret["id"],
                "title": {"$regex": "^CQ-10"},
            },
            {"_id": 0, "id": 1},
        )
        if not existing:
            t = await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_retencao",
                entity_id=ret["id"],
                title=f"CQ-10 Amostra de retenção vencendo — {ret.get('numero_ret')}",
                description=(
                    f"Amostra {ret.get('numero_ret')} vence em {ret.get('data_limite_guarda')}. "
                    f"Item: {ret.get('item_nome') or '—'}. Lote: {ret.get('lote_numero') or '—'}."
                ),
                category="qa",
                blocking=False,
                due_in_days=30,
                created_by=user,
            )
            created.append({"tipo": "CQ-10", "ret_id": ret["id"], "task_id": t.get("id")})

    # ── CQ-13: tarefa CQ-06 vencida há >30 min e ainda pendente ──────────────
    thirty_min_ago = (now_dt - timedelta(minutes=30)).isoformat()
    async for ck6_task in db.workflow_tasks.find(
        {
            "tenant_id": tenant_id,
            "title": {"$regex": "^CQ-06"},
            "status": "pendente",
            "due_date": {"$lt": thirty_min_ago},
        },
        {"_id": 0},
    ):
        ck_eid = ck6_task.get("entity_id", "")
        exists_cq13 = await db.workflow_tasks.find_one(
            {
                "tenant_id": tenant_id,
                "entity_id": ck_eid,
                "title": {"$regex": "^CQ-13"},
            },
            {"_id": 0, "id": 1},
        )
        if not exists_cq13:
            t = await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_checklist",
                entity_id=ck_eid,
                title="CQ-13 Ronda atrasada >30min — escalonamento supervisor",
                description=(
                    f"Tarefa '{ck6_task.get('title')}' está pendente há mais de 30 minutos. "
                    f"Supervisor deve verificar o status da linha imediatamente."
                ),
                category="qa",
                blocking=True,
                due_in_days=0,
                created_by=user,
                metadata={"cq06_task_id": ck6_task.get("id")},
            )
            created.append({"tipo": "CQ-13", "entity_id": ck_eid, "task_id": t.get("id")})

    # ── CQ-14: RNC aguardando resposta do fornecedor há >3 dias ──────────────
    three_days_ago = (now_dt - timedelta(days=3)).isoformat()
    async for rnc in db.cq_rncs.find(
        {
            "tenant_id": tenant_id,
            "status": "aguardando_fornecedor",
            "comunicado_enviado_em": {"$lt": three_days_ago},
        },
        {"_id": 0},
    ):
        exists_cq14 = await db.workflow_tasks.find_one(
            {
                "tenant_id": tenant_id,
                "entity_id": rnc["id"],
                "title": {"$regex": "^CQ-14"},
                "status": "pendente",
            },
            {"_id": 0, "id": 1},
        )
        if not exists_cq14:
            t = await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="cq_rnc",
                entity_id=rnc["id"],
                title=f"CQ-14 Fornecedor sem resposta à RNC — {rnc.get('numero_rnc')}",
                description=(
                    f"RNC {rnc.get('numero_rnc')} aguarda resposta de "
                    f"'{rnc.get('fornecedor_nome') or '—'}' há >3 dias "
                    f"(comunicado em {(rnc.get('comunicado_enviado_em') or '')[:10]})."
                ),
                category="qa",
                blocking=False,
                due_in_days=3,
                created_by=user,
            )
            created.append({"tipo": "CQ-14", "rnc_id": rnc["id"], "task_id": t.get("id")})

    return {
        "tick_at": now_dt.isoformat(),
        "tarefas_criadas": len(created),
        "detalhe": created,
    }


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 6 — INSTRUMENTOS DE CALIBRAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

class InstrumentoUpdate(BaseModel):
    nome: Optional[str] = None
    localizacao: Optional[str] = None
    frequencia_calibracao_dias: Optional[int] = None
    status: Optional[str] = None          # em_calibracao | bloqueado (manual override)
    certificado_file_id: Optional[str] = None


class RegistrarCalibracaoInput(BaseModel):
    data_calibracao: str                   # ISO date — REQUIRED
    laboratorio: Optional[str] = None
    certificado_numero: Optional[str] = None
    resultado: str = "aprovado"            # aprovado | reprovado
    certificado_file_id: Optional[str] = None


# ─── GET /api/cq/instrumentos ─────────────────────────────────────────────────

@cq_router.get("/instrumentos")
async def listar_instrumentos(
    request: Request,
    tipo: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, CQ_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if tipo:
        query["tipo"] = tipo

    cursor = (
        db.cq_instrumentos.find(query, {"_id": 0})
        .sort("nome", 1)
        .skip(offset)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    total = await db.cq_instrumentos.count_documents(query)

    # Real-time status recalculation + DB sync for stale records
    for instr in items:
        status_real = _calc_instrumento_status(instr)
        if status_real != instr.get("status"):
            instr["status"] = status_real
            await db.cq_instrumentos.update_one(
                {"id": instr["id"], "tenant_id": tenant_id},
                {"$set": {"status": status_real, "updated_at": now_iso()}},
            )

    # Apply status filter after real-time calculation
    if status:
        items = [i for i in items if i.get("status") == status]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ─── POST /api/cq/instrumentos ────────────────────────────────────────────────

@cq_router.post("/instrumentos", status_code=201)
async def criar_instrumento(data: InstrumentoCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    dup = await db.cq_instrumentos.find_one(
        {"tenant_id": tenant_id, "codigo_interno": data.codigo_interno},
        {"_id": 0, "id": 1},
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Código interno '{data.codigo_interno}' já está em uso neste tenant",
        )

    TIPOS_VALIDOS_INSTR = {"phmetro", "balanca", "torquimetro", "densimetro", "termohigrometro"}
    if data.tipo not in TIPOS_VALIDOS_INSTR:
        raise HTTPException(
            status_code=422,
            detail=f"tipo inválido. Valores aceitos: {sorted(TIPOS_VALIDOS_INSTR)}",
        )

    proxima_calibracao = None
    if data.ultima_calibracao:
        # +1: freq=180 means "valid for 180 days starting on calibration day",
        # so the next calibration is due on day freq+1 after the last one.
        proxima_calibracao = _add_days_iso(data.ultima_calibracao, data.frequencia_calibracao_dias + 1)

    # Status at creation: vencido if proxima_calibracao is already in the past
    status_inicial = "calibrado"
    if proxima_calibracao:
        today = datetime.now(timezone.utc).date().isoformat()
        if proxima_calibracao < today:
            status_inicial = "vencido"

    instr_id = new_id()
    instr = {
        "id": instr_id,
        "tenant_id": tenant_id,
        "nome": data.nome,
        "codigo_interno": data.codigo_interno,
        "tipo": data.tipo,
        "localizacao": data.localizacao,
        "frequencia_calibracao_dias": data.frequencia_calibracao_dias,
        "ultima_calibracao": data.ultima_calibracao,
        "proxima_calibracao": proxima_calibracao,
        "status": status_inicial,
        "certificado_file_id": data.certificado_file_id,
        "historico_calibracoes": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.cq_instrumentos.insert_one(instr)

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="create",
        entity_type="cq_instrumento",
        entity_id=instr_id,
        after=instr,
    )

    instr.pop("_id", None)
    return instr


# ─── PUT /api/cq/instrumentos/{instr_id} ──────────────────────────────────────

@cq_router.put("/instrumentos/{instr_id}")
async def atualizar_instrumento(
    instr_id: str, data: InstrumentoUpdate, request: Request
):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    instr = await db.cq_instrumentos.find_one(
        {"id": instr_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not instr:
        raise HTTPException(status_code=404, detail="Instrumento não encontrado")

    update_fields: Dict[str, Any] = {"updated_at": now_iso()}
    for field in ("nome", "localizacao", "frequencia_calibracao_dias",
                  "status", "certificado_file_id"):
        val = getattr(data, field, None)
        if val is not None:
            update_fields[field] = val

    await db.cq_instrumentos.update_one({"id": instr_id}, {"$set": update_fields})

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="update",
        entity_type="cq_instrumento",
        entity_id=instr_id,
        before={k: instr.get(k) for k in update_fields if k != "updated_at"},
        after=update_fields,
    )

    instr_updated = await db.cq_instrumentos.find_one({"id": instr_id}, {"_id": 0})
    return instr_updated


# ─── POST /api/cq/instrumentos/{instr_id}/registrar-calibracao ────────────────

@cq_router.post("/instrumentos/{instr_id}/registrar-calibracao")
async def registrar_calibracao(
    instr_id: str, data: RegistrarCalibracaoInput, request: Request
):
    user = await get_current_user(request)
    require_roles(user, CQ_FULL)
    tenant_id = user["tenant_id"]

    instr = await db.cq_instrumentos.find_one(
        {"id": instr_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not instr:
        raise HTTPException(status_code=404, detail="Instrumento não encontrado")

    if data.resultado not in ("aprovado", "reprovado"):
        raise HTTPException(
            status_code=422,
            detail="resultado deve ser 'aprovado' ou 'reprovado'",
        )

    # Recalculate proxima_calibracao from the new calibration date (+1 for same
    # convention: freq=180 means valid through day 180, due on day 181).
    proxima_calibracao = _add_days_iso(
        data.data_calibracao, instr["frequencia_calibracao_dias"] + 1
    )
    novo_status = "calibrado" if data.resultado == "aprovado" else "bloqueado"

    historico_entry = {
        "data": data.data_calibracao,
        "laboratorio": data.laboratorio,
        "certificado_numero": data.certificado_numero,
        "resultado": data.resultado,
        "certificado_file_id": data.certificado_file_id,
        "registrado_por_id": user["id"],
        "registrado_por_nome": user.get("name", ""),
        "created_at": now_iso(),
    }

    update: Dict[str, Any] = {
        "ultima_calibracao": data.data_calibracao,
        "proxima_calibracao": proxima_calibracao,
        "status": novo_status,
        "updated_at": now_iso(),
    }
    if data.certificado_file_id:
        update["certificado_file_id"] = data.certificado_file_id

    await db.cq_instrumentos.update_one(
        {"id": instr_id},
        {"$set": update, "$push": {"historico_calibracoes": historico_entry}},
    )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="registrar_calibracao",
        entity_type="cq_instrumento",
        entity_id=instr_id,
        before={
            "status": instr.get("status"),
            "ultima_calibracao": instr.get("ultima_calibracao"),
        },
        after={"status": novo_status, "proxima_calibracao": proxima_calibracao},
    )

    if _broadcast_event:
        await _broadcast_event(
            tenant_id,
            "cq_instrumento_calibrado",
            {
                "instrumento_id": instr_id,
                "status": novo_status,
                "proxima_calibracao": proxima_calibracao,
            },
        )

    instr_updated = await db.cq_instrumentos.find_one({"id": instr_id}, {"_id": 0})
    return instr_updated
