"""
P&D (Pesquisa & Desenvolvimento) Module - Complete Routes
Collections: pd_requests, pd_request_status_history, pd_developments,
             pd_formulas, pd_formula_items, pd_tests, pd_samples,
             pd_approvals, pd_costs, pd_documents
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, Field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import uuid
import io
import logging
import asyncio
import unicodedata
from validation_utils import clean_text, normalize_cnpj, normalize_email, normalize_phone, is_valid_cnpj, is_valid_email, is_valid_phone
from workflow_engine import create_workflow_task, audit_log, get_blocking_tasks, next_sequence
from rbac import (
    require_roles,
    has_role,
    can_view_formula_composition,
    can_view_live_document_revisions,
    can_view_commercial_costs,
    PD_READ,
    PD_FULL,
    PD_WRITE,
    HOMOLOGACAO_WRITE,
    HOMOLOGACAO_APPROVE,
    DOC_REVIEWERS,
    QA_APPROVERS,
    ADMIN_ONLY,
    COMPRAS_FULL,
    COMERCIAL_FULL,
)

logger = logging.getLogger(__name__)

pd_router = APIRouter(prefix="/api/pd")

# Will be set from server.py
db = None
get_current_user = None
new_id_func = None
now_iso_func = None
put_object_func = None
_broadcast_event = None

def init_pd(database, auth_func, id_func, iso_func, storage_func=None, broadcast_event_fn=None):
    global db, get_current_user, new_id_func, now_iso_func, put_object_func, _broadcast_event
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func
    put_object_func = storage_func
    _broadcast_event = broadcast_event_fn

def new_id():
    return new_id_func()

def now_iso():
    return now_iso_func()


PD_KANBAN_TO_CRM_STATUS = {
    "solicitado": "solicitada",
    "em_desenvolvimento": "em_elaboracao",
    "em_testes": None,
    "aguardando_aprovacao": "enviada",
    "retrabalho_interno": "retrabalho",
    "aprovado": "aprovada",
    "concluido": None,
}


def _validate_supplier_payload(payload: dict) -> dict:
    payload["razao_social"] = clean_text(payload.get("razao_social", ""))
    payload["nome_fantasia"] = clean_text(payload.get("nome_fantasia", ""))
    payload["contato_nome"] = clean_text(payload.get("contato_nome", ""))
    payload["contato_email"] = normalize_email(payload.get("contato_email", ""))
    payload["contato_telefone"] = normalize_phone(payload.get("contato_telefone", ""))
    payload["cnpj"] = clean_text(payload.get("cnpj", ""))
    payload["cnpj_normalized"] = normalize_cnpj(payload.get("cnpj", ""))

    if not payload["razao_social"]:
        raise HTTPException(status_code=400, detail="Razao social obrigatoria")
    if payload["cnpj_normalized"] and not is_valid_cnpj(payload["cnpj_normalized"]):
        raise HTTPException(status_code=400, detail="CNPJ do fornecedor invalido")
    if payload["contato_email"] and not is_valid_email(payload["contato_email"]):
        raise HTTPException(status_code=400, detail="E-mail do fornecedor invalido")
    if payload["contato_telefone"] and not is_valid_phone(payload["contato_telefone"]):
        raise HTTPException(status_code=400, detail="Telefone do fornecedor invalido")

    return payload

# ============ STATUS DEFINITIONS ============

VALID_STATUSES = ["OPEN", "IN_PROGRESS", "IN_TESTS", "WAITING_APPROVAL", "APPROVED", "COMPLETED", "REJECTED"]

ALLOWED_TRANSITIONS = {
    "OPEN": ["IN_PROGRESS"],
    "IN_PROGRESS": ["IN_TESTS"],
    "IN_TESTS": ["WAITING_APPROVAL"],
    "WAITING_APPROVAL": ["APPROVED", "REJECTED"],
    "APPROVED": ["COMPLETED"],
    "REJECTED": ["IN_PROGRESS"],
    "COMPLETED": [],
}

ALLOWED_BACKWARD_TRANSITIONS = {
    "IN_PROGRESS": ["OPEN"],
    "IN_TESTS": ["IN_PROGRESS"],
    "WAITING_APPROVAL": ["IN_TESTS"],
    "APPROVED": ["WAITING_APPROVAL"],
}

STATUS_LABELS = {
    "OPEN": "Aberto",
    "IN_PROGRESS": "Em Desenvolvimento",
    "IN_TESTS": "Em Testes",
    "WAITING_APPROVAL": "Aguardando Aprovação",
    "APPROVED": "Aprovado",
    "COMPLETED": "Concluído",
    "REJECTED": "Rejeitado",
}

PD_STATUS_TO_KANBAN = {
    "OPEN": "solicitado",
    "IN_PROGRESS": "em_desenvolvimento",
    "IN_TESTS": "em_testes",
    "WAITING_APPROVAL": "aguardando_aprovacao",
    "REJECTED": "retrabalho_interno",
    "APPROVED": "aprovado",
    "COMPLETED": "concluido",
}

PD_KANBAN_LABELS = {
    "solicitado": "Solicitado",
    "em_desenvolvimento": "Em Desenvolvimento",
    "em_testes": "Em Testes",
    "aguardando_aprovacao": "Aguardando Aprovação",
    "retrabalho_interno": "Retrabalho",
    "aprovado": "Aprovado",
    "concluido": "Concluído",
}


def _has_meaningful_lab_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, dict):
        return any(_has_meaningful_lab_value(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_lab_value(v) for v in value)
    return True


async def _sync_request_status_to_pipeline(
    *,
    req_id: str,
    tenant_id: str,
    new_status: str,
    linked_pd_card_id: Optional[str] = None,
    user: Optional[dict] = None,
    movement_comment: str = "",
):
    kanban_status = PD_STATUS_TO_KANBAN.get(new_status)
    if not kanban_status:
        return None

    card = await db.pd_cards.find_one(
        {"pd_request_id": req_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not card and linked_pd_card_id:
        card = await db.pd_cards.find_one(
            {"id": linked_pd_card_id, "tenant_id": tenant_id},
            {"_id": 0},
        )
    if not card:
        return None

    now = now_iso()
    old_card_status = card.get("status_pd", "")
    update_doc: Dict[str, Any] = {
        "$set": {
            "status_pd": kanban_status,
            "pd_request_id": req_id,
            "updated_at": now,
        }
    }
    if user and old_card_status != kanban_status:
        update_doc["$push"] = {
            "historico_movimentacoes": {
                "de": old_card_status,
                "para": kanban_status,
                "data": now,
                "usuario": user.get("name", ""),
                "usuario_id": user["id"],
                "observacao": movement_comment or f"Sincronizado automaticamente pela requisição P&D: {STATUS_LABELS.get(new_status, new_status)}",
                "sincronizado_pd_request": True,
            }
        }

    await db.pd_cards.update_one(
        {"id": card["id"], "tenant_id": tenant_id},
        update_doc,
    )

    updated_card = {**card, "status_pd": kanban_status, "pd_request_id": req_id, "updated_at": now}
    if user and old_card_status != kanban_status:
        historico = list(card.get("historico_movimentacoes") or [])
        historico.append(update_doc["$push"]["historico_movimentacoes"])
        updated_card["historico_movimentacoes"] = historico

    if _broadcast_event and old_card_status != kanban_status:
        await _broadcast_event(
            tenant_id,
            "pd_card_moved",
            {"card": updated_card, "from_status": old_card_status, "to_status": kanban_status},
        )

    if updated_card.get("amostra_variacao_id"):
        crm_status = PD_KANBAN_TO_CRM_STATUS.get(kanban_status)
        set_ops = {
            "variacoes.$.status_pd_raw": kanban_status,
            "variacoes.$.status_pd_label": PD_KANBAN_LABELS.get(kanban_status, kanban_status),
            "updated_at": now,
        }
        if crm_status:
            set_ops["variacoes.$.status"] = crm_status
        if kanban_status == "aguardando_aprovacao":
            set_ops["variacoes.$.aprovacao_interna"] = True
            set_ops["variacoes.$.enviado_comercial_em"] = now
            set_ops["data_envio"] = now
            set_ops["aprovacao_interna"] = True
        elif kanban_status == "aprovado":
            set_ops["variacoes.$.resultado"] = "aprovada"
            set_ops["variacoes.$.aprovacao_interna"] = True
            set_ops["variacoes.$.aprovacao_externa"] = True
            set_ops["variacoes.$.aprovado_cliente_em"] = now
        elif kanban_status == "retrabalho_interno":
            set_ops["variacoes.$.aprovacao_externa"] = False

        await db.crm_samples.update_one(
            {
                "id": updated_card.get("amostra_id"),
                "tenant_id": tenant_id,
                "variacoes.id": updated_card["amostra_variacao_id"],
            },
            {"$set": set_ops}
        )
        if _broadcast_event:
            await _broadcast_event(
                tenant_id,
                "crm_sample_pd_synced",
                {
                    "amostra_id": updated_card.get("amostra_id"),
                    "variacao_id": updated_card["amostra_variacao_id"],
                    "status_pd_raw": kanban_status,
                    "status_pd_label": PD_KANBAN_LABELS.get(kanban_status, kanban_status),
                }
            )

    project_id = updated_card.get("projeto_id")
    if user and not project_id and updated_card.get("amostra_id"):
        linked_sample = await db.crm_samples.find_one(
            {"id": updated_card["amostra_id"], "tenant_id": tenant_id},
            {"_id": 0, "projeto_id": 1},
        )
        project_id = (linked_sample or {}).get("projeto_id")

    if user and project_id:
        project_sync = {
            "em_desenvolvimento": (
                "amostra_em_desenvolvimento",
                "pd_request_in_development",
                {"data_inicio_desenvolvimento": now},
            ),
            "aguardando_aprovacao": (
                "amostra_enviada",
                "pd_request_waiting_approval",
                {"data_ultima_amostra_enviada": now},
            ),
        }.get(kanban_status)
        if project_sync:
            from crm_routes import _advance_project_stage_if_needed

            target_stage, movement_source, extra_set = project_sync
            await _advance_project_stage_if_needed(
                project_id,
                target_stage,
                user,
                movement_source=movement_source,
                extra_set=extra_set,
            )

    return updated_card

# ============ PYDANTIC MODELS ============

class PDRequestCreate(BaseModel):
    client_card_id: Optional[str] = None
    client_name: Optional[str] = None
    project_name: str
    technical_name: Optional[str] = None
    commercial_name: Optional[str] = None
    internal_code: Optional[str] = None
    request_type: str = "Produto Novo"
    category: Optional[str] = None
    description: Optional[str] = None
    references: Optional[str] = None
    restrictions: Optional[str] = None
    volume: Optional[str] = None
    packaging: Optional[str] = None
    priority: str = "Normal"
    deadline: Optional[str] = None
    is_internal_research: bool = False
    kickoff_completed: bool = False

class PDRequestUpdate(BaseModel):
    project_name: Optional[str] = None
    technical_name: Optional[str] = None
    commercial_name: Optional[str] = None
    internal_code: Optional[str] = None
    request_type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    references: Optional[str] = None
    restrictions: Optional[str] = None
    volume: Optional[str] = None
    packaging: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[str] = None
    sku: Optional[str] = None
    kickoff_completed: Optional[bool] = None

class StatusTransition(BaseModel):
    new_status: str
    comment: Optional[str] = None
    is_backward: bool = False

class FormulaCreate(BaseModel):
    name: str
    notes: Optional[str] = None
    volume: Optional[float] = None
    volume_unit: Optional[str] = "mL"
    indice_perdas: Optional[float] = 0
    cotacao_usd: Optional[float] = 6.00

class FormulaUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    volume: Optional[float] = None
    volume_unit: Optional[str] = None
    indice_perdas: Optional[float] = None
    cotacao_usd: Optional[float] = None
    fragrance_target: Optional[float] = None

class FormulaItemCreate(BaseModel):
    ingredient_name: str
    percentage: float
    price_per_kg: float = 0.0
    price_usd: Optional[float] = None   # R04: preço em US$ (fragrâncias cotadas em dólar)
    fornecedor: Optional[str] = ""
    phase: Optional[str] = None
    function: Optional[str] = None
    catalog_id: Optional[str] = None  # Link to cost catalog

class FormulaItemUpdate(BaseModel):
    ingredient_name: Optional[str] = None
    percentage: Optional[float] = None
    price_per_kg: Optional[float] = None
    price_usd: Optional[float] = None   # R04: preço em US$
    fornecedor: Optional[str] = None
    phase: Optional[str] = None
    function: Optional[str] = None
    catalog_id: Optional[str] = None

class TestCreate(BaseModel):
    test_type: str
    status: str = "PENDING"
    # Structured test data
    dados: Optional[Dict[str, Any]] = None

class TestUpdate(BaseModel):
    status: Optional[str] = None
    dados: Optional[Dict[str, Any]] = None

class SampleCreate(BaseModel):
    formula_version: int
    sent_to_client: bool = False
    feedback: Optional[str] = None

class SampleUpdate(BaseModel):
    sent_to_client: Optional[bool] = None
    feedback: Optional[str] = None
    internal_approved: Optional[bool] = None
    client_approved: Optional[bool] = None

class ApprovalCreate(BaseModel):
    approved_by_client: bool = False
    approved_by_internal: bool = False
    notes: Optional[str] = None

class CostCreate(BaseModel):
    ingredient_cost: float = 0.0
    packaging_cost: float = 0.0
    labor_cost: float = 0.0

# --- Cost versioning (new system) ---

class PDCostV1Upsert(BaseModel):
    """P&D saves a draft of ingredient-level costs (v1)."""
    ingredient_cost_manual: float = 0.0
    notes: str = ""

class ComprasCostUpsert(BaseModel):
    """Commercial/cost team fills in the commercial cost breakdown (v2)."""
    packaging_cost: float = 0.0
    labor_cost: float = 0.0
    overhead_cost: float = 0.0
    other_cost: float = 0.0
    notes: str = ""

class DocumentCreate(BaseModel):
    doc_type: str
    file_url: str
    file_name: Optional[str] = None


class LiveDocumentGenerate(BaseModel):
    reason: str = ""
    changed_fields: List[str] = []


LIVE_DOCUMENT_TYPES = {"ficha_tecnica", "epa"}
LIVE_DOCUMENT_REVIEW_ROLES = {"admin", "gestor", "lider_pd", "qa", "formulador", "engenharia_produto"}

# Status liberados: homologada (aprovada), pendente, rejeitada, suspensa (bloqueio temporario por nao conformidade)
MP_BLOCKED_STATUSES = {"rejeitada", "suspensa"}
MP_OK_STATUSES = {"homologada"}

STABILITY_CONDITIONS = [
    {"code": "ambient",       "label": "Ambiente",         "temperature": "25°C",        "humidity": "60% UR",  "protected_from_light": False},
    {"code": "oven_45",       "label": "Estufa 45°C",      "temperature": "45°C",        "humidity": "Controlada", "protected_from_light": False},
    {"code": "freezer_minus5","label": "Freezer -5°C",     "temperature": "-5°C",        "humidity": "N/A",     "protected_from_light": False},
    {"code": "light_exposure","label": "Exposição a Luz",  "temperature": "25°C",        "humidity": "60% UR",  "protected_from_light": False},
    {"code": "freeze_thaw",   "label": "Ciclo Freeze/Thaw","temperature": "-5°C ↔ 40°C", "humidity": "Cíclico", "protected_from_light": False, "checkpoints": [1, 2, 7, 15]},
]

STABILITY_PARAMETERS = [
    {"code": "appearance", "label": "Aspecto"},
    {"code": "color", "label": "Cor"},
    {"code": "odor", "label": "Odor"},
    {"code": "ph", "label": "pH"},
    {"code": "viscosity", "label": "Viscosidade"},
    {"code": "density", "label": "Densidade"},
    {"code": "spreadability", "label": "Espalhabilidade"},
    {"code": "separation", "label": "Separacao de fases"},
    {"code": "precipitation", "label": "Precipitacao"},
    {"code": "microbiology", "label": "Microbiologia"},
    {"code": "package_compatibility", "label": "Compatibilidade com embalagem"},
    {"code": "mass_variation", "label": "Variacao de massa"},
]

STABILITY_CHECKPOINTS = [1, 2, 7, 30, 60, 90]  # D24h, D48h, D7, D30, D60, D90
STABILITY_OPEN_STATUSES = {"ativo", "em_revisao"}


class StabilityReadingCreate(BaseModel):
    condition_code: str
    day_offset: int = Field(ge=0, le=365)
    reading_at: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    photo_urls: List[str] = Field(default_factory=list)


def _stability_condition_map() -> Dict[str, Dict[str, Any]]:
    return {condition["code"]: condition for condition in STABILITY_CONDITIONS}


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_after_days(base_iso: str, days: int) -> str:
    base_dt = _parse_iso_datetime(base_iso) or datetime.now(timezone.utc)
    return (base_dt + timedelta(days=days)).isoformat()


def _build_stability_conditions(started_at: str) -> List[Dict[str, Any]]:
    conditions = []
    for condition in STABILITY_CONDITIONS:
        cps = list(condition.get("checkpoints") or STABILITY_CHECKPOINTS)
        conditions.append({
            **condition,
            "checkpoints": cps,
            "completed_day_offsets": [],
            "next_due_day_offset": cps[0],
            "next_due_at": _iso_after_days(started_at, cps[0]),
            "last_reading_at": None,
            "status": "pending",
        })
    return conditions


def _allowed_stability_checkpoints(study: Optional[Dict[str, Any]], condition_code: str) -> List[int]:
    for condition in (study or {}).get("conditions", []):
        if condition.get("code") == condition_code:
            checkpoints = list(condition.get("checkpoints") or [])
            if checkpoints:
                return checkpoints
            break
    template = _stability_condition_map().get(condition_code) or {}
    return list(template.get("checkpoints") or STABILITY_CHECKPOINTS)


def _normalize_stability_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {item["code"] for item in STABILITY_PARAMETERS}
    cleaned: Dict[str, Any] = {}
    for key, value in (parameters or {}).items():
        normalized_key = clean_text(str(key)).lower().replace(" ", "_")
        if normalized_key in allowed and value not in (None, ""):
            cleaned[normalized_key] = value
    return cleaned


def _summarize_stability_conditions(study: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    condition_summaries: List[Dict[str, Any]] = []
    counts = {"pending": 0, "due_soon": 0, "overdue": 0, "completed": 0, "on_track": 0}

    for condition in study.get("conditions", []):
        next_due_at = _parse_iso_datetime(condition.get("next_due_at"))
        completed = list(condition.get("completed_day_offsets") or [])
        checkpoints = list(condition.get("checkpoints") or [])
        if len(completed) >= len(checkpoints):
            status = "completed"
        elif next_due_at and next_due_at < now:
            status = "overdue"
        elif next_due_at and next_due_at <= now + timedelta(days=2):
            status = "due_soon"
        elif completed:
            status = "on_track"
        else:
            status = "pending"

        counts[status] += 1
        condition_summaries.append({
            **condition,
            "status": status,
        })

    if counts["overdue"]:
        overall_status = "critico"
    elif counts["due_soon"]:
        overall_status = "atencao"
    elif counts["completed"] == len(condition_summaries) and condition_summaries:
        overall_status = "concluido"
    else:
        overall_status = "em_dia"

    next_due_candidates = [
        _parse_iso_datetime(condition.get("next_due_at"))
        for condition in condition_summaries
        if condition.get("status") in {"due_soon", "on_track", "overdue"}
    ]
    next_due_candidates = [item for item in next_due_candidates if item is not None]

    return {
        "conditions": condition_summaries,
        "summary": {
            "overall_status": overall_status,
            "counts": counts,
            "next_due_at": min(next_due_candidates).isoformat() if next_due_candidates else None,
            "completed_conditions": counts["completed"],
            "total_conditions": len(condition_summaries),
        },
    }


async def _recalculate_stability_study(study_id: str) -> Dict[str, Any]:
    study = await db.pd_stability_studies.find_one({"id": study_id}, {"_id": 0})
    if not study:
        raise HTTPException(status_code=404, detail="Estudo de estabilidade nao encontrado")

    recalculated = _summarize_stability_conditions(study)
    status = study.get("status", "ativo")
    if recalculated["summary"]["overall_status"] == "concluido":
        status = "concluido"

    await db.pd_stability_studies.update_one(
        {"id": study_id},
        {
            "$set": {
                "conditions": recalculated["conditions"],
                "summary": recalculated["summary"],
                "status": status,
                "updated_at": now_iso(),
            }
        },
    )
    return await db.pd_stability_studies.find_one({"id": study_id}, {"_id": 0})


async def _ensure_stability_study_for_pd_card(card: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    existing = await db.pd_stability_studies.find_one(
        {"tenant_id": user["tenant_id"], "pd_card_id": card["id"]},
        {"_id": 0},
    )
    if existing:
        return existing

    started_at = now_iso()
    study = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "pd_card_id": card["id"],
        "amostra_id": card.get("amostra_id"),
        "amostra_variacao_id": card.get("amostra_variacao_id"),
        "amostra_numero": card.get("amostra_numero", ""),
        "numero_completo": card.get("numero_completo", ""),
        "produto": card.get("produto", ""),
        "cliente": card.get("cliente", ""),
        "cliente_id": card.get("cliente_id"),
        "projeto_id": card.get("projeto_id"),
        "projeto_nome": card.get("projeto_nome", ""),
        "status": "ativo",
        "d0_completed": False,
        "started_at": started_at,
        "conditions": _build_stability_conditions(started_at),
        "summary": {},
        "created_at": started_at,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "updated_at": started_at,
    }
    summary = _summarize_stability_conditions(study)
    study["conditions"] = summary["conditions"]
    study["summary"] = summary["summary"]
    await db.pd_stability_studies.insert_one(study)
    study.pop("_id", None)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="stability_study_auto_created",
        entity_type="stability_study",
        entity_id=study["id"],
        after={
            "pd_card_id": card["id"],
            "numero_completo": card.get("numero_completo", ""),
            "conditions": len(study["conditions"]),
        },
    )
    return study


async def _create_stability_alert_task(
    *,
    study: Dict[str, Any],
    condition: Dict[str, Any],
    alert_kind: str,
) -> Optional[Dict[str, Any]]:
    next_due_day = condition.get("next_due_day_offset")
    if next_due_day is None:
        return None

    alert_key = f"{alert_kind}:{condition['code']}:{next_due_day}"
    existing = await db.workflow_tasks.find_one(
        {
            "tenant_id": study["tenant_id"],
            "entity_type": "stability_study",
            "entity_id": study["id"],
            "status": {"$in": ["pendente", "em_andamento", "em_atraso"]},
            "metadata.alert_key": alert_key,
        },
        {"_id": 0},
    )
    if existing:
        return None

    due_at = _parse_iso_datetime(condition.get("next_due_at")) or datetime.now(timezone.utc)
    due_in_days = max(0, int((due_at - datetime.now(timezone.utc)).total_seconds() // 86400))
    title = (
        f"Registrar leitura de estabilidade D{next_due_day} - {condition['label']}"
        if alert_kind == "d_minus_2"
        else f"Leitura de estabilidade atrasada D{next_due_day} - {condition['label']}"
    )
    description = (
        f"Amostra {study.get('numero_completo') or study.get('amostra_numero', '')} em {condition['label']}."
    )
    return await create_workflow_task(
        tenant_id=study["tenant_id"],
        entity_type="stability_study",
        entity_id=study["id"],
        title=title,
        description=description,
        category="pd_dev",
        blocking=False,
        due_in_days=due_in_days,
        created_by={"id": "system", "name": "System Scheduler"},
        metadata={
            "trigger": "stability_scheduler",
            "alert_kind": alert_kind,
            "alert_key": alert_key,
            "condition_code": condition["code"],
            "day_offset": next_due_day,
            "pd_card_id": study.get("pd_card_id"),
            "priority": "alta" if alert_kind == "overdue" else "media",
        },
    )


async def check_stability_alerts_for_tenant(tenant_id: str) -> int:
    studies = await db.pd_stability_studies.find(
        {"tenant_id": tenant_id, "status": {"$in": list(STABILITY_OPEN_STATUSES)}},
        {"_id": 0},
    ).to_list(2000)
    created = 0
    now = datetime.now(timezone.utc)

    for study in studies:
        refreshed = _summarize_stability_conditions(study)
        for condition in refreshed["conditions"]:
            next_due_at = _parse_iso_datetime(condition.get("next_due_at"))
            if not next_due_at or condition.get("next_due_day_offset") is None:
                continue
            if next_due_at <= now:
                task = await _create_stability_alert_task(study=study, condition=condition, alert_kind="overdue")
                created += 1 if task else 0
            elif next_due_at <= now + timedelta(days=2):
                task = await _create_stability_alert_task(study=study, condition=condition, alert_kind="d_minus_2")
                created += 1 if task else 0

    return created


async def run_stability_scheduler():
    await asyncio.sleep(60)
    while True:
        try:
            tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(500)
            for tenant in tenants:
                created = await check_stability_alerts_for_tenant(tenant["id"])
                # Persist last-run for UI visibility
                await db.system_status.update_one(
                    {"id": "stability_scheduler"},
                    {"$set": {
                        "id": "stability_scheduler",
                        "last_run_at": now_iso(),
                        "last_tenant_id": tenant["id"],
                        "last_alerts_created": created,
                    }},
                    upsert=True,
                )
        except Exception as exc:  # pragma: no cover
            logger.error(f"Stability scheduler error: {exc}")
        await asyncio.sleep(3600)  # run every 1 hour for better D-2 responsiveness

# ============ HELPER: Calculate formula item costs ============

def calc_item_costs(percentage: float, price_per_kg: float, cotacao_usd: float, price_usd: Optional[float] = None):
    """Calculate derived cost fields for a formula item.
    R04: price_usd é preço em US$/kg; cost_brl_via_cambio = (pct/100) × price_usd × cotacao_usd.
    """
    cost_brl = (percentage / 100.0) * price_per_kg if percentage and price_per_kg else 0.0
    cost_kg_usd = price_per_kg / cotacao_usd if cotacao_usd and cotacao_usd > 0 else 0.0
    cost_brl_via_cambio: Optional[float] = None
    if price_usd is not None and cotacao_usd and cotacao_usd > 0 and percentage:
        cost_brl_via_cambio = round((percentage / 100.0) * price_usd * cotacao_usd, 4)
    return round(cost_brl, 4), round(cost_kg_usd, 4), cost_brl_via_cambio


def _normalize_currency_code_local(value: Optional[str], default: str = "BRL") -> str:
    code = str(value or default or "BRL").strip().upper()
    return code if code in {"BRL", "USD"} else default


async def _repair_prefilled_fragrance_item_from_variacao(
    formula: dict,
    item: dict,
    variacao: Optional[dict],
):
    if not formula or not item or not variacao:
        return item

    if _normalize_currency_code_local(variacao.get("custo_fragrancia_currency"), "BRL") != "USD":
        return item

    frag_pct = float(variacao.get("percentual_fragrancia") or 0)
    frag_cost_usd = float(variacao.get("custo_fragrancia") or 0)
    item_pct = float(item.get("percentage") or 0)
    ingredient_name = clean_text(item.get("ingredient_name", "")).lower()
    ref_frag = clean_text(variacao.get("referencia_fragrancia", "")).lower()
    phase = clean_text(item.get("phase", "")).lower()
    function = clean_text(item.get("function", "")).lower()
    is_fragrance_item = (
        ("fragr" in ingredient_name)
        or ("fragr" in phase)
        or ("fragr" in function)
        or (ref_frag and ingredient_name == ref_frag)
    )

    if not is_fragrance_item or frag_pct <= 0 or frag_cost_usd <= 0:
        return item
    if abs(item_pct - frag_pct) > 0.0001:
        return item

    cotacao = float(formula.get("cotacao_usd", 6.00) or 6.00)
    price_per_kg = round(frag_cost_usd * cotacao, 4)
    cost_brl, cost_kg_usd, cost_brl_via_cambio = calc_item_costs(
        item_pct,
        price_per_kg,
        cotacao,
        frag_cost_usd,
    )

    expected_fields = {
        "price_per_kg": price_per_kg,
        "price_usd": frag_cost_usd,
        "cost_brl": cost_brl,
        "cost_kg_usd": cost_kg_usd,
        "cost_brl_via_cambio": cost_brl_via_cambio,
    }
    if all(item.get(field) == value for field, value in expected_fields.items()):
        return item

    await db.pd_formula_items.update_one(
        {"id": item["id"]},
        {"$set": expected_fields},
    )
    return {**item, **expected_fields}


def _document_label(doc_type: str) -> str:
    return "Ficha Técnica" if doc_type == "ficha_tecnica" else "EPA"


def _document_version_code(doc_type: str, version_number: int) -> str:
    prefix = "FT" if doc_type == "ficha_tecnica" else "EPA"
    return f"{prefix}-V{version_number:03d}"


async def _get_pd_request_context(req_id: str, tenant_id: str) -> Dict[str, Any]:
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": tenant_id}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")

    dev = await db.pd_developments.find_one({"pd_request_id": req_id, "tenant_id": tenant_id}, {"_id": 0})
    approval = None
    lab_results = {}
    latest_formula = None
    formula_items = []
    if dev:
        approval = await db.pd_approvals.find_one({"development_id": dev["id"]}, {"_id": 0})
        lab_results = await db.pd_lab_results.find_one({"development_id": dev["id"]}, {"_id": 0}) or {}
        latest_formula = await db.pd_formulas.find_one(
            {"development_id": dev["id"]},
            {"_id": 0},
            sort=[("version", -1)]
        )
        if latest_formula:
            formula_items = await db.pd_formula_items.find({"formula_id": latest_formula["id"]}, {"_id": 0}).to_list(500)

    return {
        "request": pd_req,
        "development": dev,
        "approval": approval,
        "lab_results": lab_results,
        "formula": latest_formula,
        "formula_items": formula_items,
    }


async def _enrich_formula_items(tenant_id: str, formula_items: List[Dict[str, Any]], formula: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    catalog_ids = [item.get("catalog_id") for item in formula_items if item.get("catalog_id")]
    catalog_map: Dict[str, Dict[str, Any]] = {}
    if catalog_ids:
        catalog_docs = await db.pd_catalog.find(
            {"tenant_id": tenant_id, "id": {"$in": catalog_ids}},
            {"_id": 0}
        ).to_list(1000)
        catalog_map = {doc["id"]: doc for doc in catalog_docs if doc.get("id")}

    base_volume = (formula or {}).get("volume", 0) or 0
    volume_unit = (formula or {}).get("volume_unit", "mL")
    volume_factor = base_volume / 1000.0 if volume_unit == "mL" else base_volume

    enriched = []
    for item in formula_items:
        catalog = catalog_map.get(item.get("catalog_id"))
        percentage = item.get("percentage", 0) or 0
        qty = round(volume_factor * (percentage / 100.0), 6) if volume_factor else 0
        enriched.append({
            **item,
            "nome_tecnico": catalog.get("nome") if catalog else item.get("ingredient_name", ""),
            "nome_comercial": catalog.get("nome") if catalog else item.get("ingredient_name", ""),
            "inci": catalog.get("inci", "") if catalog else "",
            "fornecedor": catalog.get("fornecedor", "") if catalog else item.get("fornecedor", ""),
            "unidade_lote": "kg" if volume_unit == "L" else volume_unit,
            "quantidade_lote_padrao": qty,
        })
    return enriched


def _is_ficha_tecnica_eligible(ctx: Dict[str, Any]) -> bool:
    approval = ctx.get("approval") or {}
    return bool(approval.get("approved_by_client")) and bool(ctx.get("formula"))


def _is_epa_eligible(ctx: Dict[str, Any]) -> bool:
    req = ctx.get("request") or {}
    approval = ctx.get("approval") or {}
    return bool(req.get("kickoff_completed")) and bool(approval.get("approved_by_client")) and bool(ctx.get("formula"))


def _pd_request_requires_commercial_approval(pd_req: Dict[str, Any]) -> bool:
    """Solicitacoes vinculadas a cliente/amostra comercial precisam de aceite Comercial."""
    if not pd_req:
        return False
    if pd_req.get("is_internal_research"):
        return False
    commercial_links = (
        pd_req.get("client_card_id"),
        pd_req.get("linked_amostra_id"),
        pd_req.get("linked_variacao_id"),
        pd_req.get("crm_project_id"),
        pd_req.get("order_id"),
        pd_req.get("pedido_id"),
    )
    if any(commercial_links):
        return True
    request_type = clean_text(pd_req.get("request_type") or "").lower()
    return request_type not in {"", "pesquisa interna", "internal research"}


def _assert_can_register_client_approval(pd_req: Dict[str, Any], user: Dict[str, Any]) -> None:
    if _pd_request_requires_commercial_approval(pd_req) and not has_role(user, COMERCIAL_FULL):
        raise HTTPException(
            status_code=403,
            detail="Solicitacao comercial: a aprovacao do cliente/comercial deve ser registrada por Comercial ou Admin. P&D deve entregar para aprovacao e aguardar retorno.",
        )


async def _build_live_document_snapshot(req_id: str, doc_type: str, tenant_id: str) -> Dict[str, Any]:
    ctx = await _get_pd_request_context(req_id, tenant_id)
    req = ctx["request"]
    formula = ctx.get("formula") or {}
    approval = ctx.get("approval") or {}
    lab_results = ctx.get("lab_results") or {}
    enriched_items = await _enrich_formula_items(tenant_id, ctx.get("formula_items") or [], formula)

    if doc_type == "ficha_tecnica":
        if not _is_ficha_tecnica_eligible(ctx):
            raise HTTPException(status_code=400, detail="Ficha Técnica só pode ser gerada após aprovação do cliente e fórmula disponível.")
        _COST_FIELDS = {"price_per_kg", "price_currency", "cost_brl", "cost_kg_usd", "catalog_id"}
        composicao_ft = [
            {k: v for k, v in item.items() if k not in _COST_FIELDS}
            for item in enriched_items
        ]
        return {
            "identificacao": {
                "nome_tecnico": req.get("technical_name") or formula.get("name") or req.get("project_name"),
                "nome_comercial": req.get("commercial_name") or req.get("project_name"),
                "codigo_interno": req.get("internal_code") or req.get("sku") or "",
                "versao_formula": formula.get("version"),
                "data_snapshot": now_iso(),
                "formulador": formula.get("created_by_name", ""),
                "cliente": req.get("client_name") or "Portfólio Kuryos",
            },
            "composicao_completa": composicao_ft,
            "modo_preparo": {
                "resumo": formula.get("notes", ""),
                "temperatura_processo": lab_results.get("ph", {}).get("temperatura", ""),
                "equipamento": "",
                "rpm": lab_results.get("viscosidade", {}).get("spindle", ""),
                "alertas_processo": lab_results.get("compatibilidade", {}).get("observacoes", ""),
            },
            "parametros_in_process": {
                "ph_esperado": lab_results.get("ph", {}).get("faixa_aceitavel", ""),
                "ph_medido": lab_results.get("ph", {}).get("valor_medido", ""),
                "viscosidade_esperada": lab_results.get("viscosidade", {}).get("valor_medido", ""),
                "criterios_bulk": lab_results.get("estabilidade", {}).get("aspecto", ""),
                "ativos_termossensiveis": "",
            },
            "rendimento_teorico": {
                "lote_padrao": formula.get("volume", 0),
                "unidade": formula.get("volume_unit", "mL"),
                "fator_perdas_percentual": formula.get("indice_perdas", 0),
            },
            "observacoes_tecnicas": {
                "gerais": formula.get("notes", ""),
                "compatibilidade": lab_results.get("compatibilidade", {}).get("resultado", ""),
                "substituicoes_permitidas": "",
                "substituicoes_nao_permitidas": "",
            },
        }

    if not _is_epa_eligible(ctx):
        raise HTTPException(status_code=400, detail="EPA só pode ser gerado após kickoff concluído, aprovação do cliente e fórmula disponível.")

    return {
        "identificacao_produto": {
            "nome_comercial": req.get("commercial_name") or req.get("project_name"),
            "codigo_interno": req.get("internal_code") or req.get("sku") or "",
            "cliente": req.get("client_name") or "Portfólio Kuryos",
            "sku": req.get("sku", ""),
            "data_snapshot": now_iso(),
        },
        "bom_bulk_formula": {
            "formula_referencia": formula.get("name", ""),
            "versao": formula.get("version"),
            "quantidade_bulk_unidade": formula.get("volume", 0),
            "unidade": formula.get("volume_unit", "mL"),
            "composicao": enriched_items,
        },
        "bom_embalagem_primaria": {
            "descricao": req.get("packaging", ""),
        },
        "bom_embalagem_secundaria": {
            "descricao": "",
        },
        "especificacoes_produto_acabado": {
            "ph": lab_results.get("ph", {}),
            "viscosidade": lab_results.get("viscosidade", {}),
            "densidade": {},
            "aspecto": lab_results.get("sensorial", {}).get("aspecto", ""),
            "cor": lab_results.get("sensorial", {}).get("cor", ""),
            "odor": lab_results.get("sensorial", {}).get("odor", ""),
            "estabilidade": lab_results.get("estabilidade", {}),
        },
        "especificacoes_embalagem": {
            "volume_nominal": formula.get("volume", 0),
            "volume_enchimento": formula.get("volume", 0),
            "torque_fechamento": "",
            "teste_vedacao": "",
        },
        "etapas_producao_resumidas": [
            "Pesagem",
            "Manipulação",
            "Envase",
            "Rotulagem",
            "Finalização",
        ],
        "informacoes_rotulo": {
            "inci": ", ".join([item.get("inci", "") for item in enriched_items if item.get("inci")]),
            "modo_uso": "",
            "advertencias": "",
            "prazo_validade": "",
            "lote": "",
            "armazenamento": "",
        },
        "referencia_anvisa": {
            "numero": "",
            "validade": "",
            "responsavel_tecnico": "",
        },
        "criterios_liberacao_lote": {
            "cq_checklist": [
                "Conferir especificações físico-químicas",
                "Conferir aspecto visual e odor",
                "Conferir embalagem, lote e rotulagem",
            ]
        },
    }


async def _create_document_approval_tasks(doc_version: Dict[str, Any], user: dict, reason: str, changed_fields: List[str], source_changes: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    task_ids: List[str] = []
    base_metadata = {
        "module_origin": "documentos_internos",
        "document_type": doc_version["doc_type"],
        "document_version_id": doc_version["id"],
        "changed_fields": changed_fields,
        "source_changes": source_changes or [],
        "generation_reason": reason,
        "task_type": "approval",
        "priority": "alta",
    }

    if doc_version["doc_type"] == "ficha_tecnica":
        main_task = await create_workflow_task(
            tenant_id=doc_version["tenant_id"],
            entity_type="pd_document",
            entity_id=doc_version["id"],
            title=f"Aprovar {_document_label(doc_version['doc_type'])} {doc_version['version_code']}",
            description="Registrar aprovação formal da nova versão da Ficha Técnica.",
            category="documentacao",
            blocking=True,
            due_in_days=2,
            created_by=user,
            metadata={**base_metadata, "approver_role": "lider_pd"},
        )
        task_ids.append(main_task["id"])
        needs_qa = any(field in {"modo_preparo", "ordem_adicao", "parametros_in_process"} for field in changed_fields)
        if needs_qa:
            qa_task = await create_workflow_task(
                tenant_id=doc_version["tenant_id"],
                entity_type="pd_document",
                entity_id=doc_version["id"],
                title=f"Revisão CQ da Ficha Técnica {doc_version['version_code']}",
                description="Alteração de processo exige revisão adicional do CQ.",
                category="qa",
                blocking=True,
                due_in_days=2,
                created_by=user,
                metadata={**base_metadata, "approver_role": "cq"},
            )
            task_ids.append(qa_task["id"])
        return task_ids

    for title, category, approver_role in [
        (f"Aprovar EPA {doc_version['version_code']} - CQ", "qa", "cq"),
        (f"Aprovar EPA {doc_version['version_code']} - Líder P&D", "pd_dev", "lider_pd"),
        (f"Aprovar EPA {doc_version['version_code']} - Engenharia de Produto", "engenharia_produto", "engenharia_produto"),
    ]:
        task = await create_workflow_task(
            tenant_id=doc_version["tenant_id"],
            entity_type="pd_document",
            entity_id=doc_version["id"],
            title=title,
            description="Registrar aprovação formal da nova versão do EPA.",
            category=category,
            blocking=True,
            due_in_days=2,
            created_by=user,
            metadata={**base_metadata, "approver_role": approver_role},
        )
        task_ids.append(task["id"])
    return task_ids


async def _generate_live_document_version(
    req_id: str,
    doc_type: str,
    user: dict,
    reason: str = "",
    changed_fields: Optional[List[str]] = None,
    trigger: str = "manual",
    source_changes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if doc_type not in LIVE_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de documento vivo inválido")

    changed_fields = changed_fields or []
    snapshot = await _build_live_document_snapshot(req_id, doc_type, user["tenant_id"])
    current_versions = await db.pd_document_versions.find(
        {"tenant_id": user["tenant_id"], "pd_request_id": req_id, "doc_type": doc_type},
        {"_id": 0, "version_number": 1}
    ).sort("version_number", -1).to_list(1)
    next_version = (current_versions[0]["version_number"] + 1) if current_versions else 1

    doc_version = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "pd_request_id": req_id,
        "doc_type": doc_type,
        "version_number": next_version,
        "version_code": _document_version_code(doc_type, next_version),
        "status": "em_revisao",
        "active_for_operation": False,
        "snapshot": snapshot,
        "reason": reason or f"Nova versão de {_document_label(doc_type)}",
        "changed_fields": changed_fields,
        "source_trigger": trigger,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "approved_at": None,
        "approval_task_ids": [],
    }
    await db.pd_document_versions.insert_one(doc_version)
    approval_task_ids = await _create_document_approval_tasks(doc_version, user, reason, changed_fields, source_changes)
    await db.pd_document_versions.update_one(
        {"id": doc_version["id"]},
        {"$set": {"approval_task_ids": approval_task_ids}}
    )
    doc_version["approval_task_ids"] = approval_task_ids
    return doc_version


async def _try_auto_generate_document(
    req_id: str,
    doc_type: str,
    user: dict,
    trigger: str,
    changed_fields: Optional[List[str]] = None,
    source_changes: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    ctx = await _get_pd_request_context(req_id, user["tenant_id"])
    eligible = _is_ficha_tecnica_eligible(ctx) if doc_type == "ficha_tecnica" else _is_epa_eligible(ctx)
    if not eligible:
        return None
    return await _generate_live_document_version(
        req_id=req_id,
        doc_type=doc_type,
        user=user,
        reason=f"Atualização automática por {trigger}",
        changed_fields=changed_fields or [],
        trigger=trigger,
        source_changes=source_changes or [],
    )


def _user_can_review_live_documents(user: dict) -> bool:
    return can_view_live_document_revisions(user)


def _build_source_changes(
    before: Optional[Dict[str, Any]],
    after_updates: Dict[str, Any],
    labels: Optional[Dict[str, str]] = None,
    *,
    ignored_fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    before = before or {}
    labels = labels or {}
    ignored = set(ignored_fields or [])
    changes: List[Dict[str, Any]] = []
    for field, after_value in after_updates.items():
        if field in ignored:
            continue
        before_value = before.get(field)
        if before_value == after_value:
            continue
        changes.append({
            "field": field,
            "label": labels.get(field, field),
            "before": before_value,
            "after": after_value,
        })
    return changes


async def _auto_generate_documents_for_request(
    req_id: str,
    user: dict,
    trigger: str,
    *,
    ficha_changed_fields: Optional[List[str]] = None,
    epa_changed_fields: Optional[List[str]] = None,
    source_changes: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    generated: List[Dict[str, Any]] = []
    if ficha_changed_fields:
        doc = await _try_auto_generate_document(
            req_id=req_id,
            doc_type="ficha_tecnica",
            user=user,
            trigger=trigger,
            changed_fields=ficha_changed_fields,
            source_changes=source_changes,
        )
        if doc:
            generated.append(doc)
    if epa_changed_fields:
        doc = await _try_auto_generate_document(
            req_id=req_id,
            doc_type="epa",
            user=user,
            trigger=trigger,
            changed_fields=epa_changed_fields,
            source_changes=source_changes,
        )
        if doc:
            generated.append(doc)
    return generated


async def _auto_generate_documents_for_development(
    dev_id: str,
    user: dict,
    trigger: str,
    *,
    ficha_changed_fields: Optional[List[str]] = None,
    epa_changed_fields: Optional[List[str]] = None,
    source_changes: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "pd_request_id": 1})
    if not dev or not dev.get("pd_request_id"):
        return []
    return await _auto_generate_documents_for_request(
        dev["pd_request_id"],
        user,
        trigger,
        ficha_changed_fields=ficha_changed_fields,
        epa_changed_fields=epa_changed_fields,
        source_changes=source_changes,
    )


async def _request_ids_from_formula_ids(formula_ids: List[str], tenant_id: str) -> List[str]:
    if not formula_ids:
        return []
    formulas = await db.pd_formulas.find(
        {"id": {"$in": formula_ids}},
        {"_id": 0, "development_id": 1}
    ).to_list(1000)
    dev_ids = [formula.get("development_id") for formula in formulas if formula.get("development_id")]
    if not dev_ids:
        return []
    devs = await db.pd_developments.find(
        {"tenant_id": tenant_id, "id": {"$in": dev_ids}},
        {"_id": 0, "pd_request_id": 1}
    ).to_list(1000)
    return list({dev.get("pd_request_id") for dev in devs if dev.get("pd_request_id")})


async def _auto_generate_documents_for_catalog_items(
    catalog_ids: List[str],
    user: dict,
    trigger: str,
    *,
    ficha_changed_fields: Optional[List[str]] = None,
    epa_changed_fields: Optional[List[str]] = None,
    source_changes: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if not catalog_ids:
        return []
    formula_items = await db.pd_formula_items.find(
        {"catalog_id": {"$in": catalog_ids}},
        {"_id": 0, "formula_id": 1}
    ).to_list(5000)
    formula_ids = list({item.get("formula_id") for item in formula_items if item.get("formula_id")})
    request_ids = await _request_ids_from_formula_ids(formula_ids, user["tenant_id"])
    generated: List[Dict[str, Any]] = []
    for req_id in request_ids:
        generated.extend(await _auto_generate_documents_for_request(
            req_id,
            user,
            trigger,
            ficha_changed_fields=ficha_changed_fields,
            epa_changed_fields=epa_changed_fields,
            source_changes=source_changes,
        ))
    return generated


async def _get_live_document_version(version_id: str, user: dict) -> Dict[str, Any]:
    query = {"id": version_id, "tenant_id": user["tenant_id"]}
    if not _user_can_review_live_documents(user):
        query["status"] = "aprovado"
        query["active_for_operation"] = True
    doc_version = await db.pd_document_versions.find_one(query, {"_id": 0})
    if not doc_version:
        raise HTTPException(status_code=404, detail="Versao de documento nao encontrada")
    approval_tasks = await db.workflow_tasks.find(
        {"tenant_id": user["tenant_id"], "entity_type": "pd_document", "entity_id": version_id},
        {"_id": 0}
    ).sort("created_at", 1).to_list(50)
    doc_version["approval_tasks"] = approval_tasks
    return doc_version

# ============ CRM CLIENT SEARCH ============

@pd_router.get("/clients/search")
async def search_clients(request: Request, q: str = ""):
    user = await get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if q:
        query["nome_cliente"] = {"$regex": q, "$options": "i"}
    cards = await db.cards.find(query, {"_id": 0}).to_list(20)
    return cards

# ============ PD REQUESTS CRUD ============

@pd_router.post("/requests")
async def create_pd_request(data: PDRequestCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    req_id = new_id()
    
    pd_request = {
        "id": req_id,
        "tenant_id": user["tenant_id"],
        "client_card_id": data.client_card_id,
        "client_name": data.client_name or "",
        "project_name": data.project_name,
        "technical_name": data.technical_name or data.project_name,
        "commercial_name": data.commercial_name or data.project_name,
        "internal_code": data.internal_code or "",
        "request_type": data.request_type,
        "category": data.category or "",
        "description": data.description or "",
        "references": data.references or "",
        "restrictions": data.restrictions or "",
        "volume": data.volume or "",
        "packaging": data.packaging or "",
        "priority": data.priority,
        "deadline": data.deadline,
        "status": "OPEN",
        "is_internal_research": data.is_internal_research or False,
        "kickoff_completed": data.kickoff_completed or False,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    
    await db.pd_requests.insert_one(pd_request)
    pd_request.pop("_id", None)
    
    # Log initial status
    await db.pd_request_status_history.insert_one({
        "id": new_id(),
        "pd_request_id": req_id,
        "from_status": None,
        "to_status": "OPEN",
        "changed_by": user["id"],
        "changed_by_name": user["name"],
        "comment": "Solicitação criada",
        "created_at": now_iso(),
    })
    
    return pd_request

@pd_router.get("/requests")
async def list_pd_requests(request: Request, status: Optional[str] = None):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    query = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    
    requests_list = await db.pd_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return requests_list

@pd_router.get("/requests/{req_id}")
async def get_pd_request(req_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    return pd_req

@pd_router.put("/requests/{req_id}")
async def update_pd_request(req_id: str, data: PDRequestUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    existing = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada")
    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    source_changes = _build_source_changes(
        existing,
        update_fields,
        {
            "technical_name": "Nome tecnico",
            "commercial_name": "Nome comercial",
            "internal_code": "Codigo interno",
            "client_name": "Cliente",
            "packaging": "Embalagem",
            "kickoff_completed": "Kickoff concluido",
        },
    )

    update_fields["updated_at"] = now_iso()
    result = await db.pd_requests.update_one(
        {"id": req_id, "tenant_id": user["tenant_id"]},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    
    pd_req = await db.pd_requests.find_one({"id": req_id}, {"_id": 0})
    ficha_changed_fields: List[str] = []
    epa_changed_fields: List[str] = []
    if any(field in update_fields for field in ("technical_name", "commercial_name", "internal_code", "client_name")):
        ficha_changed_fields.append("identificacao")
    if any(field in update_fields for field in ("commercial_name", "internal_code", "client_name")):
        epa_changed_fields.append("identificacao_produto")
    if "packaging" in update_fields:
        epa_changed_fields.append("bom_embalagem_primaria")
    if update_fields.get("kickoff_completed") is True:
        epa_changed_fields.append("kickoff")
    if ficha_changed_fields or epa_changed_fields:
        await _auto_generate_documents_for_request(
            req_id,
            user,
            "atualizacao_request",
            ficha_changed_fields=ficha_changed_fields,
            epa_changed_fields=epa_changed_fields,
            source_changes=source_changes,
        )
    return pd_req

@pd_router.delete("/requests/{req_id}")
async def delete_pd_request(req_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    result = await db.pd_requests.delete_one({"id": req_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    # Clean up related data
    dev = await db.pd_developments.find_one({"pd_request_id": req_id}, {"_id": 0})
    if dev:
        dev_id = dev["id"]
        formula_ids = [f["id"] for f in await db.pd_formulas.find({"development_id": dev_id}, {"id": 1, "_id": 0}).to_list(100)]
        if formula_ids:
            await db.pd_formula_items.delete_many({"formula_id": {"$in": formula_ids}})
        await db.pd_formulas.delete_many({"development_id": dev_id})
        await db.pd_tests.delete_many({"development_id": dev_id})
        await db.pd_samples.delete_many({"development_id": dev_id})
        await db.pd_approvals.delete_many({"development_id": dev_id})
        await db.pd_costs.delete_many({"development_id": dev_id})
        await db.pd_documents.delete_many({"development_id": dev_id})
        await db.pd_developments.delete_one({"id": dev_id})
    await db.pd_request_status_history.delete_many({"pd_request_id": req_id})
    return {"message": "Solicitação removida"}

# ============ STATUS TRANSITIONS ============

async def assert_d48h_stability_ok(pd_request_id: str, tenant_id: str):
    """RN-PD-STAB: exige ao menos uma leitura D48h antes de entregar ao Comercial.

    Ponto unico de verdade para o gate — usado pelos 3 caminhos que podem levar
    uma requisicao/amostra/card a esse estagio (transition_status, update_sample
    e o drag-and-drop do board via assert_pd_card_ready_for_approval). Antes,
    cada caminho tinha sua propria checagem inline com uma estrategia de busca
    diferente, e o caminho do board (crm_routes.move_pd_card) nao tinha checagem
    nenhuma — permitindo pular a estabilidade ao mover o card pelo Kanban (B7).

    BUGFIX pos-auditoria: apesar do nome do campo, `pd_stability_studies.pd_card_id`
    NAO guarda o id real de `pd_cards` no caminho que os usuarios de fato usam —
    `_ensure_stability_study_for_pd_card` (chamada por
    GET /pd/requests/{req_id}/stability-study, o endpoint que a aba Testes/
    Estabilidades usa para ler e criar o estudo) recebe o proprio `pd_request`
    como `card` e grava `pd_card_id = pd_request["id"]`. A primeira versao desta
    funcao resolvia o id real de `pd_cards` e buscava por ele — nunca batia com
    o estudo de verdade, entao o gate bloqueava toda entrega mesmo com D48h
    registrado. A chave certa (e a que o antigo check de update_sample usava,
    corretamente) e o proprio pd_request_id.
    """
    study = await db.pd_stability_studies.find_one(
        {"pd_card_id": pd_request_id, "tenant_id": tenant_id}, {"_id": 0, "conditions": 1}
    )
    if not study:
        raise HTTPException(
            status_code=400,
            detail="Estudo de estabilidade não iniciado. Registre ao menos o D48h em qualquer condição de estabilidade antes de entregar ao Comercial.",
        )
    has_d48h = any(
        2 in (cond.get("completed_day_offsets") or [])
        for cond in study.get("conditions", [])
    )
    if not has_d48h:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma leitura D48h (48 horas) registrada. Conclua o checkpoint D48h em ao menos uma condição de estabilidade antes de entregar ao Comercial.",
        )


async def _sync_linked_variacao_from_pd_approval(pd_req: dict, user: dict, new_status: str, comment: str = ""):
    sample_id = pd_req.get("linked_amostra_id")
    variacao_id = pd_req.get("linked_variacao_id")
    if not sample_id or not variacao_id:
        return None, None, None

    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    if not sample:
        return None, None, None

    variacao = next((v for v in sample.get("variacoes", []) if v.get("id") == variacao_id), None)
    if not variacao:
        return sample, None, None

    now = now_iso()
    set_ops = {
        "variacoes.$.updated_at": now,
        "variacoes.$.aprovacao_interna": True,
    }

    if new_status == "APPROVED":
        set_ops.update({
            "variacoes.$.status": "aprovada",
            "variacoes.$.status_pd_raw": "aprovado",
            "variacoes.$.status_pd_label": "Aprovado pelo Cliente",
            "variacoes.$.resultado": "aprovada",
            "variacoes.$.aprovacao_externa": True,
            "variacoes.$.aprovado_cliente_em": now,
            "variacoes.$.enviado_comercial_em": variacao.get("enviado_comercial_em") or now,
            "data_envio": sample.get("data_envio") or now,
            "aprovacao_interna": True,
        })
    elif new_status == "REJECTED":
        rework_note = clean_text(comment) or "Reprovado comercialmente no P&D"
        set_ops.update({
            "variacoes.$.status": "retrabalho",
            "variacoes.$.status_pd_raw": "retrabalho_interno",
            "variacoes.$.status_pd_label": "Retrabalho Solicitado",
            "variacoes.$.resultado": "retrabalho",
            "variacoes.$.aprovacao_externa": False,
            "variacoes.$.reprovacao_motivo": rework_note,
            "variacoes.$.retrabalho_anotacoes": rework_note,
            "variacoes.$.retrabalho_solicitado_em": now,
            "variacoes.$.retrabalho_solicitado_por": user.get("name", ""),
        })
    else:
        return sample, variacao, None

    await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"], "variacoes.id": variacao_id},
        {
            "$set": set_ops,
            "$push": {
                "variacoes.$.historico_status": {
                    "de": variacao.get("status", ""),
                    "para": set_ops["variacoes.$.status"],
                    "data": now,
                    "usuario": user.get("name", ""),
                    "usuario_id": user["id"],
                    "origem": "pd_request_commercial_approval",
                }
            },
        },
    )

    updated_sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    updated_variacao = next((v for v in (updated_sample or {}).get("variacoes", []) if v.get("id") == variacao_id), None)

    if new_status == "REJECTED":
        await db.pd_updates.insert_one({
            "id": new_id(),
            "pd_request_id": pd_req["id"],
            "tenant_id": user["tenant_id"],
            "tipo": "retrabalho",
            "mensagem": clean_text(comment) or "Retrabalho solicitado pelo Comercial.",
            "visivel_comercial": True,
            "item_solicitado": None,
            "fornecedor": None,
            "previsao_entrega": None,
            "recebido": False,
            "recebido_em": None,
            "user_id": user["id"],
            "user_name": user["name"],
            "user_role": user.get("role", ""),
            "created_at": now,
        })

    sku_created = None
    if new_status == "APPROVED" and updated_sample and updated_variacao:
        from crm_routes import _create_sku_from_variacao_v2

        sku_created = await _create_sku_from_variacao_v2(
            updated_sample,
            updated_variacao,
            user,
            fasttrack_variacao=True,
        )

    return updated_sample, updated_variacao, sku_created


@pd_router.put("/requests/{req_id}/status")
async def transition_status(req_id: str, data: StatusTransition, request: Request):
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")

    current = pd_req["status"]
    new_status = data.new_status

    # Aprovação/rejeição comercial: roles comerciais podem agir somente nessa transição
    COMERCIAL_FULL = {"admin", "vendedor", "sales_ops", "sucesso_cliente"}
    is_comercial_action = (
        current == "WAITING_APPROVAL"
        and new_status in ("APPROVED", "REJECTED")
        and has_role(user, COMERCIAL_FULL)
    )
    if is_comercial_action:
        require_roles(user, PD_FULL | COMERCIAL_FULL)
    else:
        require_roles(user, PD_FULL)
    
    if new_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status inválido: {new_status}")

    if data.is_backward:
        if not data.comment or len(data.comment.strip()) < 10:
            raise HTTPException(status_code=400, detail="Justificativa obrigatória para retroceder (mínimo 10 caracteres).")
        backward_allowed = ALLOWED_BACKWARD_TRANSITIONS.get(current, [])
        if new_status not in backward_allowed:
            raise HTTPException(status_code=400, detail=f"Retrocesso não permitido: {current} → {new_status}")
    else:
        allowed = ALLOWED_TRANSITIONS.get(current, [])
        if new_status not in allowed:
            raise HTTPException(status_code=400, detail=f"Transição não permitida: {current} → {new_status}. Permitidas: {allowed}")

    # RN-PD-02: Block IN_TESTS if formula without ingredients
    if new_status == "IN_TESTS":
        dev_check = await db.pd_developments.find_one({"pd_request_id": req_id}, {"_id": 0})
        if not dev_check:
            raise HTTPException(status_code=400, detail="Inicie o desenvolvimento antes de avançar para Em Testes.")
        formula_check = await db.pd_formulas.find_one(
            {"development_id": dev_check["id"]}, {"_id": 0}, sort=[("version", -1)]
        )
        if not formula_check:
            raise HTTPException(status_code=400, detail="Registre a fórmula antes de avançar para Em Testes (RN-PD-02).")
        items_check = await db.pd_formula_items.find({"formula_id": formula_check["id"]}, {"_id": 0}).to_list(200)
        if not items_check:
            raise HTTPException(status_code=400, detail="Adicione ingredientes à fórmula antes de avançar para Em Testes (RN-PD-02).")
        total_pct = sum(it.get("percentage", 0) for it in items_check)
        if abs(total_pct - 100.0) > 0.5:
            raise HTTPException(
                status_code=400,
                detail=f"O total da fórmula deve ser 100% (atual: {total_pct:.2f}%). Ajuste os ingredientes antes de avançar (RN-PD-02)."
            )
        # RN-BF-01: Auto-lock formula on transition to IN_TESTS
        await db.pd_formulas.update_one(
            {"id": formula_check["id"]},
            {"$set": {"locked": True, "locked_at": now_iso(), "locked_by": user["id"], "locked_by_name": user.get("name", "")}}
        )

    # RN-PD-STAB: D48h checkpoint required before delivering to Comercial
    if new_status == "WAITING_APPROVAL":
        await assert_d48h_stability_ok(req_id, user["tenant_id"])

    # Check blocking workflow tasks
    if new_status not in ("IN_PROGRESS", "REJECTED"):
        blocking = await get_blocking_tasks(
            tenant_id=user["tenant_id"],
            entity_type="pd_card",
            entity_id=req_id,
            target_stage=new_status,
        )
        if blocking:
            titles = " | ".join(t.get("title", "") for t in blocking[:3])
            raise HTTPException(status_code=409, detail=f"Existem tarefas bloqueantes pendentes: {titles}")

    if new_status == "APPROVED" and not is_comercial_action:
        raise HTTPException(
            status_code=403,
            detail="Somente o Comercial pode aprovar a formulacao final. P&D deve entregar para aprovacao e aguardar a decisao comercial.",
        )
    if new_status == "REJECTED" and is_comercial_action and len(clean_text(data.comment)) < 5:
        raise HTTPException(status_code=400, detail="Informe as anotacoes do retrabalho para o P&D antes de reprovar.")

    # Check / auto-register approval for APPROVED status
    if new_status == "APPROVED":
        dev = await db.pd_developments.find_one({"pd_request_id": req_id}, {"_id": 0})
        if dev:
            tests = await db.pd_tests.find({"development_id": dev["id"]}, {"_id": 0}).to_list(100)
            failed_tests = [t for t in tests if t["status"] == "FAILED"]
            if failed_tests:
                raise HTTPException(status_code=400, detail="Existem testes com falha. Corrija antes de aprovar.")

            approval = await db.pd_approvals.find_one({"development_id": dev["id"]}, {"_id": 0})

            if is_comercial_action:
                # Comercial clicking "Aprovar" IS the approval — upsert the record automatically
                now = now_iso()
                if approval:
                    await db.pd_approvals.update_one(
                        {"development_id": dev["id"]},
                        {"$set": {
                            "approved_by_internal": True,
                            "approved_by_client": True,
                            "approved_by_comercial": True,
                            "approved_by_comercial_id": user["id"],
                            "approved_by_comercial_name": user.get("name", ""),
                            "approved_at": now,
                            "updated_at": now,
                        }}
                    )
                else:
                    await db.pd_approvals.insert_one({
                        "id": new_id(),
                        "development_id": dev["id"],
                        "pd_request_id": req_id,
                        "tenant_id": user["tenant_id"],
                        "approved_by_internal": True,
                        "approved_by_client": True,
                        "approved_by_comercial": True,
                        "approved_by_comercial_id": user["id"],
                        "approved_by_comercial_name": user.get("name", ""),
                        "notes": f"Aprovado comercialmente por {user.get('name', '')}",
                        "approved_at": now,
                        "created_at": now,
                        "updated_at": now,
                    })
            else:
                # P&D team approval — enforce existing checklist
                if not approval:
                    raise HTTPException(status_code=400, detail="Registre uma aprovação antes de mover para APROVADO.")
                if not approval.get("approved_by_internal"):
                    raise HTTPException(
                        status_code=400,
                        detail="Aprovação interna pendente. O líder de P&D deve aprovar internamente antes de marcar como APROVADO.",
                    )
                if not approval.get("approved_by_client"):
                    raise HTTPException(
                        status_code=400,
                        detail="Aprovação do cliente pendente. Registre a confirmação do cliente antes de marcar como APROVADO.",
                    )
    
    sku_created = None

    await db.pd_requests.update_one(
        {"id": req_id},
        {"$set": {"status": new_status, "updated_at": now_iso()}}
    )

    try:
        await _sync_request_status_to_pipeline(
            req_id=req_id,
            tenant_id=user["tenant_id"],
            new_status=new_status,
            linked_pd_card_id=pd_req.get("linked_pd_card_id"),
            user=user,
            movement_comment=data.comment or f"Status alterado para {STATUS_LABELS.get(new_status, new_status)}",
        )
    except Exception as exc:
        logger.warning(f"PD→CRM reverse sync failed for req {req_id}: {exc}")

    if is_comercial_action:
        try:
            _updated_sample, _updated_variacao, sku_created = await _sync_linked_variacao_from_pd_approval(
                pd_req,
                user,
                new_status,
                data.comment or "",
            )
        except Exception as exc:
            logger.warning(f"PD commercial approval reverse sync failed for req {req_id}: {exc}")

    await db.pd_request_status_history.insert_one({
        "id": new_id(),
        "pd_request_id": req_id,
        "from_status": current,
        "to_status": new_status,
        "changed_by": user["id"],
        "changed_by_name": user["name"],
        "comment": data.comment or f"Status alterado de {STATUS_LABELS.get(current, current)} para {STATUS_LABELS.get(new_status, new_status)}",
        "created_at": now_iso(),
    })
    
    # Auto-create development when moving to IN_PROGRESS
    if new_status == "IN_PROGRESS":
        existing_dev = await db.pd_developments.find_one({"pd_request_id": req_id})
        if not existing_dev:
            dev_id = new_id()
            await db.pd_developments.insert_one({
                "id": dev_id,
                "pd_request_id": req_id,
                "tenant_id": user["tenant_id"],
                "assigned_to": user["id"],
                "assigned_to_name": user["name"],
                "lab_responsible": None,
                "current_version": 0,
                "status": "active",
                "started_at": now_iso(),
                "completed_at": None,
            })
    
    if new_status == "COMPLETED":
        await db.pd_developments.update_one(
            {"pd_request_id": req_id},
            {"$set": {"status": "completed", "completed_at": now_iso()}}
        )

    # Auto-create order when PD is APPROVED
    if new_status == "APPROVED":
        try:
            from orders_routes import auto_create_order_on_pd_approval
            await auto_create_order_on_pd_approval(req_id, user)
        except Exception as exc:
            logger.error(f"Failed to auto-create order for PD {req_id}: {exc}")
    
    updated = await db.pd_requests.find_one({"id": req_id}, {"_id": 0})
    if sku_created is not None:
        updated["sku_created"] = sku_created
    return updated

@pd_router.get("/requests/{req_id}/history")
async def get_status_history(req_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    
    history = await db.pd_request_status_history.find(
        {"pd_request_id": req_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return history

# ============ DEVELOPMENTS ============

@pd_router.get("/requests/{req_id}/development")
async def get_development(req_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    
    dev = await db.pd_developments.find_one({"pd_request_id": req_id}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento ainda não iniciado")
    return dev

# ============ FORMULAS (with Manipulação structure) ============

@pd_router.post("/developments/{dev_id}/formulas")
async def create_formula(dev_id: str, data: FormulaCreate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    last_formula = await db.pd_formulas.find(
        {"development_id": dev_id}
    ).sort("version", -1).to_list(1)
    next_version = (last_formula[0]["version"] + 1) if last_formula else 1
    
    formula_id = new_id()
    formula = {
        "id": formula_id,
        "tenant_id": user["tenant_id"],
        "development_id": dev_id,
        "version": next_version,
        "name": data.name,
        "notes": data.notes or "",
        "volume": data.volume or 0,
        "volume_unit": data.volume_unit or "mL",
        "indice_perdas": data.indice_perdas or 0,
        "cotacao_usd": data.cotacao_usd or 6.00,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
    }
    await db.pd_formulas.insert_one(formula)
    formula.pop("_id", None)
    
    await db.pd_developments.update_one(
        {"id": dev_id},
        {"$set": {"current_version": next_version}}
    )

    await _auto_generate_documents_for_request(
        dev["pd_request_id"],
        user,
        "nova_formula",
        ficha_changed_fields=["identificacao", "composicao_completa", "modo_preparo", "rendimento_teorico"],
        epa_changed_fields=["bom_bulk_formula", "especificacoes_embalagem"],
        source_changes=[{
            "field": "formula_version",
            "label": "Versao da formula",
            "before": next_version - 1 if next_version > 1 else None,
            "after": next_version,
        }],
    )

    return formula

@pd_router.put("/formulas/{formula_id}")
async def update_formula(formula_id: str, data: FormulaUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Formula nao encontrada")
    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    source_changes = _build_source_changes(
        existing,
        update_fields,
        {
            "name": "Nome da formula",
            "notes": "Modo de preparo / observacoes",
            "volume": "Volume do lote padrao",
            "volume_unit": "Unidade do lote padrao",
            "indice_perdas": "Fator de perdas",
            "cotacao_usd": "Cotacao USD",
            "fragrance_target": "Target % fragrance",
        },
    )

    result = await db.pd_formulas.update_one({"id": formula_id}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")
    
    # If cotacao_usd changed, recalculate all items
    if "cotacao_usd" in update_fields:
        formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
        cotacao = formula.get("cotacao_usd", 6.00)
        items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(200)
        for item in items:
            cost_brl, cost_kg_usd, cost_brl_via_cambio = calc_item_costs(
                item.get("percentage", 0),
                item.get("price_per_kg", 0),
                cotacao,
                item.get("price_usd")
            )
            set_fields = {"cost_brl": cost_brl, "cost_kg_usd": cost_kg_usd}
            if cost_brl_via_cambio is not None:
                set_fields["cost_brl_via_cambio"] = cost_brl_via_cambio
            await db.pd_formula_items.update_one(
                {"id": item["id"]},
                {"$set": set_fields}
            )
    
    formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    ficha_changed_fields: List[str] = []
    epa_changed_fields: List[str] = []
    if "name" in update_fields:
        ficha_changed_fields.append("identificacao")
        epa_changed_fields.append("bom_bulk_formula")
    if "notes" in update_fields:
        ficha_changed_fields.extend(["modo_preparo", "observacoes_tecnicas"])
    if any(field in update_fields for field in ("volume", "volume_unit", "indice_perdas")):
        ficha_changed_fields.append("rendimento_teorico")
        epa_changed_fields.extend(["bom_bulk_formula", "especificacoes_embalagem"])
    if ficha_changed_fields or epa_changed_fields:
        await _auto_generate_documents_for_development(
            formula["development_id"],
            user,
            "atualizacao_formula",
            ficha_changed_fields=list(dict.fromkeys(ficha_changed_fields)),
            epa_changed_fields=list(dict.fromkeys(epa_changed_fields)),
            source_changes=source_changes,
        )
    return formula

@pd_router.get("/developments/{dev_id}/formulas")
async def list_formulas(dev_id: str, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    formulas = await db.pd_formulas.find({"development_id": dev_id}, {"_id": 0}).sort("version", -1).to_list(100)
    for f in formulas:
        items = await db.pd_formula_items.find({"formula_id": f["id"]}, {"_id": 0}).to_list(200)
        # Calculate cost_percentage for each item based on total
        total_cost = sum(it.get("cost_brl", 0) for it in items)
        for it in items:
            it["cost_percentage"] = round((it.get("cost_brl", 0) / total_cost * 100), 2) if total_cost > 0 else 0
        f["items"] = items
        # Calculate custo_unitario
        volume = f.get("volume", 0) or 0
        volume_unit = f.get("volume_unit", "mL")
        volume_kg = volume / 1000.0 if volume_unit == "mL" else volume  # mL to kg (density~1)
        f["custo_unitario"] = round(total_cost * volume_kg, 2) if volume_kg > 0 else round(total_cost, 2)
        f["total_cost_per_kg"] = round(total_cost, 4)
    return formulas


@pd_router.get("/formulas/bank")
async def formula_bank(
    request: Request,
    q: Optional[str] = None,
    origem: Optional[str] = None,
    somente_registradas: bool = False,
):
    """Banco global de formulas do P&D com contexto de projeto e aprovacoes.

    Visibilidade RBAC:
      - Perfis P&D/CQ/Eng/Doc Reviewers: composicao completa.
      - Comercial (vendedor/sales_ops/sucesso_cliente): apenas metadados (sem composicao nem custos).
    """
    user = await get_current_user(request)
    require_roles(user, PD_READ | {"vendedor", "sales_ops", "sucesso_cliente"})
    show_full = can_view_formula_composition(user)
    tenant_id = user["tenant_id"]

    developments = await db.pd_developments.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "pd_request_id": 1}
    ).to_list(5000)
    if not developments:
        return []

    dev_ids = [d["id"] for d in developments if d.get("id")]
    req_ids = [d["pd_request_id"] for d in developments if d.get("pd_request_id")]
    dev_map = {d["id"]: d for d in developments if d.get("id")}

    requests_docs = await db.pd_requests.find(
        {"tenant_id": tenant_id, "id": {"$in": req_ids}},
        {
            "_id": 0,
            "id": 1,
            "project_name": 1,
            "client_name": 1,
            "status": 1,
            "is_internal_research": 1,
            "created_at": 1,
            "updated_at": 1,
        }
    ).to_list(5000)
    requests_map = {r["id"]: r for r in requests_docs if r.get("id")}

    approvals = await db.pd_approvals.find(
        {"development_id": {"$in": dev_ids}},
        {
            "_id": 0,
            "development_id": 1,
            "approved_by_client": 1,
            "approved_by_internal": 1,
            "notes": 1,
        }
    ).to_list(5000)
    approvals_map = {a["development_id"]: a for a in approvals if a.get("development_id")}

    formulas = await db.pd_formulas.find(
        {"development_id": {"$in": dev_ids}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(10000)
    if not formulas:
        return []

    formula_ids = [f["id"] for f in formulas if f.get("id")]
    items = await db.pd_formula_items.find(
        {"formula_id": {"$in": formula_ids}},
        {"_id": 0}
    ).to_list(20000)
    items_by_formula: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        items_by_formula.setdefault(item.get("formula_id"), []).append(item)

    latest_by_dev: Dict[str, Dict[str, Any]] = {}
    for formula in formulas:
        dev_id = formula.get("development_id")
        existing = latest_by_dev.get(dev_id)
        if not existing or formula.get("version", 0) > existing.get("version", 0):
            latest_by_dev[dev_id] = formula

    result = []
    for formula in formulas:
        dev_id = formula.get("development_id")
        req = requests_map.get(dev_map.get(dev_id, {}).get("pd_request_id"))
        if not req:
            continue

        formula_items = items_by_formula.get(formula.get("id"), [])
        approval = approvals_map.get(dev_id, {})
        approved_by_client = bool(approval.get("approved_by_client"))
        approved_by_internal = bool(approval.get("approved_by_internal"))
        is_registered = approved_by_client and approved_by_internal
        origin_label = req.get("client_name") or "Portfólio Kuryos"
        origin_type = "portfolio" if req.get("is_internal_research") or not req.get("client_name") else "cliente"

        if origem and origin_type != origem:
            continue
        if somente_registradas and not is_registered:
            continue

        total_cost_per_kg = round(sum((it.get("cost_brl") or 0) for it in formula_items), 4)
        total_percentage = round(sum((it.get("percentage") or 0) for it in formula_items), 4)
        _frag_kws = ["fragr", "essência", "essencia", "perfum", "aroma"]
        fragrance_pct = round(sum(
            (it.get("percentage") or 0) for it in formula_items
            if any(kw in str(it.get("ingredient_name", "")).lower() for kw in _frag_kws)
        ), 4)

        row = {
            "id": formula.get("id"),
            "development_id": dev_id,
            "pd_request_id": req.get("id"),
            "name": formula.get("name"),
            "version": formula.get("version", 1),
            "is_latest_version": formula.get("id") == latest_by_dev.get(dev_id, {}).get("id"),
            "notes": formula.get("notes", "") if show_full else "",
            "created_at": formula.get("created_at"),
            "created_by_name": formula.get("created_by_name", ""),
            "project_name": req.get("project_name", ""),
            "client_name": req.get("client_name", ""),
            "origin_label": origin_label,
            "origin_type": origin_type,
            "request_status": req.get("status"),
            "approved_by_client": approved_by_client,
            "approved_by_internal": approved_by_internal,
            "is_registered": is_registered,
            "item_count": len(formula_items),
            "total_percentage": total_percentage if show_full else None,
            "total_cost_per_kg": total_cost_per_kg if show_full else None,
            "fragrance_percentage": fragrance_pct if show_full else None,
            "fragrance_target": formula.get("fragrance_target"),
            "volume": formula.get("volume", 0),
            "volume_unit": formula.get("volume_unit", "mL"),
            "items": (sorted(
                formula_items,
                key=lambda item: (
                    str(item.get("phase", "")),
                    -(item.get("percentage") or 0),
                    str(item.get("ingredient_name", "")),
                )
            ) if show_full else []),
            "restricted_view": not show_full,
        }

        if q:
            search_blob = " ".join([
                str(row.get("name", "")),
                str(row.get("project_name", "")),
                str(row.get("client_name", "")),
                str(row.get("origin_label", "")),
                str(row.get("created_by_name", "")),
                " ".join(str(it.get("ingredient_name", "")) for it in (row.get("items") or [])),
            ]).lower()
            if q.lower() not in search_blob:
                continue

        result.append(row)

    result.sort(
        key=lambda row: (
            row.get("created_at") or "",
            row.get("version", 0),
            row.get("name") or "",
        ),
        reverse=True,
    )
    return result

@pd_router.post("/formulas/{formula_id}/items")
async def add_formula_item(formula_id: str, data: FormulaItemCreate, request: Request):
    user = await get_current_user(request)
    formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    if not formula:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")
    if formula.get("locked"):
        raise HTTPException(status_code=409, detail=f"Fórmula v{formula.get('version',1)} está registrada e bloqueada (RN-BF-01). Crie uma nova versão para editar.")
    
    cotacao = formula.get("cotacao_usd", 6.00) or 6.00
    cost_brl, cost_kg_usd, cost_brl_via_cambio = calc_item_costs(
        data.percentage, data.price_per_kg, cotacao, data.price_usd
    )

    item_id = new_id()
    item = {
        "id": item_id,
        "formula_id": formula_id,
        "ingredient_name": data.ingredient_name,
        "percentage": data.percentage,
        "price_per_kg": data.price_per_kg,
        "price_usd": data.price_usd,          # R04
        "cost_brl": cost_brl,
        "cost_kg_usd": cost_kg_usd,
        "cost_brl_via_cambio": cost_brl_via_cambio,   # R04
        "fornecedor": data.fornecedor or "",
        "phase": data.phase or "",
        "function": data.function or "",
        "catalog_id": data.catalog_id or None,
    }
    await db.pd_formula_items.insert_one(item)
    item.pop("_id", None)
    await _auto_generate_documents_for_development(
        formula["development_id"],
        user,
        "novo_item_formula",
        ficha_changed_fields=["composicao_completa"],
        epa_changed_fields=["bom_bulk_formula"],
        source_changes=[{
            "field": "formula_item",
            "label": "Composicao da formula",
            "before": None,
            "after": {
                "ingredient_name": item["ingredient_name"],
                "percentage": item["percentage"],
                "catalog_id": item.get("catalog_id"),
            },
        }],
    )
    return item

@pd_router.put("/formula-items/{item_id}")
async def update_formula_item(item_id: str, data: FormulaItemUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_formula_items.find_one({"id": item_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    # Recalculate costs if percentage or price changed
    pct = update_fields.get("percentage", existing.get("percentage", 0))
    ppk = update_fields.get("price_per_kg", existing.get("price_per_kg", 0))
    p_usd = update_fields.get("price_usd", existing.get("price_usd"))  # R04

    formula = await db.pd_formulas.find_one({"id": existing["formula_id"]}, {"_id": 0})
    if formula and formula.get("locked"):
        raise HTTPException(status_code=409, detail=f"Fórmula v{formula.get('version',1)} está registrada e bloqueada (RN-BF-01). Crie uma nova versão para editar.")
    cotacao = formula.get("cotacao_usd", 6.00) if formula else 6.00

    cost_brl, cost_kg_usd, cost_brl_via_cambio = calc_item_costs(pct, ppk, cotacao, p_usd)
    update_fields["cost_brl"] = cost_brl
    update_fields["cost_kg_usd"] = cost_kg_usd
    if cost_brl_via_cambio is not None:
        update_fields["cost_brl_via_cambio"] = cost_brl_via_cambio

    source_changes = _build_source_changes(
        existing,
        update_fields,
        {
            "ingredient_name": "Ingrediente",
            "percentage": "Concentracao",
            "phase": "Fase",
            "function": "Funcao",
            "catalog_id": "Item do catalogo",
        },
        ignored_fields=["cost_brl", "cost_kg_usd"],
    )
    await db.pd_formula_items.update_one({"id": item_id}, {"$set": update_fields})
    item = await db.pd_formula_items.find_one({"id": item_id}, {"_id": 0})
    if any(field in update_fields for field in ("ingredient_name", "percentage", "phase", "function", "catalog_id")):
        await _auto_generate_documents_for_development(
            formula["development_id"],
            user,
            "atualizacao_item_formula",
            ficha_changed_fields=["composicao_completa"],
            epa_changed_fields=["bom_bulk_formula"],
            source_changes=source_changes,
        )
    return item

@pd_router.delete("/formula-items/{item_id}")
async def delete_formula_item(item_id: str, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_formula_items.find_one({"id": item_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Item nao encontrado")
    result = await db.pd_formula_items.delete_one({"id": item_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    formula = await db.pd_formulas.find_one({"id": existing["formula_id"]}, {"_id": 0})
    if formula:
        await _auto_generate_documents_for_development(
            formula["development_id"],
            user,
            "remocao_item_formula",
            ficha_changed_fields=["composicao_completa"],
            epa_changed_fields=["bom_bulk_formula"],
            source_changes=[{
                "field": "formula_item",
                "label": "Composicao da formula",
                "before": {
                    "ingredient_name": existing.get("ingredient_name"),
                    "percentage": existing.get("percentage"),
                    "catalog_id": existing.get("catalog_id"),
                },
                "after": None,
            }],
        )
    return {"message": "Ingrediente removido"}

@pd_router.get("/formulas/{formula_id}/items")
async def list_formula_items(formula_id: str, request: Request):
    user = await get_current_user(request)
    items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(200)
    return items

# ============ FORMULA COST REPORT ============

@pd_router.get("/formulas/{formula_id}/cost-report")
async def formula_cost_report(formula_id: str, request: Request):
    """Returns full cost breakdown for a formula - Relatório de Custo Acabado"""
    user = await get_current_user(request)
    formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    if not formula:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")
    
    items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(200)
    
    total_percentage = sum(it.get("percentage", 0) for it in items)
    total_cost_per_kg = sum(it.get("cost_brl", 0) for it in items)
    total_price_sum = sum(it.get("price_per_kg", 0) for it in items)
    cotacao = formula.get("cotacao_usd", 6.00) or 6.00
    
    volume = formula.get("volume", 0) or 0
    volume_unit = formula.get("volume_unit", "mL")
    volume_kg = volume / 1000.0 if volume_unit == "mL" else volume
    indice_perdas = formula.get("indice_perdas", 0) or 0
    
    custo_unitario = total_cost_per_kg * volume_kg if volume_kg > 0 else total_cost_per_kg
    custo_com_perdas = custo_unitario * (1 + indice_perdas / 100.0) if indice_perdas > 0 else custo_unitario
    
    # Calculate cost_percentage for each item
    for it in items:
        it["cost_percentage"] = round((it.get("cost_brl", 0) / total_cost_per_kg * 100), 2) if total_cost_per_kg > 0 else 0
    
    return {
        "formula": formula,
        "items": items,
        "totals": {
            "total_percentage": round(total_percentage, 3),
            "total_price_sum": round(total_price_sum, 2),
            "total_cost_per_kg": round(total_cost_per_kg, 4),
            "custo_unitario": round(custo_unitario, 2),
            "custo_com_perdas": round(custo_com_perdas, 2),
            "cotacao_usd": cotacao,
            "volume": volume,
            "volume_unit": volume_unit,
            "indice_perdas": indice_perdas,
        }
    }

# ============ TESTS (Structured) ============

@pd_router.post("/developments/{dev_id}/tests")
async def create_test(dev_id: str, data: TestCreate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    test_id = new_id()
    test = {
        "id": test_id,
        "development_id": dev_id,
        "test_type": data.test_type,
        "dados": data.dados or {},
        "status": data.status,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.pd_tests.insert_one(test)
    test.pop("_id", None)
    return test

@pd_router.get("/developments/{dev_id}/tests")
async def list_tests(dev_id: str, request: Request):
    user = await get_current_user(request)
    tests = await db.pd_tests.find({"development_id": dev_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return tests

@pd_router.put("/tests/{test_id}")
async def update_test(test_id: str, data: TestUpdate, request: Request):
    user = await get_current_user(request)
    update_fields = {}
    if data.status is not None:
        update_fields["status"] = data.status
    if data.dados is not None:
        update_fields["dados"] = data.dados
    
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    update_fields["updated_at"] = now_iso()
    result = await db.pd_tests.update_one({"id": test_id}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Teste não encontrado")
    
    test = await db.pd_tests.find_one({"id": test_id}, {"_id": 0})
    return test

@pd_router.delete("/tests/{test_id}")
async def delete_test(test_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.pd_tests.delete_one({"id": test_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Teste não encontrado")
    return {"message": "Teste removido"}

# ============ LAB RESULTS (Unified - all test types at once) ============

class LabResultsUpdate(BaseModel):
    estabilidade: Optional[Dict[str, Any]] = None
    ph: Optional[Dict[str, Any]] = None
    viscosidade: Optional[Dict[str, Any]] = None
    sensorial: Optional[Dict[str, Any]] = None
    compatibilidade: Optional[Dict[str, Any]] = None

@pd_router.get("/developments/{dev_id}/lab-results")
async def get_lab_results(dev_id: str, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    results = await db.pd_lab_results.find_one({"development_id": dev_id}, {"_id": 0})
    if not results:
        return {
            "development_id": dev_id,
            "estabilidade": {},
            "ph": {},
            "viscosidade": {},
            "sensorial": {},
            "compatibilidade": {},
        }
    return results

@pd_router.put("/developments/{dev_id}/lab-results")
async def save_lab_results(dev_id: str, data: LabResultsUpdate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    update_data = {}
    if data.estabilidade is not None:
        update_data["estabilidade"] = data.estabilidade
    if data.ph is not None:
        update_data["ph"] = data.ph
    if data.viscosidade is not None:
        update_data["viscosidade"] = data.viscosidade
    if data.sensorial is not None:
        update_data["sensorial"] = data.sensorial
    if data.compatibilidade is not None:
        update_data["compatibilidade"] = data.compatibilidade
    
    update_data["updated_at"] = now_iso()
    update_data["updated_by"] = user["id"]
    update_data["updated_by_name"] = user["name"]

    existing = await db.pd_lab_results.find_one({"development_id": dev_id})
    source_changes = _build_source_changes(
        existing or {},
        update_data,
        {
            "estabilidade": "Estabilidade",
            "ph": "pH",
            "viscosidade": "Viscosidade",
            "sensorial": "Sensorial",
            "compatibilidade": "Compatibilidade",
        },
        ignored_fields=["updated_at", "updated_by", "updated_by_name"],
    )
    if existing:
        await db.pd_lab_results.update_one(
            {"development_id": dev_id},
            {"$set": update_data}
        )
    else:
        doc = {
            "id": new_id(),
            "development_id": dev_id,
            "estabilidade": data.estabilidade or {},
            "ph": data.ph or {},
            "viscosidade": data.viscosidade or {},
            "sensorial": data.sensorial or {},
            "compatibilidade": data.compatibilidade or {},
            "updated_at": now_iso(),
            "updated_by": user["id"],
            "updated_by_name": user["name"],
            "created_at": now_iso(),
        }
        await db.pd_lab_results.insert_one(doc)
    
    results = await db.pd_lab_results.find_one({"development_id": dev_id}, {"_id": 0})
    ficha_changed_fields: List[str] = []
    epa_changed_fields: List[str] = []
    if any(field in update_data for field in ("ph", "viscosidade", "estabilidade", "compatibilidade")):
        ficha_changed_fields.append("parametros_in_process")
    if "sensorial" in update_data:
        epa_changed_fields.append("especificacoes_produto_acabado")
    if any(field in update_data for field in ("ph", "viscosidade", "estabilidade", "compatibilidade")):
        epa_changed_fields.extend(["especificacoes_produto_acabado", "criterios_liberacao_lote"])
    if ficha_changed_fields or epa_changed_fields:
        await _auto_generate_documents_for_development(
            dev_id,
            user,
            "lab_results",
            ficha_changed_fields=list(dict.fromkeys(ficha_changed_fields)),
            epa_changed_fields=list(dict.fromkeys(epa_changed_fields)),
            source_changes=source_changes,
        )

    has_meaningful_results = any(
        _has_meaningful_lab_value(update_data.get(field))
        for field in ("estabilidade", "ph", "viscosidade", "sensorial", "compatibilidade")
    )
    if has_meaningful_results and dev.get("pd_request_id"):
        pd_req = await db.pd_requests.find_one(
            {"id": dev["pd_request_id"], "tenant_id": user["tenant_id"]},
            {"_id": 0},
        )
        if pd_req and pd_req.get("status") in {"OPEN", "IN_PROGRESS"}:
            now = now_iso()
            previous_status = pd_req.get("status")
            await db.pd_requests.update_one(
                {"id": pd_req["id"], "tenant_id": user["tenant_id"]},
                {"$set": {"status": "IN_TESTS", "updated_at": now}},
            )
            await _sync_request_status_to_pipeline(
                req_id=pd_req["id"],
                tenant_id=user["tenant_id"],
                new_status="IN_TESTS",
                linked_pd_card_id=pd_req.get("linked_pd_card_id"),
                user=user,
                movement_comment="Movido automaticamente para testes após registro de resultados laboratoriais",
            )
            await db.pd_request_status_history.insert_one({
                "id": new_id(),
                "pd_request_id": pd_req["id"],
                "from_status": previous_status,
                "to_status": "IN_TESTS",
                "changed_by": user["id"],
                "changed_by_name": user["name"],
                "comment": "Movido automaticamente para Em Testes após registro de resultados laboratoriais",
                "created_at": now,
            })

    return results

# ============ STABILITY STUDIES ============

@pd_router.get("/stability/constants")
async def get_stability_constants(request: Request):
    await get_current_user(request)
    return {
        "conditions": STABILITY_CONDITIONS,
        "parameters": STABILITY_PARAMETERS,
        "checkpoints": STABILITY_CHECKPOINTS,
    }


@pd_router.get("/stability/studies")
async def list_stability_studies(
    request: Request,
    status: Optional[str] = None,
    pd_card_id: Optional[str] = None,
    sample_id: Optional[str] = None,
    variacao_id: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if pd_card_id:
        query["pd_card_id"] = pd_card_id
    if sample_id:
        query["amostra_id"] = sample_id
    if variacao_id:
        query["amostra_variacao_id"] = variacao_id

    studies = await db.pd_stability_studies.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return studies


@pd_router.get("/stability/studies/{study_id}")
async def get_stability_study(study_id: str, request: Request):
    user = await get_current_user(request)
    study = await db.pd_stability_studies.find_one(
        {"id": study_id, "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    if not study:
        raise HTTPException(status_code=404, detail="Estudo de estabilidade nao encontrado")
    return study


@pd_router.get("/stability/studies/{study_id}/readings")
async def list_stability_readings(study_id: str, request: Request):
    user = await get_current_user(request)
    study = await db.pd_stability_studies.find_one(
        {"id": study_id, "tenant_id": user["tenant_id"]},
        {"_id": 0, "id": 1},
    )
    if not study:
        raise HTTPException(status_code=404, detail="Estudo de estabilidade nao encontrado")
    readings = await db.pd_stability_readings.find(
        {"study_id": study_id, "tenant_id": user["tenant_id"]},
        {"_id": 0},
    ).sort([("day_offset", 1), ("created_at", 1)]).to_list(5000)
    return readings


@pd_router.post("/stability/studies/{study_id}/readings")
async def create_stability_reading(study_id: str, data: StabilityReadingCreate, request: Request):
    user = await get_current_user(request)
    study = await db.pd_stability_studies.find_one(
        {"id": study_id, "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    if not study:
        raise HTTPException(status_code=404, detail="Estudo de estabilidade nao encontrado")
    if study.get("status") == "concluido":
        raise HTTPException(status_code=400, detail="Estudo concluido nao aceita novas leituras")

    condition_map = _stability_condition_map()
    condition_template = condition_map.get(data.condition_code)
    if not condition_template:
        raise HTTPException(status_code=400, detail="Condicao de estabilidade invalida")

    parameters = _normalize_stability_parameters(data.parameters)
    if not parameters:
        raise HTTPException(status_code=400, detail="Informe ao menos um parametro valido da leitura")

    allowed_checkpoints = _allowed_stability_checkpoints(study, data.condition_code)
    if data.day_offset not in allowed_checkpoints:
        allowed_label = ", ".join(f"D{checkpoint}" if checkpoint not in (1, 2) else ("D24h" if checkpoint == 1 else "D48h") for checkpoint in allowed_checkpoints)
        raise HTTPException(
            status_code=400,
            detail=f"Checkpoint invalido para esta condicao. Permitidos: {allowed_label}",
        )

    existing = await db.pd_stability_readings.find_one(
        {
            "study_id": study_id,
            "tenant_id": user["tenant_id"],
            "condition_code": data.condition_code,
            "day_offset": data.day_offset,
        },
        {"_id": 0},
    )
    if existing:
        raise HTTPException(status_code=409, detail="Ja existe leitura registrada para esta condicao e checkpoint")

    reading_at = data.reading_at or now_iso()
    reading = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "study_id": study_id,
        "pd_card_id": study.get("pd_card_id"),
        "amostra_id": study.get("amostra_id"),
        "amostra_variacao_id": study.get("amostra_variacao_id"),
        "condition_code": data.condition_code,
        "condition_label": condition_template["label"],
        "day_offset": data.day_offset,
        "reading_at": reading_at,
        "parameters": parameters,
        "notes": clean_text(data.notes),
        "photo_urls": [clean_text(url) for url in data.photo_urls if clean_text(url)],
        "created_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    }
    await db.pd_stability_readings.insert_one(reading)
    reading.pop("_id", None)

    updated_conditions: List[Dict[str, Any]] = []
    for condition in study.get("conditions", []):
        if condition.get("code") != data.condition_code:
            updated_conditions.append(condition)
            continue

        completed = sorted(set(list(condition.get("completed_day_offsets") or []) + [data.day_offset]))
        pending = [checkpoint for checkpoint in condition.get("checkpoints", []) if checkpoint not in completed]
        updated_conditions.append({
            **condition,
            "completed_day_offsets": completed,
            "next_due_day_offset": pending[0] if pending else None,
            "next_due_at": _iso_after_days(study["started_at"], pending[0]) if pending else None,
            "last_reading_at": reading_at,
        })

    await db.pd_stability_studies.update_one(
        {"id": study_id, "tenant_id": user["tenant_id"]},
        {
            "$set": {
                "conditions": updated_conditions,
                "updated_at": now_iso(),
            }
        },
    )
    refreshed = await _recalculate_stability_study(study_id)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="stability_reading_created",
        entity_type="stability_study",
        entity_id=study_id,
        after={
            "condition_code": data.condition_code,
            "day_offset": data.day_offset,
            "parameters": list(parameters.keys()),
        },
    )
    return {
        "reading": reading,
        "study": refreshed,
    }


@pd_router.get("/stability/dashboard")
async def get_stability_dashboard(request: Request):
    user = await get_current_user(request)
    studies = await db.pd_stability_studies.find(
        {"tenant_id": user["tenant_id"]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(2000)

    counts = {"critico": 0, "atencao": 0, "em_dia": 0, "pendente_d0": 0, "concluido": 0}
    for study in studies:
        status = (study.get("summary") or {}).get("overall_status", "em_dia")
        counts[status] = counts.get(status, 0) + 1

    return {
        "counts": counts,
        "studies": studies,
    }


@pd_router.post("/stability/admin/check-alerts")
async def trigger_stability_alert_check(request: Request):
    user = await get_current_user(request)
    if user.get("role") not in ("admin", "gestor"):
        raise HTTPException(status_code=403, detail="Apenas admin/gestor podem executar a varredura de alertas")
    created = await check_stability_alerts_for_tenant(user["tenant_id"])
    return {"tasks_created": created}

# ============ SAMPLES ============

@pd_router.post("/developments/{dev_id}/samples")
async def create_sample(dev_id: str, data: SampleCreate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    sample_id = new_id()
    sample = {
        "id": sample_id,
        "development_id": dev_id,
        "formula_version": data.formula_version,
        "sent_to_client": data.sent_to_client,
        "sent_at": now_iso() if data.sent_to_client else None,
        "feedback": data.feedback or "",
        "created_at": now_iso(),
    }
    await db.pd_samples.insert_one(sample)
    sample.pop("_id", None)
    return sample

@pd_router.get("/developments/{dev_id}/samples")
async def list_samples(dev_id: str, request: Request):
    user = await get_current_user(request)
    samples = await db.pd_samples.find({"development_id": dev_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return samples

@pd_router.put("/samples/{sample_id}")
async def update_sample(sample_id: str, data: SampleUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_samples.find_one({"id": sample_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")
    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    if update_fields.get("sent_to_client") == True:
        # D48h gate: mesmo ponto de verdade usado por transition_status e pelo drag-and-drop do board
        dev = await db.pd_developments.find_one({"id": existing.get("development_id")}, {"_id": 0, "pd_request_id": 1})
        if dev and dev.get("pd_request_id"):
            await assert_d48h_stability_ok(dev["pd_request_id"], user["tenant_id"])
        update_fields["sent_at"] = now_iso()
        update_fields.setdefault("internal_approved", True)

    sent_to_client = bool(update_fields.get("sent_to_client", existing.get("sent_to_client")))

    if "client_approved" in update_fields:
        if not sent_to_client:
            raise HTTPException(
                status_code=409,
                detail="Amostra precisa ser enviada ao cliente antes de registrar aprovação externa.",
            )
    
    result = await db.pd_samples.update_one({"id": sample_id}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")
    
    sample = await db.pd_samples.find_one({"id": sample_id}, {"_id": 0})
    return sample

# ============ APPROVALS ============

@pd_router.post("/developments/{dev_id}/approval")
async def create_approval(dev_id: str, data: ApprovalCreate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    pd_req = await db.pd_requests.find_one(
        {"id": dev.get("pd_request_id"), "tenant_id": user["tenant_id"]},
        {"_id": 0},
    )
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitacao P&D nao encontrada")

    existing = await db.pd_approvals.find_one({"development_id": dev_id})
    existing_client_approved = bool((existing or {}).get("approved_by_client"))
    requested_client_approval = bool(data.approved_by_client)
    if requested_client_approval and not existing_client_approved:
        _assert_can_register_client_approval(pd_req, user)

    approved_by_client = requested_client_approval or existing_client_approved
    if existing_client_approved and not requested_client_approval and not has_role(user, COMERCIAL_FULL):
        approved_by_client = True
    approved_by_internal = bool(data.approved_by_internal)
    source_changes = _build_source_changes(
        existing or {},
        {
            "approved_by_client": approved_by_client,
            "approved_by_internal": approved_by_internal,
            "notes": data.notes or "",
        },
        {
            "approved_by_client": "Aprovacao do cliente",
            "approved_by_internal": "Aprovacao interna",
            "notes": "Observacoes da aprovacao",
        },
    )
    if existing:
        await db.pd_approvals.update_one(
            {"development_id": dev_id},
            {"$set": {
                "approved_by_client": approved_by_client,
                "approved_by_internal": approved_by_internal,
                "notes": data.notes or "",
                "approval_date": now_iso(),
                "approved_by_user": user["id"],
                "approved_by_user_name": user["name"],
            }}
        )
        approval = await db.pd_approvals.find_one({"development_id": dev_id}, {"_id": 0})
    else:
        approval_id = new_id()
        approval = {
            "id": approval_id,
            "development_id": dev_id,
            "approved_by_client": approved_by_client,
            "approved_by_internal": approved_by_internal,
            "approval_date": now_iso(),
            "notes": data.notes or "",
            "approved_by_user": user["id"],
            "approved_by_user_name": user["name"],
        }
        await db.pd_approvals.insert_one(approval)
        approval.pop("_id", None)
    
    if approved_by_client and not existing_client_approved:
        await _auto_generate_documents_for_request(
            dev["pd_request_id"],
            user,
            "aprovacao_cliente",
            ficha_changed_fields=["aprovacao_cliente"],
            epa_changed_fields=["aprovacao_cliente"],
            source_changes=source_changes,
        )
    return approval

@pd_router.get("/developments/{dev_id}/approval")
async def get_approval(dev_id: str, request: Request):
    user = await get_current_user(request)
    approval = await db.pd_approvals.find_one({"development_id": dev_id}, {"_id": 0})
    if not approval:
        return None
    return approval

# ============ COSTS (auto-calculated from formula) ============

@pd_router.post("/developments/{dev_id}/costs")
async def save_costs(dev_id: str, data: CostCreate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    total = data.ingredient_cost + data.packaging_cost + data.labor_cost
    
    existing = await db.pd_costs.find_one({"development_id": dev_id})
    if existing:
        await db.pd_costs.update_one(
            {"development_id": dev_id},
            {"$set": {
                "ingredient_cost": data.ingredient_cost,
                "packaging_cost": data.packaging_cost,
                "labor_cost": data.labor_cost,
                "total_cost": total,
                "updated_at": now_iso(),
            }}
        )
        cost = await db.pd_costs.find_one({"development_id": dev_id}, {"_id": 0})
    else:
        cost_id = new_id()
        cost = {
            "id": cost_id,
            "development_id": dev_id,
            "ingredient_cost": data.ingredient_cost,
            "packaging_cost": data.packaging_cost,
            "labor_cost": data.labor_cost,
            "total_cost": total,
            "updated_at": now_iso(),
        }
        await db.pd_costs.insert_one(cost)
        cost.pop("_id", None)
    
    return cost

@pd_router.get("/developments/{dev_id}/costs")
async def get_costs(dev_id: str, request: Request):
    user = await get_current_user(request)
    cost = await db.pd_costs.find_one({"development_id": dev_id}, {"_id": 0})
    if not cost:
        return {"ingredient_cost": 0, "packaging_cost": 0, "labor_cost": 0, "total_cost": 0}
    return cost


# ============ COST VERSIONS (versioned system: P&D v1 -> Comercial v2) ============

def _default_cost_versions_doc(dev_id: str, tenant_id: str) -> dict:
    return {
        "development_id": dev_id,
        "tenant_id": tenant_id,
        "v1": {
            "ingredient_cost_auto": 0.0,
            "ingredient_cost_manual": 0.0,
            "total": 0.0,
            "notes": "",
            "status": "rascunho",
            "submitted_at": None,
            "submitted_by_name": None,
        },
        "v2": None,
        "total_final": 0.0,
        "updated_at": None,
    }


def _build_cost_versions_response(doc: dict, user: dict, formula_cost_auto: float = 0.0) -> dict:
    """Return a role-filtered view of the cost versions document.

    comercial / compras / admin -> full breakdown of both v1 and v2.
    P&D roles        → full v1 (they own it), but from v2 only status + total_final.
    """
    if not doc:
        doc = {}

    v1 = dict(doc.get("v1") or {})
    v1.setdefault("ingredient_cost_auto", formula_cost_auto)
    v1.setdefault("ingredient_cost_manual", 0.0)
    v1.setdefault("total", 0.0)
    v1.setdefault("notes", "")
    v1.setdefault("status", "rascunho")
    v1.setdefault("submitted_at", None)
    v1.setdefault("submitted_by_name", None)
    v1_blank = (
        v1.get("status") == "rascunho"
        and not v1.get("submitted_at")
        and float(v1.get("ingredient_cost_auto") or 0) == 0
        and float(v1.get("ingredient_cost_manual") or 0) == 0
        and not clean_text(v1.get("notes"))
    )

    v2_raw = doc.get("v2")
    total_final = doc.get("total_final", 0.0)

    if can_view_commercial_costs(user):
        return {
            "v1": v1,
            "v2": v2_raw,
            "total_final": total_final,
            "updated_at": doc.get("updated_at"),
            "pd_cost_blank": v1_blank,
            "pd_cost_analysis_required": v1_blank,
            "_role_view": "comercial",
        }

    # P&D view: full v1, but v2 is redacted to just status + total
    v2_summary = None
    if v2_raw:
        v2_summary = {
            "status": v2_raw.get("status"),
            "finalized_at": v2_raw.get("finalized_at"),
        }

    return {
        "v1": v1,
        "v2": v2_summary,
        "total_final": total_final if v2_raw and v2_raw.get("status") == "finalizado" else None,
        "updated_at": doc.get("updated_at"),
        "pd_cost_blank": v1_blank,
        "pd_cost_analysis_required": v1_blank,
        "_role_view": "pd",
    }


@pd_router.get("/developments/{dev_id}/cost-versions")
async def get_cost_versions(dev_id: str, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    require_roles(user, PD_READ)

    doc = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})

    # Derive auto ingredient cost from latest formula
    formula_cost_auto = 0.0
    latest_formula = await db.pd_formulas.find(
        {"development_id": dev_id}, {"_id": 0}
    ).sort("version", -1).to_list(1)
    if latest_formula:
        items = await db.pd_formula_items.find(
            {"formula_id": latest_formula[0]["id"]}, {"_id": 0}
        ).to_list(200)
        formula_cost_auto = round(sum(it.get("cost_brl", 0) for it in items), 4)

    return _build_cost_versions_response(doc, user, formula_cost_auto)


@pd_router.put("/developments/{dev_id}/cost-versions/v1")
async def upsert_cost_v1(dev_id: str, data: PDCostV1Upsert, request: Request):
    """P&D saves or updates their cost draft (v1). Only allowed while status is 'rascunho'."""
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    require_roles(user, PD_WRITE)

    existing = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    if existing and (existing.get("v1") or {}).get("status") == "enviado":
        raise HTTPException(status_code=409, detail="Custo v1 já enviado para análise comercial. Não é possível editar.")

    # Derive ingredient_cost_auto from latest formula
    formula_cost_auto = 0.0
    latest_formula = await db.pd_formulas.find(
        {"development_id": dev_id}, {"_id": 0}
    ).sort("version", -1).to_list(1)
    if latest_formula:
        items = await db.pd_formula_items.find(
            {"formula_id": latest_formula[0]["id"]}, {"_id": 0}
        ).to_list(200)
        formula_cost_auto = round(sum(it.get("cost_brl", 0) for it in items), 4)

    v1_total = round(formula_cost_auto + (data.ingredient_cost_manual or 0.0), 4)
    v1_patch = {
        "v1.ingredient_cost_auto": formula_cost_auto,
        "v1.ingredient_cost_manual": data.ingredient_cost_manual or 0.0,
        "v1.total": v1_total,
        "v1.notes": data.notes or "",
        "v1.status": "rascunho",
        "updated_at": now_iso(),
    }

    if existing:
        await db.pd_cost_versions.update_one({"development_id": dev_id}, {"$set": v1_patch})
    else:
        doc = _default_cost_versions_doc(dev_id, user["tenant_id"])
        doc["v1"].update({
            "ingredient_cost_auto": formula_cost_auto,
            "ingredient_cost_manual": data.ingredient_cost_manual or 0.0,
            "total": v1_total,
            "notes": data.notes or "",
        })
        doc["updated_at"] = now_iso()
        await db.pd_cost_versions.insert_one(doc)

    doc = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    await audit_log(tenant_id=user["tenant_id"], user_id=user["id"], user_name=user.get("name", ""),
                    action="cost_v1_saved", entity_type="pd_cost_versions", entity_id=dev_id,
                    after={"v1_total": v1_total})
    return _build_cost_versions_response(doc, user, formula_cost_auto)


@pd_router.post("/developments/{dev_id}/cost-versions/v1/submit")
async def submit_cost_v1(dev_id: str, request: Request):
    """P&D freezes v1 and sends it to Comercial for cost approval."""
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    require_roles(user, PD_WRITE)

    existing = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=400, detail="Salve um rascunho de custo antes de enviar.")
    if (existing.get("v1") or {}).get("status") == "enviado":
        raise HTTPException(status_code=409, detail="Custo v1 já foi enviado para análise comercial.")

    patch = {
        "v1.status": "enviado",
        "v1.submitted_at": now_iso(),
        "v1.submitted_by_name": user.get("name", ""),
        "updated_at": now_iso(),
    }
    await db.pd_cost_versions.update_one({"development_id": dev_id}, {"$set": patch})

    doc = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    await audit_log(tenant_id=user["tenant_id"], user_id=user["id"], user_name=user.get("name", ""),
                    action="cost_v1_submitted", entity_type="pd_cost_versions", entity_id=dev_id,
                    before={"v1_status": "rascunho"}, after={"v1_status": "enviado"})
    return _build_cost_versions_response(doc, user)


@pd_router.put("/developments/{dev_id}/cost-versions/v2")
async def upsert_cost_v2(dev_id: str, data: ComprasCostUpsert, request: Request):
    """Commercial/cost team fills in the commercial cost breakdown (v2). Requires v1 to be submitted."""
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    require_roles(user, COMPRAS_FULL | COMERCIAL_FULL)

    existing = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    if not existing or (existing.get("v1") or {}).get("status") != "enviado":
        raise HTTPException(status_code=400, detail="Aguardando envio do custo v1 pelo P&D.")
    if (existing.get("v2") or {}).get("status") == "finalizado":
        raise HTTPException(status_code=409, detail="Custo v2 já foi finalizado e não pode ser alterado.")

    v1_total = (existing.get("v1") or {}).get("total", 0.0)
    v2_total = round(
        (data.packaging_cost or 0) + (data.labor_cost or 0) +
        (data.overhead_cost or 0) + (data.other_cost or 0), 4
    )
    total_final = round(v1_total + v2_total, 4)

    v2_doc = {
        "packaging_cost": data.packaging_cost or 0.0,
        "labor_cost": data.labor_cost or 0.0,
        "overhead_cost": data.overhead_cost or 0.0,
        "other_cost": data.other_cost or 0.0,
        "notes": data.notes or "",
        "total": v2_total,
        "status": "rascunho",
        "finalized_at": (existing.get("v2") or {}).get("finalized_at"),
        "finalized_by_name": (existing.get("v2") or {}).get("finalized_by_name"),
    }

    await db.pd_cost_versions.update_one(
        {"development_id": dev_id},
        {"$set": {"v2": v2_doc, "total_final": total_final, "updated_at": now_iso()}}
    )

    doc = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    await audit_log(tenant_id=user["tenant_id"], user_id=user["id"], user_name=user.get("name", ""),
                    action="cost_v2_saved", entity_type="pd_cost_versions", entity_id=dev_id,
                    after={"v2_total": v2_total, "total_final": total_final})
    return _build_cost_versions_response(doc, user)


@pd_router.post("/developments/{dev_id}/cost-versions/v2/finalize")
async def finalize_cost_v2(dev_id: str, request: Request):
    """Comercial finalizes/approves v2. After this, costs are locked and visible to P&D."""
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    require_roles(user, COMERCIAL_FULL)

    existing = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    if not existing or not existing.get("v2"):
        raise HTTPException(status_code=400, detail="Salve os dados de custo comercial antes de finalizar.")
    if (existing.get("v2") or {}).get("status") == "finalizado":
        raise HTTPException(status_code=409, detail="Custo v2 já está finalizado.")

    patch = {
        "v2.status": "finalizado",
        "v2.finalized_at": now_iso(),
        "v2.finalized_by_name": user.get("name", ""),
        "v2.finalized_by_role": user.get("role", ""),
        "v2.approved_by_commercial": True,
        "updated_at": now_iso(),
    }
    await db.pd_cost_versions.update_one({"development_id": dev_id}, {"$set": patch})

    doc = await db.pd_cost_versions.find_one({"development_id": dev_id}, {"_id": 0})
    await audit_log(tenant_id=user["tenant_id"], user_id=user["id"], user_name=user.get("name", ""),
                    action="cost_v2_finalized", entity_type="pd_cost_versions", entity_id=dev_id,
                    before={"v2_status": "rascunho"},
                    after={"v2_status": "finalizado", "approved_by_commercial": True, "total_final": doc.get("total_final", 0)})
    return _build_cost_versions_response(doc, user)

# ============ COSTS AUTO-CALCULATE FROM FORMULA ============

@pd_router.get("/developments/{dev_id}/formula-costs")
async def get_formula_costs(dev_id: str, request: Request):
    """Auto-calculate costs from the latest formula"""
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    # Get latest formula
    formulas = await db.pd_formulas.find({"development_id": dev_id}, {"_id": 0}).sort("version", -1).to_list(1)
    if not formulas:
        return {"formula": None, "items": [], "totals": None}
    
    formula = formulas[0]
    items = await db.pd_formula_items.find({"formula_id": formula["id"]}, {"_id": 0}).to_list(200)
    
    total_percentage = sum(it.get("percentage", 0) for it in items)
    total_cost_per_kg = sum(it.get("cost_brl", 0) for it in items)
    total_price_sum = sum(it.get("price_per_kg", 0) for it in items)
    cotacao = formula.get("cotacao_usd", 6.00) or 6.00
    
    volume = formula.get("volume", 0) or 0
    volume_unit = formula.get("volume_unit", "mL")
    volume_kg = volume / 1000.0 if volume_unit == "mL" else volume
    indice_perdas = formula.get("indice_perdas", 0) or 0
    
    custo_unitario = total_cost_per_kg * volume_kg if volume_kg > 0 else total_cost_per_kg
    custo_com_perdas = custo_unitario * (1 + indice_perdas / 100.0) if indice_perdas > 0 else custo_unitario
    
    for it in items:
        it["cost_percentage"] = round((it.get("cost_brl", 0) / total_cost_per_kg * 100), 2) if total_cost_per_kg > 0 else 0
    
    return {
        "formula": formula,
        "items": items,
        "totals": {
            "total_percentage": round(total_percentage, 3),
            "total_price_sum": round(total_price_sum, 2),
            "total_cost_per_kg": round(total_cost_per_kg, 4),
            "custo_unitario": round(custo_unitario, 2),
            "custo_com_perdas": round(custo_com_perdas, 2),
            "cotacao_usd": cotacao,
            "volume": volume,
            "volume_unit": volume_unit,
            "indice_perdas": indice_perdas,
        }
    }

# ============ SAMPLE BATCHES ============

class SampleBatchOverride(BaseModel):
    ingredient_name_base: str = ""  # ingredient in base formula being overridden
    ingredient_name: str = ""
    percentage: float = 0.0
    fornecedor: str = ""

SAMPLE_BATCH_BASE_STATUSES = {"ativa", "bloqueada", "encerrada"}
SAMPLE_BATCH_QUALITY_STATUSES = {"aprovada", "pendente", "reprovada"}
SAMPLE_BATCH_DEFAULT_BASE_INGREDIENTS = ["Agua", "Alcool", "Acido hialuronico"]
SAMPLE_BATCH_ALLOWED_CHANGE_SCOPES = {"cor", "ativo", "fragrancia"}
SAMPLE_BATCH_SCOPE_KEYWORDS = {
    "fragrancia": ("fragr", "essencia", "essência", "perfume", "aroma", "odor"),
    "cor": ("cor", "corante", "pigmento", "color"),
    "ativo": ("ativo", "actif", "active", "hialuron", "hyaluron", "niacinamida", "vitamina", "extrato"),
}

class SampleBatchVariante(BaseModel):
    id: str = ""
    nome: str
    versao: int = 1
    overrides: List[SampleBatchOverride] = []
    notas: str = ""

class SampleBatchCreate(BaseModel):
    nome: str
    formula_base_id: str
    volume_base_ml: float = 15.0
    base_total_volume_ml: Optional[float] = None
    max_derivacoes: Optional[int] = None
    perda_operacional_percent: float = 0.0
    validade_base: Optional[str] = None
    condicoes_armazenamento: str = ""
    status_base: str = "ativa"
    status_qualidade: str = "aprovada"
    allowed_change_scopes: List[str] = Field(default_factory=lambda: ["cor", "ativo", "fragrancia"])
    base_reference_ingredients: List[str] = Field(default_factory=lambda: list(SAMPLE_BATCH_DEFAULT_BASE_INGREDIENTS))
    variantes: List[SampleBatchVariante] = []
    notas: str = ""


def _normalize_sample_batch_scope(value: Any) -> str:
    normalized = (
        unicodedata.normalize("NFD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
        .lower()
    )
    if normalized in {"fragrance", "fragrancia", "fragrancia"}:
        return "fragrancia"
    if normalized in SAMPLE_BATCH_ALLOWED_CHANGE_SCOPES:
        return normalized
    return normalized


def _classify_sample_batch_change_scope(*values: Any) -> Optional[str]:
    text = " ".join(str(value or "") for value in values)
    normalized = (
        unicodedata.normalize("NFD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    for scope, keywords in SAMPLE_BATCH_SCOPE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return scope
    return None


def _parse_optional_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = clean_text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="validade_base deve estar no formato YYYY-MM-DD") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_sample_batch_payload(
    data: SampleBatchCreate,
    *,
    tenant_id: str,
    dev_id: str,
    existing_id: Optional[str] = None,
    current_now: Optional[str] = None,
) -> Dict[str, Any]:
    nome = clean_text(data.nome)
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do lote obrigatorio")

    formula_base_id = clean_text(data.formula_base_id)
    if not formula_base_id:
        raise HTTPException(status_code=400, detail="Formula base obrigatoria")

    volume_por_amostra = round(float(data.volume_base_ml or 0), 4)
    if volume_por_amostra <= 0:
        raise HTTPException(status_code=400, detail="volume_base_ml deve ser maior que zero")

    perda_operacional_percent = round(float(data.perda_operacional_percent or 0), 4)
    if perda_operacional_percent < 0 or perda_operacional_percent >= 100:
        raise HTTPException(status_code=400, detail="perda_operacional_percent deve estar entre 0 e 99.9999")

    allowed_change_scopes = [
        _normalize_sample_batch_scope(scope)
        for scope in (data.allowed_change_scopes or [])
        if _normalize_sample_batch_scope(scope)
    ]
    if not allowed_change_scopes:
        allowed_change_scopes = ["cor", "ativo", "fragrancia"]
    invalid_scopes = [scope for scope in allowed_change_scopes if scope not in SAMPLE_BATCH_ALLOWED_CHANGE_SCOPES]
    if invalid_scopes:
        raise HTTPException(
            status_code=400,
            detail=f"allowed_change_scopes invalido. Use apenas: {sorted(SAMPLE_BATCH_ALLOWED_CHANGE_SCOPES)}",
        )
    allowed_change_scopes = list(dict.fromkeys(allowed_change_scopes))

    base_reference_ingredients = [
        clean_text(ingredient)
        for ingredient in (data.base_reference_ingredients or [])
        if clean_text(ingredient)
    ] or list(SAMPLE_BATCH_DEFAULT_BASE_INGREDIENTS)

    variantes = []
    nomes_normalizados = set()
    for idx, variante in enumerate(data.variantes or []):
        nome_variante = clean_text(variante.nome) or f"Variante {idx + 1}"
        nome_chave = nome_variante.lower()
        if nome_chave in nomes_normalizados:
            raise HTTPException(status_code=400, detail=f"Nome de variante duplicado: {nome_variante}")
        nomes_normalizados.add(nome_chave)

        seen_base_slots = set()
        overrides = []
        for override in variante.overrides or []:
            ingredient_name_base = clean_text(override.ingredient_name_base)
            ingredient_name = clean_text(override.ingredient_name)
            fornecedor = clean_text(override.fornecedor)
            percentage = round(float(override.percentage or 0), 4)
            is_empty = not ingredient_name_base and not ingredient_name and not fornecedor and percentage == 0
            if is_empty:
                continue
            if not ingredient_name_base or not ingredient_name:
                raise HTTPException(status_code=400, detail=f"Override incompleto na variante '{nome_variante}'")
            if ingredient_name_base in seen_base_slots:
                raise HTTPException(status_code=400, detail=f"Ingrediente base duplicado em overrides da variante '{nome_variante}'")
            if percentage <= 0:
                raise HTTPException(status_code=400, detail=f"Percentual invalido para override '{ingredient_name}' na variante '{nome_variante}'")
            change_scope = _classify_sample_batch_change_scope(ingredient_name_base, ingredient_name)
            if change_scope not in allowed_change_scopes:
                allowed_label = ", ".join(allowed_change_scopes)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Override '{ingredient_name_base}' nao permitido no lote rapido. "
                        f"Altere apenas {allowed_label}; mantenha a base fixa ({', '.join(base_reference_ingredients)})."
                    ),
                )
            seen_base_slots.add(ingredient_name_base)
            overrides.append({
                "ingredient_name_base": ingredient_name_base,
                "ingredient_name": ingredient_name,
                "percentage": percentage,
                "fornecedor": fornecedor,
                "change_scope": change_scope,
            })

        variantes.append({
            "id": variante.id if variante.id else new_id(),
            "nome": nome_variante,
            "versao": max(int(variante.versao or 1), 1),
            "overrides": overrides,
            "notas": clean_text(variante.notas),
        })

    if not variantes:
        raise HTTPException(status_code=400, detail="Adicione ao menos uma amostra derivada")

    base_total_volume_ml = data.base_total_volume_ml
    if base_total_volume_ml is None:
        base_total_volume_ml = volume_por_amostra * len(variantes)
    base_total_volume_ml = round(float(base_total_volume_ml or 0), 4)
    if base_total_volume_ml <= 0:
        raise HTTPException(status_code=400, detail="base_total_volume_ml deve ser maior que zero")

    max_derivacoes = data.max_derivacoes if data.max_derivacoes not in (None, 0) else None
    if max_derivacoes is not None and int(max_derivacoes) <= 0:
        raise HTTPException(status_code=400, detail="max_derivacoes deve ser maior que zero")
    max_derivacoes = int(max_derivacoes) if max_derivacoes is not None else None

    status_base = clean_text(data.status_base).lower() or "ativa"
    if status_base not in SAMPLE_BATCH_BASE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status_base invalido. Use: {sorted(SAMPLE_BATCH_BASE_STATUSES)}")

    status_qualidade = clean_text(data.status_qualidade).lower() or "aprovada"
    if status_qualidade not in SAMPLE_BATCH_QUALITY_STATUSES:
        raise HTTPException(status_code=400, detail=f"status_qualidade invalido. Use: {sorted(SAMPLE_BATCH_QUALITY_STATUSES)}")

    validade_dt = _parse_optional_iso_date(data.validade_base)
    validade_base = validade_dt.date().isoformat() if validade_dt else None

    usable_volume_ml = round(base_total_volume_ml * (1 - (perda_operacional_percent / 100.0)), 4)
    max_por_volume = int(usable_volume_ml // volume_por_amostra) if volume_por_amostra > 0 else 0
    capacidade_maxima = max_por_volume if max_derivacoes is None else min(max_por_volume, max_derivacoes)
    derivadas_count = len(variantes)
    capacidade_restante = capacidade_maxima - derivadas_count
    volume_consumido_ml = round(derivadas_count * volume_por_amostra, 4)
    volume_disponivel_ml = round(max(base_total_volume_ml - volume_consumido_ml, 0.0), 4)

    if capacidade_maxima <= 0:
        raise HTTPException(status_code=400, detail="A base informada nao gera nenhuma derivacao util com o volume atual")
    if derivadas_count > capacidade_maxima:
        raise HTTPException(
            status_code=400,
            detail=f"A base suporta no maximo {capacidade_maxima} derivacoes e voce informou {derivadas_count}",
        )

    blocked_reasons: List[str] = []
    if current_now:
        try:
            today = datetime.fromisoformat(str(current_now).replace("Z", "+00:00")).astimezone(timezone.utc).date()
        except ValueError:
            today = datetime.now(timezone.utc).date()
    else:
        today = datetime.now(timezone.utc).date()
    if validade_dt and validade_dt.date() < today:
        blocked_reasons.append("validade_expirada")
    if status_base != "ativa":
        blocked_reasons.append(f"status_base_{status_base}")
    if status_qualidade != "aprovada":
        blocked_reasons.append(f"qualidade_{status_qualidade}")
    if capacidade_restante <= 0:
        blocked_reasons.append("capacidade_esgotada")
    if volume_disponivel_ml < volume_por_amostra:
        blocked_reasons.append("volume_insuficiente")

    return {
        "id": existing_id or new_id(),
        "development_id": dev_id,
        "tenant_id": tenant_id,
        "nome": nome,
        "formula_base_id": formula_base_id,
        "volume_base_ml": volume_por_amostra,
        "base_total_volume_ml": base_total_volume_ml,
        "max_derivacoes": max_derivacoes,
        "perda_operacional_percent": perda_operacional_percent,
        "validade_base": validade_base,
        "condicoes_armazenamento": clean_text(data.condicoes_armazenamento),
        "status_base": status_base,
        "status_qualidade": status_qualidade,
        "allowed_change_scopes": allowed_change_scopes,
        "base_reference_ingredients": base_reference_ingredients,
        "variantes": variantes,
        "notas": clean_text(data.notas),
        "derivadas_count": derivadas_count,
        "capacidade_maxima_derivacoes": capacidade_maxima,
        "capacidade_restante_derivacoes": max(capacidade_restante, 0),
        "volume_consumido_ml": volume_consumido_ml,
        "volume_disponivel_ml": volume_disponivel_ml,
        "bloqueado_para_novas_derivacoes": bool(blocked_reasons),
        "motivos_bloqueio": blocked_reasons,
        "updated_at": current_now or now_iso(),
    }


def _serialize_sample_batch(doc: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(doc)
    payload.setdefault("base_total_volume_ml", None)
    payload.setdefault("max_derivacoes", None)
    payload.setdefault("perda_operacional_percent", 0.0)
    payload.setdefault("validade_base", None)
    payload.setdefault("condicoes_armazenamento", "")
    payload.setdefault("status_base", "ativa")
    payload.setdefault("status_qualidade", "aprovada")
    payload.setdefault("allowed_change_scopes", ["cor", "ativo", "fragrancia"])
    payload.setdefault("base_reference_ingredients", list(SAMPLE_BATCH_DEFAULT_BASE_INGREDIENTS))
    payload.setdefault("notas", "")

    rebuilt = _build_sample_batch_payload(
        SampleBatchCreate.model_validate({
            "nome": payload.get("nome"),
            "formula_base_id": payload.get("formula_base_id"),
            "volume_base_ml": payload.get("volume_base_ml"),
            "base_total_volume_ml": payload.get("base_total_volume_ml"),
            "max_derivacoes": payload.get("max_derivacoes"),
            "perda_operacional_percent": payload.get("perda_operacional_percent"),
            "validade_base": payload.get("validade_base"),
            "condicoes_armazenamento": payload.get("condicoes_armazenamento"),
            "status_base": payload.get("status_base"),
            "status_qualidade": payload.get("status_qualidade"),
            "allowed_change_scopes": payload.get("allowed_change_scopes"),
            "base_reference_ingredients": payload.get("base_reference_ingredients"),
            "variantes": payload.get("variantes") or [],
            "notas": payload.get("notas"),
        }),
        tenant_id=payload.get("tenant_id", ""),
        dev_id=payload.get("development_id", ""),
        existing_id=payload.get("id"),
        current_now=payload.get("updated_at"),
    )
    for field in ("created_at", "created_by", "created_by_name"):
        if field in payload:
            rebuilt[field] = payload[field]
    return rebuilt

@pd_router.get("/developments/{dev_id}/sample-batches")
async def list_sample_batches(dev_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    batches = await db.pd_sample_batches.find(
        {"development_id": dev_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return [_serialize_sample_batch(batch) for batch in batches]

@pd_router.post("/developments/{dev_id}/sample-batches")
async def create_sample_batch(dev_id: str, data: SampleBatchCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    formula = await db.pd_formulas.find_one(
        {"id": clean_text(data.formula_base_id), "development_id": dev_id, "tenant_id": user["tenant_id"]},
        {"_id": 0, "id": 1},
    )
    if not formula:
        raise HTTPException(status_code=404, detail="Formula base nao encontrada para este desenvolvimento")
    now = now_iso()
    doc = _build_sample_batch_payload(data, tenant_id=user["tenant_id"], dev_id=dev_id, current_now=now)
    doc["created_at"] = now
    doc["created_by"] = user["id"]
    doc["created_by_name"] = user["name"]
    await db.pd_sample_batches.insert_one({**doc, "_id": doc["id"]})
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="created",
        entity_type="pd_sample_batches",
        entity_id=doc["id"],
        after=doc,
    )
    return _serialize_sample_batch(doc)

@pd_router.put("/developments/{dev_id}/sample-batches/{batch_id}")
async def update_sample_batch(dev_id: str, batch_id: str, data: SampleBatchCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    existing = await db.pd_sample_batches.find_one({"id": batch_id, "development_id": dev_id, "tenant_id": user["tenant_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Lote não encontrado")
    formula = await db.pd_formulas.find_one(
        {"id": clean_text(data.formula_base_id), "development_id": dev_id, "tenant_id": user["tenant_id"]},
        {"_id": 0, "id": 1},
    )
    if not formula:
        raise HTTPException(status_code=404, detail="Formula base nao encontrada para este desenvolvimento")
    updates = _build_sample_batch_payload(
        data,
        tenant_id=user["tenant_id"],
        dev_id=dev_id,
        existing_id=batch_id,
        current_now=now_iso(),
    )
    await db.pd_sample_batches.update_one({"id": batch_id, "tenant_id": user["tenant_id"]}, {"$set": updates})
    await audit_log(tenant_id=user["tenant_id"], user_id=user["id"], user_name=user.get("name", ""),
                    action="updated", entity_type="pd_sample_batches", entity_id=batch_id,
                    before={"nome": existing.get("nome")}, after=updates)
    return _serialize_sample_batch({**{k: v for k, v in existing.items() if k != "_id"}, **updates})

@pd_router.delete("/developments/{dev_id}/sample-batches/{batch_id}")
async def delete_sample_batch(dev_id: str, batch_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    existing = await db.pd_sample_batches.find_one(
        {"id": batch_id, "development_id": dev_id, "tenant_id": user["tenant_id"]}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Lote não encontrado")
    await db.pd_sample_batches.delete_one({"id": batch_id})
    await audit_log(tenant_id=user["tenant_id"], user_id=user["id"], user_name=user.get("name", ""),
                    action="deleted", entity_type="pd_sample_batches", entity_id=batch_id,
                    before={"nome": existing.get("nome")})
    return {"ok": True}

# ============ DOCUMENTS ============

@pd_router.post("/developments/{dev_id}/documents")
async def add_document(dev_id: str, data: DocumentCreate, request: Request):
    user = await get_current_user(request)
    dev = await db.pd_developments.find_one({"id": dev_id, "tenant_id": user["tenant_id"]})
    if not dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento não encontrado")
    
    doc_id = new_id()
    doc = {
        "id": doc_id,
        "development_id": dev_id,
        "doc_type": data.doc_type,
        "file_url": data.file_url,
        "file_name": data.file_name or "",
        "uploaded_by": user["id"],
        "uploaded_by_name": user["name"],
        "uploaded_at": now_iso(),
    }
    await db.pd_documents.insert_one(doc)
    doc.pop("_id", None)
    return doc

@pd_router.get("/developments/{dev_id}/documents")
async def list_documents(dev_id: str, request: Request):
    user = await get_current_user(request)
    docs = await db.pd_documents.find({"development_id": dev_id}, {"_id": 0}).sort("uploaded_at", -1).to_list(100)
    return docs

@pd_router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.pd_documents.delete_one({"id": doc_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return {"message": "Documento removido"}


@pd_router.post("/requests/{req_id}/live-documents/{doc_type}/generate")
async def generate_live_document(req_id: str, doc_type: str, data: LiveDocumentGenerate, request: Request):
    user = await get_current_user(request)
    if doc_type not in LIVE_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de documento vivo invalido")
    return await _generate_live_document_version(
        req_id=req_id,
        doc_type=doc_type,
        user=user,
        reason=data.reason,
        changed_fields=data.changed_fields or [doc_type],
        trigger="manual",
        source_changes=[],
    )


@pd_router.get("/requests/{req_id}/live-documents/{doc_type}/versions")
async def list_live_document_versions(req_id: str, doc_type: str, request: Request):
    user = await get_current_user(request)
    if doc_type not in LIVE_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de documento vivo invalido")
    query = {"tenant_id": user["tenant_id"], "pd_request_id": req_id, "doc_type": doc_type}
    if not _user_can_review_live_documents(user):
        query["status"] = "aprovado"
        query["active_for_operation"] = True
    return await db.pd_document_versions.find(query, {"_id": 0}).sort("version_number", -1).to_list(100)


@pd_router.get("/requests/{req_id}/live-documents/{doc_type}/current")
async def get_current_live_document(req_id: str, doc_type: str, request: Request):
    user = await get_current_user(request)
    if doc_type not in LIVE_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de documento vivo invalido")
    base_query = {"tenant_id": user["tenant_id"], "pd_request_id": req_id, "doc_type": doc_type}
    query = dict(base_query)
    if not _user_can_review_live_documents(user):
        query["status"] = "aprovado"
        query["active_for_operation"] = True
    doc_version = await db.pd_document_versions.find_one(query, {"_id": 0}, sort=[("version_number", -1)])
    if not doc_version and _user_can_review_live_documents(user):
        doc_version = await db.pd_document_versions.find_one(base_query, {"_id": 0}, sort=[("version_number", -1)])
    if not doc_version:
        raise HTTPException(status_code=404, detail="Documento vivo nao encontrado")
    return await _get_live_document_version(doc_version["id"], user)


@pd_router.get("/document-versions/{version_id}")
async def get_live_document_version(version_id: str, request: Request):
    user = await get_current_user(request)
    return await _get_live_document_version(version_id, user)


@pd_router.get("/document-versions/{version_id}/pdf")
async def export_live_document_pdf(version_id: str, request: Request):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfgen import canvas as rl_canvas

    user = await get_current_user(request)
    doc_version = await _get_live_document_version(version_id, user)
    snapshot = doc_version.get("snapshot") or {}
    tenant = await db.tenants.find_one({"id": user["tenant_id"]}, {"_id": 0})
    org_name = tenant["name"] if tenant else "Kuryos"
    is_approved = doc_version.get("status") == "aprovado" and doc_version.get("active_for_operation")
    label = _document_label(doc_version["doc_type"])

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, topMargin=22*mm, bottomMargin=18*mm, leftMargin=18*mm, rightMargin=18*mm, title=f"{label} {doc_version.get('version_code', '')}")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("LDTitle", parent=styles["Title"], fontSize=22, textColor=rl_colors.HexColor("#0A0A0B"), spaceAfter=4)
    sub_style = ParagraphStyle("LDSub", parent=styles["Normal"], fontSize=11, textColor=rl_colors.HexColor("#737373"), spaceAfter=10)
    h_style = ParagraphStyle("LDHead", parent=styles["Heading2"], fontSize=13, textColor=rl_colors.HexColor("#0A0A0B"), spaceBefore=12, spaceAfter=6)
    n_style = ParagraphStyle("LDNorm", parent=styles["Normal"], fontSize=9.5, leading=13)
    s_style = ParagraphStyle("LDSm", parent=styles["Normal"], fontSize=8, textColor=rl_colors.HexColor("#737373"))

    elements: List[Any] = []
    elements.append(Paragraph(label.upper(), title_style))
    elements.append(Paragraph(f"{org_name} - Documento Vivo (versionado)", sub_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=rl_colors.HexColor("#E5E5E5")))

    meta_rows = [
        ["Codigo:", doc_version.get("version_code", "")],
        ["Versao:", str(doc_version.get("version_number", ""))],
        ["Status:", "APROVADO E VIGENTE" if is_approved else "EM REVISAO (NAO LIBERADO PARA PRODUCAO)"],
        ["Gerado em:", doc_version.get("created_at", "")],
        ["Por:", doc_version.get("created_by_name", "")],
        ["Motivo:", doc_version.get("reason", "")],
    ]
    meta_table = Table(meta_rows, colWidths=[35*mm, 140*mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), rl_colors.HexColor("#737373")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(Spacer(1, 4*mm))
    elements.append(meta_table)

    _ITEM_COST_FIELDS = {"price_per_kg", "cost_brl", "cost_kg_usd", "price_currency", "catalog_id"}
    _ALLOWED_ITEM_KEYS_FT  = ("ingredient_name", "nome_tecnico", "nome_comercial", "inci", "fornecedor", "phase", "function", "percentage", "quantidade_lote_padrao", "unidade_lote")
    _ALLOWED_ITEM_KEYS_ALL = _ALLOWED_ITEM_KEYS_FT + ("price_per_kg", "cost_brl")
    _allowed_item_keys = _ALLOWED_ITEM_KEYS_FT if doc_version.get("doc_type") == "ficha_tecnica" else _ALLOWED_ITEM_KEYS_ALL

    def render_section(title: str, data: Any):
        elements.append(Paragraph(title, h_style))
        if isinstance(data, dict):
            rows = []
            for k, v in data.items():
                if isinstance(v, (list, dict)):
                    continue
                rows.append([str(k).replace("_", " ").capitalize() + ":", str(v) if v not in (None, "") else "-"])
            if rows:
                t = Table(rows, colWidths=[55*mm, 120*mm])
                t.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), rl_colors.HexColor("#737373")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                elements.append(t)
            for k, v in data.items():
                if isinstance(v, list) and v:
                    if all(isinstance(it, dict) for it in v):
                        keys = list({key for it in v for key in it.keys()})
                        keys = [k for k in keys if k in _allowed_item_keys]
                        if keys:
                            header = [k.replace("_", " ").capitalize() for k in keys]
                            rows = [header]
                            for it in v[:200]:
                                rows.append([str(it.get(k, "") or "") for k in keys])
                            tab = Table(rows, repeatRows=1)
                            tab.setStyle(TableStyle([
                                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0A0A0B")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                                ("GRID", (0, 0), (-1, -1), 0.3, rl_colors.HexColor("#E5E5E5")),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ]))
                            elements.append(Paragraph(k.replace("_", " ").capitalize(), s_style))
                            elements.append(tab)
                    else:
                        elements.append(Paragraph(", ".join(str(it) for it in v), n_style))

    for section_key, section_value in snapshot.items():
        render_section(section_key.replace("_", " ").upper(), section_value)

    elements.append(Spacer(1, 14*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.HexColor("#E5E5E5"), spaceAfter=4))
    elements.append(Paragraph(
        f"Documento gerado automaticamente em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC - {org_name}",
        s_style,
    ))

    def watermark(canvas: rl_canvas.Canvas, _doc):
        if not is_approved:
            canvas.saveState()
            canvas.setFillColorRGB(0.85, 0.0, 0.0, alpha=0.18)
            canvas.setFont("Helvetica-Bold", 80)
            canvas.translate(297, 421)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "EM REVISAO")
            canvas.restoreState()

    pdf.build(elements, onFirstPage=watermark, onLaterPages=watermark)
    buffer.seek(0)
    safe_code = (doc_version.get("version_code") or "doc").replace("/", "_")
    filename = f"{label.replace(' ', '_').lower()}_{safe_code}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------- Live document inbox + diff helpers ----------

def _flatten_snapshot(snapshot: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten a nested dict snapshot into dot-path -> value pairs (lists kept as-is)."""
    flat: Dict[str, Any] = {}
    if isinstance(snapshot, dict):
        for k, v in snapshot.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                flat.update(_flatten_snapshot(v, key))
            else:
                flat[key] = v
    return flat


