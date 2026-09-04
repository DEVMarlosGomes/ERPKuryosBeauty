"""
Categorias — Cadastro de Categorias de Produto (R22)
=====================================================

Lista fechada e governada de categorias. Cada categoria tem um CAT3 único
(3 letras maiúsculas) que compõe o SKU: [CAT3]-[CLI4]-[SEQ4].

Criação passa por fluxo de aprovação:
  solicitação (P&D / gestor) → aprovação (admin / sócio)

CAT3 duplicado é bloqueado com mensagem identificando a categoria existente.
Categoria aprovada só fica ativa após aprovação — log imutável de quem
solicitou, quem aprovou, data e justificativa.
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from rbac import require_roles, ADMIN_ONLY, PD_FULL, COMERCIAL_FULL

logger = logging.getLogger(__name__)

categorias_router = APIRouter(prefix="/api/cadastros", tags=["categorias"])

# ---- module-level state (injected via init_categorias) ----
db = None
_get_current_user = None
_new_id = None
_now_iso = None

# Roles that may request a new category
_SOLICITAR_ROLES = PD_FULL | COMERCIAL_FULL
# Roles that may approve (admin/sócio only)
_APROVAR_ROLES = ADMIN_ONLY


def init_categorias(database, get_current_user_fn, new_id_fn, now_iso_fn):
    global db, _get_current_user, _new_id, _now_iso
    db = database
    _get_current_user = get_current_user_fn
    _new_id = new_id_fn
    _now_iso = now_iso_fn
    logger.info("Categorias module initialized")


async def create_categorias_indexes():
    await db.categorias.create_index(
        [("tenant_id", 1), ("cat3", 1)], unique=True
    )
    await db.categorias.create_index([("tenant_id", 1), ("status", 1)])


# ======================================================================
#   SCHEMAS
# ======================================================================

class CategoriaRequest(BaseModel):
    cat3: str          # 3 uppercase letters
    nome: str
    justificativa: str


class CategoriaApprove(BaseModel):
    justificativa: Optional[str] = ""


class CategoriaUpdate(BaseModel):
    nome: Optional[str] = None
    justificativa: Optional[str] = None
    status: Optional[str] = None


# ======================================================================
#   HELPERS
# ======================================================================

def _validate_cat3(cat3: str) -> str:
    cat3 = cat3.upper().strip()
    if not re.match(r"^[A-Z]{3}$", cat3):
        raise HTTPException(status_code=400, detail="CAT3 deve ter exatamente 3 letras maiúsculas (ex: CAP, BSP)")
    return cat3


# ======================================================================
#   ENDPOINTS
# ======================================================================

@categorias_router.get("/categorias")
async def list_categorias(
    request: Request,
    status: Optional[str] = None,
):
    """Lista todas as categorias do tenant. Filtra por status se fornecido."""
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    cursor = db.categorias.find(query, {"_id": 0}).sort("cat3", 1)
    items = await cursor.to_list(500)
    return {"categorias": items, "total": len(items)}


@categorias_router.get("/categorias/{cat3}")
async def get_categoria(cat3: str, request: Request):
    """Detalhe de uma categoria pelo código CAT3."""
    user = await _get_current_user(request)
    cat3 = _validate_cat3(cat3)
    doc = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Categoria {cat3} não encontrada")
    return doc


@categorias_router.post("/categorias", status_code=201)
async def request_categoria(data: CategoriaRequest, request: Request):
    """
    Solicita criação de nova categoria.
    Fluxo: P&D solicita → admin aprova.
    CAT3 duplicado é bloqueado citando a categoria existente.
    """
    user = await _get_current_user(request)
    require_roles(user, _SOLICITAR_ROLES)

    cat3 = _validate_cat3(data.cat3)
    nome = data.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome da categoria é obrigatório")
    if not data.justificativa.strip():
        raise HTTPException(status_code=400, detail="Justificativa é obrigatória")

    existing = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"CAT3 '{cat3}' já está em uso pela categoria '{existing['nome']}' (status: {existing['status']})"
        )

    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "cat3": cat3,
        "nome": nome,
        "status": "pendente",
        "solicitado_por": user.get("name", ""),
        "solicitado_por_id": user["id"],
        "solicitado_em": now,
        "aprovado_por": None,
        "aprovado_por_id": None,
        "aprovado_em": None,
        "justificativa": data.justificativa.strip(),
        "created_at": now,
        "updated_at": now,
    }
    await db.categorias.insert_one(doc)
    doc.pop("_id", None)
    logger.info(f"Categoria {cat3} solicitada por {user.get('name')} — aguardando aprovação")
    return {"categoria": doc, "msg": f"Categoria {cat3} criada com status 'pendente'. Aguardando aprovação do administrador."}


@categorias_router.post("/categorias/{cat3}/approve")
async def approve_categoria(cat3: str, data: CategoriaApprove, request: Request):
    """
    Aprova uma categoria pendente (admin/sócio only).
    Registro imutável: quem aprovou, quando e justificativa.
    """
    user = await _get_current_user(request)
    require_roles(user, _APROVAR_ROLES)

    cat3 = _validate_cat3(cat3)
    doc = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Categoria {cat3} não encontrada")
    if doc["status"] == "ativa":
        raise HTTPException(status_code=409, detail=f"Categoria {cat3} já está ativa")
    if doc["status"] != "pendente":
        raise HTTPException(status_code=409, detail=f"Categoria {cat3} está com status '{doc['status']}' — apenas 'pendente' pode ser aprovada")

    now = _now_iso()
    await db.categorias.update_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3},
        {"$set": {
            "status": "ativa",
            "aprovado_por": user.get("name", ""),
            "aprovado_por_id": user["id"],
            "aprovado_em": now,
            "justificativa_aprovacao": (data.justificativa or "").strip(),
            "updated_at": now,
        }},
    )
    updated = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    logger.info(f"Categoria {cat3} aprovada por {user.get('name')}")
    return {"categoria": updated, "msg": f"Categoria {cat3} aprovada e ativa."}


@categorias_router.put("/categorias/{cat3}")
async def update_categoria(cat3: str, data: CategoriaUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, _APROVAR_ROLES)

    cat3 = _validate_cat3(cat3)
    doc = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Categoria {cat3} nao encontrada")

    payload = data.model_dump(exclude_unset=True)
    updates = {"updated_at": _now_iso()}
    for field in ("nome", "justificativa", "status"):
        if field in payload:
            updates[field] = (payload[field] or "").strip()

    await db.categorias.update_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3},
        {"$set": updates},
    )
    updated = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    return {"categoria": updated, "msg": f"Categoria {cat3} atualizada."}


@categorias_router.post("/categorias/{cat3}/inactivate")
async def inactivate_categoria(cat3: str, request: Request):
    """Inativa uma categoria ativa (admin only). Não afeta SKUs existentes."""
    user = await _get_current_user(request)
    require_roles(user, _APROVAR_ROLES)

    cat3 = _validate_cat3(cat3)
    doc = await db.categorias.find_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Categoria {cat3} não encontrada")
    if doc["status"] != "ativa":
        raise HTTPException(status_code=409, detail=f"Apenas categorias ativas podem ser inativadas")

    # Guard: block inactivation if any active SKUs use this CAT3
    sku_count = await db.skus.count_documents(
        {"tenant_id": user["tenant_id"], "cat3": cat3, "status": "ativo"}
    )
    if sku_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Categoria {cat3} possui {sku_count} SKU(s) ativos — inative os SKUs antes de inativar a categoria"
        )

    now = _now_iso()
    await db.categorias.update_one(
        {"tenant_id": user["tenant_id"], "cat3": cat3},
        {"$set": {"status": "inativa", "updated_at": now}},
    )
    return {"msg": f"Categoria {cat3} inativada. SKUs existentes não foram alterados."}
