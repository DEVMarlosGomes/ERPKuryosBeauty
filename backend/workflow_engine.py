"""
Workflow Engine - Kuryos Beauty ERP v3.0
=========================================

Core process-driven engine providing:
- Immutable audit logs for every mutation
- Global sequential numbering (atomic counters)
- Task entity & task templates per stage transition
- Blocking-task validation (entity cannot advance until prerequisites are met)
- Hierarchy validation (client → project → sample → pd_card)
- Inheritance helpers (auto-fill child fields from parent)

This module is the single source of truth for ALL workflow rules.
Routes (crm_routes.py, pd_routes.py) MUST call helpers here on every transition.
"""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from pymongo import ReturnDocument
import logging

logger = logging.getLogger(__name__)

# ============ MODULE STATE ============
db = None
_new_id = None
_now_iso = None


def init_workflow(database, new_id_fn, now_iso_fn):
    global db, _new_id, _now_iso
    db = database
    _new_id = new_id_fn
    _now_iso = now_iso_fn
    logger.info("Workflow engine initialized")


# ======================================================================
#   ENTITY TYPES & ROLE MAPPING
# ======================================================================

ENTITY_TYPES = {"client", "project", "sample", "variacao", "pd_card", "sku", "pd_document", "stability_study", "kickoff"}

# Default RBAC role responsible for each task category.
# Falls back to entity owner if no user with the role exists.
TASK_CATEGORY_ROLES = {
    "comercial": "vendedor",
    "qualificacao": "vendedor",
    "projeto": "gestor",
    "amostra": "gestor",
    "pd_dev": "gestor",     # P&D / desenvolvimento
    "qa": "gestor",         # CQ Approval
    "documentacao": "gestor",
    "engenharia_produto": "gestor",
    "cadastros": "engenharia_produto",
    "compras": "compras",
    "cliente_feedback": "vendedor",
    "fechamento": "vendedor",
    "manual": "vendedor",
}


# ======================================================================
#   AUDIT LOG (immutable)
# ======================================================================

async def audit_log(
    *,
    tenant_id: str,
    user_id: str,
    user_name: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    metadata: Optional[dict] = None,
):
    """Append-only audit log entry. Never updated, never deleted."""
    entry = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "user_name": user_name,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": _safe_diff(before),
        "after": _safe_diff(after),
        "metadata": metadata or {},
        "timestamp": _now_iso(),
    }
    await db.audit_logs.insert_one(entry)
    return entry


def _safe_diff(doc: Optional[dict]) -> Optional[dict]:
    """Strip _id and large arrays for compact audit entries."""
    if not doc:
        return None
    cleaned = {}
    for k, v in doc.items():
        if k == "_id":
            continue
        if isinstance(v, list) and len(v) > 20:
            cleaned[k] = f"<list len={len(v)}>"
        else:
            cleaned[k] = v
    return cleaned


async def list_audit_logs(
    tenant_id: str,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 200,
):
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    if user_id:
        query["user_id"] = user_id
    if action:
        query["action"] = action
    cursor = db.audit_logs.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
    return await cursor.to_list(limit)


# ======================================================================
#   GLOBAL SEQUENTIAL NUMBERING (atomic counters)
# ======================================================================