@pd_router.get("/live-documents/pending")
async def list_pending_live_documents(request: Request):
    """List FT/EPA versions awaiting approval (em_revisao) for the current tenant.
    Useful as inbox for QA/Lider PD/Engenharia."""
    user = await get_current_user(request)
    if not _user_can_review_live_documents(user):
        raise HTTPException(status_code=403, detail="Sua funcao nao tem acesso ao inbox de documentos vivos.")

    versions = await db.pd_document_versions.find(
        {"tenant_id": user["tenant_id"], "status": "em_revisao"},
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)

    pd_request_ids = list({v.get("pd_request_id") for v in versions if v.get("pd_request_id")})
    pd_requests = []
    if pd_request_ids:
        pd_requests = await db.pd_requests.find(
            {"id": {"$in": pd_request_ids}, "tenant_id": user["tenant_id"]},
            {"_id": 0, "id": 1, "project_name": 1, "client_name": 1, "sku": 1},
        ).to_list(1000)
    pd_map = {p["id"]: p for p in pd_requests}

    result = []
    for v in versions:
        approval_tasks = await db.workflow_tasks.find(
            {"tenant_id": user["tenant_id"], "entity_type": "pd_document", "entity_id": v["id"]},
            {"_id": 0},
        ).sort("created_at", 1).to_list(50)
        pending_tasks = [t for t in approval_tasks if t.get("status") not in ("concluida", "cancelada")]
        my_role = (user.get("role") or "").lower()
        my_tasks = [
            t for t in pending_tasks
            if (t.get("metadata") or {}).get("approver_role") in {my_role, "qa" if my_role == "qa" else None, "lider_pd" if my_role == "lider_pd" else None}
            or t.get("responsible_id") == user["id"]
        ]
        pd_req = pd_map.get(v.get("pd_request_id")) or {}
        result.append({
            "id": v["id"],
            "doc_type": v["doc_type"],
            "version_code": v.get("version_code"),
            "version_number": v.get("version_number"),
            "status": v.get("status"),
            "reason": v.get("reason", ""),
            "changed_fields": v.get("changed_fields", []),
            "source_trigger": v.get("source_trigger", ""),
            "created_at": v.get("created_at"),
            "created_by_name": v.get("created_by_name", ""),
            "pd_request_id": v.get("pd_request_id"),
            "project_name": pd_req.get("project_name", ""),
            "client_name": pd_req.get("client_name", ""),
            "sku": pd_req.get("sku", ""),
            "pending_approvals_count": len(pending_tasks),
            "my_pending_tasks_count": len(my_tasks),
        })
    return result


@pd_router.get("/document-versions/{version_id}/diff")
async def diff_live_document_version(version_id: str, request: Request):
    """Diff a version's snapshot against the previous (non-rejected) version of the same doc.
    Returns a list of {path, before, after} field-level changes plus the version's source_changes."""
    user = await get_current_user(request)
    current = await _get_live_document_version(version_id, user)

    # find previous version (any status except rejeitado/reprovado, lower version_number)
    previous = await db.pd_document_versions.find_one(
        {
            "tenant_id": user["tenant_id"],
            "pd_request_id": current["pd_request_id"],
            "doc_type": current["doc_type"],
            "version_number": {"$lt": current["version_number"]},
            "status": {"$ne": "reprovado"},
        },
        {"_id": 0},
        sort=[("version_number", -1)],
    )

    flat_current = _flatten_snapshot(current.get("snapshot") or {})
    flat_previous = _flatten_snapshot((previous or {}).get("snapshot") or {})
    keys = sorted(set(flat_current.keys()) | set(flat_previous.keys()))
    differences: List[Dict[str, Any]] = []
    for key in keys:
        before = flat_previous.get(key)
        after = flat_current.get(key)
        if before == after:
            continue
        differences.append({
            "path": key,
            "label": key.replace("_", " ").replace(".", " · "),
            "before": before,
            "after": after,
        })

    approval_tasks = await db.workflow_tasks.find(
        {"tenant_id": user["tenant_id"], "entity_type": "pd_document", "entity_id": version_id},
        {"_id": 0},
    ).sort("created_at", 1).to_list(50)

    return {
        "current": {
            "id": current["id"],
            "version_code": current.get("version_code"),
            "version_number": current.get("version_number"),
            "status": current.get("status"),
            "reason": current.get("reason", ""),
            "changed_fields": current.get("changed_fields", []),
            "source_changes": current.get("source_changes", []),
            "source_trigger": current.get("source_trigger", ""),
            "created_at": current.get("created_at"),
            "created_by_name": current.get("created_by_name", ""),
            "snapshot": current.get("snapshot"),
        },
        "previous": (
            {
                "id": previous["id"],
                "version_code": previous.get("version_code"),
                "version_number": previous.get("version_number"),
                "status": previous.get("status"),
                "created_at": previous.get("created_at"),
            }
            if previous else None
        ),
        "differences": differences,
        "approval_tasks": approval_tasks,
    }