async def next_sequence(tenant_id: str, name: str, start: int = 100) -> int:
    """Atomically increment and return a tenant-scoped global counter."""
    key = f"{name}:{tenant_id}"
    res = await db.counters.find_one_and_update(
        {"_id": key},
        {"$inc": {"seq": 1}, "$setOnInsert": {"start": start}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = (res or {}).get("seq", 1)
    return seq + start


async def peek_sequence(tenant_id: str, name: str, start: int = 100) -> int:
    key = f"{name}:{tenant_id}"
    doc = await db.counters.find_one({"_id": key})
    if not doc:
        return start
    return doc.get("seq", 0) + start


async def next_sample_number(tenant_id: str) -> int:
    """Global sample sequential number, starts at 101. Legacy — prefer next_sample_code()."""
    return await next_sequence(tenant_id, "sample", start=100)


def int_to_letters(n: int) -> str:
    """Convert 0-based index to lowercase letter suffix: 0→'a', 25→'z', 26→'aa', 51→'az', …"""
    result = ""
    while n >= 0:
        result = chr(ord("a") + (n % 26)) + result
        n = n // 26 - 1
    return result


async def next_sample_code(tenant_id: str, year: int = None) -> str:
    """Return next sample base code in format '{YEAR}-{NNNN}', starting at 1001 per year."""
    if year is None:
        year = datetime.now(timezone.utc).year
    seq = await next_sequence(tenant_id, f"sample_seq:{year}", start=1000)
    return f"{year}-{str(seq).zfill(4)}"


async def next_sku_number(tenant_id: str) -> int:
    return await next_sequence(tenant_id, "sku", start=0)


# ======================================================================
#   SKU CODE GENERATION  [CAT2]-[CLI3]-[SEQ4]
# ======================================================================

CAT2_MAP: Dict[str, str] = {
    "capilares": "CA", "capilar": "CA",
    "skin_care": "SC", "skincare": "SC", "skin care": "SC",
    "dermocosmeticos": "SC", "dermocosmetico": "SC", "dermo": "SC",
    "higiene_pessoal": "HP", "higiene pessoal": "HP", "higiene": "HP",
    "perfumaria": "PF",
    "maquiagem": "MQ", "makeup": "MQ",
    "corporal": "CO", "spa": "CO", "corporal_spa": "CO", "corporal / spa": "CO",
    "infantil": "IN",
    "masculino": "MA",
    "profissional": "PS", "salao": "PS", "profissional_salao": "PS",
    "profissional / salão": "PS",
}

# CAT3: 3-letter codes for the new SKU format [CAT3]-[CLI4]-[SEQ4].
# Kept in sync with db.categorias — this map is a read-through cache for internal use.
CAT3_MAP: Dict[str, str] = {
    "capilares": "CAP", "capilar": "CAP",
    "skin_care": "SKC", "skincare": "SKC", "skin care": "SKC",
    "dermocosmeticos": "SKC", "dermocosmetico": "SKC", "dermo": "SKC",
    "higiene_pessoal": "HGP", "higiene pessoal": "HGP", "higiene": "HGP",
    "perfumaria": "PFM",
    "maquiagem": "MAQ", "makeup": "MAQ",
    "corporal": "COR", "spa": "COR", "corporal_spa": "COR", "corporal / spa": "COR",
    "infantil": "INF",
    "masculino": "MAS",
    "profissional": "PRS", "salao": "PRS", "profissional_salao": "PRS",
    "profissional / salão": "PRS",
    "body_splash": "BSP", "body splash": "BSP",
}

# Canonical seed categories (id, cat3, nome) — used by migration m002 and as fallback.
SEED_CATEGORIAS = [
    ("CAP", "Capilares"),
    ("SKC", "Skin Care / Dermocosméticos"),
    ("HGP", "Higiene Pessoal"),
    ("PFM", "Perfumaria"),
    ("MAQ", "Maquiagem"),
    ("COR", "Corporal / Spa"),
    ("INF", "Infantil"),
    ("MAS", "Masculino"),
    ("PRS", "Profissional / Salão"),
    ("BSP", "Body Splash"),
]


def cat2_from_categoria(categoria: str) -> str:
    """Return the 2-letter CAT2 code for a product category string."""
    if not categoria:
        return "GE"
    key = categoria.lower().strip()
    if key in CAT2_MAP:
        return CAT2_MAP[key]
    key_norm = key.replace(" ", "_").replace("/", "_").replace("ã", "a").replace("é", "e").replace("ó", "o")
    if key_norm in CAT2_MAP:
        return CAT2_MAP[key_norm]
    for k, v in CAT2_MAP.items():
        if k in key or key in k:
            return v
    return "GE"


def cat3_from_categoria(categoria: str) -> str:
    """Return the 3-letter CAT3 code for a product category string (new SKU format)."""
    if not categoria:
        return "GEN"
    key = categoria.lower().strip()
    if key in CAT3_MAP:
        return CAT3_MAP[key]
    key_norm = key.replace(" ", "_").replace("/", "_").replace("ã", "a").replace("é", "e").replace("ó", "o")
    if key_norm in CAT3_MAP:
        return CAT3_MAP[key_norm]
    for k, v in CAT3_MAP.items():
        if k in key or key in k:
            return v
    return "GEN"


def normalise_cli3(raw: str) -> str:
    """Return exactly 3 uppercase alpha chars from raw string, padded with 'X' if needed."""
    letters = "".join(c for c in (raw or "").upper() if c.isalpha())[:3]
    return letters.ljust(3, "X") if letters else "GEN"


def normalise_cli4(raw: str) -> str:
    """Return exactly 4 uppercase alpha chars from raw string, padded with 'X' if needed."""
    letters = "".join(c for c in (raw or "").upper() if c.isalpha())[:4]
    return letters.ljust(4, "X") if letters else "GENX"


def suggest_cli4_candidates(nome: str) -> List[str]:
    """Return ordered list of CLI4 candidates for a company name, deduplicated."""
    nome_up = (nome or "").upper()
    words = nome_up.split()
    word_letters = ["".join(c for c in w if c.isalpha()) for w in words if any(c.isalpha() for c in w)]
    all_letters = "".join(word_letters)

    # Ordem prioriza padrões que soam mais "legíveis" como sigla de marca (3 letras da
    # 1ª palavra + inicial da 2ª, ex: "Miss Rose" -> MISR) antes do bloco corrido de 4
    # letras (ex: MISS) — mesmo conjunto de candidatos de antes, só reordenado.
    candidates: List[str] = []
    if len(word_letters) >= 2 and len(word_letters[0]) >= 3:
        candidates.append((word_letters[0][:3] + word_letters[1][0]).ljust(4, "X"))
    if all_letters:
        candidates.append(all_letters[:4].ljust(4, "X"))
    if len(word_letters) >= 2:
        candidates.append((word_letters[0][:2] + word_letters[1][:2]).ljust(4, "X"))
    initials = "".join(w[0] for w in word_letters if w)
    if len(initials) >= 2:
        candidates.append(initials[:4].ljust(4, "X"))
    for start in range(1, max(0, len(all_letters) - 3)):
        candidates.append(all_letters[start : start + 4].ljust(4, "X"))

    seen: set = set()
    result: List[str] = []
    for c in candidates:
        if c not in seen and len(c) == 4 and c.isalpha():
            seen.add(c)
            result.append(c)
    return result


async def next_sku_per_pair(tenant_id: str, cat2: str, cli3: str) -> int:
    """Atomic counter per (tenant, cat2, cli3) pair — returns 1-based integer. Legacy."""
    key = f"sku_{cat2}_{cli3}"
    return await next_sequence(tenant_id, key, start=0)


async def next_sku_per_pair_v2(tenant_id: str, cat3: str, cli4: str) -> int:
    """Atomic counter per (tenant, cat3, cli4) pair for new [CAT3]-[CLI4]-[SEQ4] format."""
    key = f"skuv2_{cat3}_{cli4}"
    return await next_sequence(tenant_id, key, start=0)


def build_sku_code_v2(cat3: str, cli4: str, seq: int) -> str:
    """Build new-format SKU code: CAT3-CLI4-SEQ4. Forces uppercase."""
    return f"{cat3.upper()}-{cli4.upper()}-{str(seq).zfill(4)}"


async def next_lote_per_day(tenant_id: str, data_iso: str) -> int:
    """Returns sequential lote number for a given calendar day (global across all OPs for that day)."""
    day_key = data_iso[:10].replace("-", "")  # YYYYMMDD
    return await next_sequence(tenant_id, f"lote_{day_key}", start=0)


def format_lote_numero(data_iso: str, seq: int) -> str:
    """Format lote number as YYYYY/NN per spec 3.2 — e.g. 26014/03 for 14-Jan-2026 lote #3."""
    d = datetime.fromisoformat(data_iso[:10])
    year2 = str(d.year)[-2:]
    doy = d.timetuple().tm_yday
    return f"{year2}{str(doy).zfill(3)}/{str(seq).zfill(2)}"


async def recalc_sku_averages(tenant_id: str, sku_id: str) -> None:
    """Recalculate all automatic production averages for a SKU from its historico_producao."""
    sku = await db.skus.find_one({"id": sku_id, "tenant_id": tenant_id})
    if not sku:
        return
    historico = (sku.get("medias_producao") or {}).get("historico_producao", [])
    if not historico:
        return

    now = datetime.now(timezone.utc)

    def avg_unh(records):
        vals = [r["unh"] for r in records if r.get("unh") and r["unh"] > 0]
        return round(sum(vals) / len(vals), 1) if vals else None

    def within_days(days):
        cutoff = (now - timedelta(days=days)).isoformat()
        return [r for r in historico if (r.get("data") or "") >= cutoff]

    await db.skus.update_one(
        {"id": sku_id, "tenant_id": tenant_id},
        {"$set": {
            "medias_producao.media_geral_unh": avg_unh(historico),
            "medias_producao.media_12m_unh": avg_unh(within_days(365)),
            "medias_producao.media_3m_unh": avg_unh(within_days(90)),
            "medias_producao.media_1m_unh": avg_unh(within_days(30)),
        }}
    )


# ======================================================================
#   HIERARCHY VALIDATION
# ======================================================================

async def assert_client_exists(tenant_id: str, client_id: str) -> dict:
    if not client_id:
        raise HTTPException(status_code=400, detail="cliente_id obrigatório")
    doc = await db.crm_clients.find_one(
        {"id": client_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Cliente pai não encontrado — bloqueado pela hierarquia")
    return doc


async def assert_project_exists(tenant_id: str, project_id: str) -> dict:
    if not project_id:
        raise HTTPException(status_code=400, detail="projeto_id obrigatório")
    doc = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Projeto pai não encontrado — bloqueado pela hierarquia")
    return doc


async def assert_sample_exists(tenant_id: str, sample_id: str) -> dict:
    if not sample_id:
        raise HTTPException(status_code=400, detail="amostra_id obrigatório")
    doc = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Amostra pai não encontrada — bloqueado pela hierarquia")
    return doc


# ======================================================================
#   INHERITANCE
# ======================================================================

# Map of fields that propagate from parent to child upon creation.
INHERITED_FROM_CLIENT = {
    "categoria_interesse": "categoria_interesse_cliente",
    "canal_origem": "canal_origem_cliente",
    "tem_anvisa": "tem_anvisa_cliente",
    "volume_estimado_mensal": "volume_estimado_mensal_cliente",
    "anvisa_necessario": "anvisa_necessario_cliente",
}

INHERITED_FROM_PROJECT = {
    "categoria": "categoria",
    "briefing_tecnico": "briefing_tecnico_projeto",
    "responsavel_interno": "responsavel_pd",
    "prazo_prometido_cliente": "prazo_prometido_cliente",
    # R02: campos ricos do projeto → amostra (quando sample ainda não preencheu o campo)
    "ideia_conceito": "objetivo_projeto",
    "referencia_mercado": "referencias",
    "sensorial_desejado": "sensorial",
    "claims_desejados": "ativos_claims",
    "prazo_desejado_amostra": "prazo_entrega_cliente",
}

INHERITED_FROM_SAMPLE = {
    "nome_produto": "produto",
    "categoria": "categoria",
    "briefing_base": "briefing_base",
    "produto": "produto",
    "objetivo_projeto": "objetivo_projeto",
    "aplicacoes_desenvolver": "aplicacoes_desenvolver",
    "ativos_claims": "ativos_claims",
    "referencias": "referencias",
    "textura_esperada": "textura_esperada",
    "aplicacao": "aplicacao",
    "sensorial": "sensorial",
    "ph": "ph",
    "responsavel_pd": "responsavel_pd",
}


def inherit(child: dict, parent: dict, mapping: Dict[str, str]) -> dict:
    """Fill empty/missing child fields from parent (respects existing non-empty values)."""
    for parent_key, child_key in mapping.items():
        if parent_key in parent and parent[parent_key] not in (None, "", []):
            current = child.get(child_key)
            if current in (None, "", []):
                child[child_key] = parent[parent_key]
    return child


# ======================================================================
#   TASK ENGINE
# ======================================================================

TASK_STATUSES = ("pendente", "em_andamento", "em_atraso", "concluida", "cancelada")
TASK_OPEN_STATUSES = ("pendente", "em_andamento", "em_atraso")
TASK_TYPES = ("standard", "approval")
TASK_PRIORITY_MAP = {
    "baixa": "baixa",
    "low": "baixa",
    "media": "media",
    "média": "media",
    "medium": "media",
    "normal": "media",
    "alta": "alta",
    "high": "alta",
    "critica": "critica",
    "crítica": "critica",
    "critical": "critica",
    "urgent": "critica",
    "urgente": "critica",
}
TASK_MANAGER_ROLES = {"admin", "gestor"}


def _normalize_task_priority(value: Optional[str], *, blocking: bool) -> str:
    if not value:
        return "alta" if blocking else "media"
    return TASK_PRIORITY_MAP.get(str(value).strip().lower(), str(value).strip().lower())


def _can_act_on_task(task: dict, user: dict) -> bool:
    if user.get("role") in TASK_MANAGER_ROLES:
        return True
    return task.get("responsible_id") == user.get("id")


def _approval_summary(tasks: List[dict]) -> List[dict]:
    return [{
        "task_id": task.get("id"),
        "display_code": task.get("display_code"),
        "title": task.get("title"),
        "responsible_id": task.get("responsible_id"),
        "responsible_name": task.get("responsible_name"),
        "decision": task.get("decision"),
        "decision_comment": task.get("decision_comment", ""),
        "decision_at": task.get("decision_at"),
        "decision_by": task.get("decision_by"),
        "decision_by_name": task.get("decision_by_name"),
    } for task in tasks]


def _get_default_responsible_sync(tenant_users: List[dict], category: str, fallback_user_id: Optional[str] = None) -> Optional[dict]:
    """Pure helper — caller must pre-fetch tenant users."""
    target_role = TASK_CATEGORY_ROLES.get(category, "vendedor")
    # 1. Try matching role
    for u in tenant_users:
        if u.get("role") == target_role:
            return u
    # 2. Try owner
    if fallback_user_id:
        for u in tenant_users:
            if u.get("id") == fallback_user_id:
                return u
    # 3. Any admin
    for u in tenant_users:
        if u.get("role") == "admin":
            return u
    # 4. First user
    return tenant_users[0] if tenant_users else None


async def create_workflow_task(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    title: str,
    description: str = "",
    category: str = "manual",
    blocking: bool = True,
    blocks_stages: Optional[List[str]] = None,
    due_in_days: int = 3,
    responsible_id: Optional[str] = None,
    created_by: dict,
    metadata: Optional[dict] = None,
) -> dict:
    """Create a workflow task. If responsible_id is None, auto-assign by category role."""
    # Auto-assign
    if not responsible_id:
        users = await db.users.find(
            {"tenant_id": tenant_id}, {"_id": 0, "password_hash": 0}
        ).to_list(200)
        chosen = _get_default_responsible_sync(users, category, created_by.get("id"))
        if chosen:
            responsible_id = chosen["id"]
            responsible_name = chosen.get("name", "")
        else:
            responsible_name = ""
    else:
        u = await db.users.find_one(
            {"id": responsible_id, "tenant_id": tenant_id}, {"_id": 0, "password_hash": 0}
        )
        responsible_name = u.get("name", "") if u else ""

    now = _now_iso()
    seq = await next_sequence(tenant_id, "workflow_task", start=0)
    display_code = f"TRF-{datetime.now(timezone.utc).year}-{seq:05d}"
    task_metadata = metadata or {}
    task_type = task_metadata.get("task_type") or ("approval" if category == "qa" else "standard")
    priority = _normalize_task_priority(task_metadata.get("priority"), blocking=blocking)
    due_date = (datetime.now(timezone.utc) + timedelta(days=due_in_days)).isoformat()
    module_origin = task_metadata.get("module_origin") or entity_type

    task = {
        "id": _new_id(),
        "display_code": display_code,
        "tenant_id": tenant_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "module_origin": module_origin,
        "title": title,
        "description": description,
        "category": category,
        "task_type": task_type,
        "priority": priority,
        "blocking": blocking,
        "blocks_stages": blocks_stages or [],
        "responsible_id": responsible_id or "",
        "responsible_name": responsible_name,
        "assignment_history": [],
        "due_date": due_date,
        "status": "pendente",
        "decision": None,
        "decision_comment": "",
        "decision_at": None,
        "decision_by": None,
        "decision_by_name": None,
        "completed_at": None,
        "completed_by": None,
        "completed_by_name": None,
        "created_by": created_by.get("id", ""),
        "created_by_name": created_by.get("name", ""),
        "created_at": now,
        "updated_at": now,
        "metadata": task_metadata,
        "notification_flags": {
            "assigned_at": None,
            "due_1d_at": None,
            "overdue_at": None,
            "completed_at": None,
        },
    }
    if responsible_id:
        task["assignment_history"].append({
            "responsible_id": responsible_id,
            "responsible_name": responsible_name,
            "assigned_by": created_by.get("id", ""),
            "assigned_by_name": created_by.get("name", ""),
            "assigned_at": now,
            "reason": "initial_assignment",
        })
    await db.workflow_tasks.insert_one(task)
    task.pop("_id", None)

    if responsible_id:
        await create_user_notification(
            tenant_id=tenant_id,
            user_id=responsible_id,
            title=f"Nova tarefa: {display_code}",
            message=f"Prazo: {due_date[:10]} · {entity_type} #{entity_id[:8]}",
            notif_type="workflow_task",
            metadata={
                "task_id": task["id"],
                "display_code": display_code,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "task_type": task_type,
                "priority": priority,
            },
        )
        await db.workflow_tasks.update_one(
            {"id": task["id"], "tenant_id": tenant_id},
            {"$set": {"notification_flags.assigned_at": now}},
        )
        task["notification_flags"]["assigned_at"] = now

    await audit_log(
        tenant_id=tenant_id,
        user_id=created_by.get("id", ""),
        user_name=created_by.get("name", ""),
        action="task_created",
        entity_type="workflow_task",
        entity_id=task["id"],
        after={
            "display_code": display_code,
            "title": title,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "blocking": blocking,
            "category": category,
            "task_type": task_type,
        },
    )
    return task


async def get_blocking_tasks(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    target_stage: Optional[str] = None,
) -> List[dict]:
    """Return open blocking tasks that prevent the entity from advancing."""
    query = {
        "tenant_id": tenant_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "blocking": True,
        "status": {"$in": list(TASK_OPEN_STATUSES)},
    }
    tasks = await db.workflow_tasks.find(query, {"_id": 0}).to_list(500)
    if target_stage is None:
        return tasks
    # If a task lists blocks_stages, check it; if it lists none, treat as blocks-all-advances.
    return [
        t for t in tasks
        if not t.get("blocks_stages") or target_stage in t["blocks_stages"]
    ]


async def assert_no_blocking_tasks(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    target_stage: Optional[str] = None,
):
    pending = await get_blocking_tasks(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        target_stage=target_stage,
    )
    if pending:
        titles = ", ".join(t["title"] for t in pending[:5])
        raise HTTPException(
            status_code=409,
            detail=f"Avanço bloqueado por {len(pending)} tarefa(s) obrigatória(s): {titles}",
        )


async def complete_task(*, tenant_id: str, task_id: str, user: dict, comment: str = "") -> dict:
    task = await db.workflow_tasks.find_one(
        {"id": task_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if task and task.get("task_type") == "approval":
        raise HTTPException(status_code=400, detail="Tarefas de aprovacao exigem decisao formal. Use aprovar ou reprovar.")
    if task and not _can_act_on_task(task, user):
        raise HTTPException(status_code=403, detail="Somente o responsavel da tarefa ou a lideranca pode conclui-la.")
    if task and task["status"] == "cancelada":
        raise HTTPException(status_code=400, detail="Tarefa cancelada nao pode ser concluida.")
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if task["status"] == "concluida":
        return task

    now = _now_iso()
    await db.workflow_tasks.update_one(
        {"id": task_id, "tenant_id": tenant_id},
        {
            "$set": {
                "status": "concluida",
                "decision": task.get("decision"),
                "decision_comment": task.get("decision_comment", ""),
                "decision_at": task.get("decision_at"),
                "decision_by": task.get("decision_by"),
                "decision_by_name": task.get("decision_by_name"),
                "completed_at": now,
                "completed_by": user["id"],
                "completed_by_name": user.get("name", ""),
                "updated_at": now,
                "completion_comment": comment,
                "notification_flags.completed_at": now,
            }
        },
    )
    updated = await db.workflow_tasks.find_one({"id": task_id}, {"_id": 0})

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="task_completed",
        entity_type="workflow_task",
        entity_id=task_id,
        before={"status": task["status"]},
        after={"status": "concluida", "comment": comment},
        metadata={"linked_entity_type": task["entity_type"], "linked_entity_id": task["entity_id"]},
    )
    await _notify_task_closure(updated, actor=user, action_label="concluída")
    return updated


async def decide_task(
    *,
    tenant_id: str,
    task_id: str,
    user: dict,
    decision: str,
    comment: str = "",
) -> dict:
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Decision inválida. Use approved ou rejected.")
    if decision == "rejected" and not comment.strip():
        raise HTTPException(status_code=400, detail="Justificativa obrigatória para reprovação.")

    task = await db.workflow_tasks.find_one(
        {"id": task_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    if task.get("task_type") != "approval":
        raise HTTPException(status_code=400, detail="Esta tarefa não suporta decisão formal.")
    if not _can_act_on_task(task, user):
        raise HTTPException(status_code=403, detail="Somente o responsavel da tarefa ou a lideranca pode decidir esta aprovacao.")
    if task["status"] == "concluida":
        return task
    if task["status"] == "cancelada":
        raise HTTPException(status_code=400, detail="Tarefa cancelada nao pode receber decisao.")

    now = _now_iso()
    await db.workflow_tasks.update_one(
        {"id": task_id, "tenant_id": tenant_id},
        {
            "$set": {
                "status": "concluida",
                "decision": decision,
                "decision_comment": comment,
                "decision_at": now,
                "decision_by": user["id"],
                "decision_by_name": user.get("name", ""),
                "completed_at": now,
                "completed_by": user["id"],
                "completed_by_name": user.get("name", ""),
                "completion_comment": comment,
                "updated_at": now,
                "notification_flags.completed_at": now,
            }
        },
    )
    updated = await db.workflow_tasks.find_one({"id": task_id}, {"_id": 0})
    await _sync_pd_document_version_status(updated)

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="task_decided",
        entity_type="workflow_task",
        entity_id=task_id,
        before={"status": task["status"], "decision": task.get("decision")},
        after={"status": "concluida", "decision": decision, "comment": comment},
        metadata={"linked_entity_type": task["entity_type"], "linked_entity_id": task["entity_id"]},
    )
    await _notify_task_closure(
        updated,
        actor=user,
        action_label="aprovada" if decision == "approved" else "reprovada",
    )
    return updated


# ======================================================================
#   TASK TEMPLATES (auto-generated tasks per stage transition)
# ======================================================================

# Returns list of task dicts (kwargs for create_workflow_task) to be created.
def tasks_for_client_transition(old: str, new: str) -> List[dict]:
    if new == "qualificado":
        return [{
            "title": "Qualificar lead — preencher decisores, ANVISA, volume e fornecedor atual",
            "category": "qualificacao",
            "blocking": True,
            "blocks_stages": ["projeto_em_discussao"],
            "due_in_days": 5,
        }]
    if new == "projeto_em_discussao":
        return [{
            "title": "Cadastrar projetos do cliente (briefing técnico)",
            "category": "projeto",
            "blocking": True,
            "blocks_stages": ["negociacao"],
            "due_in_days": 5,
        }]
    if new == "negociacao":
        return [{
            "title": "Enviar proposta comercial e registrar feedback",
            "category": "comercial",
            "blocking": True,
            "blocks_stages": ["cliente_fechado"],
            "due_in_days": 7,
        }]
    if new == "cliente_fechado":
        return [
            {
                "title": "Confirmar pedido e registrar SKUs",
                "category": "fechamento",
                "blocking": False,
                "due_in_days": 3,
            },
            {
                "title": "Acionar fila de Sucesso do Cliente",
                "category": "comercial",
                "blocking": False,
                "due_in_days": 1,
            },
        ]
    return []


def tasks_for_project_transition(old: str, new: str) -> List[dict]:
    if new == "amostra_solicitada":
        return [{
            "title": "Iniciar lote de amostras do projeto",
            "category": "amostra",
            "blocking": False,
            "blocks_stages": [],
            "due_in_days": 1,
        }]
    if new == "amostra_em_desenvolvimento":
        return [{
            "title": "Atualizar andamento tecnico da amostra",
            "category": "pd_dev",
            "blocking": False,
            "due_in_days": 2,
        }]
    if new == "amostra_enviada":
        return [
            {
                "title": "Follow-up D+3 do projeto apos envio de amostra",
                "category": "cliente_feedback",
                "blocking": False,
                "due_in_days": 3,
            },
            {
                "title": "Follow-up D+7 do projeto apos envio de amostra",
                "category": "cliente_feedback",
                "blocking": False,
                "due_in_days": 7,
            },
            {
                "title": "Follow-up D+14 do projeto apos envio de amostra",
                "category": "cliente_feedback",
                "blocking": False,
                "due_in_days": 14,
            },
        ]
    if new == "cotacao":
        return [{
            "title": "Levantar cotacao comercial do projeto",
            "category": "comercial",
            "blocking": False,
            "due_in_days": 2,
        }]
    if new == "orcamento_completo":
        return [{
            "title": "Montar orcamento completo do projeto",
            "category": "fechamento",
            "blocking": False,
            "due_in_days": 2,
        }]
    if new == "em_negociacao":
        return [{
            "title": "Montar proposta comercial do projeto",
            "category": "fechamento",
            "blocking": False,
            "due_in_days": 2,
        }]
    if new == "pedido_aprovado":
        return [
            {
                "title": "Validar homologacoes antes de liberar compras",
                "category": "pd_dev",
                "blocking": True,
                "blocks_stages": [],
                "due_in_days": 1,
            },
            {
                "title": "Executar kickoff comercial e contrato",
                "category": "fechamento",
                "blocking": False,
                "due_in_days": 2,
            },
        ]
    if new == "projeto_arquivado":
        return [{
            "title": "Programar reativacao futura do projeto",
            "category": "comercial",
            "blocking": False,
            "due_in_days": 30,
        }]
    if new == "amostras":
        return [{
            "title": "Iniciar lote de amostras com numeração global e variações",
            "category": "amostra",
            "blocking": True,
            "blocks_stages": [],
            "due_in_days": 3,
        }]
    return []


def tasks_for_sample_transition(old: str, new: str) -> List[dict]:
    # Keep simple: enviada → aprovada needs feedback registered.
    if new == "aprovada":
        return []
    if new == "enviada":
        return [{
            "title": "Registrar feedback do cliente após envio",
            "category": "cliente_feedback",
            "blocking": True,
            "blocks_stages": ["aprovada", "reprovada"],
            "due_in_days": 7,
        }]
    return []


def tasks_for_pd_transition(old: str, new: str) -> List[dict]:
    """P&D pipeline tasks. Notably: aguardando_aprovacao requires CQ approval before close."""
    if new == "em_testes":
        return [{
            "title": "Executar testes laboratoriais (estabilidade, pH, viscosidade, sensorial)",
            "category": "pd_dev",
            "blocking": True,
            "blocks_stages": ["aguardando_aprovacao"],
            "due_in_days": 5,
        }]
    if new == "aguardando_aprovacao":
        # CQ approval blocks any further movement on the P&D card itself.
        # We list the only forward-compatible PD stage as a safety guard; in practice
        # operators advance the related variação to 'aprovada' (which generates SKU)
        # and the linked /variacao route also calls assert_no_blocking_tasks for the
        # variação's open tasks. To enforce CQ for both paths, the task is created on
        # the pd_card and (mirrored) tasks must also be created on its variacao.
        return [{
            "title": "Aprovação do Controle de Qualidade (CQ)",
            "category": "qa",
            "blocking": True,
            # Block reverse moves and any close intent on the PD card.
            "blocks_stages": [],  # empty = blocks ALL transitions (per assert_no_blocking_tasks rule)
            "due_in_days": 3,
        }]
    return []


# Override the minimal templates above with the ERP v3.0 rule set used in production.
def tasks_for_sample_transition(old: str, new: str) -> List[dict]:
    if new == "aprovada":
        return [
            {
                "title": "Registrar formula aprovada",
                "category": "pd_dev",
                "blocking": False,
                "due_in_days": 1,
            },
            {
                "title": "Gerar ficha tecnica da formula aprovada",
                "category": "pd_dev",
                "blocking": False,
                "due_in_days": 2,
            },
        ]
    if new == "enviada":
        return [
            {
                "title": "Registrar feedback do cliente apos envio",
                "category": "cliente_feedback",
                "blocking": True,
                "blocks_stages": ["aprovada", "reprovada"],
                "due_in_days": 7,
            },
            {
                "title": "Follow-up D+3 da amostra enviada",
                "category": "cliente_feedback",
                "blocking": False,
                "due_in_days": 3,
            },
            {
                "title": "Follow-up D+7 da amostra enviada",
                "category": "cliente_feedback",
                "blocking": False,
                "due_in_days": 7,
            },
            {
                "title": "Follow-up D+14 da amostra enviada",
                "category": "cliente_feedback",
                "blocking": False,
                "due_in_days": 14,
            },
        ]
    return []


def tasks_for_pd_transition(old: str, new: str) -> List[dict]:
    if new == "em_testes":
        return [{
            "title": "Executar testes laboratoriais (estabilidade, pH, viscosidade, sensorial)",
            "category": "pd_dev",
            "blocking": True,
            "blocks_stages": ["aguardando_aprovacao"],
            "due_in_days": 5,
        }]
    if new == "aguardando_aprovacao":
        return [{
            "title": "Aprovacao do Controle de Qualidade (CQ)",
            "category": "qa",
            "description": "Registre aprovacao ou reprovacao com justificativa.",
            "blocking": True,
            "blocks_stages": [],
            "due_in_days": 3,
            "metadata": {"task_type": "approval", "priority": "alta"},
        }]
    return []


async def trigger_tasks_for_transition(
    *,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    old_stage: str,
    new_stage: str,
    user: dict,
):
    """Generate workflow tasks based on a stage transition."""
    if entity_type == "client":
        templates = tasks_for_client_transition(old_stage, new_stage)
    elif entity_type == "project":
        templates = tasks_for_project_transition(old_stage, new_stage)
    elif entity_type == "sample" or entity_type == "variacao":
        templates = tasks_for_sample_transition(old_stage, new_stage)
    elif entity_type == "pd_card":
        templates = tasks_for_pd_transition(old_stage, new_stage)
    else:
        templates = []

    created = []
    for tpl in templates:
        task = await create_workflow_task(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            title=tpl["title"],
            description=tpl.get("description", ""),
            category=tpl["category"],
            blocking=tpl.get("blocking", True),
            blocks_stages=tpl.get("blocks_stages", []),
            due_in_days=tpl.get("due_in_days", 3),
            created_by=user,
            metadata={
                "trigger": "stage_transition",
                "from": old_stage,
                "to": new_stage,
                **tpl.get("metadata", {}),
            },
        )
        created.append(task)

    # ERP v3.0 mirror: when a pd_card enters aguardando_aprovacao, also create
    # a CQ task on the linked CRM variação so the variação cannot be approved
    # (and SKU generated) until CQ signs off.
    if entity_type == "pd_card" and new_stage == "aguardando_aprovacao":
        card = await db.pd_cards.find_one(
            {"id": entity_id, "tenant_id": tenant_id}, {"_id": 0}
        )
        if card and card.get("amostra_variacao_id"):
            mirror = await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="variacao",
                entity_id=card["amostra_variacao_id"],
                title="Aprovação CQ pendente (vinculada ao Card P&D)",
                description=f"Card P&D {card.get('numero_completo', '')} aguarda aprovação do CQ.",
                category="qa",
                blocking=True,
                blocks_stages=["aprovada"],
                due_in_days=3,
                created_by=user,
                metadata={
                    "trigger": "pd_aguardando_aprovacao_mirror",
                    "pd_card_id": entity_id,
                    "amostra_id": card.get("amostra_id"),
                    "task_type": "approval",
                    "priority": "alta",
                },
            )
            created.append(mirror)

    return created


# ======================================================================
#   QUERY HELPERS
# ======================================================================

async def list_tasks_for_entity(tenant_id: str, entity_type: str, entity_id: str) -> List[dict]:
    return await db.workflow_tasks.find(
        {
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "is_deleted": {"$ne": True},
        },
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)


async def list_tasks_filtered(
    tenant_id: str,
    *,
    status: Optional[str] = None,
    responsible_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    blocking: Optional[bool] = None,
    overdue: Optional[bool] = None,
    due_within_days: Optional[int] = None,
    task_type: Optional[str] = None,
) -> List[dict]:
    query: Dict[str, Any] = {"tenant_id": tenant_id, "is_deleted": {"$ne": True}}
    if status:
        query["status"] = status
    if responsible_id:
        query["responsible_id"] = responsible_id
    if entity_type:
        query["entity_type"] = entity_type
    if blocking is not None:
        query["blocking"] = blocking
    if task_type:
        query["task_type"] = task_type
    if overdue:
        query["status"] = {"$in": list(TASK_OPEN_STATUSES)}
        query["due_date"] = {"$lt": datetime.now(timezone.utc).isoformat()}
    elif due_within_days is not None:
        now = datetime.now(timezone.utc)
        query["status"] = {"$in": list(TASK_OPEN_STATUSES)}
        query["due_date"] = {
            "$gte": now.isoformat(),
            "$lte": (now + timedelta(days=due_within_days)).isoformat(),
        }
    return await db.workflow_tasks.find(query, {"_id": 0}).sort("due_date", 1).to_list(2000)


async def create_user_notification(
    *,
    tenant_id: str,
    user_id: str,
    title: str,
    message: str,
    notif_type: str = "workflow_task",
    metadata: Optional[dict] = None,
):
    if not user_id:
        return None
    notification = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "type": notif_type,
        "title": title,
        "message": message,
        "metadata": metadata or {},
        "read": False,
        "created_at": _now_iso(),
    }
    await db.notifications.insert_one(notification)
    return notification


async def _notify_task_closure(task: dict, *, actor: dict, action_label: str):
    recipients = {task.get("created_by"), task.get("responsible_id")}
    for user_id in recipients:
        if user_id and user_id != actor.get("id"):
            await create_user_notification(
                tenant_id=task["tenant_id"],
                user_id=user_id,
                title=f"Tarefa {action_label}: {task.get('display_code', task.get('title', ''))}",
                message=f"{actor.get('name', '')} registrou a conclusão da tarefa.",
                metadata={"task_id": task["id"], "entity_type": task["entity_type"], "entity_id": task["entity_id"]},
            )


async def _sync_pd_document_version_status(task: dict):
    if not task or task.get("entity_type") != "pd_document":
        return

    version_id = task.get("entity_id")
    if not version_id:
        return

    doc_version = await db.pd_document_versions.find_one({"id": version_id}, {"_id": 0})
    if not doc_version:
        return

    approval_tasks = await db.workflow_tasks.find(
        {
            "tenant_id": task["tenant_id"],
            "entity_type": "pd_document",
            "entity_id": version_id,
            "task_type": "approval",
        },
        {"_id": 0},
    ).to_list(100)
    if not approval_tasks:
        return

    now = _now_iso()
    rejected = [t for t in approval_tasks if t.get("status") == "concluida" and t.get("decision") == "rejected"]
    if rejected:
        await db.pd_document_versions.update_one(
            {"id": version_id},
            {"$set": {
                "status": "reprovado",
                "active_for_operation": False,
                "approved_at": None,
                "updated_at": now,
                "approval_summary": _approval_summary(approval_tasks),
            }}
        )
        return

    pending = [t for t in approval_tasks if t.get("status") != "concluida"]
    if pending:
        await db.pd_document_versions.update_one(
            {"id": version_id},
            {"$set": {
                "status": "em_revisao",
                "updated_at": now,
                "approval_summary": _approval_summary(approval_tasks),
            }}
        )
        return

    if not all(t.get("decision") == "approved" for t in approval_tasks):
        return

    await db.pd_document_versions.update_many(
        {
            "tenant_id": doc_version["tenant_id"],
            "pd_request_id": doc_version["pd_request_id"],
            "doc_type": doc_version["doc_type"],
            "id": {"$ne": version_id},
            "status": "aprovado",
        },
        {"$set": {"status": "substituido", "active_for_operation": False, "updated_at": now}}
    )
    await db.pd_document_versions.update_one(
        {"id": version_id},
        {
            "$set": {
                "status": "aprovado",
                "active_for_operation": True,
                "approved_at": now,
                "updated_at": now,
                "approval_summary": _approval_summary(approval_tasks),
            }
        }
    )


async def check_workflow_due_notifications_for_tenant(tenant_id: str) -> int:
    now = datetime.now(timezone.utc)
    created = 0
    tasks = await db.workflow_tasks.find(
        {
            "tenant_id": tenant_id,
            "status": {"$in": list(TASK_OPEN_STATUSES)},
            "responsible_id": {"$ne": ""},
        },
        {"_id": 0},
    ).to_list(5000)

    for task in tasks:
        due_date = task.get("due_date")
        if not due_date:
            continue
        try:
            due_dt = datetime.fromisoformat(str(due_date).replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        flags = task.get("notification_flags") or {}
        if due_dt < now and not flags.get("overdue_at"):
            await create_user_notification(
                tenant_id=tenant_id,
                user_id=task.get("responsible_id", ""),
                title=f"Tarefa em atraso: {task.get('display_code', task.get('title', ''))}",
                message=f"Prazo vencido em {due_dt.date().isoformat()}",
                metadata={"task_id": task["id"], "entity_type": task["entity_type"], "entity_id": task["entity_id"]},
            )
            await db.workflow_tasks.update_one(
                {"id": task["id"], "tenant_id": tenant_id},
                {"$set": {"notification_flags.overdue_at": _now_iso(), "status": "em_atraso", "updated_at": _now_iso()}},
            )
            created += 1
            continue

        hours_until_due = (due_dt - now).total_seconds() / 3600
        if 0 <= hours_until_due <= 24 and not flags.get("due_1d_at"):
            await create_user_notification(
                tenant_id=tenant_id,
                user_id=task.get("responsible_id", ""),
                title=f"Tarefa vence em ate 1 dia: {task.get('title', '')}",
                message=f"Prazo: {due_dt.date().isoformat()}",
                metadata={"task_id": task["id"], "entity_type": task["entity_type"], "entity_id": task["entity_id"]},
            )
            await db.workflow_tasks.update_one(
                {"id": task["id"], "tenant_id": tenant_id},
                {"$set": {"notification_flags.due_1d_at": _now_iso()}},
            )
            created += 1

        # Auto-escalate blocking tasks overdue > 3 days
        if due_dt < now and task.get("blocking") and not task.get("escalated"):
            delta_days = (now - due_dt).days
            if delta_days >= 3:
                await db.workflow_tasks.update_one(
                    {"id": task["id"], "tenant_id": tenant_id},
                    {"$set": {"escalated": True, "escalated_at": _now_iso(), "updated_at": _now_iso()}},
                )

    return created


async def check_followup_notifications_for_tenant(tenant_id: str):
    """R19: Notify commercial users when order follow-up marcos (1m/3m/6m) are reached."""
    now = datetime.now(timezone.utc).isoformat()
    orders = await db.orders.find(
        {
            "tenant_id": tenant_id,
            "status": "concluido",
            "followups": {"$elemMatch": {"notificado": False, "vence_em": {"$lte": now}}},
        },
        {"_id": 0, "id": 1, "numero_pedido": 1, "followups": 1, "cliente": 1, "created_by": 1},
    ).to_list(500)

    for order in orders:
        for i, fu in enumerate(order.get("followups", [])):
            if fu.get("notificado") or fu.get("vence_em", "9999") > now:
                continue
            cliente_nome = (order.get("cliente") or {}).get("nome") or (order.get("cliente") or {}).get("razao_social", "")
            await create_user_notification(
                tenant_id=tenant_id,
                user_id=order.get("created_by", ""),
                notif_type="followup",
                title=f"Follow-up {fu['marco']} — Pedido #{order.get('numero_pedido', '')}",
                message=f"Marco de {fu['marco']} atingido para o pedido #{order.get('numero_pedido', '')} — {cliente_nome}",
                metadata={"order_id": order["id"], "marco": fu["marco"]},
            )
            await db.orders.update_one(
                {"id": order["id"]},
                {"$set": {f"followups.{i}.notificado": True}},
            )


async def run_workflow_notification_scheduler():
    await asyncio.sleep(45)
    while True:
        try:
            tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(500)
            for tenant in tenants:
                await check_workflow_due_notifications_for_tenant(tenant["id"])
                await check_followup_notifications_for_tenant(tenant["id"])
        except Exception as exc:  # pragma: no cover
            logger.error(f"Workflow notification scheduler error: {exc}")
        await asyncio.sleep(3600)