@pd_router.get("/stability/scheduler-status")
async def stability_scheduler_status(request: Request):
    """Return last-run info for the stability D-2 scheduler. Visible to PD roles + admin."""
    user = await get_current_user(request)
    require_roles(user, PD_READ | DOC_REVIEWERS)
    status = await db.system_status.find_one({"id": "stability_scheduler"}, {"_id": 0}) or {}
    return {
        "scheduler_active": True,
        "interval_seconds": 3600,
        "last_run_at": status.get("last_run_at"),
        "last_alerts_created": status.get("last_alerts_created", 0),
    }


@pd_router.post("/stability/run-scheduler")
async def run_stability_scheduler_now(request: Request):
    """Manually trigger the stability D-2 scan for the current tenant. Admin/PD leadership only."""
    user = await get_current_user(request)
    require_roles(user, ADMIN_ONLY | {"lider_pd", "qa", "formulador"})
    created = await check_stability_alerts_for_tenant(user["tenant_id"])
    await db.system_status.update_one(
        {"id": "stability_scheduler"},
        {"$set": {
            "id": "stability_scheduler",
            "last_run_at": now_iso(),
            "last_tenant_id": user["tenant_id"],
            "last_alerts_created": created,
            "last_run_kind": "manual",
            "last_run_by": user.get("name", ""),
        }},
        upsert=True,
    )
    return {"alerts_created": created, "ran_at": now_iso()}


# ============ FULL DETAIL VIEW ============

@pd_router.get("/requests/{req_id}/full")
async def get_pd_full_detail(req_id: str, request: Request):
    """Get complete P&D request with all related data"""
    user = await get_current_user(request)
    require_roles(user, PD_READ | COMERCIAL_FULL)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    
    history = await db.pd_request_status_history.find(
        {"pd_request_id": req_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    dev = await db.pd_developments.find_one({"pd_request_id": req_id}, {"_id": 0})
    
    formulas = []
    tests = []
    samples = []
    approval = None
    costs = {"ingredient_cost": 0, "packaging_cost": 0, "labor_cost": 0, "total_cost": 0}
    documents = []
    formula_cost_data = None
    cost_versions = None
    lab_results_doc = None
    linked_sample = None
    linked_variacao = None

    if pd_req.get("linked_amostra_id"):
        linked_sample = await db.crm_samples.find_one(
            {"id": pd_req["linked_amostra_id"], "tenant_id": user["tenant_id"]},
            {"_id": 0},
        )
        if linked_sample and pd_req.get("linked_variacao_id"):
            linked_variacao = next(
                (v for v in linked_sample.get("variacoes", []) if v.get("id") == pd_req["linked_variacao_id"]),
                None,
            )

    if dev:
        formulas = await db.pd_formulas.find({"development_id": dev["id"]}, {"_id": 0}).sort("version", -1).to_list(100)
        for f in formulas:
            items = await db.pd_formula_items.find({"formula_id": f["id"]}, {"_id": 0}).to_list(200)
            if linked_variacao:
                repaired_items = []
                for item in items:
                    repaired_items.append(
                        await _repair_prefilled_fragrance_item_from_variacao(f, item, linked_variacao)
                    )
                items = repaired_items
            total_cost = sum(it.get("cost_brl", 0) for it in items)
            for it in items:
                it["cost_percentage"] = round((it.get("cost_brl", 0) / total_cost * 100), 2) if total_cost > 0 else 0
            f["items"] = items
            volume = f.get("volume", 0) or 0
            volume_unit = f.get("volume_unit", "mL")
            volume_kg = volume / 1000.0 if volume_unit == "mL" else volume
            f["custo_unitario"] = round(total_cost * volume_kg, 2) if volume_kg > 0 else round(total_cost, 2)
            f["total_cost_per_kg"] = round(total_cost, 4)
        
        tests = await db.pd_tests.find({"development_id": dev["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
        samples = await db.pd_samples.find({"development_id": dev["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
        approval = await db.pd_approvals.find_one({"development_id": dev["id"]}, {"_id": 0})
        cost_doc = await db.pd_costs.find_one({"development_id": dev["id"]}, {"_id": 0})
        if cost_doc:
            costs = cost_doc
        documents = await db.pd_documents.find({"development_id": dev["id"]}, {"_id": 0}).sort("uploaded_at", -1).to_list(100)

        # Get unified lab results
        lab_results_doc = await db.pd_lab_results.find_one({"development_id": dev["id"]}, {"_id": 0})

        # Load cost versions (new versioned system) — response is role-filtered
        cost_versions_raw = await db.pd_cost_versions.find_one({"development_id": dev["id"]}, {"_id": 0})
        
        # Calculate formula cost data from latest formula
        formula_cost_auto = 0.0
        if formulas:
            latest = formulas[0]
            items = latest.get("items", [])
            total_cost_per_kg = sum(it.get("cost_brl", 0) for it in items)
            formula_cost_auto = round(total_cost_per_kg, 4)
            total_price_sum = sum(it.get("price_per_kg", 0) for it in items)
            cotacao = latest.get("cotacao_usd", 6.00) or 6.00
            vol = latest.get("volume", 0) or 0
            vu = latest.get("volume_unit", "mL")
            vkg = vol / 1000.0 if vu == "mL" else vol
            ip = latest.get("indice_perdas", 0) or 0
            cu = total_cost_per_kg * vkg if vkg > 0 else total_cost_per_kg
            cp = cu * (1 + ip / 100.0) if ip > 0 else cu
            formula_cost_data = {
                "total_cost_per_kg": round(total_cost_per_kg, 4),
                "total_price_sum": round(total_price_sum, 2),
                "custo_unitario": round(cu, 2),
                "custo_com_perdas": round(cp, 2),
                "cotacao_usd": cotacao,
                "volume": vol,
                "volume_unit": vu,
                "indice_perdas": ip,
            }

        # Build role-filtered cost_versions response
        cost_versions = _build_cost_versions_response(cost_versions_raw, user, formula_cost_auto)
    
    # Get client info from CRM if linked
    client_info = None
    if pd_req.get("client_card_id"):
        client_info = await db.cards.find_one({"id": pd_req["client_card_id"]}, {"_id": 0})

    # CRM v3 fallback: pd_request can come from a sample variation (linked_amostra_id)
    if not client_info and pd_req.get("linked_amostra_id"):
        sample = linked_sample or await db.crm_samples.find_one(
            {"id": pd_req["linked_amostra_id"], "tenant_id": user["tenant_id"]},
            {"_id": 0},
        )
        if sample:
            variacao = linked_variacao
            if not variacao and pd_req.get("linked_variacao_id"):
                variacao = next(
                    (v for v in sample.get("variacoes", []) if v.get("id") == pd_req["linked_variacao_id"]),
                    None,
                )
            client_info = {
                "produto": sample.get("produto") or sample.get("nome_produto", ""),
                "nome_cliente": sample.get("cliente_nome", ""),
                "nome_projeto": sample.get("projeto_nome", ""),
                "orcamento_projeto": sample.get("orcamento_projeto", ""),
                "textura_esperada": sample.get("textura_esperada", ""),
                "aplicacao": sample.get("aplicacao", ""),
                "sensorial": sample.get("sensorial", ""),
                "ph": sample.get("ph", ""),
                "objetivo_projeto": sample.get("objetivo_projeto", ""),
                "aplicacoes_desenvolver": sample.get("aplicacoes_desenvolver", ""),
                "ativos_claims": sample.get("ativos_claims", ""),
                "referencias": sample.get("referencias", ""),
                "referencias_fotos": sample.get("referencias_fotos", []) or [],
                "observacoes": (variacao or {}).get("observacoes_especificas", "")
                or sample.get("observacao_tecnica", ""),
                "feedback_cliente": (variacao or {}).get("feedback_cliente") or sample.get("feedback_cliente", ""),
                "direcoes_retrabalho": (variacao or {}).get("direcoes_retrabalho") or sample.get("direcoes_retrabalho", ""),
                "resultado_cliente": (variacao or {}).get("resultado_cliente") or (variacao or {}).get("resultado") or sample.get("resultado", ""),
                "_source": "crm_sample",
                "_amostra_id": sample.get("id"),
                "_variacao_id": (variacao or {}).get("id"),
                "_variacao_codigo": (variacao or {}).get("codigo"),
            }

    # Get updates + pending (new feature: Atualizações)
    updates_list = await db.pd_updates.find(
        {"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    pending_list = await db.pd_pending_items.find(
        {"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    now_dt = datetime.now(timezone.utc)
    for it in pending_list:
        if it["status"] == "pendente" and it.get("data_prevista"):
            try:
                dp = datetime.fromisoformat(it["data_prevista"].replace("Z", "+00:00")) if isinstance(it["data_prevista"], str) else it["data_prevista"]
                if dp.tzinfo is None:
                    dp = dp.replace(tzinfo=timezone.utc)
                it["status_calc"] = "atrasado" if dp < now_dt else "pendente"
            except Exception:
                it["status_calc"] = "pendente"
        else:
            it["status_calc"] = it["status"]

    return {
        "request": pd_req,
        "history": history,
        "development": dev,
        "formulas": formulas,
        "tests": tests,
        "samples": samples,
        "approval": approval,
        "costs": costs,
        "documents": documents,
        "client_info": client_info,
        "formula_cost_data": formula_cost_data,
        "cost_versions": cost_versions if dev else None,
        "lab_results": lab_results_doc if dev else None,
        "updates": updates_list,
        "pending": pending_list,
        "blocking_tasks": await get_blocking_tasks(
            tenant_id=user["tenant_id"],
            entity_type="pd_card",
            entity_id=req_id,
        ),
    }

# ============ DASHBOARD METRICS ============

@pd_router.get("/metrics")
async def pd_metrics(request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    
    total = await db.pd_requests.count_documents({"tenant_id": tid})
    by_status = {}
    for status in VALID_STATUSES:
        by_status[status] = await db.pd_requests.count_documents({"tenant_id": tid, "status": status})
    
    by_priority = {}
    for prio in ["Baixa", "Normal", "Alta", "Urgente"]:
        by_priority[prio] = await db.pd_requests.count_documents({"tenant_id": tid, "priority": prio})
    
    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
    }

# ============ FORMULA VERSIONAMENTO (RN-BF-01 / RN-PD-06) ============

class FormulaNewVersionInput(BaseModel):
    justification: str = Field(min_length=10, description="Justificativa obrigatória para nova versão")

@pd_router.post("/formulas/{formula_id}/new-version")
async def create_formula_new_version(formula_id: str, data: FormulaNewVersionInput, request: Request):
    """RN-BF-01 / RN-PD-06: Creates a new unlocked version of a locked formula with mandatory justification."""
    user = await get_current_user(request)
    old = await db.pd_formulas.find_one({"id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")
    if not old.get("locked"):
        raise HTTPException(status_code=400, detail="Apenas fórmulas registradas (bloqueadas) podem ser versionadas. Edite diretamente a fórmula atual.")

    old_items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(200)
    new_formula_id = new_id()
    new_version_num = old.get("version", 1) + 1

    new_formula = {
        "id": new_formula_id,
        "tenant_id": user["tenant_id"],
        "development_id": old["development_id"],
        "name": old.get("name", f"Fórmula v{new_version_num}"),
        "notes": old.get("notes", ""),
        "volume": old.get("volume", 0),
        "volume_unit": old.get("volume_unit", "mL"),
        "indice_perdas": old.get("indice_perdas", 0),
        "cotacao_usd": old.get("cotacao_usd", 6.00),
        "version": new_version_num,
        "locked": False,
        "parent_formula_id": formula_id,
        "version_justification": data.justification.strip(),
        "created_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    }
    await db.pd_formulas.insert_one(new_formula)
    new_formula.pop("_id", None)

    new_items = []
    for item in old_items:
        new_item = {**{k: v for k, v in item.items() if k != "_id"}, "id": new_id(), "formula_id": new_formula_id}
        new_items.append(new_item)
    if new_items:
        await db.pd_formula_items.insert_many(new_items)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="formula_new_version_created",
        entity_type="pd_formula",
        entity_id=new_formula_id,
        after={"version": new_version_num, "parent_formula_id": formula_id, "justification": data.justification.strip()},
    )
    new_formula["items"] = [
        {k: v for k, v in it.items() if k != "_id"} for it in new_items
    ]
    return new_formula


@pd_router.post("/formulas/{formula_id}/duplicate")
async def duplicate_formula(formula_id: str, request: Request):
    """Duplica uma fórmula (bloqueada ou não) como nova variação — ideal para lotes com base comum."""
    user = await get_current_user(request)
    src = await db.pd_formulas.find_one({"id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")

    siblings = await db.pd_formulas.find(
        {"development_id": src["development_id"]}, {"version": 1}
    ).to_list(100)
    next_version = max((s.get("version", 1) for s in siblings), default=1) + 1

    src_items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(200)
    new_formula_id = new_id()
    new_formula = {
        k: v for k, v in src.items()
        if k not in ("id", "locked", "locked_at", "locked_by", "locked_by_name", "parent_formula_id",
                     "version_justification", "created_at", "created_by", "created_by_name", "items")
    }
    new_formula.update({
        "id": new_formula_id,
        "version": next_version,
        "name": src.get("name", f"Fórmula v{next_version}"),
        "locked": False,
        "parent_formula_id": formula_id,
        "version_justification": "Variação duplicada",
        "created_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    })
    await db.pd_formulas.insert_one(new_formula)
    new_formula.pop("_id", None)

    new_items = []
    for item in src_items:
        new_item = {**{k: v for k, v in item.items() if k != "_id"}, "id": new_id(), "formula_id": new_formula_id}
        new_items.append(new_item)
    if new_items:
        await db.pd_formula_items.insert_many(new_items)

    new_formula["items"] = [{k: v for k, v in it.items() if k != "_id"} for it in new_items]
    return new_formula


@pd_router.post("/formulas/{formula_id}/import-into/{development_id}")
async def import_formula_into_development(formula_id: str, development_id: str, request: Request):
    """B13: importa a composição de uma fórmula existente (banco de fórmulas) como
    rascunho editável em outro desenvolvimento — deep copy, nunca referência: alterar
    a cópia não afeta a fórmula de origem. Registra importada_de_* para rastreabilidade."""
    user = await get_current_user(request)
    if not can_view_formula_composition(user):
        raise HTTPException(status_code=403, detail="Seu perfil não tem permissão para importar composição de fórmulas.")

    src = await db.pd_formulas.find_one({"id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not src:
        raise HTTPException(status_code=404, detail="Fórmula de origem não encontrada")

    target_dev = await db.pd_developments.find_one({"id": development_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not target_dev:
        raise HTTPException(status_code=404, detail="Desenvolvimento de destino não encontrado")

    src_dev = await db.pd_developments.find_one({"id": src["development_id"]}, {"_id": 0, "pd_request_id": 1})
    src_req_id = src_dev.get("pd_request_id") if src_dev else None

    src_items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(200)

    siblings = await db.pd_formulas.find(
        {"development_id": development_id}, {"version": 1}
    ).to_list(100)
    next_version = max((s.get("version", 1) for s in siblings), default=0) + 1

    new_formula_id = new_id()
    new_formula = {
        "id": new_formula_id,
        "tenant_id": user["tenant_id"],
        "development_id": development_id,
        "name": src.get("name", "Fórmula importada"),
        "notes": src.get("notes", ""),
        "volume": src.get("volume", 0),
        "volume_unit": src.get("volume_unit", "mL"),
        "indice_perdas": src.get("indice_perdas", 0),
        "cotacao_usd": src.get("cotacao_usd", 6.00),
        "version": next_version,
        "locked": False,
        "parent_formula_id": None,
        "version_justification": "Importada de outra requisição",
        "importada_de_formula_id": formula_id,
        "importada_de_request_id": src_req_id,
        "created_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    }
    await db.pd_formulas.insert_one(new_formula)
    new_formula.pop("_id", None)

    new_items = []
    for item in src_items:
        new_item = {**{k: v for k, v in item.items() if k != "_id"}, "id": new_id(), "formula_id": new_formula_id}
        new_items.append(new_item)
    if new_items:
        await db.pd_formula_items.insert_many(new_items)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="formula_imported",
        entity_type="pd_formula",
        entity_id=new_formula_id,
        after={"imported_from_formula_id": formula_id, "imported_from_request_id": src_req_id, "target_development_id": development_id},
    )

    new_formula["items"] = [{k: v for k, v in it.items() if k != "_id"} for it in new_items]
    return new_formula


# ============ STABILITY STUDY INIT FOR PD CARD ============

@pd_router.get("/requests/{req_id}/stability-study")
async def get_or_init_stability_study_for_card(req_id: str, request: Request):
    """Gets (or auto-creates) the stability study for a P&D card, including all readings."""
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    study = await _ensure_stability_study_for_pd_card(pd_req, user)
    readings = await db.pd_stability_readings.find(
        {"study_id": study["id"], "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort([("day_offset", 1), ("created_at", 1)]).to_list(5000)
    constants = {"conditions": STABILITY_CONDITIONS, "parameters": STABILITY_PARAMETERS, "checkpoints": STABILITY_CHECKPOINTS}
    return {"study": study, "readings": readings, "constants": constants}


# ============ FICHA TÉCNICA - UI DATA (analise laboratorial) ============

class FichaTecnicaParam(BaseModel):
    especificacao: str = ""
    resultado: str = ""
    pa: str = ""  # "Conforme" | "Não Conforme" | ""

class FichaTecnicaAnaliseUpsert(BaseModel):
    produto: Optional[str] = None
    lote: Optional[str] = None
    data_fabricacao: Optional[str] = None
    validade: Optional[str] = None
    quantidade: Optional[str] = None
    aspecto: Optional[FichaTecnicaParam] = None
    cor: Optional[FichaTecnicaParam] = None
    densidade: Optional[FichaTecnicaParam] = None
    odor: Optional[FichaTecnicaParam] = None
    ph: Optional[FichaTecnicaParam] = None
    teor_alcool: Optional[FichaTecnicaParam] = None
    elaboracao: Optional[Any] = None  # structured: {secoes: [{id, nome, temperatura, etapas:[str]}]}
    resp_tecnico: Optional[str] = None
    status_aprovacao: Optional[str] = None  # "aprovado" | "reprovado"


def _build_ficha_default_params_from_lab_results(lab_results: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    return {
        "aspecto": {
            "especificacao": "",
            "resultado": str(lab_results.get("sensorial", {}).get("aspecto") or ""),
            "pa": "",
        },
        "cor": {
            "especificacao": "",
            "resultado": str(lab_results.get("sensorial", {}).get("cor") or ""),
            "pa": "",
        },
        "densidade": {"especificacao": "", "resultado": "", "pa": ""},
        "odor": {
            "especificacao": "",
            "resultado": str(lab_results.get("sensorial", {}).get("odor") or ""),
            "pa": "",
        },
        "ph": {
            "especificacao": "",
            "resultado": str(lab_results.get("ph", {}).get("valor_medido") or ""),
            "pa": "",
        },
        "teor_alcool": {"especificacao": "", "resultado": "", "pa": ""},
    }


def _merge_ficha_analise_with_lab_defaults(
    analise: Dict[str, Any],
    lab_results: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, bool]]:
    merged = dict(analise or {})
    auto_filled: Dict[str, bool] = {}
    defaults = _build_ficha_default_params_from_lab_results(lab_results or {})

    for key, default_value in defaults.items():
        existing = merged.get(key)
        if not isinstance(existing, dict):
            existing = {"especificacao": "", "resultado": str(existing or ""), "pa": ""}
        merged_value = {
            "especificacao": str(existing.get("especificacao") or ""),
            "resultado": str(existing.get("resultado") or ""),
            "pa": str(existing.get("pa") or ""),
        }
        if not merged_value["resultado"] and default_value["resultado"]:
            merged_value["resultado"] = default_value["resultado"]
            auto_filled[key] = True
        merged[key] = merged_value

    return merged, auto_filled

@pd_router.get("/requests/{req_id}/ficha-tecnica-ui")
async def get_ficha_tecnica_ui(req_id: str, request: Request):
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    dev = await db.pd_developments.find_one({"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    formula = None
    items = []
    if dev:
        formula = await db.pd_formulas.find_one({"development_id": dev["id"]}, {"_id": 0}, sort=[("version", -1)])
        if formula:
            items = await db.pd_formula_items.find({"formula_id": formula["id"]}, {"_id": 0}).to_list(200)
    analise = await db.pd_ficha_tecnica.find_one({"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0}) or {}
    lab_results = {}
    if dev:
        lab_results = await db.pd_lab_results.find_one({"development_id": dev["id"]}, {"_id": 0}) or {}
    analise_merged, auto_filled = _merge_ficha_analise_with_lab_defaults(analise, lab_results)
    return {
        "request": pd_req,
        "development": dev,
        "formula": formula,
        "formula_items": items,
        "analise": analise_merged,
        "lab_results": lab_results,
        "auto_filled": auto_filled,
    }

@pd_router.put("/requests/{req_id}/ficha-tecnica-ui")
async def save_ficha_tecnica_ui(req_id: str, data: FichaTecnicaAnaliseUpsert, request: Request):
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    dev = await db.pd_developments.find_one({"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if clean_text(data.status_aprovacao or "").lower() == "aprovado" and _pd_request_requires_commercial_approval(pd_req):
        if not dev:
            raise HTTPException(status_code=409, detail="Inicie o desenvolvimento antes de aprovar a ficha tecnica.")
        approval = await db.pd_approvals.find_one({"development_id": dev["id"]}, {"_id": 0})
        if not (approval and approval.get("approved_by_client")):
            raise HTTPException(
                status_code=409,
                detail="Ficha tecnica de solicitacao comercial so pode ser aprovada apos aprovacao comercial/cliente registrada.",
            )
    update_data = {}
    for field in ["produto", "lote", "data_fabricacao", "validade", "quantidade", "elaboracao", "resp_tecnico", "status_aprovacao"]:
        val = getattr(data, field, None)
        if val is not None:
            update_data[field] = val
    for param in ["aspecto", "cor", "densidade", "odor", "ph", "teor_alcool"]:
        val = getattr(data, param, None)
        if val is not None:
            update_data[param] = val.model_dump()
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    update_data.update({
        "updated_at": now_iso(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    })
    existing = await db.pd_ficha_tecnica.find_one({"pd_request_id": req_id, "tenant_id": user["tenant_id"]})
    if existing:
        await db.pd_ficha_tecnica.update_one({"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"$set": update_data})
    else:
        update_data.update({
            "id": new_id(),
            "pd_request_id": req_id,
            "development_id": dev["id"] if dev else None,
            "tenant_id": user["tenant_id"],
            "created_at": now_iso(),
        })
        await db.pd_ficha_tecnica.insert_one(update_data)
    result = await db.pd_ficha_tecnica.find_one({"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    return result


# ============ FICHA TÉCNICA PDF GENERATION ============

@pd_router.get("/requests/{req_id}/ficha-tecnica")
async def generate_ficha_tecnica(req_id: str, request: Request):
    """Generate a professional technical sheet PDF for a P&D development"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")

    dev = await db.pd_developments.find_one({"pd_request_id": req_id}, {"_id": 0})
    
    formulas = []
    tests = []
    approval = None
    cost_data = None
    
    if dev:
        formulas = await db.pd_formulas.find({"development_id": dev["id"]}, {"_id": 0}).sort("version", -1).to_list(100)
        for f in formulas:
            f["items"] = await db.pd_formula_items.find({"formula_id": f["id"]}, {"_id": 0}).to_list(200)
        tests = await db.pd_tests.find({"development_id": dev["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
        approval = await db.pd_approvals.find_one({"development_id": dev["id"]}, {"_id": 0})
        cost_data = await db.pd_costs.find_one({"development_id": dev["id"]}, {"_id": 0})

    # Get client info
    client_info = None
    if pd_req.get("client_card_id"):
        client_info = await db.cards.find_one({"id": pd_req["client_card_id"]}, {"_id": 0})

    tenant = await db.tenants.find_one({"id": user["tenant_id"]}, {"_id": 0})
    org_name = tenant["name"] if tenant else "Kuryos"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=25*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('FTTitle', parent=styles['Title'], fontSize=22, spaceAfter=4, textColor=rl_colors.HexColor('#0A0A0B'))
    subtitle_style = ParagraphStyle('FTSubtitle', parent=styles['Normal'], fontSize=12, textColor=rl_colors.HexColor('#737373'), spaceAfter=8)
    heading_style = ParagraphStyle('FTHeading', parent=styles['Heading2'], fontSize=13, spaceAfter=6, spaceBefore=14, textColor=rl_colors.HexColor('#0A0A0B'))
    normal_style = ParagraphStyle('FTNormal', parent=styles['Normal'], fontSize=9.5, spaceAfter=3, leading=13)
    small_style = ParagraphStyle('FTSmall', parent=styles['Normal'], fontSize=8, textColor=rl_colors.HexColor('#737373'))
    
    elements = []

    elements.append(Paragraph("FICHA TÉCNICA", title_style))
    elements.append(Paragraph(f"{org_name} — Pesquisa & Desenvolvimento", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=rl_colors.HexColor('#E5E5E5'), spaceAfter=8))

    # Product Info
    elements.append(Paragraph("1. IDENTIFICAÇÃO DO PRODUTO", heading_style))
    info_data = [
        ["Projeto:", pd_req["project_name"]],
        ["Tipo:", pd_req.get("request_type", "—")],
        ["Cliente:", pd_req.get("client_name", "—")],
        ["Prioridade:", pd_req.get("priority", "—")],
        ["Status:", STATUS_LABELS.get(pd_req["status"], pd_req["status"])],
    ]
    
    info_table = Table(info_data, colWidths=[40*mm, 130*mm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('TEXTCOLOR', (0, 0), (0, -1), rl_colors.HexColor('#737373')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)

    # Briefing from CRM
    if client_info:
        elements.append(Paragraph("2. BRIEFING DO PROJETO", heading_style))
        briefing_data = []
        if client_info.get("produto"):
            briefing_data.append(["Produto:", client_info["produto"]])
        if client_info.get("objetivo_projeto"):
            briefing_data.append(["Objetivo:", client_info["objetivo_projeto"]])
        if client_info.get("aplicacoes_desenvolver"):
            briefing_data.append(["Aplicações:", client_info["aplicacoes_desenvolver"]])
        if client_info.get("textura_esperada"):
            briefing_data.append(["Textura:", client_info["textura_esperada"]])
        if client_info.get("sensorial"):
            briefing_data.append(["Sensorial:", client_info["sensorial"]])
        if client_info.get("ph"):
            briefing_data.append(["pH:", client_info["ph"]])
        if client_info.get("orcamento_projeto"):
            briefing_data.append(["Orçamento:", client_info["orcamento_projeto"]])
        if briefing_data:
            bt = Table(briefing_data, colWidths=[40*mm, 130*mm])
            bt.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9.5),
                ('TEXTCOLOR', (0, 0), (0, -1), rl_colors.HexColor('#737373')),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(bt)

    # Formula with costs
    section_num = 3
    if formulas:
        latest = formulas[0]
        elements.append(Paragraph(f"{section_num}. MANIPULAÇÃO / FORMULAÇÃO (v{latest['version']})", heading_style))
        
        if latest.get("items"):
            # Ficha Técnica is an operational document — no cost columns
            vol = latest.get("volume", 0) or 0
            vu = latest.get("volume_unit", "mL")
            formula_header = ["Ingrediente", "Fornecedor", "%Fórmula", f"Qtd/Lote ({vu})"]
            formula_rows = [formula_header]
            total_pct = 0
            for item in latest["items"]:
                pct = item.get("percentage", 0)
                total_pct += pct
                qty = f"{(vol * pct / 100):.3f}" if vol > 0 else "—"
                formula_rows.append([
                    item["ingredient_name"],
                    item.get("fornecedor") or "—",
                    f"{pct:.3f}",
                    qty,
                ])
            formula_rows.append(["TOTAL", "", f"{total_pct:.2f}", f"{vol:.0f}" if vol > 0 else "—"])

            ft = Table(formula_rows, colWidths=[55*mm, 40*mm, 25*mm, 31*mm])
            ft.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#0A0A0B')),
                ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('GRID', (0, 0), (-1, -2), 0.5, rl_colors.HexColor('#E5E5E5')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('TOPPADDING', (0, -1), (-1, -1), 8),
                ('LINEABOVE', (0, -1), (-1, -1), 1, rl_colors.HexColor('#0A0A0B')),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('TOPPADDING', (0, 0), (-1, 0), 6),
            ]))
            elements.append(ft)
        section_num += 1

    # Tests
    if tests:
        elements.append(Paragraph(f"{section_num}. RESULTADOS DE TESTES", heading_style))
        status_label = {"PENDING": "Pendente", "RUNNING": "Em andamento", "APPROVED": "Aprovado", "FAILED": "Reprovado"}
        for t in tests:
            dados = t.get("dados", {})
            result_text = ""
            if dados:
                for k, v in dados.items():
                    if v:
                        result_text += f"{k}: {v}; "
            elements.append(Paragraph(f"<b>{t['test_type']}</b> — {status_label.get(t['status'], t['status'])}", normal_style))
            if result_text:
                elements.append(Paragraph(result_text.rstrip("; "), small_style))
        section_num += 1

    # Footer
    elements.append(Spacer(1, 20*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.HexColor('#E5E5E5'), spaceAfter=4))
    elements.append(Paragraph(
        f"Documento gerado automaticamente em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC — {org_name}",
        small_style
    ))

    doc.build(elements)
    buffer.seek(0)

    safe_name = pd_req["project_name"].replace(" ", "_").replace("/", "-")
    filename = f"ficha_tecnica_{safe_name}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

# ============================================================
# EXTENSÕES P&D: CATALOG, INTERNAL RESEARCH, STOCK, UPDATES
# ============================================================

# ----------- MODELS ------------

class FornecedorCatalog(BaseModel):
    nome: str
    codigo: Optional[str] = None
    preco_rs_kg: float = 0.0
    moeda: str = "BRL"

class CatalogItemCreate(BaseModel):
    nome: str
    inci: Optional[str] = None
    codigo_interno: Optional[str] = None
    fornecedor: Optional[str] = None
    preco_rs_kg: float = 0.0
    moeda: str = "BRL"
    unidade: str = "kg"
    categoria: Optional[str] = None
    observacoes: Optional[str] = None
    fornecedores: Optional[List[FornecedorCatalog]] = []

class CatalogItemUpdate(BaseModel):
    nome: Optional[str] = None
    inci: Optional[str] = None
    codigo_interno: Optional[str] = None
    fornecedor: Optional[str] = None
    preco_rs_kg: Optional[float] = None
    moeda: Optional[str] = None
    unidade: Optional[str] = None
    categoria: Optional[str] = None
    observacoes: Optional[str] = None
    fornecedores: Optional[List[FornecedorCatalog]] = None


def _normalize_catalog_lookup(value: Any) -> str:
    return str(value or "").strip().lower()


def _catalog_match_keys(doc: Dict[str, Any]) -> set[str]:
    return {
        key
        for key in (
            _normalize_catalog_lookup(doc.get("nome")),
            _normalize_catalog_lookup(doc.get("codigo_interno")),
            _normalize_catalog_lookup(doc.get("inci")),
        )
        if key
    }


def _dedupe_catalog_suppliers(suppliers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for supplier in suppliers:
        name_key = _normalize_catalog_lookup(supplier.get("nome"))
        code_key = _normalize_catalog_lookup(supplier.get("codigo"))
        key = f"{name_key}|{code_key}"
        if not name_key:
            continue
        existing = deduped.get(key)
        if not existing:
            deduped[key] = supplier
            continue
        existing_price = existing.get("preco_rs_kg")
        next_price = supplier.get("preco_rs_kg")
        if existing_price in (None, 0) and next_price not in (None, 0):
            deduped[key] = supplier
    return sorted(
        deduped.values(),
        key=lambda supplier: (
            supplier.get("preco_rs_kg") is None,
            supplier.get("preco_rs_kg") if supplier.get("preco_rs_kg") is not None else float("inf"),
            supplier.get("nome", ""),
        ),
    )


async def _enrich_catalog_items_with_procurement_data(
    tenant_id: str,
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not items:
        return items

    materiais = await db.materiais.find(
        {"tenant_id": tenant_id, "tipo2": "MP"},
        {"_id": 0, "nome": 1, "codigo_interno": 1, "fornecedores": 1, "subtipo": 1},
    ).to_list(5000)
    homologacao_mps = await db.homologacao_mps.find(
        {"tenant_id": tenant_id, "status": "homologada"},
        {"_id": 0, "nome": 1, "codigo_interno": 1, "inci": 1, "fornecedor_id": 1, "fornecedor_nome": 1, "funcao": 1, "custo_referencia": 1, "unidade": 1},
    ).to_list(5000)

    materiais_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for material in materiais:
        for key in _catalog_match_keys(material):
            materiais_by_key.setdefault(key, []).append(material)

    homologacao_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for mp in homologacao_mps:
        for key in _catalog_match_keys(mp):
            homologacao_by_key.setdefault(key, []).append(mp)

    enriched_items = []
    for original in items:
        item = dict(original)
        match_keys = _catalog_match_keys(item)
        merged_suppliers = list(item.get("fornecedores") or [])
        existing_keys = {
            (_normalize_catalog_lookup(supplier.get("nome")), _normalize_catalog_lookup(supplier.get("codigo")))
            for supplier in merged_suppliers
        }

        matched_materials = []
        matched_homologacoes = []
        for key in match_keys:
            matched_materials.extend(materiais_by_key.get(key, []))
            matched_homologacoes.extend(homologacao_by_key.get(key, []))

        for material in matched_materials:
            if not item.get("categoria") and material.get("subtipo"):
                item["categoria"] = material["subtipo"]
            for supplier in material.get("fornecedores") or []:
                if supplier.get("status_homologacao") != "homologado":
                    continue
                supplier_doc = {
                    "nome": supplier.get("fornecedor_nome", ""),
                    "codigo": supplier.get("codigo_fornecedor") or None,
                    "preco_rs_kg": supplier.get("preco_por_unidade") if (supplier.get("moeda") or "BRL") == "BRL" else None,
                    "moeda": supplier.get("moeda", "BRL"),
                    "origem": "materiais_homologados",
                }
                supplier_key = (
                    _normalize_catalog_lookup(supplier_doc.get("nome")),
                    _normalize_catalog_lookup(supplier_doc.get("codigo")),
                )
                if supplier_key in existing_keys or not supplier_key[0]:
                    continue
                merged_suppliers.append(supplier_doc)
                existing_keys.add(supplier_key)

        for mp in matched_homologacoes:
            if not item.get("inci") and mp.get("inci"):
                item["inci"] = mp["inci"]
            if not item.get("codigo_interno") and mp.get("codigo_interno"):
                item["codigo_interno"] = mp["codigo_interno"]
            if not item.get("categoria") and mp.get("funcao"):
                item["categoria"] = mp["funcao"]
            supplier_doc = {
                "nome": mp.get("fornecedor_nome", ""),
                "codigo": mp.get("fornecedor_id") or None,
                "preco_rs_kg": mp.get("custo_referencia"),
                "moeda": "BRL",
                "origem": "mp_homologada",
            }
            supplier_key = (
                _normalize_catalog_lookup(supplier_doc.get("nome")),
                _normalize_catalog_lookup(supplier_doc.get("codigo")),
            )
            if supplier_key in existing_keys or not supplier_key[0]:
                continue
            merged_suppliers.append(supplier_doc)
            existing_keys.add(supplier_key)

        item["fornecedores"] = _dedupe_catalog_suppliers(merged_suppliers)
        if not item.get("fornecedor") and item["fornecedores"]:
            item["fornecedor"] = item["fornecedores"][0].get("nome", "")
        enriched_items.append(item)

    return enriched_items

class InternalResearchCreate(BaseModel):
    project_name: str
    description: Optional[str] = None
    category: Optional[str] = None
    references: Optional[str] = None
    objectives: Optional[str] = None
    priority: str = "Normal"
    deadline: Optional[str] = None

class StockItemCreate(BaseModel):
    categoria: str  # mp, insumo, amostra_acabada
    nome: str
    codigo_interno: Optional[str] = None
    fragrancia_id: Optional[str] = None  # R09: FR-NNNNN do cadastro de fragrâncias
    unidade_medida: str = "kg"  # kg, g, mL, L, un
    quantidade_atual: float = 0.0
    quantidade_minima: float = 0.0
    lote: Optional[str] = None
    validade: Optional[str] = None  # ISO date string
    localizacao: Optional[str] = None  # gaveta/prateleira/local
    custo_unitario: float = 0.0
    fornecedor: Optional[str] = None
    observacoes: Optional[str] = None
    catalog_id: Optional[str] = None  # Link to catalog (for MPs)
    # For amostra_acabada
    formula_ref: Optional[str] = None  # e.g., "Body Splash La Vie 3% fragrância"
    fragrancia_percentual: Optional[float] = None
    linked_pd_request_id: Optional[str] = None
    linked_formula_id: Optional[str] = None

class StockItemUpdate(BaseModel):
    nome: Optional[str] = None
    codigo_interno: Optional[str] = None
    unidade_medida: Optional[str] = None
    quantidade_minima: Optional[float] = None
    lote: Optional[str] = None
    validade: Optional[str] = None
    localizacao: Optional[str] = None
    custo_unitario: Optional[float] = None
    fornecedor: Optional[str] = None
    observacoes: Optional[str] = None
    catalog_id: Optional[str] = None
    formula_ref: Optional[str] = None
    fragrancia_percentual: Optional[float] = None

class StockMovementCreate(BaseModel):
    tipo: str  # entrada, saida, ajuste
    quantidade: float
    motivo: Optional[str] = None
    lote: Optional[str] = None
    linked_dev_id: Optional[str] = None
    linked_pd_request_id: Optional[str] = None

class UpdateCreate(BaseModel):
    mensagem: str
    tipo: Optional[str] = "observacao"  # observacao, status, pendencia_resolvida, chegada_material, solicitacao_mp, solicitacao_fragrancia, recebimento
    visivel_comercial: bool = True
    item_solicitado: Optional[str] = None
    fornecedor: Optional[str] = None
    previsao_entrega: Optional[str] = None  # ISO date

class PendingItemCreate(BaseModel):
    tipo: str  # fragrancia, mp, insumo, amostra, outro
    descricao: str
    data_prevista: Optional[str] = None  # ISO date
    fornecedor: Optional[str] = None
    observacoes: Optional[str] = None

class PendingItemUpdate(BaseModel):
    tipo: Optional[str] = None
    descricao: Optional[str] = None
    data_prevista: Optional[str] = None
    fornecedor: Optional[str] = None
    observacoes: Optional[str] = None
    status: Optional[str] = None  # pendente, recebido, atrasado, cancelado


# ============ 1) BANCO DE CUSTOS (CATALOG) ============

@pd_router.post("/catalog")
async def create_catalog_item(data: CatalogItemCreate, request: Request):
    user = await get_current_user(request)
    item_id = new_id()
    item = {
        "id": item_id,
        "tenant_id": user["tenant_id"],
        "nome": data.nome.strip(),
        "inci": (data.inci or "").strip(),
        "codigo_interno": (data.codigo_interno or "").strip(),
        "fornecedor": (data.fornecedor or "").strip(),
        "preco_rs_kg": float(data.preco_rs_kg or 0),
        "moeda": data.moeda or "BRL",
        "unidade": data.unidade or "kg",
        "categoria": (data.categoria or "").strip(),
        "observacoes": (data.observacoes or "").strip(),
        "fornecedores": [f.model_dump() for f in (data.fornecedores or [])],
        "ultima_atualizacao": now_iso(),
        "atualizado_por": user["name"],
        "atualizado_por_id": user["id"],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
    }
    item = (await _enrich_catalog_items_with_procurement_data(user["tenant_id"], [item]))[0]
    await db.pd_catalog.insert_one(item)
    item.pop("_id", None)
    return item

@pd_router.get("/catalog")
async def list_catalog(request: Request, q: Optional[str] = None, categoria: Optional[str] = None):
    user = await get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if q:
        query["$or"] = [
            {"nome": {"$regex": q, "$options": "i"}},
            {"inci": {"$regex": q, "$options": "i"}},
            {"codigo_interno": {"$regex": q, "$options": "i"}},
            {"fornecedor": {"$regex": q, "$options": "i"}},
            {"fornecedores.nome": {"$regex": q, "$options": "i"}},
        ]
    if categoria:
        query["categoria"] = categoria
    items = await db.pd_catalog.find(query, {"_id": 0}).sort("nome", 1).to_list(1000)
    return await _enrich_catalog_items_with_procurement_data(user["tenant_id"], items)

@pd_router.get("/catalog/{item_id}")
async def get_catalog_item(item_id: str, request: Request):
    user = await get_current_user(request)
    item = await db.pd_catalog.find_one({"id": item_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado no banco de custos")
    return (await _enrich_catalog_items_with_procurement_data(user["tenant_id"], [item]))[0]

@pd_router.put("/catalog/{item_id}")
async def update_catalog_item(item_id: str, data: CatalogItemUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_catalog.find_one({"id": item_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # Track price change history if preco changed
    if "preco_rs_kg" in update_fields and update_fields["preco_rs_kg"] != existing.get("preco_rs_kg"):
        history_entry = {
            "id": new_id(),
            "catalog_item_id": item_id,
            "preco_anterior": existing.get("preco_rs_kg", 0),
            "preco_novo": update_fields["preco_rs_kg"],
            "moeda": update_fields.get("moeda") or existing.get("moeda", "BRL"),
            "atualizado_por": user["name"],
            "atualizado_por_id": user["id"],
            "created_at": now_iso(),
        }
        await db.pd_catalog_price_history.insert_one(history_entry)

    update_fields["ultima_atualizacao"] = now_iso()
    update_fields["atualizado_por"] = user["name"]
    update_fields["atualizado_por_id"] = user["id"]
    source_changes = _build_source_changes(
        existing,
        update_fields,
        {
            "nome": "Nome tecnico",
            "inci": "INCI",
            "fornecedor": "Fornecedor homologado",
        },
        ignored_fields=["preco_rs_kg", "moeda", "unidade", "categoria", "observacoes", "ultima_atualizacao", "atualizado_por", "atualizado_por_id", "fornecedores", "codigo_interno"],
    )

    enriched_item = (await _enrich_catalog_items_with_procurement_data(
        user["tenant_id"],
        [{**existing, **update_fields}],
    ))[0]
    update_fields["fornecedores"] = enriched_item.get("fornecedores", [])
    if not update_fields.get("fornecedor"):
        update_fields["fornecedor"] = enriched_item.get("fornecedor", "")

    await db.pd_catalog.update_one({"id": item_id}, {"$set": update_fields})
    item = await db.pd_catalog.find_one({"id": item_id}, {"_id": 0})
    if any(field in update_fields for field in ("nome", "inci", "fornecedor")):
        ficha_fields = ["composicao_completa"]
        epa_fields = ["bom_bulk_formula"]
        if "inci" in update_fields:
            epa_fields.append("informacoes_rotulo")
        await _auto_generate_documents_for_catalog_items(
            [item_id],
            user,
            "catalogo_mp",
            ficha_changed_fields=ficha_fields,
            epa_changed_fields=epa_fields,
            source_changes=source_changes,
        )
    return (await _enrich_catalog_items_with_procurement_data(user["tenant_id"], [item]))[0]

@pd_router.delete("/catalog/{item_id}")
async def delete_catalog_item(item_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.pd_catalog.delete_one({"id": item_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")
    # Do not delete formula items referring to catalog - just unset catalog_id
    await db.pd_formula_items.update_many({"catalog_id": item_id}, {"$set": {"catalog_id": None}})
    return {"message": "Ingrediente removido do banco de custos"}

@pd_router.get("/catalog/{item_id}/price-history")
async def catalog_price_history(item_id: str, request: Request):
    user = await get_current_user(request)
    await get_catalog_item(item_id, request)  # tenant check
    history = await db.pd_catalog_price_history.find(
        {"catalog_item_id": item_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return history


# ============ 2) PESQUISA INTERNA (INTERNAL RESEARCH) ============

@pd_router.post("/requests/internal-research")
async def create_internal_research(data: InternalResearchCreate, request: Request):
    """Cria um desenvolvimento iniciado pelo lab (sem cliente / sem CRM)"""
    user = await get_current_user(request)
    req_id = new_id()

    # Monta briefing
    briefing_parts = []
    if data.objectives:
        briefing_parts.append(f"Objetivo da Pesquisa: {data.objectives}")
    if data.description:
        briefing_parts.append(f"Descrição: {data.description}")
    if data.references:
        briefing_parts.append(f"Referências: {data.references}")
    description = "\n".join(briefing_parts) if briefing_parts else (data.description or "")

    pd_request = {
        "id": req_id,
        "tenant_id": user["tenant_id"],
        "client_card_id": None,
        "client_name": "— Pesquisa Interna —",
        "project_name": data.project_name,
        "request_type": "Pesquisa Interna",
        "category": data.category or "",
        "description": description,
        "references": data.references or "",
        "restrictions": "",
        "volume": "",
        "packaging": "",
        "priority": data.priority or "Normal",
        "deadline": data.deadline,
        "status": "IN_PROGRESS",  # start directly as in-progress
        "is_internal_research": True,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.pd_requests.insert_one(pd_request)
    pd_request.pop("_id", None)

    # Status history
    await db.pd_request_status_history.insert_one({
        "id": new_id(),
        "pd_request_id": req_id,
        "from_status": None,
        "to_status": "OPEN",
        "changed_by": user["id"],
        "changed_by_name": user["name"],
        "comment": "Pesquisa Interna iniciada pelo lab",
        "created_at": now_iso(),
    })
    await db.pd_request_status_history.insert_one({
        "id": new_id(),
        "pd_request_id": req_id,
        "from_status": "OPEN",
        "to_status": "IN_PROGRESS",
        "changed_by": user["id"],
        "changed_by_name": user["name"],
        "comment": "Auto-iniciado como Pesquisa Interna",
        "created_at": now_iso(),
    })

    # Auto-create development
    dev_id = new_id()
    await db.pd_developments.insert_one({
        "id": dev_id,
        "pd_request_id": req_id,
        "tenant_id": user["tenant_id"],
        "assigned_to": user["id"],
        "assigned_to_name": user["name"],
        "lab_responsible": user["name"],
        "current_version": 0,
        "status": "active",
        "started_at": now_iso(),
        "completed_at": None,
        "is_internal_research": True,
    })

    # Auto-create pd_card so it shows on Pipeline P&D kanban
    card_id = new_id()
    # Generate PI-XXX number
    existing_pi = await db.pd_cards.count_documents({
        "tenant_id": user["tenant_id"],
        "numero_completo": {"$regex": "^PI-"}
    })
    numero = f"PI-{(existing_pi + 1):03d}"
    await db.pd_cards.insert_one({
        "id": card_id,
        "tenant_id": user["tenant_id"],
        "tipo": "pesquisa_interna",
        "numero_completo": numero,
        "produto": data.project_name,
        "cliente": "— Pesquisa Interna —",
        "cliente_id": None,
        "descricao_aplicacao": data.objectives or data.description or "",
        "briefing_base": data.description or "",
        "observacoes_especificas": data.references or "",
        "responsavel_pd": user["name"],
        "data_solicitacao": now_iso(),
        "prazo_prometido": data.deadline,
        "status_pd": "em_desenvolvimento",  # skip "solicitado", start in dev
        "amostra_id": None,
        "amostra_variacao_id": None,
        "pd_request_id": req_id,  # NEW: link to pd_request for navigation
        "is_internal_research": True,
        "historico_movimentacoes": [{
            "de": "",
            "para": "em_desenvolvimento",
            "data": now_iso(),
            "usuario": user["name"],
            "usuario_id": user["id"],
            "observacao": "Pesquisa Interna iniciada"
        }],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    # Also link pd_request with pd_card_id for reverse navigation
    await db.pd_requests.update_one(
        {"id": req_id},
        {"$set": {"pd_card_id": card_id}}
    )

    pd_request["pd_card_id"] = card_id
    return pd_request


# ============ 3) ESTOQUE DO LAB (STOCK) ============

VALID_STOCK_CATEGORIES = ["mp", "insumo", "amostra_acabada"]

@pd_router.post("/stock")
async def create_stock_item(data: StockItemCreate, request: Request):
    user = await get_current_user(request)
    if data.categoria not in VALID_STOCK_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Categoria inválida. Use: {VALID_STOCK_CATEGORIES}")

    # R05: auto-gerar código interno se vazio
    codigo = (data.codigo_interno or "").strip()
    if not codigo:
        if data.fragrancia_id:
            # R09: usar o FR-NNNNN do cadastro de fragrâncias
            fr_doc = await db.fragrancias.find_one(
                {"tenant_id": user["tenant_id"], "codigo_interno": data.fragrancia_id.upper()},
                {"codigo_interno": 1},
            )
            codigo = fr_doc["codigo_interno"] if fr_doc else await _next_lab_seq(user["tenant_id"], data.categoria)
        else:
            codigo = await _next_lab_seq(user["tenant_id"], data.categoria)

    item_id = new_id()
    item = {
        "id": item_id,
        "tenant_id": user["tenant_id"],
        "categoria": data.categoria,
        "nome": data.nome.strip(),
        "codigo_interno": codigo,
        "fragrancia_id": data.fragrancia_id or None,
        "unidade_medida": data.unidade_medida or "kg",
        "quantidade_atual": float(data.quantidade_atual or 0),
        "quantidade_minima": float(data.quantidade_minima or 0),
        "lote": (data.lote or "").strip(),
        "validade": data.validade,
        "localizacao": (data.localizacao or "").strip(),
        "custo_unitario": float(data.custo_unitario or 0),
        "fornecedor": (data.fornecedor or "").strip(),
        "observacoes": (data.observacoes or "").strip(),
        "catalog_id": data.catalog_id,
        "formula_ref": (data.formula_ref or "").strip(),
        "fragrancia_percentual": data.fragrancia_percentual,
        "linked_pd_request_id": data.linked_pd_request_id,
        "linked_formula_id": data.linked_formula_id,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.pd_stock_items.insert_one(item)
    item.pop("_id", None)

    # Initial movement (entrada) if quantity > 0
    if item["quantidade_atual"] > 0:
        await db.pd_stock_movements.insert_one({
            "id": new_id(),
            "tenant_id": user["tenant_id"],
            "stock_item_id": item_id,
            "tipo": "entrada",
            "quantidade": item["quantidade_atual"],
            "quantidade_antes": 0.0,
            "quantidade_depois": item["quantidade_atual"],
            "motivo": "Estoque inicial",
            "lote": item.get("lote") or None,
            "user_id": user["id"],
            "user_name": user["name"],
            "created_at": now_iso(),
        })

    return item

@pd_router.get("/stock")
async def list_stock(request: Request, categoria: Optional[str] = None, q: Optional[str] = None, low_stock: bool = False):
    user = await get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if categoria:
        query["categoria"] = categoria
    if q:
        query["$or"] = [
            {"nome": {"$regex": q, "$options": "i"}},
            {"codigo_interno": {"$regex": q, "$options": "i"}},
            {"formula_ref": {"$regex": q, "$options": "i"}},
        ]
    items = await db.pd_stock_items.find(query, {"_id": 0}).sort("nome", 1).to_list(2000)
    if low_stock:
        items = [it for it in items if it.get("quantidade_atual", 0) <= it.get("quantidade_minima", 0) and it.get("quantidade_minima", 0) > 0]
    return items

@pd_router.get("/stock/alerts")
async def stock_alerts(request: Request):
    """Items below minimum stock or expiring soon"""
    user = await get_current_user(request)
    items = await db.pd_stock_items.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).to_list(5000)
    low_stock = []
    expiring = []
    now_dt = datetime.now(timezone.utc)
    soon = now_dt + timedelta(days=30)
    for it in items:
        qa = it.get("quantidade_atual", 0) or 0
        qm = it.get("quantidade_minima", 0) or 0
        if qm > 0 and qa <= qm:
            low_stock.append(it)
        val = it.get("validade")
        if val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00")) if isinstance(val, str) else val
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= soon:
                    expiring.append(it)
            except Exception:
                pass
    return {"low_stock": low_stock, "expiring": expiring}

_LAB_SEQ_MAP = {
    "mp":              ("lab_mp_seq",  "MP"),
    "insumo":          ("lab_in_seq",  "IN"),
    "amostra_acabada": ("lab_am_seq",  "AM"),
}

async def _next_lab_seq(tenant_id: str, categoria: str) -> str:
    """R05: Gera código interno automático para Estoque Lab. MP-NNNNN / IN-NNNNN / AM-NNNNN."""
    from workflow_engine import next_sequence
    seq_key, prefix = _LAB_SEQ_MAP.get(categoria, ("lab_xx_seq", "XX"))
    seq = await next_sequence(tenant_id, seq_key, start=0)
    return f"{prefix}-{str(seq).zfill(5)}"


@pd_router.get("/stock/movements")
async def list_all_lab_movements(
    request: Request,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    limit: int = 500,
):
    """R06: Movimentações agregadas do Estoque Lab (para relatório)."""
    user = await get_current_user(request)
    t_id = user["tenant_id"]

    # Busca itens para filtrar por categoria e enriquecer movimentos
    items_cursor = db.pd_stock_items.find({"tenant_id": t_id}, {"_id": 0})
    items_list = await items_cursor.to_list(10000)
    items_map = {i["id"]: i for i in items_list}

    if categoria:
        valid_ids = {i["id"] for i in items_list if i.get("categoria") == categoria}
    else:
        valid_ids = set(items_map.keys())

    query: dict = {"tenant_id": t_id}
    if valid_ids:
        query["stock_item_id"] = {"$in": list(valid_ids)}
    else:
        return {"movimentos": [], "kpis": {"entradas": 0, "saidas": 0, "saldo": 0, "itens_abaixo_minimo": 0}}

    if tipo:
        query["tipo"] = tipo
    if data_inicio or data_fim:
        dt: dict = {}
        if data_inicio:
            dt["$gte"] = data_inicio
        if data_fim:
            dt["$lte"] = data_fim + "T23:59:59"
        query["created_at"] = dt

    movs = await db.pd_stock_movements.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)

    # Enriquecer com nome/categoria do item
    for m in movs:
        item = items_map.get(m.get("stock_item_id"), {})
        m["item_nome"] = item.get("nome", "")
        m["item_categoria"] = item.get("categoria", "")
        m["item_codigo"] = item.get("codigo_interno", "")
        m["deposito"] = "lab"

    total_entradas = sum(m["quantidade"] for m in movs if m.get("tipo") == "entrada")
    total_saidas = sum(m["quantidade"] for m in movs if m.get("tipo") == "saida")
    itens_abaixo = sum(
        1 for i in items_list
        if i.get("quantidade_minima", 0) > 0 and i.get("quantidade_atual", 0) <= i.get("quantidade_minima", 0)
    )

    return {
        "movimentos": movs,
        "kpis": {
            "entradas": round(total_entradas, 3),
            "saidas": round(total_saidas, 3),
            "saldo": round(total_entradas - total_saidas, 3),
            "itens_abaixo_minimo": itens_abaixo,
        },
    }


@pd_router.get("/stock/{item_id}")
async def get_stock_item(item_id: str, request: Request):
    user = await get_current_user(request)
    item = await db.pd_stock_items.find_one({"id": item_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item de estoque não encontrado")
    return item

@pd_router.put("/stock/{item_id}")
async def update_stock_item(item_id: str, data: StockItemUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_stock_items.find_one({"id": item_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    update_fields["updated_at"] = now_iso()
    await db.pd_stock_items.update_one({"id": item_id}, {"$set": update_fields})
    item = await db.pd_stock_items.find_one({"id": item_id}, {"_id": 0})
    return item

@pd_router.delete("/stock/{item_id}")
async def delete_stock_item(item_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.pd_stock_items.delete_one({"id": item_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    await db.pd_stock_movements.delete_many({"stock_item_id": item_id})
    return {"message": "Item removido"}

@pd_router.post("/stock/{item_id}/movements")
async def create_stock_movement(item_id: str, data: StockMovementCreate, request: Request):
    user = await get_current_user(request)
    item = await db.pd_stock_items.find_one({"id": item_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    if data.tipo not in ["entrada", "saida", "ajuste"]:
        raise HTTPException(status_code=400, detail="Tipo deve ser entrada, saida ou ajuste")
    if data.quantidade is None or data.quantidade < 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser positiva")

    current = float(item.get("quantidade_atual", 0) or 0)
    qty = float(data.quantidade)

    if data.tipo == "entrada":
        new_qty = current + qty
    elif data.tipo == "saida":
        if qty > current:
            raise HTTPException(status_code=400, detail=f"Saída de {qty} maior que estoque atual ({current})")
        new_qty = current - qty
    else:  # ajuste: set absolute qty
        new_qty = qty

    move_id = new_id()
    movement = {
        "id": move_id,
        "tenant_id": user["tenant_id"],
        "stock_item_id": item_id,
        "tipo": data.tipo,
        "quantidade": qty,
        "quantidade_antes": current,
        "quantidade_depois": new_qty,
        "motivo": data.motivo or "",
        "lote": data.lote or item.get("lote") or None,
        "linked_dev_id": data.linked_dev_id,
        "linked_pd_request_id": data.linked_pd_request_id,
        "user_id": user["id"],
        "user_name": user["name"],
        "created_at": now_iso(),
    }
    await db.pd_stock_movements.insert_one(movement)
    movement.pop("_id", None)

    await db.pd_stock_items.update_one(
        {"id": item_id},
        {"$set": {"quantidade_atual": new_qty, "updated_at": now_iso()}}
    )

    return movement

@pd_router.get("/stock/{item_id}/movements")
async def list_stock_movements(item_id: str, request: Request):
    user = await get_current_user(request)
    await get_stock_item(item_id, request)
    movements = await db.pd_stock_movements.find(
        {"stock_item_id": item_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return movements


# ============ 4) ATUALIZAÇÕES DA AMOSTRA (UPDATES + PENDING) ============

@pd_router.post("/requests/{req_id}/updates")
async def create_update(req_id: str, data: UpdateCreate, request: Request):
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    up_id = new_id()
    upd = {
        "id": up_id,
        "pd_request_id": req_id,
        "tenant_id": user["tenant_id"],
        "tipo": data.tipo or "observacao",
        "mensagem": data.mensagem.strip(),
        "visivel_comercial": bool(data.visivel_comercial),
        "item_solicitado": (data.item_solicitado or "").strip() or None,
        "fornecedor": (data.fornecedor or "").strip() or None,
        "previsao_entrega": data.previsao_entrega or None,
        "recebido": False,
        "recebido_em": None,
        "user_id": user["id"],
        "user_name": user["name"],
        "user_role": user.get("role", ""),
        "created_at": now_iso(),
    }
    await db.pd_updates.insert_one(upd)
    upd.pop("_id", None)
    return upd

@pd_router.get("/requests/{req_id}/updates")
async def list_updates(req_id: str, request: Request):
    user = await get_current_user(request)
    updates = await db.pd_updates.find(
        {"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return updates

@pd_router.delete("/updates/{up_id}")
async def delete_update(up_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.pd_updates.delete_one({"id": up_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Atualização não encontrada")
    return {"message": "Atualização removida"}

# Pending items (aguardando fragrância/MP/insumo etc)

@pd_router.post("/requests/{req_id}/pending")
async def create_pending(req_id: str, data: PendingItemCreate, request: Request):
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    p_id = new_id()
    pending = {
        "id": p_id,
        "pd_request_id": req_id,
        "tenant_id": user["tenant_id"],
        "tipo": data.tipo,
        "descricao": data.descricao.strip(),
        "data_solicitacao": now_iso(),
        "data_prevista": data.data_prevista,
        "data_recebido": None,
        "fornecedor": (data.fornecedor or "").strip(),
        "observacoes": (data.observacoes or "").strip(),
        "status": "pendente",  # pendente, recebido, atrasado, cancelado
        "user_id": user["id"],
        "user_name": user["name"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.pd_pending_items.insert_one(pending)
    pending.pop("_id", None)

    # Also log as update (visible to commercial)
    await db.pd_updates.insert_one({
        "id": new_id(),
        "pd_request_id": req_id,
        "tenant_id": user["tenant_id"],
        "tipo": "pendencia_criada",
        "mensagem": f"Solicitado(a) {data.tipo}: {data.descricao}" + (f" — previsão {data.data_prevista}" if data.data_prevista else ""),
        "visivel_comercial": True,
        "user_id": user["id"],
        "user_name": user["name"],
        "user_role": user.get("role", ""),
        "pending_item_id": p_id,
        "created_at": now_iso(),
    })
    return pending

@pd_router.get("/requests/{req_id}/pending")
async def list_pending(req_id: str, request: Request, status: Optional[str] = None):
    user = await get_current_user(request)
    query = {"pd_request_id": req_id, "tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    items = await db.pd_pending_items.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Calculate if atrasado
    now_dt = datetime.now(timezone.utc)
    for it in items:
        if it["status"] == "pendente" and it.get("data_prevista"):
            try:
                dp = datetime.fromisoformat(it["data_prevista"].replace("Z", "+00:00")) if isinstance(it["data_prevista"], str) else it["data_prevista"]
                if dp.tzinfo is None:
                    dp = dp.replace(tzinfo=timezone.utc)
                if dp < now_dt:
                    it["status_calc"] = "atrasado"
                else:
                    it["status_calc"] = "pendente"
            except Exception:
                it["status_calc"] = "pendente"
        else:
            it["status_calc"] = it["status"]
    return items

@pd_router.put("/pending/{p_id}")
async def update_pending(p_id: str, data: PendingItemUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.pd_pending_items.find_one({"id": p_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Pendência não encontrada")
    update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    # Mark recebido date
    if update_fields.get("status") == "recebido" and existing.get("status") != "recebido":
        update_fields["data_recebido"] = now_iso()
        # Log as update
        await db.pd_updates.insert_one({
            "id": new_id(),
            "pd_request_id": existing["pd_request_id"],
            "tenant_id": user["tenant_id"],
            "tipo": "pendencia_resolvida",
            "mensagem": f"Recebido(a): {existing['descricao']}",
            "visivel_comercial": True,
            "user_id": user["id"],
            "user_name": user["name"],
            "user_role": user.get("role", ""),
            "pending_item_id": p_id,
            "created_at": now_iso(),
        })
    update_fields["updated_at"] = now_iso()
    await db.pd_pending_items.update_one({"id": p_id}, {"$set": update_fields})
    it = await db.pd_pending_items.find_one({"id": p_id}, {"_id": 0})
    return it

@pd_router.delete("/pending/{p_id}")
async def delete_pending(p_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.pd_pending_items.delete_one({"id": p_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pendência não encontrada")
    return {"message": "Pendência removida"}

# ------ CRM-facing view: aggregate pending + updates by pd_request ------

@pd_router.get("/requests/{req_id}/activity")
async def get_activity_for_crm(req_id: str, request: Request):
    """Endpoint que o CRM comercial usa para ver o que o lab está fazendo.
    Retorna updates visíveis + pendências."""
    user = await get_current_user(request)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    updates = await db.pd_updates.find(
        {"pd_request_id": req_id, "tenant_id": user["tenant_id"], "visivel_comercial": True}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    pending = await db.pd_pending_items.find(
        {"pd_request_id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    # Calculate atrasado
    now_dt = datetime.now(timezone.utc)
    for it in pending:
        if it["status"] == "pendente" and it.get("data_prevista"):
            try:
                dp = datetime.fromisoformat(it["data_prevista"].replace("Z", "+00:00")) if isinstance(it["data_prevista"], str) else it["data_prevista"]
                if dp.tzinfo is None:
                    dp = dp.replace(tzinfo=timezone.utc)
                it["status_calc"] = "atrasado" if dp < now_dt else "pendente"
            except Exception:
                it["status_calc"] = "pendente"
        else:
            it["status_calc"] = it["status"]
    return {"updates": updates, "pending": pending}


# ============ HELPER: list all internal research requests for Pipeline P&D view ============

@pd_router.get("/requests/internal-research/list")
async def list_internal_research(request: Request):
    user = await get_current_user(request)
    items = await db.pd_requests.find(
        {"tenant_id": user["tenant_id"], "is_internal_research": True}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return items



# =========================================================================
#  HOMOLOGAÇÕES — MPs e FORNECEDORES
# =========================================================================


# ----- HELPERS: Bloqueio de formulas com insumos nao homologados/suspensos ----

async def _evaluate_formula_homologacao(formula_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Inspeciona todos os itens de uma formula e classifica o status de homologacao
    de cada MP usada (via catalog -> homologacao_mps por nome+inci).
    Retorna estrutura: {ok: bool, blocked: [..], pending: [..], total_items: int, summary: str}
    """
    items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(2000)
    if not items:
        return {"ok": True, "blocked": [], "pending": [], "total_items": 0, "summary": "Formula sem itens"}

    catalog_ids = [it["catalog_id"] for it in items if it.get("catalog_id")]
    catalogs: Dict[str, Dict[str, Any]] = {}
    if catalog_ids:
        docs = await db.pd_catalog.find(
            {"tenant_id": tenant_id, "id": {"$in": catalog_ids}}, {"_id": 0}
        ).to_list(2000)
        catalogs = {d["id"]: d for d in docs if d.get("id")}

    mp_index: Dict[str, Dict[str, Any]] = {}
    mps = await db.homologacao_mps.find({"tenant_id": tenant_id}, {"_id": 0}).to_list(5000)
    for mp in mps:
        for key in (mp.get("nome", ""), mp.get("inci", ""), mp.get("codigo_interno", "")):
            normalized = (key or "").strip().lower()
            if normalized:
                mp_index.setdefault(normalized, mp)

    blocked: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []

    for item in items:
        ingredient = (item.get("ingredient_name") or "").strip()
        catalog = catalogs.get(item.get("catalog_id")) or {}
        candidate_keys = [
            (catalog.get("nome") or "").strip().lower(),
            (catalog.get("inci") or "").strip().lower(),
            ingredient.lower(),
        ]
        mp_doc = next((mp_index[k] for k in candidate_keys if k and k in mp_index), None)
        if not mp_doc:
            pending.append({
                "ingredient_name": ingredient or catalog.get("nome", ""),
                "reason": "MP nao cadastrada em Homologacoes",
                "status": "ausente",
            })
            continue
        status = mp_doc.get("status", "pendente")
        if status in MP_BLOCKED_STATUSES:
            blocked.append({
                "ingredient_name": ingredient or mp_doc.get("nome", ""),
                "mp_id": mp_doc.get("id"),
                "fornecedor_nome": mp_doc.get("fornecedor_nome", ""),
                "status": status,
                "parecer": mp_doc.get("parecer_homologacao", ""),
            })
        elif status not in MP_OK_STATUSES:
            pending.append({
                "ingredient_name": ingredient or mp_doc.get("nome", ""),
                "mp_id": mp_doc.get("id"),
                "fornecedor_nome": mp_doc.get("fornecedor_nome", ""),
                "status": status,
                "reason": "MP em avaliacao",
            })

    summary = f"{len(blocked)} bloqueadas, {len(pending)} pendentes, {len(items)} itens"
    return {
        "ok": len(blocked) == 0,
        "blocked": blocked,
        "pending": pending,
        "total_items": len(items),
        "summary": summary,
    }


async def assert_formula_homologacao_ok(formula_id: str, tenant_id: str, *, allow_pending: bool = True):
    """Raises 409 if formula has insumos reprovados/suspensos. Pending only blocks if allow_pending=False."""
    result = await _evaluate_formula_homologacao(formula_id, tenant_id)
    if result["blocked"]:
        names = ", ".join(item["ingredient_name"] for item in result["blocked"][:5])
        raise HTTPException(
            status_code=409,
            detail=f"Formula bloqueada: {len(result['blocked'])} insumo(s) reprovado(s)/suspenso(s) na Homologacao: {names}",
        )
    if not allow_pending and result["pending"]:
        names = ", ".join(item["ingredient_name"] for item in result["pending"][:5])
        raise HTTPException(
            status_code=409,
            detail=f"Formula bloqueada: {len(result['pending'])} insumo(s) sem homologacao concluida: {names}",
        )


async def assert_pd_card_ready_for_approval(card_id: str, tenant_id: str):
    """Antes de mover para aguardando_aprovacao/aprovado, validar todas as formulas ativas vinculadas."""
    card = await db.pd_cards.find_one({"id": card_id, "tenant_id": tenant_id}, {"_id": 0, "amostra_variacao_id": 1, "amostra_id": 1})
    if not card:
        return
    pd_request = await db.pd_requests.find_one(
        {"tenant_id": tenant_id, "amostra_id": card.get("amostra_id")},
        {"_id": 0, "id": 1},
    )
    if not pd_request:
        return
    # RN-PD-STAB: mesmo gate de D48h usado por transition_status e update_sample —
    # antes, mover o card pelo Kanban (drag-and-drop) pulava essa checagem inteira (B7).
    await assert_d48h_stability_ok(pd_request["id"], tenant_id)
    dev = await db.pd_developments.find_one(
        {"tenant_id": tenant_id, "pd_request_id": pd_request["id"]},
        {"_id": 0, "id": 1},
    )
    if not dev:
        return
    latest = await db.pd_formulas.find_one(
        {"development_id": dev["id"]},
        {"_id": 0, "id": 1},
        sort=[("version", -1)],
    )
    if not latest:
        return
    await assert_formula_homologacao_ok(latest["id"], tenant_id, allow_pending=True)


@pd_router.get("/formulas/{formula_id}/homologacao-status")
async def formula_homologacao_status(formula_id: str, request: Request):
    """Retorna o status de homologacao agregado para uma formula (bloqueada/pending/ok)."""
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    return await _evaluate_formula_homologacao(formula_id, user["tenant_id"])


# =========================================================================
#  HOMOLOGAÇÕES — MPs e FORNECEDORES (continued)
# =========================================================================

class FornecedorHomologacao(BaseModel):
    razao_social: str
    cnpj: str = ""
    nome_fantasia: str = ""
    contato_nome: str = ""
    contato_email: str = ""
    contato_telefone: str = ""
    endereco: str = ""
    categoria: str = ""  # MP_FORMULACAO, MP_ROTULO, MP_EMBALAGEM, SERVICO, etc
    observacoes: str = ""


class FornecedorUpdate(BaseModel):
    razao_social: Optional[str] = None
    cnpj: Optional[str] = None
    nome_fantasia: Optional[str] = None
    contato_nome: Optional[str] = None
    contato_email: Optional[str] = None
    contato_telefone: Optional[str] = None
    endereco: Optional[str] = None
    categoria: Optional[str] = None
    observacoes: Optional[str] = None


class MPHomologacao(BaseModel):
    nome: str
    codigo_interno: str = ""
    inci: str = ""
    tipo_mp: str  # FORMULACAO, ROTULO, EMBALAGEM
    fornecedor_id: Optional[str] = None
    fornecedor_nome: str = ""  # snapshot se fornecedor não está cadastrado ainda
    funcao: str = ""            # Ex: emulsificante, conservante, ativo
    custo_referencia: Optional[float] = None
    unidade: str = "kg"
    especificacoes_tecnicas: str = ""
    certificados: List[str] = []   # URLs/IDs de laudos/COAs
    msds_url: str = ""
    validade_laudo: Optional[str] = None
    observacoes: str = ""


class MPUpdate(BaseModel):
    nome: Optional[str] = None
    codigo_interno: Optional[str] = None
    inci: Optional[str] = None
    tipo_mp: Optional[str] = None
    fornecedor_id: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    funcao: Optional[str] = None
    custo_referencia: Optional[float] = None
    unidade: Optional[str] = None
    especificacoes_tecnicas: Optional[str] = None
    certificados: Optional[List[str]] = None
    msds_url: Optional[str] = None
    validade_laudo: Optional[str] = None
    observacoes: Optional[str] = None


class HomologarRequest(BaseModel):
    aprovado: bool
    parecer: str = ""


class SuspenderRequest(BaseModel):
    parecer: str = ""


def _serialize_doc(doc):
    if doc:
        doc.pop("_id", None)
    return doc


def _homologacao_status_for_compras(status: str) -> str:
    return {
        "pendente": "em_processo",
        "homologado": "homologado",
        "homologada": "homologado",
        "rejeitado": "reprovado",
        "rejeitada": "reprovado",
        "suspenso": "suspenso",
        "suspensa": "suspenso",
    }.get((status or "").strip().lower(), "nao_iniciada")


def _pd_mp_tipo2(tipo_mp: str) -> str:
    tipo = (tipo_mp or "").strip().upper()
    if tipo == "ROTULO":
        return "RT"
    if tipo == "EMBALAGEM":
        return "EP"
    return "MP"


def _pd_mp_categoria_compras(mp: Dict[str, Any]) -> str:
    tipo = (mp.get("tipo_mp") or "").strip().upper()
    funcao = (mp.get("funcao") or "").strip().lower()
    nome = (mp.get("nome") or "").strip().lower()
    if "fragr" in funcao or "fragr" in nome:
        return "fragrancia"
    if tipo in {"ROTULO", "EMBALAGEM"}:
        return "embalagem"
    return "mp"


async def _next_pd_material_code(tenant_id: str, tipo2: str) -> str:
    seq = await next_sequence(tenant_id, f"mat_{tipo2}", start=0)
    return f"{tipo2}-{seq:05d}"


async def _upsert_compras_fornecedor_from_homologacao(tenant_id: str, supplier: Dict[str, Any], user: Optional[dict] = None) -> Optional[dict]:
    if not supplier or not getattr(db, "compras_fornecedores", None):
        return None

    now = now_iso()
    cnpj_norm = supplier.get("cnpj_normalized") or normalize_cnpj(supplier.get("cnpj", ""))
    lookup_or: List[Dict[str, Any]] = [
        {"origem_homologacao_id": supplier.get("id")},
        {"homologacao.origem_homologacao_id": supplier.get("id")},
    ]
    if cnpj_norm:
        lookup_or.extend([
            {"cnpj_normalizado": cnpj_norm},
            {"cnpj_normalized": cnpj_norm},
        ])
    if supplier.get("razao_social"):
        lookup_or.append({"razao_social": supplier.get("razao_social")})

    existing = await db.compras_fornecedores.find_one(
        {"tenant_id": tenant_id, "$or": lookup_or},
        {"_id": 0},
    )
    status_homologacao = _homologacao_status_for_compras(supplier.get("status"))
    categorias = [supplier.get("categoria")] if supplier.get("categoria") else []
    contato = {
        "id": (existing.get("contatos") or [{}])[0].get("id") if existing else new_id(),
        "nome": supplier.get("contato_nome", ""),
        "email": supplier.get("contato_email", ""),
        "telefone": supplier.get("contato_telefone", ""),
        "whatsapp": supplier.get("contato_telefone", ""),
    }
    homologacao = {
        "status": status_homologacao,
        "data_homologacao": supplier.get("data_homologacao"),
        "proxima_reavaliacao": None,
        "documentos_file_ids": [],
        "historico_rncs_count": 0,
        "historico_rncs_criticas_12m": 0,
        "origem_modulo": "pd_homologacao",
        "origem_homologacao_id": supplier.get("id"),
        "parecer": supplier.get("parecer_homologacao", ""),
    }
    base_updates = {
        "razao_social": supplier.get("razao_social", ""),
        "nome_fantasia": supplier.get("nome_fantasia", ""),
        "cnpj": supplier.get("cnpj", ""),
        "cnpj_normalizado": cnpj_norm,
        "cnpj_normalized": cnpj_norm,
        "endereco": {"logradouro": supplier.get("endereco", "")} if supplier.get("endereco") else {},
        "contatos": [contato] if any(contato.get(k) for k in ("nome", "email", "telefone")) else [],
        "categorias": categorias,
        "homologacao": homologacao,
        "status_cadastro": "ativo" if status_homologacao != "suspenso" else "inativo",
        "origem": "pd_homologacao",
        "origem_homologacao_id": supplier.get("id"),
        "updated_at": now,
    }

    if existing:
        await db.compras_fornecedores.update_one(
            {"tenant_id": tenant_id, "id": existing["id"]},
            {
                "$set": base_updates,
                "$push": {
                    "log_auditoria": {
                        "acao": "sincronizado_pd_homologacao",
                        "por_id": (user or {}).get("id", ""),
                        "por_nome": (user or {}).get("name", ""),
                        "em": now,
                    }
                },
            },
        )
        supplier_id = existing["id"]
    else:
        supplier_id = new_id()
        doc = {
            "id": supplier_id,
            "tenant_id": tenant_id,
            "codigo_interno": f"FOR-{(await next_sequence(tenant_id, 'compras_fornecedores', start=0)):05d}",
            "ie": "",
            "im": "",
            **base_updates,
            "created_at": now,
            "log_auditoria": [{
                "acao": "criado_por_pd_homologacao",
                "por_id": (user or {}).get("id", ""),
                "por_nome": (user or {}).get("name", ""),
                "em": now,
            }],
        }
        await db.compras_fornecedores.insert_one(doc)

    synced = await db.compras_fornecedores.find_one({"tenant_id": tenant_id, "id": supplier_id}, {"_id": 0})
    await db.homologacao_fornecedores.update_one(
        {"tenant_id": tenant_id, "id": supplier.get("id")},
        {"$set": {
            "compras_fornecedor_id": supplier_id,
            "compras_codigo_interno": (synced or {}).get("codigo_interno", ""),
            "updated_at": now,
        }},
    )
    return synced


async def _resolve_compras_fornecedor_for_mp(tenant_id: str, mp: Dict[str, Any], user: Optional[dict] = None) -> tuple[str, str]:
    if mp.get("fornecedor_id"):
        fornecedor_pd = await db.homologacao_fornecedores.find_one(
            {"tenant_id": tenant_id, "id": mp["fornecedor_id"]},
            {"_id": 0},
        )
        if fornecedor_pd:
            synced = await _upsert_compras_fornecedor_from_homologacao(tenant_id, fornecedor_pd, user)
            if synced:
                return synced.get("id", ""), synced.get("razao_social") or synced.get("nome_fantasia") or mp.get("fornecedor_nome", "")

    if mp.get("fornecedor_nome") and getattr(db, "compras_fornecedores", None):
        fornecedor = await db.compras_fornecedores.find_one(
            {
                "tenant_id": tenant_id,
                "$or": [
                    {"razao_social": mp.get("fornecedor_nome")},
                    {"nome_fantasia": mp.get("fornecedor_nome")},
                ],
            },
            {"_id": 0},
        )
        if fornecedor:
            return fornecedor.get("id", ""), fornecedor.get("razao_social") or fornecedor.get("nome_fantasia") or mp.get("fornecedor_nome", "")
    return "", mp.get("fornecedor_nome", "")


async def _upsert_material_from_homologacao_mp(tenant_id: str, mp: Dict[str, Any], user: Optional[dict] = None) -> Optional[dict]:
    if not mp:
        return None

    now = now_iso()
    tipo2 = _pd_mp_tipo2(mp.get("tipo_mp", ""))
    codigo = (mp.get("codigo_interno") or "").strip()
    if not codigo:
        codigo = await _next_pd_material_code(tenant_id, tipo2)
        await db.homologacao_mps.update_one(
            {"tenant_id": tenant_id, "id": mp.get("id")},
            {"$set": {"codigo_interno": codigo, "updated_at": now}},
        )
        mp = {**mp, "codigo_interno": codigo}

    fornecedor_compras_id, fornecedor_nome = await _resolve_compras_fornecedor_for_mp(tenant_id, mp, user)
    status_homologacao = _homologacao_status_for_compras(mp.get("status"))
    material_status = "bloqueado" if status_homologacao in {"reprovado", "suspenso"} else "ativo"
    fornecedor_entry = None
    if fornecedor_compras_id or fornecedor_nome:
        fornecedor_entry = {
            "fornecedor_id": fornecedor_compras_id,
            "fornecedor_nome": fornecedor_nome,
            "codigo_fornecedor": "",
            "status_homologacao": status_homologacao,
            "preco_por_unidade": float(mp.get("custo_referencia") or 0),
            "moeda": "BRL",
            "adicionado_em": now,
        }

    material_query = {
        "tenant_id": tenant_id,
        "$or": [
            {"homologacao_mp_id": mp.get("id")},
            {"origem_homologacao_id": mp.get("id")},
            {"codigo_interno": codigo},
            {"nome": mp.get("nome", "")},
        ],
    }
    material = await db.materiais.find_one(material_query, {"_id": 0}) if getattr(db, "materiais", None) else None
    fornecedores = list((material or {}).get("fornecedores") or [])
    if fornecedor_entry:
        fornecedores = [
            entry for entry in fornecedores
            if (entry.get("fornecedor_id") or entry.get("fornecedor_nome")) != (fornecedor_entry.get("fornecedor_id") or fornecedor_entry.get("fornecedor_nome"))
        ]
        fornecedores.append(fornecedor_entry)

    material_updates = {
        "codigo_interno": codigo,
        "tipo2": tipo2,
        "subtipo": mp.get("funcao", "") or mp.get("tipo_mp", ""),
        "nome": mp.get("nome", ""),
        "descricao": mp.get("observacoes", "") or mp.get("especificacoes_tecnicas", ""),
        "unidade_estoque": mp.get("unidade", "kg"),
        "unidade_compra": mp.get("unidade", "kg"),
        "fator_conversao": 1.0,
        "fornecedores": fornecedores,
        "atributos": {
            "inci": mp.get("inci", ""),
            "funcao": mp.get("funcao", ""),
            "tipo_mp": mp.get("tipo_mp", ""),
            "certificados": mp.get("certificados") or [],
            "msds_url": mp.get("msds_url", ""),
            "validade_laudo": mp.get("validade_laudo"),
        },
        "status": material_status,
        "homologacao_mp_id": mp.get("id"),
        "origem": "pd_homologacao",
        "origem_homologacao_id": mp.get("id"),
        "updated_at": now,
    }

    material_id = (material or {}).get("id")
    if getattr(db, "materiais", None):
        if material:
            await db.materiais.update_one({"tenant_id": tenant_id, "id": material_id}, {"$set": material_updates})
        else:
            material_id = new_id()
            await db.materiais.insert_one({
                "id": material_id,
                "tenant_id": tenant_id,
                "categoria_mp_id": "",
                "categoria_mp_codigo": "",
                "categoria_mp_nome": "",
                "created_by": (user or {}).get("id", ""),
                "created_by_name": (user or {}).get("name", ""),
                "created_at": now,
                **material_updates,
            })

    compras_item = None
    compras_item_id = ""
    if getattr(db, "compras_itens", None):
        compras_categoria = _pd_mp_categoria_compras(mp)
        item_query = {
            "tenant_id": tenant_id,
            "$or": [
                {"homologacao_mp_id": mp.get("id")},
                {"codigo_interno": codigo},
                {"descricao": mp.get("nome", "")},
            ],
        }
        compras_item = await db.compras_itens.find_one(item_query, {"_id": 0})
        homologados = set((compras_item or {}).get("fornecedores_homologados") or [])
        if fornecedor_compras_id:
            if status_homologacao == "homologado":
                homologados.add(fornecedor_compras_id)
            else:
                homologados.discard(fornecedor_compras_id)
        item_updates = {
            "codigo_interno": codigo,
            "descricao": mp.get("nome", ""),
            "categoria": compras_categoria,
            "sub_categoria": mp.get("funcao", "") or mp.get("tipo_mp", ""),
            "unidade_compra": mp.get("unidade", "kg"),
            "fator_conversao_producao": 1.0,
            "estoque_minimo": (compras_item or {}).get("estoque_minimo"),
            "estoque_seguranca": (compras_item or {}).get("estoque_seguranca", 0.0),
            "lead_time_dias": (compras_item or {}).get("lead_time_dias", 0),
            "requer_homologacao_cq": True,
            "fornecedores_homologados": sorted(homologados),
            "homologacao_mp_id": mp.get("id"),
            "material_id": material_id or "",
            "pd_catalog_id": (compras_item or {}).get("pd_catalog_id", ""),
            "origem": "pd_homologacao",
            "updated_at": now,
        }
        if compras_item:
            compras_item_id = compras_item.get("id", "")
            await db.compras_itens.update_one({"tenant_id": tenant_id, "id": compras_item_id}, {"$set": item_updates})
        else:
            compras_item_id = new_id()
            await db.compras_itens.insert_one({
                "id": compras_item_id,
                "tenant_id": tenant_id,
                "ultimo_preco_pago": None,
                "created_at": now,
                **item_updates,
            })

    if getattr(db, "pd_catalog", None):
        catalog_query = {
            "tenant_id": tenant_id,
            "$or": [
                {"codigo_interno": codigo},
                {"nome": mp.get("nome", "")},
                {"inci": mp.get("inci", "")},
            ],
        }
        catalog_updates = {
            "nome": mp.get("nome", ""),
            "inci": mp.get("inci", ""),
            "codigo_interno": codigo,
            "fornecedor": fornecedor_nome,
            "preco_rs_kg": float(mp.get("custo_referencia") or 0),
            "moeda": "BRL",
            "unidade": mp.get("unidade", "kg"),
            "categoria": mp.get("funcao", "") or mp.get("tipo_mp", ""),
            "homologacao": {
                "mp_id": mp.get("id"),
                "status": mp.get("status"),
                "fornecedor_id": mp.get("fornecedor_id"),
                "fornecedor_compras_id": fornecedor_compras_id,
                "fornecedor_nome": fornecedor_nome,
                "parecer": mp.get("parecer_homologacao", ""),
                "data_homologacao": mp.get("data_homologacao"),
            },
            "compras_item_id": compras_item_id,
            "material_id": material_id or "",
            "ultima_atualizacao": now,
            "atualizado_por": (user or {}).get("name", ""),
            "atualizado_por_id": (user or {}).get("id", ""),
        }
        catalog_existing = await db.pd_catalog.find_one(catalog_query, {"_id": 0})
        if catalog_existing:
            await db.pd_catalog.update_one({"tenant_id": tenant_id, "id": catalog_existing["id"]}, {"$set": catalog_updates})
            await db.compras_itens.update_one(
                {"tenant_id": tenant_id, "id": compras_item_id},
                {"$set": {"pd_catalog_id": catalog_existing["id"]}},
            ) if compras_item_id and getattr(db, "compras_itens", None) else None
        else:
            catalog_id = new_id()
            await db.pd_catalog.insert_one({
                "id": catalog_id,
                "tenant_id": tenant_id,
                "observacoes": mp.get("observacoes", ""),
                "created_at": now,
                **catalog_updates,
            })
            if compras_item_id and getattr(db, "compras_itens", None):
                await db.compras_itens.update_one(
                    {"tenant_id": tenant_id, "id": compras_item_id},
                    {"$set": {"pd_catalog_id": catalog_id}},
                )

    await db.homologacao_mps.update_one(
        {"tenant_id": tenant_id, "id": mp.get("id")},
        {"$set": {
            "codigo_interno": codigo,
            "compras_item_id": compras_item_id,
            "material_id": material_id or "",
            "compras_fornecedor_id": fornecedor_compras_id,
            "updated_at": now,
        }},
    )
    return await db.homologacao_mps.find_one({"tenant_id": tenant_id, "id": mp.get("id")}, {"_id": 0})


# ----- FORNECEDORES -----

@pd_router.post("/homologacao/fornecedores")
async def create_fornecedor(data: FornecedorHomologacao, request: Request):
    user = await get_current_user(request)
    require_roles(user, HOMOLOGACAO_WRITE)
    now = now_iso()
    f_id = new_id()
    payload = _validate_supplier_payload(data.model_dump())
    doc = {
        "id": f_id,
        "tenant_id": user["tenant_id"],
        **payload,
        "status": "pendente",  # pendente | homologado | rejeitado
        "parecer_homologacao": "",
        "homologado_por": "",
        "homologado_por_id": "",
        "data_homologacao": None,
        "historico": [{
            "evento": "criado",
            "por": user["name"],
            "por_id": user["id"],
            "data": now,
        }],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.homologacao_fornecedores.insert_one(doc)
    await _upsert_compras_fornecedor_from_homologacao(user["tenant_id"], doc, user)
    return await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@pd_router.get("/homologacao/fornecedores")
async def list_fornecedores(request: Request, status: Optional[str] = None, search: Optional[str] = None):
    user = await get_current_user(request)
    q = {"tenant_id": user["tenant_id"]}
    if status:
        q["status"] = status
    if search:
        q["$or"] = [
            {"razao_social": {"$regex": search, "$options": "i"}},
            {"nome_fantasia": {"$regex": search, "$options": "i"}},
            {"cnpj": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.homologacao_fornecedores.find(q, {"_id": 0}).sort("razao_social", 1).to_list(5000)
    return docs


@pd_router.get("/homologacao/fornecedores/{f_id}")
async def get_fornecedor(f_id: str, request: Request):
    user = await get_current_user(request)
    doc = await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    return doc


@pd_router.put("/homologacao/fornecedores/{f_id}")
async def update_fornecedor(f_id: str, data: FornecedorUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    payload = dict(existing)
    payload.update(fields)
    payload = _validate_supplier_payload(payload)
    for field in ("razao_social", "cnpj", "cnpj_normalized", "nome_fantasia", "contato_nome", "contato_email", "contato_telefone"):
        fields[field] = payload[field]
    fields["updated_at"] = now_iso()
    result = await db.homologacao_fornecedores.update_one(
        {"id": f_id, "tenant_id": user["tenant_id"]},
        {"$set": fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    updated = await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    await _upsert_compras_fornecedor_from_homologacao(user["tenant_id"], updated, user)
    return await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@pd_router.post("/homologacao/fornecedores/{f_id}/homologar")
async def homologar_fornecedor(f_id: str, data: HomologarRequest, request: Request):
    user = await get_current_user(request)
    require_roles(user, HOMOLOGACAO_APPROVE)
    now = now_iso()
    novo_status = "homologado" if data.aprovado else "rejeitado"
    update = {
        "status": novo_status,
        "parecer_homologacao": data.parecer,
        "homologado_por": user["name"],
        "homologado_por_id": user["id"],
        "data_homologacao": now,
        "updated_at": now,
    }
    evento = {
        "evento": "homologado" if data.aprovado else "rejeitado",
        "por": user["name"],
        "por_id": user["id"],
        "data": now,
        "parecer": data.parecer,
    }
    result = await db.homologacao_fornecedores.update_one(
        {"id": f_id, "tenant_id": user["tenant_id"]},
        {"$set": update, "$push": {"historico": evento}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
    updated = await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    await _upsert_compras_fornecedor_from_homologacao(user["tenant_id"], updated, user)
    return await db.homologacao_fornecedores.find_one({"id": f_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@pd_router.delete("/homologacao/fornecedores/{f_id}")
async def delete_fornecedor(f_id: str, request: Request):
    user = await get_current_user(request)
    # Bloquear se tem MP vinculada
    mp_count = await db.homologacao_mps.count_documents({"fornecedor_id": f_id, "tenant_id": user["tenant_id"]})
    if mp_count > 0:
        raise HTTPException(status_code=400, detail=f"Fornecedor tem {mp_count} MP(s) vinculada(s). Remova as MPs primeiro.")
    await db.homologacao_fornecedores.delete_one({"id": f_id, "tenant_id": user["tenant_id"]})
    return {"deleted": f_id}


# ----- MPs -----

@pd_router.post("/homologacao/mps")
async def create_mp(data: MPHomologacao, request: Request):
    user = await get_current_user(request)
    require_roles(user, HOMOLOGACAO_WRITE)
    if data.tipo_mp not in ["FORMULACAO", "ROTULO", "EMBALAGEM"]:
        raise HTTPException(status_code=400, detail="tipo_mp inválido (FORMULACAO|ROTULO|EMBALAGEM)")
    now = now_iso()
    mp_id = new_id()

    # Se fornecedor_id fornecido, buscar o nome
    fornecedor_nome = data.fornecedor_nome
    if data.fornecedor_id:
        forn = await db.homologacao_fornecedores.find_one(
            {"id": data.fornecedor_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "razao_social": 1, "nome_fantasia": 1}
        )
        if forn:
            fornecedor_nome = forn.get("nome_fantasia") or forn.get("razao_social") or fornecedor_nome

    doc = {
        "id": mp_id,
        "tenant_id": user["tenant_id"],
        **data.model_dump(),
        "fornecedor_nome": fornecedor_nome,
        "status": "pendente",  # pendente | homologada | rejeitada
        "parecer_homologacao": "",
        "homologado_por": "",
        "homologado_por_id": "",
        "data_homologacao": None,
        "historico": [{
            "evento": "criado",
            "por": user["name"],
            "por_id": user["id"],
            "data": now,
        }],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.homologacao_mps.insert_one(doc)
    await _upsert_material_from_homologacao_mp(user["tenant_id"], doc, user)
    return await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@pd_router.get("/homologacao/mps")
async def list_mps(
    request: Request,
    status: Optional[str] = None,
    tipo_mp: Optional[str] = None,
    fornecedor_id: Optional[str] = None,
    search: Optional[str] = None,
):
    user = await get_current_user(request)
    q = {"tenant_id": user["tenant_id"]}
    if status:
        q["status"] = status
    if tipo_mp:
        q["tipo_mp"] = tipo_mp
    if fornecedor_id:
        q["fornecedor_id"] = fornecedor_id
    if search:
        q["$or"] = [
            {"nome": {"$regex": search, "$options": "i"}},
            {"codigo_interno": {"$regex": search, "$options": "i"}},
            {"inci": {"$regex": search, "$options": "i"}},
            {"fornecedor_nome": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.homologacao_mps.find(q, {"_id": 0}).sort("nome", 1).to_list(5000)
    return docs


@pd_router.get("/homologacao/mps/{mp_id}")
async def get_mp(mp_id: str, request: Request):
    user = await get_current_user(request)
    doc = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="MP não encontrada")
    return doc


@pd_router.put("/homologacao/mps/{mp_id}")
async def update_mp(mp_id: str, data: MPUpdate, request: Request):
    user = await get_current_user(request)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    fields["updated_at"] = now_iso()
    result = await db.homologacao_mps.update_one(
        {"id": mp_id, "tenant_id": user["tenant_id"]},
        {"$set": fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="MP não encontrada")
    mp_doc = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    mp_doc = await _upsert_material_from_homologacao_mp(user["tenant_id"], mp_doc, user) or mp_doc
    catalog_docs = await db.pd_catalog.find(
        {
            "tenant_id": user["tenant_id"],
            "$or": [{"nome": mp_doc.get("nome", "")}, {"inci": mp_doc.get("inci", "")}],
        },
        {"_id": 0, "id": 1}
    ).to_list(100)
    if catalog_docs:
        await _auto_generate_documents_for_catalog_items(
            [doc["id"] for doc in catalog_docs if doc.get("id")],
            user,
            "homologacao_mp",
            ficha_changed_fields=["composicao_completa"],
            epa_changed_fields=["bom_bulk_formula", "informacoes_rotulo"],
            source_changes=[{
                "field": "mp_homologacao",
                "label": "Fornecedor homologado",
                "before": None,
                "after": {
                    "nome": mp_doc.get("nome"),
                    "fornecedor_nome": mp_doc.get("fornecedor_nome"),
                    "status": mp_doc.get("status"),
                },
            }],
        )
    return await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@pd_router.post("/homologacao/mps/{mp_id}/homologar")
async def homologar_mp(mp_id: str, data: HomologarRequest, request: Request):
    user = await get_current_user(request)
    require_roles(user, HOMOLOGACAO_APPROVE)
    now = now_iso()

    # Validar: MP só pode ser homologada se fornecedor vinculado está homologado
    mp = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not mp:
        raise HTTPException(status_code=404, detail="MP não encontrada")

    if data.aprovado and mp.get("fornecedor_id"):
        forn = await db.homologacao_fornecedores.find_one(
            {"id": mp["fornecedor_id"], "tenant_id": user["tenant_id"]}, {"_id": 0, "status": 1}
        )
        if forn and forn.get("status") != "homologado":
            raise HTTPException(
                status_code=400,
                detail="Fornecedor vinculado não está homologado. Homologue o fornecedor antes da MP."
            )

    novo_status = "homologada" if data.aprovado else "rejeitada"
    update = {
        "status": novo_status,
        "parecer_homologacao": data.parecer,
        "homologado_por": user["name"],
        "homologado_por_id": user["id"],
        "data_homologacao": now,
        "updated_at": now,
    }
    evento = {
        "evento": "homologada" if data.aprovado else "rejeitada",
        "por": user["name"],
        "por_id": user["id"],
        "data": now,
        "parecer": data.parecer,
    }
    await db.homologacao_mps.update_one(
        {"id": mp_id, "tenant_id": user["tenant_id"]},
        {"$set": update, "$push": {"historico": evento}}
    )
    updated_mp = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    catalog_query = {
        "tenant_id": user["tenant_id"],
        "$or": [
            {"nome": updated_mp.get("nome", "")},
            {"inci": updated_mp.get("inci", "")},
            {"codigo_interno": updated_mp.get("codigo_interno", "")},
        ],
    }
    catalog_updates = {
        "homologacao": {
            "mp_id": updated_mp.get("id"),
            "status": updated_mp.get("status"),
            "fornecedor_id": updated_mp.get("fornecedor_id"),
            "fornecedor_nome": updated_mp.get("fornecedor_nome", ""),
            "parecer": updated_mp.get("parecer_homologacao", ""),
            "data_homologacao": updated_mp.get("data_homologacao"),
        },
        "ultima_atualizacao": now,
        "atualizado_por": user["name"],
        "atualizado_por_id": user["id"],
    }
    if updated_mp.get("custo_referencia") is not None:
        catalog_updates["preco_rs_kg"] = float(updated_mp.get("custo_referencia") or 0)
        catalog_updates["moeda"] = "BRL"
    if updated_mp.get("fornecedor_nome"):
        catalog_updates["fornecedor"] = updated_mp.get("fornecedor_nome", "")
    if getattr(db, "pd_catalog", None) and hasattr(db.pd_catalog, "update_many"):
        await db.pd_catalog.update_many(catalog_query, {"$set": catalog_updates})
    if getattr(db, "pd_stock_items", None) and hasattr(db.pd_stock_items, "update_many"):
        await db.pd_stock_items.update_many(
            {
                "tenant_id": user["tenant_id"],
                "$or": [
                    {"nome": updated_mp.get("nome", "")},
                    {"codigo_interno": updated_mp.get("codigo_interno", "")},
                ],
            },
            {"$set": {
                "mp_id": updated_mp.get("id"),
                "homologacao_status": updated_mp.get("status"),
                "fornecedor": updated_mp.get("fornecedor_nome", ""),
                "custo_unitario": float(updated_mp.get("custo_referencia") or 0),
                "updated_at": now,
            }},
        )
    return await _upsert_material_from_homologacao_mp(user["tenant_id"], updated_mp, user)


@pd_router.post("/homologacao/mps/{mp_id}/suspender")
async def suspender_mp(mp_id: str, data: SuspenderRequest, request: Request):
    """Suspende uma MP (status `suspensa`). Bloqueia formulas que a usam ate revisao."""
    user = await get_current_user(request)
    require_roles(user, HOMOLOGACAO_APPROVE)
    now = now_iso()
    mp = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not mp:
        raise HTTPException(status_code=404, detail="MP nao encontrada")
    update = {
        "status": "suspensa",
        "parecer_homologacao": data.parecer,
        "homologado_por": user["name"],
        "homologado_por_id": user["id"],
        "data_homologacao": now,
        "updated_at": now,
    }
    evento = {
        "evento": "suspensa",
        "por": user["name"],
        "por_id": user["id"],
        "data": now,
        "parecer": data.parecer,
    }
    await db.homologacao_mps.update_one(
        {"id": mp_id, "tenant_id": user["tenant_id"]},
        {"$set": update, "$push": {"historico": evento}}
    )
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user["name"],
        action="mp_suspensa",
        entity_type="homologacao_mp",
        entity_id=mp_id,
        before={"status": mp.get("status")},
        after={"status": "suspensa", "parecer": data.parecer},
    )
    updated_mp = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    return await _upsert_material_from_homologacao_mp(user["tenant_id"], updated_mp, user)


@pd_router.post("/homologacao/mps/{mp_id}/reativar")
async def reativar_mp(mp_id: str, data: SuspenderRequest, request: Request):
    """Reativa uma MP suspensa, retornando para 'pendente' (precisa nova homologacao)."""
    user = await get_current_user(request)
    require_roles(user, HOMOLOGACAO_APPROVE)
    now = now_iso()
    mp = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not mp:
        raise HTTPException(status_code=404, detail="MP nao encontrada")
    if mp.get("status") != "suspensa":
        raise HTTPException(status_code=400, detail="MP nao esta suspensa")
    update = {
        "status": "pendente",
        "parecer_homologacao": data.parecer,
        "data_homologacao": None,
        "updated_at": now,
    }
    evento = {
        "evento": "reativada",
        "por": user["name"],
        "por_id": user["id"],
        "data": now,
        "parecer": data.parecer,
    }
    await db.homologacao_mps.update_one(
        {"id": mp_id, "tenant_id": user["tenant_id"]},
        {"$set": update, "$push": {"historico": evento}}
    )
    updated_mp = await db.homologacao_mps.find_one({"id": mp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    return await _upsert_material_from_homologacao_mp(user["tenant_id"], updated_mp, user)


@pd_router.delete("/homologacao/mps/{mp_id}")
async def delete_mp(mp_id: str, request: Request):
    user = await get_current_user(request)
    # Bloquear se tem item de estoque vinculado
    stock_collection = getattr(db, "pd_stock_items", None) or getattr(db, "estoque_items", None)
    est_count = await stock_collection.count_documents({"mp_id": mp_id, "tenant_id": user["tenant_id"]}) if stock_collection else 0
    if est_count > 0:
        raise HTTPException(status_code=400, detail=f"MP tem {est_count} item(ns) no estoque. Remova do estoque antes.")
    await db.homologacao_mps.delete_one({"id": mp_id, "tenant_id": user["tenant_id"]})
    return {"deleted": mp_id}


@pd_router.get("/homologacao/dashboard")
async def homologacao_dashboard(request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    t_id = user["tenant_id"]
    mps_all = await db.homologacao_mps.find({"tenant_id": t_id}, {"_id": 0}).to_list(10000)
    forn_all = await db.homologacao_fornecedores.find({"tenant_id": t_id}, {"_id": 0}).to_list(10000)

    def count_by(lst, key):
        r = {}
        for i in lst:
            v = i.get(key, "")
            r[v] = r.get(v, 0) + 1
        return r

    # Agrupa MPs homologadas por nome para detectar fornecedor unico
    mps_homologadas_por_nome: Dict[str, set] = {}
    for mp in mps_all:
        if mp.get("status") != "homologada":
            continue
        key = (mp.get("nome") or "").strip().lower()
        if not key:
            continue
        mps_homologadas_por_nome.setdefault(key, set()).add(
            mp.get("fornecedor_id") or mp.get("fornecedor_nome") or mp.get("id")
        )

    fornecedor_unico_alerts: List[Dict[str, Any]] = []
    risco_baixo_alerts: List[Dict[str, Any]] = []
    for nome_key, fornecedores in mps_homologadas_por_nome.items():
        nome_display = next(
            (mp.get("nome") for mp in mps_all if (mp.get("nome") or "").strip().lower() == nome_key),
            nome_key,
        )
        if len(fornecedores) <= 1:
            fornecedor_unico_alerts.append({
                "nome": nome_display,
                "fornecedores": list(fornecedores),
                "total_fornecedores": len(fornecedores),
            })
        elif len(fornecedores) < 3:
            risco_baixo_alerts.append({
                "nome": nome_display,
                "fornecedores": list(fornecedores),
                "total_fornecedores": len(fornecedores),
            })

    # MPs com status que bloqueiam producao
    mps_bloqueadas = [mp for mp in mps_all if mp.get("status") in MP_BLOCKED_STATUSES]

    return {
        "mps": {
            "total": len(mps_all),
            "por_status": count_by(mps_all, "status"),
            "por_tipo": count_by(mps_all, "tipo_mp"),
            "bloqueadas_total": len(mps_bloqueadas),
        },
        "fornecedores": {
            "total": len(forn_all),
            "por_status": count_by(forn_all, "status"),
            "por_categoria": count_by(forn_all, "categoria"),
        },
        "alertas": {
            "fornecedor_unico": fornecedor_unico_alerts,
            "risco_fornecimento": risco_baixo_alerts,
            "mps_bloqueadas": [
                {"id": mp.get("id"), "nome": mp.get("nome"), "status": mp.get("status"), "fornecedor_nome": mp.get("fornecedor_nome", "")}
                for mp in mps_bloqueadas[:50]
            ],
        },
    }


# ============================================================
# PD-07: FORMULA COST VERSIONS (per-formula snapshots)
# ============================================================

class FormulaCostVersionCreate(BaseModel):
    custo_embalagem: float = 0.0
    custo_mao_obra: float = 0.0

def _formula_cost_view(versions: List[dict], user: dict) -> dict:
    is_comercial = can_view_commercial_costs(user) or has_role(user, COMERCIAL_FULL)
    if is_comercial:
        return {
            "versions": versions,
            "_role_view": "comercial",
        }
    return {
        "versions": [{"versao": v["versao"], "custo_mp_total": v["custo_mp_total"], "created_at": v["created_at"]} for v in versions],
        "_role_view": "pd",
    }

@pd_router.get("/formulas/{formula_id}/costs")
async def get_formula_cost_versions(formula_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    if not formula:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")
    versions = await db.formula_cost_versions.find(
        {"formula_id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return _formula_cost_view(versions, user)

@pd_router.post("/formulas/{formula_id}/costs")
async def save_formula_cost_version(formula_id: str, data: FormulaCostVersionCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE | COMERCIAL_FULL)
    formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    if not formula:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")

    # Derive custo_mp_total from current formula items
    items = await db.pd_formula_items.find({"formula_id": formula_id}, {"_id": 0}).to_list(500)
    custo_mp_total = round(sum(it.get("cost_brl", 0) or 0 for it in items), 4)

    existing_count = await db.formula_cost_versions.count_documents({"formula_id": formula_id, "tenant_id": user["tenant_id"]})
    versao = f"v{existing_count + 1}"

    custo_total = round(custo_mp_total + data.custo_embalagem + data.custo_mao_obra, 4)

    version_doc = {
        "id": new_id(),
        "formula_id": formula_id,
        "tenant_id": user["tenant_id"],
        "versao": versao,
        "criado_por": user["id"],
        "criado_por_nome": user["name"],
        "custo_mp_total": custo_mp_total,
        "custo_embalagem": data.custo_embalagem,
        "custo_mao_obra": data.custo_mao_obra,
        "custo_total": custo_total,
        "created_at": now_iso(),
    }
    await db.formula_cost_versions.insert_one(version_doc)
    version_doc.pop("_id", None)

    # Return role-filtered view
    versions = await db.formula_cost_versions.find(
        {"formula_id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return _formula_cost_view(versions, user)


# ============================================================
# PD-08: FORMULA PROCEDURE PHASES
# ============================================================

class ProcedurePhaseCreate(BaseModel):
    nome_fase: str = Field(validation_alias=AliasChoices("nome_fase", "titulo"))
    temperatura: Optional[str] = None
    instrucoes: Optional[str] = Field(default=None, validation_alias=AliasChoices("instrucoes", "descricao"))
    observacoes: Optional[str] = Field(default=None, validation_alias=AliasChoices("observacoes", "notas"))
    ordem: int = 0

class ProcedurePhaseUpdate(BaseModel):
    nome_fase: Optional[str] = Field(default=None, validation_alias=AliasChoices("nome_fase", "titulo"))
    temperatura: Optional[str] = None
    instrucoes: Optional[str] = Field(default=None, validation_alias=AliasChoices("instrucoes", "descricao"))
    observacoes: Optional[str] = Field(default=None, validation_alias=AliasChoices("observacoes", "notas"))
    ordem: Optional[int] = None

class PhasesReorder(BaseModel):
    phase_ids: List[str]  # ordered list of phase IDs

@pd_router.get("/formulas/{formula_id}/phases")
async def list_formula_phases(formula_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    phases = await db.formula_procedure_phases.find(
        {"formula_id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("ordem", 1).to_list(100)
    return phases

@pd_router.post("/formulas/{formula_id}/phases")
async def create_formula_phase(formula_id: str, data: ProcedurePhaseCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    formula = await db.pd_formulas.find_one({"id": formula_id}, {"_id": 0})
    if not formula:
        raise HTTPException(status_code=404, detail="Fórmula não encontrada")
    max_order_doc = await db.formula_procedure_phases.find_one(
        {"formula_id": formula_id}, {"_id": 0, "ordem": 1}, sort=[("ordem", -1)]
    )
    auto_order = (max_order_doc["ordem"] + 1) if max_order_doc else 0
    phase = {
        "id": new_id(),
        "formula_id": formula_id,
        "tenant_id": user["tenant_id"],
        "nome_fase": data.nome_fase.strip(),
        "temperatura": (data.temperatura or "").strip() or None,
        "instrucoes": (data.instrucoes or "").strip() or None,
        "observacoes": (data.observacoes or "").strip() or None,
        "ordem": data.ordem if data.ordem > 0 else auto_order,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.formula_procedure_phases.insert_one(phase)
    phase.pop("_id", None)
    return phase

@pd_router.put("/formula-phases/{phase_id}")
async def update_formula_phase(phase_id: str, data: ProcedurePhaseUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    existing = await db.formula_procedure_phases.find_one({"id": phase_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Fase não encontrada")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    for text_field in ("nome_fase", "temperatura", "instrucoes", "observacoes"):
        if text_field in updates:
            updates[text_field] = (updates[text_field] or "").strip() or None
    if updates.get("nome_fase") is None:
        updates.pop("nome_fase", None)
    updates["updated_at"] = now_iso()
    await db.formula_procedure_phases.update_one({"id": phase_id}, {"$set": updates})
    return {**existing, **updates}

@pd_router.delete("/formula-phases/{phase_id}")
async def delete_formula_phase(phase_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    result = await db.formula_procedure_phases.delete_one({"id": phase_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Fase não encontrada")
    return {"message": "Fase removida"}

@pd_router.put("/formulas/{formula_id}/phases/reorder")
async def reorder_formula_phases(formula_id: str, data: PhasesReorder, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    for idx, phase_id in enumerate(data.phase_ids):
        await db.formula_procedure_phases.update_one(
            {"id": phase_id, "formula_id": formula_id, "tenant_id": user["tenant_id"]},
            {"$set": {"ordem": idx, "updated_at": now_iso()}}
        )
    phases = await db.formula_procedure_phases.find(
        {"formula_id": formula_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("ordem", 1).to_list(100)
    return phases


# ============================================================
# PD-09: TECH SHEET PDF FOR CRM SAMPLE (no monetary values)
# ============================================================

_TECH_SHEET_ROLES = PD_FULL | {"pcp", "supervisor", "vendedor", "sales_ops"}

@pd_router.get("/samples/{crm_sample_id}/tech-sheet.pdf")
async def generate_sample_tech_sheet(crm_sample_id: str, request: Request):
    """Operational tech sheet for a CRM sample — never includes monetary values."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    user = await get_current_user(request)
    require_roles(user, _TECH_SHEET_ROLES)

    sample = await db.crm_samples.find_one({"id": crm_sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")

    # Find the PD card linked to this sample
    pd_card = await db.pd_cards.find_one({"amostra_id": crm_sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    formula = None
    items_safe = []
    phases = []

    if pd_card and pd_card.get("pd_request_id"):
        dev = await db.pd_developments.find_one({"pd_request_id": pd_card["pd_request_id"]}, {"_id": 0})
        if dev:
            formula = await db.pd_formulas.find_one(
                {"development_id": dev["id"]}, {"_id": 0}, sort=[("version", -1)]
            )
            if formula:
                raw_items = await db.pd_formula_items.find(
                    {"formula_id": formula["id"]}, {"_id": 0}
                ).to_list(500)
                # NEVER include monetary values — select only safe fields
                for it in raw_items:
                    items_safe.append({
                        "ingredient_name": it.get("ingredient_name", ""),
                        "inci": it.get("inci", "") or "",
                        "fornecedor": it.get("fornecedor", "") or "",
                        "percentage": it.get("percentage", 0),
                        "phase": it.get("phase", "") or "",
                    })
                phases = await db.formula_procedure_phases.find(
                    {"formula_id": formula["id"], "tenant_id": user["tenant_id"]}, {"_id": 0}
                ).sort("ordem", 1).to_list(50)

    tenant = await db.tenants.find_one({"id": user["tenant_id"]}, {"_id": 0})
    org_name = tenant["name"] if tenant else "Kuryos"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=25*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TSTitle', parent=styles['Title'], fontSize=20, spaceAfter=4, textColor=rl_colors.HexColor('#0A0A0B'))
    subtitle_style = ParagraphStyle('TSSubtitle', parent=styles['Normal'], fontSize=11, textColor=rl_colors.HexColor('#737373'), spaceAfter=8)
    heading_style = ParagraphStyle('TSHeading', parent=styles['Heading2'], fontSize=12, spaceAfter=6, spaceBefore=12, textColor=rl_colors.HexColor('#0A0A0B'))
    normal_style = ParagraphStyle('TSNormal', parent=styles['Normal'], fontSize=9.5, spaceAfter=3, leading=13)
    small_style = ParagraphStyle('TSSmall', parent=styles['Normal'], fontSize=8, textColor=rl_colors.HexColor('#737373'))

    elements = []
    elements.append(Paragraph("FICHA TÉCNICA OPERACIONAL", title_style))
    elements.append(Paragraph(f"{org_name} — Documento de Uso Interno", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=rl_colors.HexColor('#E5E5E5'), spaceAfter=8))

    # Product identification
    elements.append(Paragraph("1. IDENTIFICAÇÃO", heading_style))
    amostra_num = sample.get("numero_amostra") or sample.get("id", "")
    info_data = [
        ["Produto:", sample.get("nome_produto", "—")],
        ["Nº Amostra:", amostra_num],
        ["Tipo:", sample.get("tipo_amostra", "—")],
        ["Data:", datetime.now(timezone.utc).strftime("%d/%m/%Y")],
        ["Responsável P&D:", pd_card.get("responsavel_pd", "—") if pd_card else "—"],
    ]
    it = Table(info_data, colWidths=[40*mm, 130*mm])
    it.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('TEXTCOLOR', (0, 0), (0, -1), rl_colors.HexColor('#737373')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(it)

    # Formula (NO PRICES)
    if items_safe:
        vol = formula.get("volume", 0) or 0
        vu = formula.get("volume_unit", "mL")
        elements.append(Paragraph(f"2. FORMULAÇÃO — v{formula.get('version', 1)}", heading_style))
        header = ["Ingrediente", "INCI", "Fase", f"% Fórmula", f"Qtd/Lote ({vu})"]
        rows = [header]
        total_pct = 0
        for itm in items_safe:
            pct = itm["percentage"]
            total_pct += pct
            qty = f"{vol * pct / 100:.3f}" if vol > 0 else "—"
            rows.append([itm["ingredient_name"], itm["inci"] or "—", itm["phase"] or "—", f"{pct:.3f}", qty])
        rows.append(["TOTAL", "", "", f"{total_pct:.2f}", f"{vol:.0f}" if vol > 0 else "—"])
        ft = Table(rows, colWidths=[50*mm, 35*mm, 20*mm, 20*mm, 26*mm])
        ft.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#0A0A0B')),
            ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -2), 0.5, rl_colors.HexColor('#E5E5E5')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('LINEABOVE', (0, -1), (-1, -1), 1, rl_colors.HexColor('#0A0A0B')),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
        ]))
        elements.append(ft)

    # Procedure phases
    if phases:
        elements.append(Paragraph("3. PROCEDIMENTO DE MANIPULAÇÃO", heading_style))
        for phase in phases:
            phase_title = phase["nome_fase"]
            if phase.get("temperatura"):
                phase_title += f" — Temperatura: {phase['temperatura']}"
            elements.append(Paragraph(f"<b>{phase_title}</b>", normal_style))
            if phase.get("instrucoes"):
                elements.append(Paragraph(phase["instrucoes"], normal_style))
            if phase.get("observacoes"):
                elements.append(Paragraph(f"<i>Obs: {phase['observacoes']}</i>", small_style))
            elements.append(Spacer(1, 4*mm))

    elements.append(Spacer(1, 16*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.HexColor('#E5E5E5'), spaceAfter=4))
    elements.append(Paragraph(
        f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC — {org_name} — DOCUMENTO OPERACIONAL (SEM VALORES MONETÁRIOS)",
        small_style
    ))

    doc.build(elements)
    buffer.seek(0)
    safe_name = (sample.get("nome_produto", "amostra") or "amostra").replace(" ", "_").replace("/", "-")
    filename = f"tech_sheet_{safe_name}_{amostra_num}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ============================================================
# PD-10: MARK UPDATE AS RECEIVED
# ============================================================

@pd_router.put("/updates/{up_id}/received")
async def mark_update_received(up_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    existing = await db.pd_updates.find_one({"id": up_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Atualização não encontrada")
    await db.pd_updates.update_one(
        {"id": up_id},
        {"$set": {"recebido": True, "recebido_em": now_iso(), "recebido_por": user["id"], "recebido_por_nome": user["name"]}}
    )
    return {**existing, "recebido": True, "recebido_em": now_iso()}


# ============================================================
# PD-12: BATCH MANIPULATION ORDER
# ============================================================

class BatchManipulationCreate(BaseModel):
    amostra_ids: List[str]
    observacao: Optional[str] = None
    volume_por_amostra_ml: float = 15.0

@pd_router.post("/batch-manipulation")
async def create_batch_manipulation(data: BatchManipulationCreate, request: Request):
    """Generate a shared-base manipulation order for a batch of samples."""
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)

    if not data.amostra_ids:
        raise HTTPException(status_code=400, detail="Selecione ao menos uma amostra")

    vol = data.volume_por_amostra_ml
    n_amostras = len(data.amostra_ids)

    # Collect formula items per sample
    sample_items: dict = {}  # amostra_id → list of items
    sample_labels: dict = {}
    for amostra_id in data.amostra_ids:
        card = await db.pd_cards.find_one({"amostra_id": amostra_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
        sample = await db.crm_samples.find_one({"id": amostra_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
        label = sample.get("numero_amostra") or amostra_id
        if sample and sample.get("variacoes"):
            # Try to get variacao codigo
            for v in sample["variacoes"]:
                if v.get("id") == card.get("amostra_variacao_id"):
                    label = f"{label}/{v.get('codigo', '')}"
                    break
        sample_labels[amostra_id] = label

        items = []
        if card and card.get("pd_request_id"):
            dev = await db.pd_developments.find_one({"pd_request_id": card["pd_request_id"]}, {"_id": 0})
            if dev:
                formula = await db.pd_formulas.find_one(
                    {"development_id": dev["id"]}, {"_id": 0}, sort=[("version", -1)]
                )
                if formula:
                    items = await db.pd_formula_items.find(
                        {"formula_id": formula["id"]}, {"_id": 0}
                    ).to_list(500)
        sample_items[amostra_id] = items

    # Find common ingredients (ingredient_name appears in ALL samples)
    if not sample_items or not any(sample_items.values()):
        raise HTTPException(status_code=400, detail="Nenhuma fórmula encontrada para as amostras selecionadas")

    all_ingredient_sets = [
        {it["ingredient_name"].strip().lower() for it in items}
        for items in sample_items.values() if items
    ]
    if not all_ingredient_sets:
        raise HTTPException(status_code=400, detail="Nenhuma fórmula ativa encontrada")

    common_names = set.intersection(*all_ingredient_sets) if len(all_ingredient_sets) > 1 else all_ingredient_sets[0]

    # Build base compartilhada (use percentual from first sample's formula)
    first_items = next(v for v in sample_items.values() if v)
    base_items = []
    for it in first_items:
        if it["ingredient_name"].strip().lower() in common_names:
            pct = it.get("percentage", 0) or 0
            qty_ml = round(vol * n_amostras * (pct / 100), 3)
            base_items.append({
                "mp": it["ingredient_name"],
                "fornecedor": it.get("fornecedor", "") or "",
                "percentual": pct,
                "qtd_ml": qty_ml,
                "unidade": "mL",
            })

    # Build per-variation additions (ingredients NOT in common base)
    ingredientes_por_variacao: dict = {}
    for amostra_id, items in sample_items.items():
        label = sample_labels[amostra_id]
        variation_items = []
        for it in items:
            if it["ingredient_name"].strip().lower() not in common_names:
                pct = it.get("percentage", 0) or 0
                qty_ml = round(vol * (pct / 100), 3)
                variation_items.append({
                    "mp": it["ingredient_name"],
                    "fornecedor": it.get("fornecedor", "") or "",
                    "percentual": pct,
                    "qtd_ml": qty_ml,
                    "unidade": "mL",
                })
        ingredientes_por_variacao[label] = variation_items

    # Generate order number
    count = await db.pd_batch_orders.count_documents({"tenant_id": user["tenant_id"]})
    ordem_numero = f"OM-{datetime.now(timezone.utc).year}-{str(count + 1).zfill(5)}"

    order_doc = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "ordem_numero": ordem_numero,
        "amostra_ids": data.amostra_ids,
        "volume_por_amostra_ml": vol,
        "n_amostras": n_amostras,
        "base_compartilhada": base_items,
        "ingredientes_por_variacao": ingredientes_por_variacao,
        "observacao": data.observacao or "",
        "criado_por": user["id"],
        "criado_por_nome": user["name"],
        "created_at": now_iso(),
    }
    await db.pd_batch_orders.insert_one(order_doc)
    order_doc.pop("_id", None)

    # Move all linked PD cards to em_desenvolvimento
    for amostra_id in data.amostra_ids:
        await db.pd_cards.update_many(
            {"amostra_id": amostra_id, "tenant_id": user["tenant_id"]},
            {"$set": {"status_pd": "em_desenvolvimento", "updated_at": now_iso()}}
        )

    return {**order_doc, "amostras_atualizadas": data.amostra_ids}


@pd_router.get("/batch-manipulation")
async def list_batch_orders(request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    orders = await db.pd_batch_orders.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return orders


# ============================================================
# PD-13: EXECUTOR ASSIGNMENT ON PD CARDS
# ============================================================

class ExecutorAssign(BaseModel):
    executor_id: Optional[str] = None
    executor_name: Optional[str] = None

@pd_router.put("/pd-cards/{card_id}/executor")
async def assign_executor(card_id: str, data: ExecutorAssign, request: Request):
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    card = await db.pd_cards.find_one({"id": card_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="Card P&D não encontrado")
    updates = {
        "executor_id": data.executor_id,
        "executor_name": data.executor_name,
        "atribuido_em": now_iso(),
        "atribuido_por": user["id"],
        "atribuido_por_nome": user["name"],
        "updated_at": now_iso(),
    }
    await db.pd_cards.update_one({"id": card_id}, {"$set": updates})
    return {**card, **updates}


# ============================================================
# PD-16: LAB STOCK ALERT ON CRM SAMPLE CREATION (helper)
# ============================================================

async def check_lab_stock_for_product(produto_nome: str, tenant_id: str) -> Optional[dict]:
    """Returns an alert if a finished sample already exists in lab stock."""
    if not produto_nome:
        return None
    from datetime import date as date_cls
    today_str = date_cls.today().isoformat()
    item = await db.pd_stock_items.find_one({
        "tenant_id": tenant_id,
        "categoria": "amostra_acabada",
        "nome": {"$regex": produto_nome.strip()[:40], "$options": "i"},
        "quantidade_atual": {"$gt": 0},
    }, {"_id": 0})
    if not item:
        return None
    # Check validity
    validade = item.get("validade")
    if validade and validade < today_str:
        return None
    return {
        "alerta": f"Há amostra em estoque: {item['nome']}",
        "quantidade": item["quantidade_atual"],
        "unidade": item.get("unidade_medida", "un"),
        "localizacao": item.get("localizacao", ""),
        "validade": validade,
        "stock_item_id": item["id"],
    }

@pd_router.get("/stock/check-product")
async def check_product_in_stock(produto_nome: str, request: Request):
    """Check if a finished sample with this name exists in lab stock."""
    user = await get_current_user(request)
    require_roles(user, PD_READ)
    alert = await check_lab_stock_for_product(produto_nome, user["tenant_id"])
    return {"alert": alert}


# ============================================================
# PD-17: LINK INTERNAL RESEARCH TO CRM PROJECT
# ============================================================

class LinkToCRMProject(BaseModel):
    crm_project_id: str
    crm_client_id: Optional[str] = None
    crm_client_name: Optional[str] = None

@pd_router.put("/requests/{req_id}/link-to-crm")
async def link_internal_research_to_crm(req_id: str, data: LinkToCRMProject, request: Request):
    """Link an internal research request to a CRM project, converting it to a client-originated request."""
    user = await get_current_user(request)
    require_roles(user, PD_WRITE)
    pd_req = await db.pd_requests.find_one({"id": req_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada")
    if not pd_req.get("is_internal_research"):
        raise HTTPException(status_code=400, detail="Esta solicitação já está vinculada a um projeto CRM")

    # Verify CRM project exists
    crm_project = await db.crm_projects.find_one({"id": data.crm_project_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not crm_project:
        raise HTTPException(status_code=404, detail="Projeto CRM não encontrado")

    old_origem = "interno"
    updates = {
        "is_internal_research": False,
        "crm_project_id": data.crm_project_id,
        "client_card_id": data.crm_client_id or crm_project.get("cliente_id"),
        "client_name": data.crm_client_name or crm_project.get("cliente_nome", ""),
        "vinculado_em": now_iso(),
        "vinculado_por": user["id"],
        "updated_at": now_iso(),
    }
    await db.pd_requests.update_one({"id": req_id}, {"$set": updates})

    # Also update the pd_card
    await db.pd_cards.update_many(
        {"pd_request_id": req_id, "tenant_id": user["tenant_id"]},
        {"$set": {
            "cliente_id": updates["client_card_id"],
            "cliente": updates["client_name"],
            "crm_project_id": data.crm_project_id,
            "updated_at": now_iso(),
        }}
    )

    # Audit log
    try:
        await audit_log(
            tenant_id=user["tenant_id"],
            user_id=user["id"],
            user_name=user["name"],
            action="LINK_INTERNAL_TO_CRM",
            resource_type="pd_request",
            resource_id=req_id,
            details={
                "old_origem": old_origem,
                "new_crm_project_id": data.crm_project_id,
                "crm_project_name": crm_project.get("nome_projeto", ""),
            }
        )
    except Exception:
        pass

    updated = await db.pd_requests.find_one({"id": req_id}, {"_id": 0})
    return updated


# ======================================================================
#  PD-18: SAMPLE VARIATION LABEL PDF (A4, 2×2, 4 labels per page)
# ======================================================================

@pd_router.get("/samples/{variacao_id}/label.pdf")
async def generate_sample_label(variacao_id: str, request: Request):
    """Generate A4 sheet with 4 identical labels (2×2) for a sample variation."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from datetime import date

    user = await get_current_user(request)
    if user["role"] not in (PD_FULL | {"admin"}):
        raise HTTPException(status_code=403, detail="Acesso negado")

    # Find the variation inside crm_samples
    sample = await db.crm_samples.find_one(
        {"tenant_id": user["tenant_id"], "variacoes.id": variacao_id},
        {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Variação não encontrada")

    variacao = next((v for v in sample.get("variacoes", []) if v["id"] == variacao_id), None)
    if not variacao:
        raise HTTPException(status_code=404, detail="Variação não encontrada")

    # Build label data
    numero_amostra = variacao.get("codigo") or f"{sample.get('numero_amostra', '?')}-{variacao.get('letra', 'a')}"
    nome_produto = sample.get("nome_produto", "")
    produto_tipo = sample.get("categoria", sample.get("tipo_amostra", ""))
    responsavel = sample.get("responsavel_pd", "")
    now_date = date.today()
    data_fabricacao = now_date.strftime("%d/%m/%Y")
    val_month = now_date.month + 6
    val_year = now_date.year + (val_month - 1) // 12
    val_month = ((val_month - 1) % 12) + 1
    validade_date = now_date.replace(year=val_year, month=val_month)
    data_validade = validade_date.strftime("%d/%m/%Y")
    observacoes = variacao.get("observacoes_especificas", "") or sample.get("observacao_tecnica", "")

    # PDF generation: A4, four 9.5cm×6cm labels in a 2×2 grid
    buffer = io.BytesIO()
    page_w, page_h = A4  # points
    c = rl_canvas.Canvas(buffer, pagesize=A4)

    label_w = 95 * mm
    label_h = 60 * mm
    margin_x = (page_w - 2 * label_w) / 2
    margin_y = (page_h - 2 * label_h) / 2

    positions = [
        (margin_x, margin_y + label_h),            # top-left
        (margin_x + label_w, margin_y + label_h),   # top-right
        (margin_x, margin_y),                        # bottom-left
        (margin_x + label_w, margin_y),              # bottom-right
    ]

    border_color = rl_colors.HexColor("#222222")
    bg_header = rl_colors.HexColor("#0A0A0B")

    def draw_label(x, y):
        c.setStrokeColor(border_color)
        c.setLineWidth(0.8)
        c.rect(x, y, label_w, label_h)

        c.setFillColor(bg_header)
        c.rect(x, y + label_h - 10 * mm, label_w, 10 * mm, fill=1, stroke=0)

        c.setFillColor(rl_colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 3 * mm, y + label_h - 6 * mm, "KURYOS BEAUTY")
        c.setFont("Helvetica", 7)
        c.drawRightString(x + label_w - 3 * mm, y + label_h - 6 * mm, f"Nr {numero_amostra}")

        row_h = 7.5 * mm
        rows = [
            ("Produto:", nome_produto[:40]),
            ("Tipo:", produto_tipo.replace("_", " ").title()[:40] if produto_tipo else "-"),
            ("Responsavel:", responsavel[:40] if responsavel else "-"),
            ("Fabricacao:", data_fabricacao),
            ("Validade:", data_validade),
            ("Obs:", (observacoes[:55] if observacoes else "-")),
        ]
        c.setFillColor(rl_colors.black)
        for i, (label_txt, value_txt) in enumerate(rows):
            row_y = y + label_h - 10 * mm - (i + 1) * row_h + 2.5 * mm
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(x + 3 * mm, row_y, label_txt)
            c.setFont("Helvetica", 6.5)
            c.drawString(x + 26 * mm, row_y, value_txt)

        c.setStrokeColor(rl_colors.HexColor("#CCCCCC"))
        c.setDash(2, 2)
        c.setLineWidth(0.3)
        c.rect(x + 1 * mm, y + 1 * mm, label_w - 2 * mm, label_h - 2 * mm)
        c.setDash()

    for px, py in positions:
        draw_label(px, py)

    c.showPage()
    c.save()

    buffer.seek(0)
    filename = f"etiqueta_{numero_amostra.replace('/', '-')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
