"""
Compras Module — KURYOS ERP

Passo 1 (Entidades): 6 coleções MongoDB imutáveis (sem DELETE em nenhuma delas).
  compras_fornecedores        — cadastro de fornecedores + homologação
  compras_itens               — catálogo de itens compráveis
  compras_condicoes_comerciais — condições de preço/prazo (imutável: sem PUT)
  compras_pos                 — Pedidos de Compra (PO-YYYY-NNN)
  compras_mrp_rodadas         — rodadas de MRP
  compras_demandas            — intermediário MRP → PO

Passo 2 (Fornecedores + Homologação):
  POST   /fornecedores                         — cadastrar (CNPJ validado)
  GET    /fornecedores                         — listar (filtros: status_homologacao, categoria)
  GET    /fornecedores/{id}                    — detalhe
  PUT    /fornecedores/{id}                    — atualizar cadastro (não homologação)
  POST   /fornecedores/{id}/homologacao/iniciar
  POST   /fornecedores/{id}/homologacao/decidir
  POST   /fornecedores/{id}/homologacao/suspender
  POST   /fornecedores/{id}/incrementar-rnc   — chamado pelo módulo CQ

Legado (Ordens de Compra vinculadas a Kickoff/BOM):
  GET    /boms
  POST   /ordens
  GET    /ordens
  GET    /ordens/{oc_id}
  PUT    /ordens/{oc_id}
  DELETE /ordens/{oc_id}  (admin only, rascunho/cancelada)

Invariantes:
  — Nenhum registro das 6 novas coleções pode ser deletado (→ 405)
  — compras_condicoes_comerciais: sem endpoint PUT (imutável após criação)
  — PO imutável após emissão (cancelar + nova PO para alterar)
  — CNPJ: dígito verificador obrigatório (→ 422 se inválido)
"""
import io
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from rbac import require_roles
from workflow_engine import audit_log, next_sequence, create_workflow_task


compras_router = APIRouter(prefix="/api/compras")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_compras(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def new_id() -> str:
    return new_id_func()


def now_iso() -> str:
    return now_iso_func()


# ══════════════════════════════════════════════════════════════════════════════
#   LEGADO — Ordens de Compra vinculadas a Kickoff/BOM
# ══════════════════════════════════════════════════════════════════════════════

OC_STATUSES = {"rascunho", "enviada", "confirmada", "entregue", "cancelada"}
OC_STATUS_LABELS = {
    "rascunho": "Rascunho",
    "enviada": "Enviada",
    "confirmada": "Confirmada",
    "entregue": "Entregue",
    "cancelada": "Cancelada",
}

COMPRAS_WRITE_ROLES = {"admin", "compras", "engenharia_produto"}
COMPRAS_READ_ROLES = {"admin", "compras", "engenharia_produto", "lider_pd", "qa", "sales_ops"}


class OCCreateInput(BaseModel):
    kickoff_id: str
    bom_item_id: str
    fornecedor_id: str
    quantidade: float
    unidade: str
    preco_unitario_rs: float
    data_necessidade: Optional[str] = None
    observacoes: Optional[str] = ""


class OCUpdateInput(BaseModel):
    quantidade: Optional[float] = None
    unidade: Optional[str] = None
    preco_unitario_rs: Optional[float] = None
    data_necessidade: Optional[str] = None
    status: Optional[str] = None
    observacoes: Optional[str] = None
    fornecedor_id: Optional[str] = None


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _add_business_days(start: datetime, days: int) -> datetime:
    if days <= 0:
        return start
    cursor = start
    remaining = days
    while remaining > 0:
        cursor = cursor - timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor


async def _get_kickoff_or_404(kickoff_id: str, tenant_id: str) -> dict:
    kickoff = await db.kickoffs.find_one({"id": kickoff_id, "tenant_id": tenant_id}, {"_id": 0})
    if not kickoff:
        raise HTTPException(status_code=404, detail="Kickoff nao encontrado.")
    return kickoff


async def _ensure_kickoff_aprovado(kickoff_id: str, tenant_id: str) -> dict:
    kickoff = await _get_kickoff_or_404(kickoff_id, tenant_id)
    if kickoff.get("status") != "aprovado":
        raise HTTPException(
            status_code=400,
            detail=f"Ordem de Compra exige Kickoff aprovado. Status atual: {kickoff.get('status')}.",
        )
    return kickoff


def _find_bom_line(kickoff: dict, bom_item_id: str) -> Optional[Dict[str, Any]]:
    bom = kickoff.get("bom") or []
    for line in bom:
        if line.get("codigo_interno") == bom_item_id or line.get("id") == bom_item_id:
            return line
    return None


async def _ensure_supplier_homologado(fornecedor_id: str, tenant_id: str) -> dict:
    forn = await db.homologacao_fornecedores.find_one(
        {"id": fornecedor_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not forn:
        raise HTTPException(status_code=404, detail="Fornecedor nao encontrado.")
    if forn.get("status") not in {"homologado", "em_avaliacao"}:
        raise HTTPException(
            status_code=400,
            detail=f"Fornecedor com status '{forn.get('status')}' nao pode receber novas Ordens de Compra.",
        )
    return forn


async def _generate_oc_number(tenant_id: str) -> str:
    seq = await next_sequence(tenant_id, "ordem_compra", start=0)
    return f"OC-{datetime.now(timezone.utc).year}-{seq:04d}"


def _calc_data_necessidade(kickoff: dict) -> Optional[str]:
    bloco2 = kickoff.get("bloco2") or {}
    entrega_str = bloco2.get("data_entrega_contratada")
    lead = bloco2.get("lead_time_producao_dias_uteis")
    entrega = _parse_iso_date(entrega_str)
    if not entrega or not lead:
        return None
    necessidade = _add_business_days(entrega, int(lead))
    return necessidade.date().isoformat()


def _decorate_oc(oc: dict) -> dict:
    out = dict(oc)
    out["status_label"] = OC_STATUS_LABELS.get(oc.get("status", ""), oc.get("status", ""))
    return out


@compras_router.get("/boms")
async def list_boms_for_compras(request: Request, kickoff_id: Optional[str] = None):
    user = await get_current_user(request)
    require_roles(user, COMPRAS_READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"], "status": "aprovado"}
    if kickoff_id:
        query["id"] = kickoff_id
    cursor = db.kickoffs.find(query, {"_id": 0}).sort("approved_at", -1)
    docs = await cursor.to_list(500)
    boms = []
    for ko in docs:
        boms.append({
            "kickoff_id": ko["id"],
            "numero_kickoff": ko.get("numero_kickoff"),
            "cliente": ko.get("cliente"),
            "projeto_vinculado": ko.get("projeto_vinculado"),
            "approved_at": ko.get("approved_at"),
            "bom": ko.get("bom") or [],
        })
    return {"boms": boms, "count": len(boms)}


@compras_router.post("/ordens")
async def create_oc(data: OCCreateInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, COMPRAS_WRITE_ROLES)
    kickoff = await _ensure_kickoff_aprovado(data.kickoff_id, user["tenant_id"])
    bom_line = _find_bom_line(kickoff, data.bom_item_id)
    if not bom_line:
        raise HTTPException(
            status_code=400,
            detail=f"Item '{data.bom_item_id}' nao encontrado no BOM do Kickoff {kickoff.get('numero_kickoff')}.",
        )
    if data.quantidade <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser maior que zero.")
    if data.preco_unitario_rs < 0:
        raise HTTPException(status_code=400, detail="Preco unitario nao pode ser negativo.")
    fornecedor = await _ensure_supplier_homologado(data.fornecedor_id, user["tenant_id"])
    data_necessidade = data.data_necessidade or _calc_data_necessidade(kickoff)
    numero_oc = await _generate_oc_number(user["tenant_id"])
    oc_doc = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "numero_oc": numero_oc,
        "kickoff_id": kickoff["id"],
        "numero_kickoff": kickoff.get("numero_kickoff"),
        "projeto_id": kickoff.get("projeto_id"),
        "bom_item_id": data.bom_item_id,
        "bom_item_descricao": bom_line.get("descricao"),
        "bom_item_tipo": bom_line.get("tipo"),
        "fornecedor_id": fornecedor["id"],
        "fornecedor_nome": fornecedor.get("razao_social", ""),
        "fornecedor_cnpj": fornecedor.get("cnpj", ""),
        "quantidade": float(data.quantidade),
        "unidade": data.unidade,
        "preco_unitario_rs": float(data.preco_unitario_rs),
        "valor_total_rs": float(data.quantidade) * float(data.preco_unitario_rs),
        "data_necessidade": data_necessidade,
        "status": "rascunho",
        "observacoes": data.observacoes or "",
        "created_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "updated_at": now_iso(),
    }
    await db.ordens_compra.insert_one(oc_doc)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="oc_created",
        entity_type="ordem_compra",
        entity_id=oc_doc["id"],
        before=None,
        after={"numero_oc": numero_oc, "kickoff_id": kickoff["id"], "fornecedor_id": fornecedor["id"]},
    )
    oc_doc.pop("_id", None)
    return _decorate_oc(oc_doc)


@compras_router.get("/ordens")
async def list_ocs(
    request: Request,
    status: Optional[str] = None,
    kickoff_id: Optional[str] = None,
    fornecedor_id: Optional[str] = None,
):
    user = await get_current_user(request)
    require_roles(user, COMPRAS_READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if kickoff_id:
        query["kickoff_id"] = kickoff_id
    if fornecedor_id:
        query["fornecedor_id"] = fornecedor_id
    cursor = db.ordens_compra.find(query, {"_id": 0}).sort("created_at", -1)
    docs = await cursor.to_list(1000)
    return {"ordens": [_decorate_oc(d) for d in docs], "count": len(docs)}


@compras_router.get("/ordens/{oc_id}")
async def get_oc(oc_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, COMPRAS_READ_ROLES)
    doc = await db.ordens_compra.find_one({"id": oc_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Ordem de Compra nao encontrada.")
    return _decorate_oc(doc)


@compras_router.put("/ordens/{oc_id}")
async def update_oc(oc_id: str, data: OCUpdateInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, COMPRAS_WRITE_ROLES)
    existing = await db.ordens_compra.find_one(
        {"id": oc_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Ordem de Compra nao encontrada.")
    if existing.get("status") in {"entregue", "cancelada"}:
        raise HTTPException(
            status_code=400,
            detail=f"Ordem de Compra com status '{existing.get('status')}' nao pode ser editada.",
        )
    update_doc: Dict[str, Any] = {"updated_at": now_iso()}
    payload = data.dict(exclude_unset=True)
    if "status" in payload:
        new_status = payload["status"]
        if new_status not in OC_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status '{new_status}' invalido.")
        update_doc["status"] = new_status
    if "fornecedor_id" in payload and payload["fornecedor_id"]:
        forn = await _ensure_supplier_homologado(payload["fornecedor_id"], user["tenant_id"])
        update_doc["fornecedor_id"] = forn["id"]
        update_doc["fornecedor_nome"] = forn.get("razao_social", "")
        update_doc["fornecedor_cnpj"] = forn.get("cnpj", "")
    for field in ("quantidade", "unidade", "preco_unitario_rs", "data_necessidade", "observacoes"):
        if field in payload:
            update_doc[field] = payload[field]
    if "quantidade" in update_doc or "preco_unitario_rs" in update_doc:
        qtd = update_doc.get("quantidade", existing.get("quantidade", 0))
        preco = update_doc.get("preco_unitario_rs", existing.get("preco_unitario_rs", 0))
        update_doc["valor_total_rs"] = float(qtd) * float(preco)
    await db.ordens_compra.update_one(
        {"id": oc_id, "tenant_id": user["tenant_id"]},
        {"$set": update_doc},
    )
    new_doc = await db.ordens_compra.find_one(
        {"id": oc_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="oc_updated",
        entity_type="ordem_compra",
        entity_id=oc_id,
        before={k: existing.get(k) for k in update_doc.keys()},
        after={k: new_doc.get(k) for k in update_doc.keys()},
    )
    return _decorate_oc(new_doc)


@compras_router.delete("/ordens/{oc_id}")
async def delete_oc(oc_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, {"admin"})
    existing = await db.ordens_compra.find_one(
        {"id": oc_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Ordem de Compra nao encontrada.")
    if existing.get("status") not in {"rascunho", "cancelada"}:
        raise HTTPException(
            status_code=400,
            detail="Apenas Ordens de Compra em rascunho ou canceladas podem ser excluidas.",
        )
    await db.ordens_compra.delete_one({"id": oc_id, "tenant_id": user["tenant_id"]})
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="oc_deleted",
        entity_type="ordem_compra",
        entity_id=oc_id,
        before=existing,
        after=None,
    )
    return {"deleted": True}


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 1 — ENTIDADES (6 coleções + índices)
# ══════════════════════════════════════════════════════════════════════════════

CATEGORIAS_FORNECEDOR = {
    "MP Química", "Fragrância", "Frasco", "Tampa", "Válvula",
    "Rótulo", "Cartucho", "Display", "Caixa", "Celofane", "Outros",
}

STATUS_HOMOLOGACAO = {"nao_iniciada", "em_processo", "homologado", "suspenso", "reprovado"}
STATUS_CADASTRO    = {"ativo", "inativo", "bloqueado"}
STATUS_PO          = {"rascunho", "emitida", "confirmada", "parcialmente_recebida", "recebida", "encerrada", "cancelada"}
STATUS_MRP         = {"gerada", "em_revisao", "aprovada", "parcialmente_aprovada", "descartada"}
STATUS_DEMANDA     = {"pendente", "em_cotacao", "po_emitida", "cancelada"}

# Roles
_CMP_FULL   = {"admin", "compras"}
_CMP_CQ     = {"admin", "qa", "lider_pd", "compras"}
_CMP_WRITE  = {"admin", "compras", "engenharia_produto"}
_CMP_READ   = {"admin", "compras", "engenharia_produto", "lider_pd", "qa", "sales_ops", "formulador"}


async def create_compras_indexes():
    """Create all Compras module indexes. Called once during server startup."""
    base_cols = [
        "compras_fornecedores",
        "compras_itens",
        "compras_condicoes_comerciais",
        "compras_pos",
        "compras_mrp_rodadas",
        "compras_demandas",
    ]
    for col in base_cols:
        await db[col].create_index("tenant_id")
        await db[col].create_index([("tenant_id", 1), ("created_at", -1)])

    # Fornecedores
    await db.compras_fornecedores.create_index(
        [("tenant_id", 1), ("cnpj_normalizado", 1)], unique=True, sparse=True
    )
    await db.compras_fornecedores.create_index([("tenant_id", 1), ("status_cadastro", 1)])
    await db.compras_fornecedores.create_index([("tenant_id", 1), ("homologacao.status", 1)])
    await db.compras_fornecedores.create_index([("tenant_id", 1), ("codigo_interno", 1)])

    # Itens
    await db.compras_itens.create_index([("tenant_id", 1), ("categoria", 1)])

    # Condições comerciais
    await db.compras_condicoes_comerciais.create_index([("tenant_id", 1), ("fornecedor_id", 1)])
    await db.compras_condicoes_comerciais.create_index([("tenant_id", 1), ("item_id", 1)])

    # POs
    await db.compras_pos.create_index([("tenant_id", 1), ("status", 1)])
    await db.compras_pos.create_index([("tenant_id", 1), ("fornecedor_id", 1)])
    await db.compras_pos.create_index(
        [("tenant_id", 1), ("numero_po", 1)], unique=True, sparse=True
    )

    # MRP
    await db.compras_mrp_rodadas.create_index([("tenant_id", 1), ("status", 1)])

    # Demandas
    await db.compras_demandas.create_index([("tenant_id", 1), ("status", 1)])
    await db.compras_demandas.create_index([("tenant_id", 1), ("mrp_rodada_id", 1)])
    await db.compras_demandas.create_index([("tenant_id", 1), ("po_id", 1)])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_cnpj(cnpj: str) -> bool:
    """Verifica dígitos verificadores do CNPJ."""
    digits = re.sub(r"\D", "", cnpj)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False

    def _digit(nums: str, weights: List[int]) -> int:
        s = sum(int(n) * w for n, w in zip(nums, weights))
        r = s % 11
        return 0 if r < 2 else 11 - r

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return (
        int(digits[12]) == _digit(digits[:12], w1)
        and int(digits[13]) == _digit(digits[:13], w2)
    )


def _normalize_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


async def _next_for_code(tenant_id: str) -> str:
    seq = await next_sequence(tenant_id, "compras_fornecedores", start=0)
    return f"FOR-{seq:04d}"


async def _get_for_or_404(forn_id: str, tenant_id: str) -> dict:
    doc = await db.compras_fornecedores.find_one(
        {"id": forn_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")
    return doc


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _date_plus_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


# ── 405 guards — novas coleções nunca deletam ──────────────────────────────────

@compras_router.delete("/fornecedores/{forn_id}")
async def bloquear_delete_fornecedor(forn_id: str):
    raise HTTPException(
        status_code=405,
        detail="Fornecedores não podem ser excluídos. Use inativação (status_cadastro=inativo) ou bloqueio.",
    )


@compras_router.delete("/itens/{item_id}")
async def bloquear_delete_item(item_id: str):
    raise HTTPException(status_code=405, detail="Itens não podem ser excluídos.")


@compras_router.delete("/condicoes-comerciais/{cond_id}")
async def bloquear_delete_condicao(cond_id: str):
    raise HTTPException(status_code=405, detail="Condições comerciais são imutáveis e não podem ser excluídas.")


@compras_router.delete("/pos/{po_id}")
async def bloquear_delete_po(po_id: str):
    raise HTTPException(status_code=405, detail="POs não podem ser excluídas. Cancele com motivo registrado.")


@compras_router.delete("/mrp/{mrp_id}")
async def bloquear_delete_mrp(mrp_id: str):
    raise HTTPException(status_code=405, detail="Rodadas MRP não podem ser excluídas.")


@compras_router.get("/demandas")
async def listar_demandas(
    request: Request,
    status: Optional[str] = Query(None),
    mrp_rodada_id: Optional[str] = Query(None),
    urgente: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if mrp_rodada_id:
        query["mrp_rodada_id"] = mrp_rodada_id
    if urgente is not None:
        query["urgente"] = urgente
    total = await db.compras_demandas.count_documents(query)
    docs = await db.compras_demandas.find(query, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return {"demandas": docs, "total": total, "limit": limit, "offset": offset}


@compras_router.get("/demandas/{demanda_id}")
async def detalhar_demanda(demanda_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    doc = await db.compras_demandas.find_one({"id": demanda_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Demanda não encontrada.")
    return doc


@compras_router.delete("/demandas/{demanda_id}")
async def bloquear_delete_demanda(demanda_id: str):
    raise HTTPException(status_code=405, detail="Demandas não podem ser excluídas.")


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 2 — FORNECEDORES (CRUD + Homologação)
# ══════════════════════════════════════════════════════════════════════════════

# ── Pydantic models ────────────────────────────────────────────────────────────

class EnderecoInput(BaseModel):
    cep: str = ""
    logradouro: str = ""
    numero: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""


class ContatoInput(BaseModel):
    nome: str
    cargo: str = ""
    telefone: str = ""
    email: str = ""
    whatsapp: str = ""
    principal_compras: bool = False


class FornecedorCreate(BaseModel):
    razao_social: str
    nome_fantasia: str = ""
    cnpj: str
    ie: str = ""
    im: str = ""
    endereco: Optional[EnderecoInput] = None
    contatos: List[ContatoInput] = []
    categorias: List[str] = []


class FornecedorUpdate(BaseModel):
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    ie: Optional[str] = None
    im: Optional[str] = None
    endereco: Optional[EnderecoInput] = None
    contatos: Optional[List[ContatoInput]] = None
    categorias: Optional[List[str]] = None
    status_cadastro: Optional[str] = None


class HomologacaoDecidirInput(BaseModel):
    decisao: str                        # homologado | reprovado
    justificativa: Optional[str] = None
    validade_dias: int = 365


class HomologacaoSuspenderInput(BaseModel):
    motivo: str


class IncrementarRNCInput(BaseModel):
    rnc_id: str
    classificacao: str                  # critica | maior | menor


# ── POST /fornecedores ─────────────────────────────────────────────────────────

@compras_router.post("/fornecedores", status_code=201)
async def criar_fornecedor(data: FornecedorCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    if not _validate_cnpj(data.cnpj):
        raise HTTPException(status_code=422, detail="CNPJ inválido — dígito verificador incorreto.")

    cnpj_norm = _normalize_cnpj(data.cnpj)
    existing = await db.compras_fornecedores.find_one(
        {"tenant_id": tenant_id, "cnpj_normalizado": cnpj_norm}
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"CNPJ já cadastrado (fornecedor: {existing.get('codigo_interno')}).",
        )

    codigo_interno = await _next_for_code(tenant_id)
    forn_id = new_id()
    contatos = [
        {**c.dict(), "id": new_id()} for c in data.contatos
    ]

    doc = {
        "id": forn_id,
        "tenant_id": tenant_id,
        "codigo_interno": codigo_interno,
        "razao_social": data.razao_social,
        "nome_fantasia": data.nome_fantasia,
        "cnpj": data.cnpj,
        "cnpj_normalizado": cnpj_norm,
        "ie": data.ie,
        "im": data.im,
        "endereco": data.endereco.dict() if data.endereco else {},
        "contatos": contatos,
        "categorias": data.categorias,
        "homologacao": {
            "status": "nao_iniciada",
            "data_homologacao": None,
            "proxima_reavaliacao": None,
            "documentos_file_ids": [],
            "historico_rncs_count": 0,
            "historico_rncs_criticas_12m": 0,
        },
        "status_cadastro": "ativo",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "log_auditoria": [
            {
                "acao": "fornecedor_criado",
                "por_id": user["id"],
                "por_nome": user.get("name", ""),
                "em": now_iso(),
            }
        ],
    }
    await db.compras_fornecedores.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ── GET /fornecedores ──────────────────────────────────────────────────────────

@compras_router.get("/fornecedores")
async def listar_fornecedores(
    request: Request,
    status_homologacao: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    status_cadastro: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status_homologacao:
        query["homologacao.status"] = status_homologacao
    if categoria:
        query["categorias"] = categoria
    if status_cadastro:
        query["status_cadastro"] = status_cadastro
    if q:
        query["$or"] = [
            {"razao_social": {"$regex": q, "$options": "i"}},
            {"nome_fantasia": {"$regex": q, "$options": "i"}},
            {"cnpj_normalizado": {"$regex": q, "$options": "i"}},
            {"codigo_interno": {"$regex": q, "$options": "i"}},
        ]

    total = await db.compras_fornecedores.count_documents(query)
    docs = await db.compras_fornecedores.find(query, {"_id": 0}).sort(
        "created_at", -1
    ).skip(offset).limit(limit).to_list(limit)

    return {"fornecedores": docs, "total": total, "limit": limit, "offset": offset}


# ── GET /fornecedores/{id} ─────────────────────────────────────────────────────

@compras_router.get("/fornecedores/{forn_id}")
async def detalhar_fornecedor(forn_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    doc = await _get_for_or_404(forn_id, user["tenant_id"])
    return doc


# ── PUT /fornecedores/{id} ─────────────────────────────────────────────────────

@compras_router.put("/fornecedores/{forn_id}")
async def atualizar_fornecedor(forn_id: str, data: FornecedorUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    existing = await _get_for_or_404(forn_id, tenant_id)

    payload = data.dict(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    if "status_cadastro" in payload and payload["status_cadastro"] not in STATUS_CADASTRO:
        raise HTTPException(
            status_code=422,
            detail=f"status_cadastro inválido. Use: {sorted(STATUS_CADASTRO)}",
        )

    updates: Dict[str, Any] = {"updated_at": now_iso()}
    for field in ("razao_social", "nome_fantasia", "ie", "im", "categorias", "status_cadastro"):
        if field in payload:
            updates[field] = payload[field]
    if "endereco" in payload and payload["endereco"] is not None:
        updates["endereco"] = payload["endereco"]
    if "contatos" in payload and payload["contatos"] is not None:
        contatos_novos = []
        for c in payload["contatos"]:
            c.setdefault("id", new_id())
            contatos_novos.append(c)
        updates["contatos"] = contatos_novos

    log_entry = {
        "acao": "cadastro_atualizado",
        "campos": list(updates.keys()),
        "por_id": user["id"],
        "por_nome": user.get("name", ""),
        "em": now_iso(),
    }
    await db.compras_fornecedores.update_one(
        {"id": forn_id, "tenant_id": tenant_id},
        {"$set": updates, "$push": {"log_auditoria": log_entry}},
    )
    return await _get_for_or_404(forn_id, tenant_id)


# ── POST /fornecedores/{id}/homologacao/iniciar ───────────────────────────────

@compras_router.post("/fornecedores/{forn_id}/homologacao/iniciar")
async def iniciar_homologacao(forn_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    doc = await _get_for_or_404(forn_id, tenant_id)
    status_atual = doc["homologacao"]["status"]
    if status_atual in {"em_processo", "homologado"}:
        raise HTTPException(
            status_code=400,
            detail=f"Processo de homologação já está '{status_atual}'. Não é possível reiniciar.",
        )

    log_entry = {
        "acao": "homologacao_iniciada",
        "por_id": user["id"],
        "por_nome": user.get("name", ""),
        "em": now_iso(),
    }
    await db.compras_fornecedores.update_one(
        {"id": forn_id, "tenant_id": tenant_id},
        {
            "$set": {
                "homologacao.status": "em_processo",
                "updated_at": now_iso(),
            },
            "$push": {"log_auditoria": log_entry},
        },
    )

    await create_workflow_task(
        tenant_id=tenant_id,
        entity_type="compras_fornecedor",
        entity_id=forn_id,
        title=f"CMP-08 Homologar Fornecedor — {doc['codigo_interno']} {doc['razao_social']}",
        description=(
            f"Processo de homologação iniciado para {doc['razao_social']} ({doc['cnpj']}). "
            f"Avalie documentação, realize auditoria e decida: homologado ou reprovado."
        ),
        category="qa",
        blocking=False,
        due_in_days=30,
        created_by=user,
        metadata={"task_type": "approval", "module_origin": "compras"},
    )

    return await _get_for_or_404(forn_id, tenant_id)


# ── POST /fornecedores/{id}/homologacao/decidir ───────────────────────────────

@compras_router.post("/fornecedores/{forn_id}/homologacao/decidir")
async def decidir_homologacao(forn_id: str, data: HomologacaoDecidirInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_CQ)
    tenant_id = user["tenant_id"]

    if data.decisao not in {"homologado", "reprovado"}:
        raise HTTPException(
            status_code=422,
            detail="decisao deve ser 'homologado' ou 'reprovado'.",
        )
    if data.decisao == "reprovado" and not (data.justificativa or "").strip():
        raise HTTPException(
            status_code=422,
            detail="justificativa é obrigatória quando decisao=reprovado.",
        )

    doc = await _get_for_or_404(forn_id, tenant_id)
    if doc["homologacao"]["status"] != "em_processo":
        raise HTTPException(
            status_code=400,
            detail=f"Homologação só pode ser decidida quando status='em_processo'. Status atual: '{doc['homologacao']['status']}'.",
        )

    hoje = _today_iso()
    hom_updates: Dict[str, Any] = {
        "homologacao.status": data.decisao,
        "updated_at": now_iso(),
    }
    if data.decisao == "homologado":
        proxima = _date_plus_days(data.validade_dias)
        hom_updates["homologacao.data_homologacao"] = hoje
        hom_updates["homologacao.proxima_reavaliacao"] = proxima

    log_entry = {
        "acao": f"homologacao_{data.decisao}",
        "justificativa": data.justificativa or "",
        "por_id": user["id"],
        "por_nome": user.get("name", ""),
        "em": now_iso(),
    }
    await db.compras_fornecedores.update_one(
        {"id": forn_id, "tenant_id": tenant_id},
        {"$set": hom_updates, "$push": {"log_auditoria": log_entry}},
    )

    if data.decisao == "homologado":
        proxima = hom_updates["homologacao.proxima_reavaliacao"]
        await create_workflow_task(
            tenant_id=tenant_id,
            entity_type="compras_fornecedor",
            entity_id=forn_id,
            title=f"CMP-09 Reavaliar Fornecedor — {doc['codigo_interno']} {doc['razao_social']}",
            description=(
                f"Reavaliação periódica de {doc['razao_social']} programada para {proxima}. "
                f"Verifique documentação, RNCs e performance de entrega."
            ),
            category="qa",
            blocking=False,
            due_in_days=max(data.validade_dias - 30, 1),
            created_by=user,
            metadata={"task_type": "standard", "module_origin": "compras", "data_reavaliacao": proxima},
        )

    return await _get_for_or_404(forn_id, tenant_id)


# ── POST /fornecedores/{id}/homologacao/suspender ─────────────────────────────

@compras_router.post("/fornecedores/{forn_id}/homologacao/suspender")
async def suspender_homologacao(forn_id: str, data: HomologacaoSuspenderInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_CQ)
    tenant_id = user["tenant_id"]

    if not data.motivo.strip():
        raise HTTPException(status_code=422, detail="motivo é obrigatório para suspender.")

    doc = await _get_for_or_404(forn_id, tenant_id)
    if doc["homologacao"]["status"] == "suspenso":
        raise HTTPException(status_code=400, detail="Fornecedor já está suspenso.")

    log_entry = {
        "acao": "homologacao_suspensa",
        "motivo": data.motivo.strip(),
        "por_id": user["id"],
        "por_nome": user.get("name", ""),
        "em": now_iso(),
    }
    await db.compras_fornecedores.update_one(
        {"id": forn_id, "tenant_id": tenant_id},
        {
            "$set": {
                "homologacao.status": "suspenso",
                "updated_at": now_iso(),
            },
            "$push": {"log_auditoria": log_entry},
        },
    )

    return await _get_for_or_404(forn_id, tenant_id)


# ── POST /fornecedores/{id}/incrementar-rnc ───────────────────────────────────
# Chamado pelo módulo CQ ao criar RNC de fornecedor.

@compras_router.post("/fornecedores/{forn_id}/incrementar-rnc")
async def incrementar_rnc(forn_id: str, data: IncrementarRNCInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_CQ | {"qa"})
    tenant_id = user["tenant_id"]

    doc = await _get_for_or_404(forn_id, tenant_id)

    inc_fields: Dict[str, Any] = {"homologacao.historico_rncs_count": 1}
    if data.classificacao == "critica":
        inc_fields["homologacao.historico_rncs_criticas_12m"] = 1

    log_entry = {
        "acao": "rnc_registrada",
        "rnc_id": data.rnc_id,
        "classificacao": data.classificacao,
        "por_id": user["id"],
        "por_nome": user.get("name", ""),
        "em": now_iso(),
    }
    await db.compras_fornecedores.update_one(
        {"id": forn_id, "tenant_id": tenant_id},
        {
            "$inc": inc_fields,
            "$set": {"updated_at": now_iso()},
            "$push": {"log_auditoria": log_entry},
        },
    )

    # Recarrega para checar threshold
    doc_atualizado = await _get_for_or_404(forn_id, tenant_id)
    criticas_12m = doc_atualizado["homologacao"].get("historico_rncs_criticas_12m", 0)

    if criticas_12m >= 3 and doc_atualizado["homologacao"]["status"] != "suspenso":
        motivo_auto = (
            f"Suspensão automática: {criticas_12m} RNCs críticas nos últimos 12 meses "
            f"(última: RNC {data.rnc_id})."
        )
        log_suspensao = {
            "acao": "homologacao_suspensa_automatica",
            "motivo": motivo_auto,
            "rnc_id": data.rnc_id,
            "por_id": "sistema",
            "por_nome": "Sistema Automático",
            "em": now_iso(),
        }
        await db.compras_fornecedores.update_one(
            {"id": forn_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "homologacao.status": "suspenso",
                    "updated_at": now_iso(),
                },
                "$push": {"log_auditoria": log_suspensao},
            },
        )
        await create_workflow_task(
            tenant_id=tenant_id,
            entity_type="compras_fornecedor",
            entity_id=forn_id,
            title=f"CMP-10 Fornecedor Suspenso Automaticamente — {doc['codigo_interno']} {doc['razao_social']}",
            description=(
                f"{doc['razao_social']} foi suspenso automaticamente após {criticas_12m} RNCs críticas "
                f"em 12 meses. Última: RNC {data.rnc_id}. "
                f"Avalie situação e decida sobre continuidade ou reprovação definitiva."
            ),
            category="qa",
            blocking=False,
            due_in_days=3,
            created_by=user,
            metadata={"task_type": "approval", "module_origin": "compras", "motivo": motivo_auto},
        )
        doc_atualizado = await _get_for_or_404(forn_id, tenant_id)

    return doc_atualizado


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 3 — ITENS DE COMPRA + CONDIÇÕES COMERCIAIS
# ══════════════════════════════════════════════════════════════════════════════

CATEGORIAS_ITEM   = {"mp", "fragrancia", "embalagem"}
FRETES_VALIDOS    = {"cif", "fob", "valor_fixo", "percentual"}

# ── Pydantic models ────────────────────────────────────────────────────────────

class ItemCompraCreate(BaseModel):
    codigo_interno: str
    descricao: str
    categoria: str                      # mp | fragrancia | embalagem
    sub_categoria: str = ""             # Frasco|Tampa|Válvula etc.
    unidade_compra: str                 # kg|L|un|rolo|caixa
    fator_conversao_producao: float = 1.0
    estoque_minimo: Optional[float] = None
    estoque_seguranca: float = 0.0
    lead_time_dias: int = 0
    requer_homologacao_cq: bool = True
    fornecedores_homologados: List[str] = []


class ItemCompraUpdate(BaseModel):
    descricao: Optional[str] = None
    sub_categoria: Optional[str] = None
    unidade_compra: Optional[str] = None
    fator_conversao_producao: Optional[float] = None
    estoque_minimo: Optional[float] = None
    estoque_seguranca: Optional[float] = None
    lead_time_dias: Optional[int] = None
    requer_homologacao_cq: Optional[bool] = None
    fornecedores_homologados: Optional[List[str]] = None


class CotacaoCreate(BaseModel):
    fornecedor_id: str
    preco_unitario: float
    preco_unitario_currency: str = "BRL"
    prazo_pagamento_texto: str          # "30 DDL"
    prazo_pagamento_dias: int
    prazo_entrega_dias_uteis: int
    moq: float = 1.0                    # minimum order quantity
    frete_tipo: str                     # cif|fob|valor_fixo|percentual
    frete_valor: float = 0.0
    valido_ate: Optional[str] = None    # ISO date (opcional)
    cotado_por_nome: Optional[str] = None


# ── PUT /condicoes-comerciais/{id} → 405 ────────────────────────────────────

@compras_router.put("/condicoes-comerciais/{cond_id}")
async def bloquear_put_condicao(cond_id: str):
    raise HTTPException(
        status_code=405,
        detail="Condições comerciais são imutáveis após criação. Registre uma nova cotação com POST /itens/{id}/cotar.",
    )


# ── POST /itens ───────────────────────────────────────────────────────────────

@compras_router.post("/itens", status_code=201)
async def criar_item(data: ItemCompraCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    if data.categoria not in CATEGORIAS_ITEM:
        raise HTTPException(
            status_code=422,
            detail=f"categoria inválida. Use: {sorted(CATEGORIAS_ITEM)}",
        )

    existing = await db.compras_itens.find_one(
        {"tenant_id": tenant_id, "codigo_interno": data.codigo_interno}
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Item com codigo_interno '{data.codigo_interno}' já existe.",
        )

    item_id = new_id()
    doc = {
        "id": item_id,
        "tenant_id": tenant_id,
        "codigo_interno": data.codigo_interno,
        "descricao": data.descricao,
        "categoria": data.categoria,
        "sub_categoria": data.sub_categoria,
        "unidade_compra": data.unidade_compra,
        "fator_conversao_producao": data.fator_conversao_producao,
        "estoque_minimo": data.estoque_minimo,
        "estoque_seguranca": data.estoque_seguranca,
        "lead_time_dias": data.lead_time_dias,
        "requer_homologacao_cq": data.requer_homologacao_cq,
        "fornecedores_homologados": data.fornecedores_homologados,
        "ultimo_preco_pago": None,          # calculado dinamicamente
        "created_at": now_iso(),
    }
    await db.compras_itens.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ── GET /itens ────────────────────────────────────────────────────────────────

@compras_router.get("/itens")
async def listar_itens(
    request: Request,
    categoria: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if categoria:
        query["categoria"] = categoria
    if q:
        query["$or"] = [
            {"descricao": {"$regex": q, "$options": "i"}},
            {"codigo_interno": {"$regex": q, "$options": "i"}},
        ]

    total = await db.compras_itens.count_documents(query)
    docs = await db.compras_itens.find(query, {"_id": 0}).sort(
        "descricao", 1
    ).skip(offset).limit(limit).to_list(limit)

    return {"itens": docs, "total": total, "limit": limit, "offset": offset}


# ── GET /itens/{id} ───────────────────────────────────────────────────────────

@compras_router.get("/itens/{item_id}")
async def detalhar_item(item_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    doc = await db.compras_itens.find_one({"id": item_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    # Última cotação por fornecedor
    ultimas_condicoes: Dict[str, dict] = {}
    conds = await db.compras_condicoes_comerciais.find(
        {"tenant_id": tenant_id, "item_id": item_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    for c in conds:
        fid = c.get("fornecedor_id")
        if fid and fid not in ultimas_condicoes:
            ultimas_condicoes[fid] = c

    # Fornecedores com dados
    fornecedores_info = []
    for fid, cond in ultimas_condicoes.items():
        forn = await db.compras_fornecedores.find_one(
            {"id": fid, "tenant_id": tenant_id}, {"_id": 0,
             "razao_social": 1, "codigo_interno": 1, "homologacao": 1}
        )
        fornecedores_info.append({
            "fornecedor_id": fid,
            "razao_social": forn.get("razao_social", "") if forn else "",
            "codigo_interno": forn.get("codigo_interno", "") if forn else "",
            "status_homologacao": (forn or {}).get("homologacao", {}).get("status", ""),
            "ultima_cotacao": cond,
        })

    # Último preço pago (PO recebida/encerrada mais recente com este item)
    ultimo_preco_pago = None
    po_recente = await db.compras_pos.find_one(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["recebida", "encerrada"]},
            "itens.item_id": item_id,
        },
        sort=[("created_at", -1)],
    )
    if po_recente:
        for it in po_recente.get("itens", []):
            if it.get("item_id") == item_id:
                ultimo_preco_pago = it.get("preco_unitario")
                break

    return {
        **doc,
        "ultimo_preco_pago": ultimo_preco_pago,
        "fornecedores": fornecedores_info,
        "total_cotacoes": len(conds),
    }


# ── PUT /itens/{id} ───────────────────────────────────────────────────────────

@compras_router.put("/itens/{item_id}")
async def atualizar_item(item_id: str, data: ItemCompraUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    existing = await db.compras_itens.find_one({"id": item_id, "tenant_id": tenant_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    payload = data.dict(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    await db.compras_itens.update_one(
        {"id": item_id, "tenant_id": tenant_id},
        {"$set": payload},
    )
    return await db.compras_itens.find_one({"id": item_id, "tenant_id": tenant_id}, {"_id": 0})


# ── POST /itens/{id}/cotar ───────────────────────────────────────────────────

@compras_router.post("/itens/{item_id}/cotar", status_code=201)
async def registrar_cotacao(item_id: str, data: CotacaoCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    item = await db.compras_itens.find_one({"id": item_id, "tenant_id": tenant_id})
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    forn = await db.compras_fornecedores.find_one(
        {"id": data.fornecedor_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not forn:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")

    if data.frete_tipo not in FRETES_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"frete_tipo inválido. Use: {sorted(FRETES_VALIDOS)}",
        )

    hoje = _today_iso()
    if data.valido_ate and data.valido_ate < hoje:
        raise HTTPException(
            status_code=422,
            detail=f"data de validade já expirada ({data.valido_ate} < {hoje}).",
        )

    cond_id = new_id()
    doc = {
        "id": cond_id,
        "tenant_id": tenant_id,
        "fornecedor_id": data.fornecedor_id,
        "fornecedor_nome": forn.get("razao_social", ""),
        "item_id": item_id,
        "item_descricao": item.get("descricao", ""),
        "preco_unitario": float(data.preco_unitario),
        "preco_unitario_currency": data.preco_unitario_currency,
        "prazo_pagamento_texto": data.prazo_pagamento_texto,
        "prazo_pagamento_dias": data.prazo_pagamento_dias,
        "prazo_entrega_dias_uteis": data.prazo_entrega_dias_uteis,
        "moq": float(data.moq),
        "frete_tipo": data.frete_tipo,
        "frete_valor": float(data.frete_valor),
        "valido_ate": data.valido_ate,
        "origem": "manual",
        "cotado_por_id": user["id"],
        "cotado_por_nome": data.cotado_por_nome or user.get("name", ""),
        "created_at": now_iso(),    # imutável — nunca sobrescrito
    }
    await db.compras_condicoes_comerciais.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ── GET /itens/{id}/historico-precos ─────────────────────────────────────────

@compras_router.get("/itens/{item_id}/historico-precos")
async def historico_precos(item_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    item = await db.compras_itens.find_one({"id": item_id, "tenant_id": tenant_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    # Todas as condições ordenadas por fornecedor + data desc
    todas = await db.compras_condicoes_comerciais.find(
        {"tenant_id": tenant_id, "item_id": item_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    # Calcular variacao_pct em relação à cotação anterior do mesmo fornecedor
    por_forn: Dict[str, List[dict]] = {}
    for c in todas:
        por_forn.setdefault(c["fornecedor_id"], []).append(c)

    historico_com_variacao: List[dict] = []
    for fid, conds in por_forn.items():
        # conds já ordenadas por created_at desc (mais recente primeiro)
        for i, c in enumerate(conds):
            c_out = dict(c)
            if i < len(conds) - 1:
                preco_anterior = conds[i + 1].get("preco_unitario", 0)
                preco_atual = c.get("preco_unitario", 0)
                if preco_anterior and preco_anterior > 0:
                    c_out["variacao_pct"] = round(
                        (preco_atual - preco_anterior) / preco_anterior * 100, 2
                    )
                else:
                    c_out["variacao_pct"] = None
            else:
                c_out["variacao_pct"] = None   # primeira cotação, sem anterior
            historico_com_variacao.append(c_out)

    # Ordenar geral por created_at desc
    historico_com_variacao.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # Último preço pago (PO recebida/encerrada mais recente)
    ultimo_preco_pago = None
    ultimo_preco_data = None
    po_recente = await db.compras_pos.find_one(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["recebida", "encerrada"]},
            "itens.item_id": item_id,
        },
        sort=[("created_at", -1)],
    )
    if po_recente:
        for it in po_recente.get("itens", []):
            if it.get("item_id") == item_id:
                ultimo_preco_pago = it.get("preco_unitario")
                ultimo_preco_data = po_recente.get("data_emissao") or po_recente.get("created_at")
                break

    # Comparativo por fornecedor — última cotação de cada um, ordenado por menor preço
    comparativo_fornecedores: List[dict] = []
    for fid, conds in por_forn.items():
        ultima = conds[0]   # mais recente
        forn = await db.compras_fornecedores.find_one(
            {"id": fid, "tenant_id": tenant_id},
            {"_id": 0, "razao_social": 1, "codigo_interno": 1, "homologacao.status": 1},
        )
        comparativo_fornecedores.append({
            "fornecedor_id": fid,
            "fornecedor_nome": ultima.get("fornecedor_nome", ""),
            "fornecedor_codigo": (forn or {}).get("codigo_interno", ""),
            "status_homologacao": (forn or {}).get("homologacao", {}).get("status", ""),
            "ultimo_preco": ultima.get("preco_unitario"),
            "data": ultima.get("created_at"),
            "prazo_entrega_dias_uteis": ultima.get("prazo_entrega_dias_uteis"),
            "moq": ultima.get("moq"),
            "valido_ate": ultima.get("valido_ate"),
            "vencida": bool(ultima.get("valido_ate") and ultima["valido_ate"] < _today_iso()),
        })

    comparativo_fornecedores.sort(key=lambda x: x.get("ultimo_preco") or float("inf"))

    return {
        "item": item,
        "historico": historico_com_variacao,
        "total_cotacoes": len(historico_com_variacao),
        "ultimo_preco_pago": ultimo_preco_pago,
        "ultimo_preco_data": ultimo_preco_data,
        "comparativo_fornecedores": comparativo_fornecedores,
    }


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 4 — MRP (ENGINE DE NECESSIDADES)
# ══════════════════════════════════════════════════════════════════════════════

# ── Pydantic models ────────────────────────────────────────────────────────────

class MRPBOMItem(BaseModel):
    item_id: str
    quantidade_por_unidade: float


class MRPOPInput(BaseModel):
    op_id: str
    op_numero: str
    sku_descricao: str = ""
    quantidade_op: float = 1
    data_necessidade: Optional[str] = None  # ISO date — prazo limite de disponibilidade
    bom_items: List[MRPBOMItem] = []


class MRPCalcularInput(BaseModel):
    ops_input: Optional[List[MRPOPInput]] = None
    horizonte_dias: int = Field(90, ge=7, le=365)


class MRPRevisarItemInput(BaseModel):
    item_id: str
    acao: str                               # "aprovar" | "ajustar" | "remover"
    quantidade_ajustada: Optional[float] = None
    justificativa: Optional[str] = None


# ── Helpers MRP ────────────────────────────────────────────────────────────────

async def _gerar_numero_mrp(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    seq = await next_sequence(tenant_id, f"compras_mrp_{year}", start=0)
    return f"MRP-{year}-{seq:03d}"


async def _get_mrp_or_404(mrp_id: str, tenant_id: str) -> dict:
    doc = await db.compras_mrp_rodadas.find_one(
        {"id": mrp_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Rodada MRP não encontrada.")
    return doc


def _business_days_delta(data_necessidade_str: str, lead_time: int, buffer: int = 2) -> tuple:
    """Retorna (data_limite_pedido_iso, urgente)."""
    hoje = datetime.now(timezone.utc).date()
    try:
        dn = datetime.fromisoformat(data_necessidade_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return None, False
    delta_dias = lead_time + buffer
    dl = dn - timedelta(days=delta_dias)
    return dl.isoformat(), dl < hoje


async def _resolve_compras_item_formula(tenant_id: str, formula_item: Dict[str, Any]) -> Optional[dict]:
    catalog_id = formula_item.get("catalog_id")
    codigo = (
        formula_item.get("codigo_interno")
        or formula_item.get("mp_codigo")
        or formula_item.get("codigo")
        or ""
    )
    nome = (
        formula_item.get("ingredient_name")
        or formula_item.get("nome_tecnico")
        or formula_item.get("nome_comercial")
        or ""
    )

    queries: List[Dict[str, Any]] = []
    if catalog_id:
        queries.extend([
            {"tenant_id": tenant_id, "catalog_id": catalog_id},
            {"tenant_id": tenant_id, "pd_catalog_id": catalog_id},
            {"tenant_id": tenant_id, "origem_id": catalog_id},
        ])
        catalog = await db.pd_catalog.find_one(
            {"tenant_id": tenant_id, "id": catalog_id},
            {"_id": 0, "codigo_interno": 1, "nome": 1},
        )
        if catalog:
            if catalog.get("codigo_interno"):
                codigo = codigo or catalog["codigo_interno"]
            if catalog.get("nome"):
                nome = nome or catalog["nome"]

    if codigo:
        queries.append({"tenant_id": tenant_id, "codigo_interno": codigo})
    if nome:
        queries.append({"tenant_id": tenant_id, "descricao": {"$regex": f"^{re.escape(nome)}$", "$options": "i"}})

    for query in queries:
        item = await db.compras_itens.find_one(query, {"_id": 0})
        if item:
            return item
    return None


def _quantidade_formula_por_unidade(formula_item: Dict[str, Any]) -> float:
    for key in ("quantidade_por_unidade", "quantidade_lote_padrao", "quantidade"):
        try:
            value = float(formula_item.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value

    try:
        pct = float(formula_item.get("percentage") or formula_item.get("percentual_mm") or 0)
    except (TypeError, ValueError):
        pct = 0
    return pct / 100 if pct > 0 else 0


async def _bom_from_op_tecnico(tenant_id: str, op: Dict[str, Any], quantidade_op: float) -> List[dict]:
    bom_items: List[dict] = []
    unresolved: List[dict] = []
    reviews = (op.get("tecnico") or {}).get("items") or []

    for review in reviews:
        for formula_item in review.get("itens_formula") or []:
            ci = await _resolve_compras_item_formula(tenant_id, formula_item)
            qtd_un = _quantidade_formula_por_unidade(formula_item)
            if not ci or qtd_un <= 0:
                unresolved.append({
                    "ingredient_name": formula_item.get("ingredient_name") or formula_item.get("mp_codigo") or "",
                    "catalog_id": formula_item.get("catalog_id"),
                    "motivo": "item_compras_nao_resolvido" if not ci else "quantidade_por_unidade_zerada",
                })
                continue
            bom_items.append({
                "item_id": ci["id"],
                "quantidade_por_unidade": qtd_un,
            })

    if unresolved:
        op.setdefault("_mrp_unresolved_items", []).extend(unresolved)
    return bom_items


async def _coletar_ops_planejadas_para_mrp(tenant_id: str, horizonte_dias: int) -> List[dict]:
    hoje = datetime.now(timezone.utc).date()
    limite = (hoje + timedelta(days=horizonte_dias)).isoformat()
    slots = await db.pcp_programacao.find(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["planejado", "em_execucao"]},
            "data_inicio": {"$lte": limite},
        },
        {"_id": 0},
    ).to_list(1000)

    ops_input: List[dict] = []
    seen_ops = set()
    for slot in slots:
        op_id = slot.get("op_id")
        if not op_id or op_id in seen_ops:
            continue
        op = await db.ops.find_one(
            {"id": op_id, "tenant_id": tenant_id, "status": {"$nin": ["concluida", "cancelada"]}},
            {"_id": 0},
        )
        if not op:
            continue
        seen_ops.add(op_id)
        quantidade_op = float(slot.get("qtd_planejada") or 0)
        if quantidade_op <= 0:
            items = op.get("items") or []
            quantidade_op = sum(float(item.get("qtd_planejada") or item.get("qtd") or 0) for item in items)
        if quantidade_op <= 0:
            quantidade_op = 1.0

        bom_items = await _bom_from_op_tecnico(tenant_id, op, quantidade_op)
        if not bom_items:
            continue

        ops_input.append({
            "op_id": op["id"],
            "op_numero": op.get("numero_op", ""),
            "sku_descricao": op.get("project_name") or (op.get("items") or [{}])[0].get("item", ""),
            "quantidade_op": quantidade_op,
            "data_necessidade": (slot.get("data_inicio") or slot.get("data_fim") or "")[:10] or None,
            "bom_items": bom_items,
            "origem": "pcp_programacao",
            "pcp_slot_id": slot.get("id"),
            "itens_nao_resolvidos": op.get("_mrp_unresolved_items", []),
        })
    return ops_input


async def _estoque_item_disponivel_para_mrp(tenant_id: str, estoque_item: Dict[str, Any]) -> bool:
    posicao_cq = estoque_item.get("posicao_cq") or estoque_item.get("cq_status") or "livre"
    if posicao_cq in {"quarentena", "reprovado"}:
        return False
    lote_id = estoque_item.get("cq_lote_id")
    if lote_id:
        ultimo_status_cq = await db.cq_status_lote.find_one(
            {"tenant_id": tenant_id, "lote_id": lote_id},
            sort=[("created_at", -1)],
        )
        if not ultimo_status_cq or ultimo_status_cq.get("status_novo") not in {"aprovado", "concessao"}:
            return False
    return True


async def _calcular_mrp(tenant_id: str, ops_input: Optional[List[dict]], disparado_por: dict, horizonte_dias: int = 90) -> dict:
    """
    Engine MRP semi-automático:
    1. Agregar necessidade bruta por item a partir das OPs
    2. Ler estoque disponível (WMS), descontando lotes reprovados pelo CQ
    3. Ler POs em trânsito (emitida|confirmada|parcialmente_recebida)
    4. Calcular necessidade líquida
    5. Camada de segurança (estoque_minimo)
    6. Respeitar MOQ do fornecedor preferencial
    7. Calcular data_limite_pedido e flag urgente
    8. Incluir itens com reposição de segurança sem OP
    """
    hoje = datetime.now(timezone.utc).date()

    # ── 1. Acumular necessidade bruta por item ─────────────────────────────────
    necessidades: Dict[str, Dict[str, Any]] = {}

    origem_demanda = "manual"
    if not ops_input:
        ops_input = await _coletar_ops_planejadas_para_mrp(tenant_id, horizonte_dias)
        origem_demanda = "pcp_programacao"

    if ops_input:
        for op in ops_input:
            for bom in op.get("bom_items", []):
                iid = bom["item_id"]
                qtd = bom["quantidade_por_unidade"] * op.get("quantidade_op", 1)
                if iid not in necessidades:
                    necessidades[iid] = {
                        "necessidade_bruta": 0.0,
                        "ops_origem": [],
                        "data_necessidade": None,
                    }
                necessidades[iid]["necessidade_bruta"] += qtd
                op_id = op.get("op_id", "")
                if op_id not in necessidades[iid]["ops_origem"]:
                    necessidades[iid]["ops_origem"].append(op_id)
                dn = op.get("data_necessidade")
                if dn:
                    if (not necessidades[iid]["data_necessidade"]
                            or dn < necessidades[iid]["data_necessidade"]):
                        necessidades[iid]["data_necessidade"] = dn

    # ── 2. Estoque disponível (WMS) — desconta lotes reprovados pelo CQ ────────
    estoque_items_raw = await db.estoque_items.find(
        {"tenant_id": tenant_id, "tipo_item": "mp"}, {"_id": 0}
    ).to_list(5000)

    estoque_por_item: Dict[str, float] = {}
    snapshot_estoque: Dict[str, float] = {}
    for ei in estoque_items_raw:
        # O mp_id é a chave de ligação com compras_itens.codigo_interno
        ref_key = ei.get("mp_id") or ei.get("id")
        if not ref_key:
            continue
        # Verificar último status CQ do lote para desconto
        aprovado = await _estoque_item_disponivel_para_mrp(tenant_id, ei)
        qty = ei.get("quantidade_atual", 0) if aprovado else 0.0
        estoque_por_item[ref_key] = estoque_por_item.get(ref_key, 0) + qty

    # ── 3. POs em trânsito ─────────────────────────────────────────────────────
    pos_transito = await db.compras_pos.find(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["emitida", "confirmada", "parcialmente_recebida"]},
        },
        {"_id": 0},
    ).to_list(1000)

    transito_por_item: Dict[str, float] = {}
    snapshot_pos_transito: Dict[str, float] = {}
    for po in pos_transito:
        for it in po.get("itens", []):
            iid = it.get("item_id")
            if not iid:
                continue
            sol = float(it.get("quantidade_solicitada", 0))
            rec = float(it.get("quantidade_recebida", 0))
            transito_por_item[iid] = transito_por_item.get(iid, 0) + max(0, sol - rec)

    # ── 4-7. Calcular sugestões por item em compras_itens ─────────────────────
    todos_itens = await db.compras_itens.find({"tenant_id": tenant_id}, {"_id": 0}).to_list(5000)
    todos_itens_map = {ci["id"]: ci for ci in todos_itens}

    itens_sugeridos: List[dict] = []

    async def _build_sugestao(item_id: str, ci: dict, necessidade_bruta: float,
                               ops_origem: List[str], data_necessidade_str: Optional[str],
                               motivo_base: str) -> Optional[dict]:
        estoque_disp = estoque_por_item.get(item_id, 0.0)
        em_transito  = transito_por_item.get(item_id, 0.0)
        necessidade_liquida = max(0.0, necessidade_bruta - estoque_disp - em_transito)
        motivo = motivo_base

        # Camada de segurança
        est_min = float(ci.get("estoque_minimo") or 0)
        est_seg = float(ci.get("estoque_seguranca") or 0)
        if est_min > 0:
            projecao = estoque_disp - necessidade_bruta
            if projecao < est_min:
                reposicao = est_min - projecao + est_seg
                if reposicao > necessidade_liquida:
                    necessidade_liquida = reposicao
                    motivo = ("demanda_op+reposicao" if necessidade_bruta > 0
                              else "reposicao_seguranca")

        if necessidade_liquida <= 0:
            return None

        # Fornecedor preferencial + MOQ
        fornecedor_preferencial_id = None
        moq = 1.0
        ultimo_po = await db.compras_pos.find_one(
            {
                "tenant_id": tenant_id,
                "itens.item_id": item_id,
                "status": {"$in": ["recebida", "encerrada"]},
            },
            sort=[("created_at", -1)],
        )
        if ultimo_po:
            fornecedor_preferencial_id = ultimo_po.get("fornecedor_id")

        ultima_cot = await db.compras_condicoes_comerciais.find_one(
            {
                "tenant_id": tenant_id,
                "item_id": item_id,
                **({"fornecedor_id": fornecedor_preferencial_id}
                   if fornecedor_preferencial_id else {}),
            },
            sort=[("created_at", -1)],
        )
        if ultima_cot:
            moq = float(ultima_cot.get("moq") or 1)
            if not fornecedor_preferencial_id:
                fornecedor_preferencial_id = ultima_cot.get("fornecedor_id")

        quantidade_sugerida = max(necessidade_liquida, moq)

        # Data limite pedido
        lead = int(ci.get("lead_time_dias") or 0)
        data_limite_pedido = None
        urgente = False
        if data_necessidade_str:
            data_limite_pedido, urgente = _business_days_delta(data_necessidade_str, lead)

        snapshot_estoque[item_id] = estoque_disp
        snapshot_pos_transito[item_id] = em_transito

        return {
            "item_id": item_id,
            "item_descricao": ci.get("descricao", ""),
            "categoria": ci.get("categoria", ""),
            "necessidade_bruta": round(necessidade_bruta, 4),
            "estoque_disponivel": round(estoque_disp, 4),
            "em_transito": round(em_transito, 4),
            "necessidade_liquida": round(necessidade_liquida, 4),
            "moq_fornecedor": moq,
            "quantidade_sugerida": round(quantidade_sugerida, 4),
            "data_limite_pedido": data_limite_pedido,
            "urgente": urgente,
            "motivo": motivo,
            "ops_origem": ops_origem,
            "fornecedor_preferencial_id": fornecedor_preferencial_id,
            # Campos de revisão PCP — preenchidos em /revisar-item
            "aprovado_pcp": None,
            "quantidade_ajustada": None,
            "justificativa_remocao": None,
        }

    # Itens com demanda de OP
    for item_id, dados in necessidades.items():
        ci = todos_itens_map.get(item_id)
        if not ci:
            continue
        sugestao = await _build_sugestao(
            item_id, ci,
            dados["necessidade_bruta"],
            dados["ops_origem"],
            dados.get("data_necessidade"),
            "demanda_op",
        )
        if sugestao:
            itens_sugeridos.append(sugestao)

    # Itens sem OP mas abaixo do estoque mínimo
    for item_id, ci in todos_itens_map.items():
        if item_id in necessidades:
            continue
        est_min = float(ci.get("estoque_minimo") or 0)
        if est_min <= 0:
            continue
        estoque_disp = estoque_por_item.get(item_id, 0.0)
        if estoque_disp >= est_min:
            continue
        sugestao = await _build_sugestao(
            item_id, ci, 0.0, [], None, "reposicao_seguranca"
        )
        if sugestao:
            itens_sugeridos.append(sugestao)

    # Ordenar: urgentes primeiro, depois por data_limite_pedido
    itens_sugeridos.sort(
        key=lambda x: (not x["urgente"], x.get("data_limite_pedido") or "9999-99-99")
    )

    return {
        "itens_sugeridos": itens_sugeridos,
        "snapshot_estoque": snapshot_estoque,
        "snapshot_pos_transito": snapshot_pos_transito,
        "ops_consideradas": [op.get("op_id", "") for op in (ops_input or [])],
        "origem_demanda": origem_demanda,
        "horizonte_dias": horizonte_dias,
        "itens_nao_resolvidos": [
            {"op_id": op.get("op_id"), **item}
            for op in (ops_input or [])
            for item in op.get("itens_nao_resolvidos", [])
        ],
    }


# ── POST /mrp/calcular ────────────────────────────────────────────────────────

@compras_router.post("/mrp/calcular", status_code=201)
async def calcular_mrp(data: MRPCalcularInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_FULL | {"engenharia_produto", "lider_pd"})
    tenant_id = user["tenant_id"]

    ops_raw = [op.dict() for op in data.ops_input] if data.ops_input else None
    resultado = await _calcular_mrp(tenant_id, ops_raw, user, data.horizonte_dias)

    numero_mrp = await _gerar_numero_mrp(tenant_id)
    mrp_id = new_id()

    doc = {
        "id": mrp_id,
        "tenant_id": tenant_id,
        "numero_mrp": numero_mrp,
        "status": "gerada",
        "ops_consideradas": resultado["ops_consideradas"],
        "origem_demanda": resultado["origem_demanda"],
        "horizonte_dias": resultado["horizonte_dias"],
        "itens_nao_resolvidos": resultado["itens_nao_resolvidos"],
        "snapshot_estoque": resultado["snapshot_estoque"],
        "snapshot_pos_transito": resultado["snapshot_pos_transito"],
        "itens_sugeridos": resultado["itens_sugeridos"],
        "aprovado_por_id": None,
        "aprovado_por_nome": None,
        "aprovado_em": None,
        "disparado_por_id": user["id"],
        "disparado_por_nome": user.get("name", ""),
        "created_at": now_iso(),
    }
    await db.compras_mrp_rodadas.insert_one(doc)
    doc.pop("_id", None)

    n_itens = len(resultado["itens_sugeridos"])
    n_urgentes = sum(1 for i in resultado["itens_sugeridos"] if i.get("urgente"))
    await create_workflow_task(
        tenant_id=tenant_id,
        entity_type="compras_mrp",
        entity_id=mrp_id,
        title=f"CMP-01 Revisar Rodada MRP — {numero_mrp} ({n_itens} itens, {n_urgentes} urgentes)",
        description=(
            f"Rodada MRP {numero_mrp} gerada com {n_itens} itens sugeridos "
            f"({n_urgentes} urgentes). Revise, ajuste quantidades e aprove a lista para emissão de demandas."
        ),
        category="compras",
        blocking=False,
        due_in_days=1,
        created_by=user,
        metadata={"task_type": "approval", "module_origin": "compras"},
    )

    return doc


# ── GET /mrp ──────────────────────────────────────────────────────────────────

@compras_router.get("/mrp")
async def listar_mrp(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        query["status"] = status

    total = await db.compras_mrp_rodadas.count_documents(query)
    docs = (
        await db.compras_mrp_rodadas.find(query, {"_id": 0, "itens_sugeridos": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
        .to_list(limit)
    )
    return {"rodadas": docs, "total": total, "limit": limit, "offset": offset}


# ── GET /mrp/{id} ─────────────────────────────────────────────────────────────

@compras_router.get("/mrp/{mrp_id}")
async def detalhar_mrp(mrp_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    return await _get_mrp_or_404(mrp_id, user["tenant_id"])


# ── PUT /mrp/{id}/revisar-item ────────────────────────────────────────────────

@compras_router.put("/mrp/{mrp_id}/revisar-item")
async def revisar_item_mrp(mrp_id: str, data: MRPRevisarItemInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_FULL | {"engenharia_produto", "lider_pd"})
    tenant_id = user["tenant_id"]

    if data.acao not in {"aprovar", "ajustar", "remover"}:
        raise HTTPException(
            status_code=422,
            detail="acao deve ser 'aprovar', 'ajustar' ou 'remover'.",
        )
    if data.acao == "remover" and not (data.justificativa or "").strip():
        raise HTTPException(
            status_code=422,
            detail="justificativa é obrigatória para acao=remover.",
        )

    doc = await _get_mrp_or_404(mrp_id, tenant_id)
    if doc["status"] in {"aprovada", "descartada"}:
        raise HTTPException(
            status_code=400,
            detail=f"Rodada MRP com status '{doc['status']}' não pode ser revisada.",
        )

    itens = doc.get("itens_sugeridos", [])
    idx = next((i for i, it in enumerate(itens) if it["item_id"] == data.item_id), None)
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{data.item_id}' não encontrado nesta rodada MRP.",
        )

    item = itens[idx]
    if data.acao == "aprovar":
        item["aprovado_pcp"] = True
        item["quantidade_ajustada"] = None
    elif data.acao == "ajustar":
        if not data.quantidade_ajustada or data.quantidade_ajustada <= 0:
            raise HTTPException(
                status_code=422,
                detail="quantidade_ajustada deve ser maior que zero para acao=ajustar.",
            )
        item["aprovado_pcp"] = True
        item["quantidade_ajustada"] = data.quantidade_ajustada
    else:  # remover
        item["aprovado_pcp"] = False
        item["justificativa_remocao"] = data.justificativa.strip()

    itens[idx] = item
    await db.compras_mrp_rodadas.update_one(
        {"id": mrp_id, "tenant_id": tenant_id},
        {"$set": {"itens_sugeridos": itens, "status": "em_revisao"}},
    )
    return await _get_mrp_or_404(mrp_id, tenant_id)


# ── POST /mrp/{id}/aprovar ────────────────────────────────────────────────────

@compras_router.post("/mrp/{mrp_id}/aprovar")
async def aprovar_mrp(mrp_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_FULL | {"engenharia_produto", "lider_pd"})
    tenant_id = user["tenant_id"]

    doc = await _get_mrp_or_404(mrp_id, tenant_id)
    if doc["status"] in {"aprovada", "descartada"}:
        raise HTTPException(
            status_code=400,
            detail=f"Rodada MRP já está '{doc['status']}'.",
        )

    itens = doc.get("itens_sugeridos", [])

    # Verificar pendências (aprovado_pcp == None)
    pendentes = [it["item_id"] for it in itens if it.get("aprovado_pcp") is None]
    if pendentes:
        raise HTTPException(
            status_code=400,
            detail=f"Há {len(pendentes)} item(ns) ainda não revisado(s): {pendentes[:5]}{'...' if len(pendentes) > 5 else ''}. Revise todos antes de aprovar.",
        )

    # Criar demandas para os itens aprovados
    itens_aprovados = [it for it in itens if it.get("aprovado_pcp") is True]
    demandas_criadas: List[str] = []
    agora = now_iso()
    for it in itens_aprovados:
        quantidade_final = it.get("quantidade_ajustada") or it.get("quantidade_sugerida", 0)
        demanda_id = new_id()
        demanda = {
            "id": demanda_id,
            "tenant_id": tenant_id,
            "mrp_rodada_id": mrp_id,
            "mrp_numero": doc.get("numero_mrp", ""),
            "item_id": it["item_id"],
            "item_descricao": it.get("item_descricao", ""),
            "quantidade": quantidade_final,
            "data_limite_pedido": it.get("data_limite_pedido"),
            "urgente": it.get("urgente", False),
            "motivo": it.get("motivo", ""),
            "fornecedor_selecionado_id": it.get("fornecedor_preferencial_id"),
            "condicao_comercial_id": None,
            "po_id": None,
            "status": "pendente",
            "created_at": agora,
        }
        await db.compras_demandas.insert_one(demanda)
        demandas_criadas.append(demanda_id)

    await db.compras_mrp_rodadas.update_one(
        {"id": mrp_id, "tenant_id": tenant_id},
        {
            "$set": {
                "status": "aprovada",
                "aprovado_por_id": user["id"],
                "aprovado_por_nome": user.get("name", ""),
                "aprovado_em": agora,
            }
        },
    )

    await create_workflow_task(
        tenant_id=tenant_id,
        entity_type="compras_mrp",
        entity_id=mrp_id,
        title=f"CMP-02 Emitir POs — {doc.get('numero_mrp', mrp_id)} ({len(demandas_criadas)} demandas)",
        description=(
            f"Rodada MRP {doc.get('numero_mrp', mrp_id)} aprovada por {user.get('name', '')}. "
            f"{len(demandas_criadas)} demanda(s) criada(s). Acesse Compras > Demandas para emitir os Pedidos de Compra."
        ),
        category="compras",
        blocking=False,
        due_in_days=1,
        created_by=user,
        metadata={"task_type": "standard", "module_origin": "compras"},
    )

    return {
        "mrp_id": mrp_id,
        "numero_mrp": doc.get("numero_mrp"),
        "status": "aprovada",
        "demandas_criadas": len(demandas_criadas),
        "demanda_ids": demandas_criadas,
    }


# ── GET /mrp/{id}/texto-disparo ───────────────────────────────────────────────

@compras_router.get("/mrp/{mrp_id}/texto-disparo")
async def texto_disparo_mrp(mrp_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    doc = await _get_mrp_or_404(mrp_id, tenant_id)
    itens = doc.get("itens_sugeridos", [])
    itens_aprovados = [it for it in itens if it.get("aprovado_pcp") is True]

    if not itens_aprovados:
        return {"blocos": [], "texto_completo": "Nenhum item aprovado nesta rodada MRP."}

    # Agrupar por fornecedor_preferencial_id
    por_fornecedor: Dict[str, List[dict]] = {}
    sem_fornecedor: List[dict] = []
    for it in itens_aprovados:
        fid = it.get("fornecedor_preferencial_id")
        if fid:
            por_fornecedor.setdefault(fid, []).append(it)
        else:
            sem_fornecedor.append(it)

    data_hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    blocos: List[dict] = []

    async def _build_bloco(forn_id: Optional[str], itens_forn: List[dict]) -> dict:
        if forn_id:
            forn = await db.compras_fornecedores.find_one(
                {"id": forn_id, "tenant_id": tenant_id},
                {"_id": 0, "razao_social": 1, "nome_fantasia": 1, "codigo_interno": 1},
            )
            forn_nome = (forn or {}).get("razao_social", forn_id) if forn else forn_id
        else:
            forn_nome = "Fornecedor a definir"

        # Sub-agrupar por categoria
        por_cat: Dict[str, List[dict]] = {}
        for it in itens_forn:
            por_cat.setdefault(it.get("categoria", "outros"), []).append(it)

        linhas_categoria: List[str] = []
        for cat, its in sorted(por_cat.items()):
            linhas_categoria.append(f"\n{cat.upper()}:")
            for it in its:
                qtd = it.get("quantidade_ajustada") or it.get("quantidade_sugerida", 0)
                urgente_tag = " ⚠️ URGENTE" if it.get("urgente") else ""
                linhas_categoria.append(
                    f"  • {it.get('item_descricao', it['item_id'])} — "
                    f"{qtd} unid{urgente_tag}"
                )
            if any(it.get("data_limite_pedido") for it in its):
                dlp = min(
                    it["data_limite_pedido"] for it in its if it.get("data_limite_pedido")
                )
                linhas_categoria.append(f"  Prazo limite do pedido: {dlp}")

        corpo = "\n".join(linhas_categoria)
        texto = (
            f"Pedido Kuryos — {forn_nome} — {data_hoje}\n"
            f"{corpo}\n\n"
            "Favor confirmar disponibilidade, preço e prazo de entrega.\n"
            "Kuryos Cosméticos — Compras"
        )
        return {
            "fornecedor_id": forn_id,
            "fornecedor_nome": forn_nome,
            "total_itens": len(itens_forn),
            "texto": texto,
        }

    for fid, its in por_fornecedor.items():
        blocos.append(await _build_bloco(fid, its))

    if sem_fornecedor:
        blocos.append(await _build_bloco(None, sem_fornecedor))

    texto_completo = "\n\n" + ("=" * 60) + "\n\n".join(b["texto"] for b in blocos)

    return {
        "mrp_id": mrp_id,
        "numero_mrp": doc.get("numero_mrp"),
        "data_geracao": data_hoje,
        "total_fornecedores": len(blocos),
        "blocos": blocos,
        "texto_completo": texto_completo.strip(),
    }


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 5 — PEDIDO DE COMPRA (PO)
# ══════════════════════════════════════════════════════════════════════════════

class POItemInput(BaseModel):
    item_id: str
    item_descricao: str = ""
    quantidade_solicitada: float
    unidade_compra: str
    preco_unitario: float
    frete_rateado: float = 0.0
    condicao_comercial_id: Optional[str] = None


class POCreate(BaseModel):
    fornecedor_id: str
    origem: str = "manual"
    ops_vinculadas: List[str] = []
    data_entrega_solicitada: Optional[str] = None
    prazo_pagamento_texto: str
    prazo_pagamento_dias: int
    itens: List[POItemInput]
    demanda_ids: Optional[List[str]] = None


class POUpdate(BaseModel):
    data_entrega_solicitada: Optional[str] = None
    prazo_pagamento_texto: Optional[str] = None
    prazo_pagamento_dias: Optional[int] = None
    itens: Optional[List[POItemInput]] = None


class POConfirmarInput(BaseModel):
    data_entrega_confirmada: str


class POCancelarInput(BaseModel):
    motivo: str


class POReceberItemInput(BaseModel):
    item_id: str
    quantidade_recebida: float


class POReceberParcialInput(BaseModel):
    nf_numero: str
    nf_data: str
    itens_recebidos: List[POReceberItemInput]


async def _gerar_numero_po(tenant_id: str) -> str:
    year = datetime.now(timezone.utc).year
    seq = await next_sequence(tenant_id, f"compras_po_{year}", start=1)
    return f"PO-{year}-{seq:03d}"


async def _get_po_or_404(po_id: str, tenant_id: str) -> dict:
    doc = await db.compras_pos.find_one({"id": po_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="PO não encontrada.")
    return doc


def _todos_itens_recebidos(itens: List[dict]) -> bool:
    return all(
        float(it.get("quantidade_recebida", 0)) >= float(it.get("quantidade_solicitada", 0))
        for it in itens
    )


async def _verificar_gatilho_financeiro(po: dict, tenant_id: str) -> None:
    if po.get("gatilho_financeiro_acionado"):
        return
    nfs = po.get("nfs_vinculadas", [])
    if not nfs:
        return
    lote_aprovado = any(n.get("status_cq") == "aprovado" for n in nfs)
    if not lote_aprovado:
        return
    prazo_dias = int(po.get("prazo_pagamento_dias") or 0)
    data_ref = nfs[-1].get("nf_data") or _today_iso()
    try:
        base = datetime.fromisoformat(data_ref.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        base = datetime.now(timezone.utc).date()
    data_vencimento = (base + timedelta(days=prazo_dias)).isoformat()
    await db.compras_pos.update_one(
        {"id": po["id"], "tenant_id": tenant_id},
        {"$set": {"gatilho_financeiro_acionado": True, "data_vencimento_pagamento": data_vencimento}},
    )


@compras_router.post("/pos", status_code=201)
async def criar_po(data: POCreate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    if not data.itens:
        raise HTTPException(status_code=422, detail="PO deve ter pelo menos 1 item.")

    forn = await db.compras_fornecedores.find_one(
        {"id": data.fornecedor_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not forn:
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado.")

    itens_doc = []
    for it in data.itens:
        valor_total_item = float(it.quantidade_solicitada) * float(it.preco_unitario) + float(it.frete_rateado)
        itens_doc.append({
            "id": new_id(),
            "item_id": it.item_id,
            "item_descricao": it.item_descricao,
            "quantidade_solicitada": float(it.quantidade_solicitada),
            "unidade_compra": it.unidade_compra,
            "preco_unitario": float(it.preco_unitario),
            "frete_rateado": float(it.frete_rateado),
            "valor_total_item": round(valor_total_item, 2),
            "condicao_comercial_id": it.condicao_comercial_id,
            "quantidade_recebida": 0.0,
            "status_cq_lote": None,
        })

    po_id = new_id()
    valor_total_po = round(sum(it["valor_total_item"] for it in itens_doc), 2)
    demandas_reservadas: List[str] = []

    if data.demanda_ids:
        seen_demanda_ids = list(dict.fromkeys(data.demanda_ids))
        demandas = await db.compras_demandas.find(
            {
                "id": {"$in": seen_demanda_ids},
                "tenant_id": tenant_id,
            },
            {"_id": 0},
        ).to_list(len(seen_demanda_ids))
        if len(demandas) != len(seen_demanda_ids):
            encontrados = {d["id"] for d in demandas}
            faltantes = [did for did in seen_demanda_ids if did not in encontrados]
            raise HTTPException(status_code=404, detail=f"Demanda(s) nao encontrada(s): {faltantes}")

        for demanda in demandas:
            if demanda.get("status") != "pendente" or demanda.get("po_id"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Demanda {demanda['id']} ja foi processada ou vinculada a uma PO.",
                )
            fornecedor_demanda = demanda.get("fornecedor_selecionado_id")
            if fornecedor_demanda and fornecedor_demanda != data.fornecedor_id:
                raise HTTPException(
                    status_code=422,
                    detail=f"Demanda {demanda['id']} pertence a outro fornecedor preferencial.",
                )

        for demanda in demandas:
            result = await db.compras_demandas.update_one(
                {
                    "id": demanda["id"],
                    "tenant_id": tenant_id,
                    "status": "pendente",
                    "$or": [{"po_id": None}, {"po_id": {"$exists": False}}],
                },
                {
                    "$set": {
                        "po_id": po_id,
                        "status": "po_reservada",
                        "reservado_por_id": user["id"],
                        "reservado_por_nome": user.get("name", ""),
                        "reservado_em": now_iso(),
                    }
                },
            )
            if getattr(result, "modified_count", 0) != 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Demanda {demanda['id']} foi alterada por outro usuario. Recarregue a tela.",
                )
            demandas_reservadas.append(demanda["id"])

    doc = {
        "id": po_id,
        "tenant_id": tenant_id,
        "numero_po": None,
        "fornecedor_id": data.fornecedor_id,
        "fornecedor_nome": forn.get("razao_social", ""),
        "fornecedor_cnpj": forn.get("cnpj", ""),
        "status": "rascunho",
        "origem": data.origem,
        "ops_vinculadas": data.ops_vinculadas,
        "demanda_ids": demandas_reservadas,
        "data_emissao": None,
        "data_entrega_solicitada": data.data_entrega_solicitada,
        "data_entrega_confirmada": None,
        "prazo_pagamento_texto": data.prazo_pagamento_texto,
        "prazo_pagamento_dias": data.prazo_pagamento_dias,
        "fornecedor_homologado": forn.get("homologacao", {}).get("status") == "homologado",
        "itens": itens_doc,
        "valor_total_po": valor_total_po,
        "compartilhamento": {
            "pdf_enviado": False, "pdf_enviado_em": None,
            "whatsapp_texto_gerado": False, "whatsapp_confirmado": False,
        },
        "nfs_vinculadas": [],
        "gatilho_financeiro_acionado": False,
        "data_vencimento_pagamento": None,
        "cancelado_motivo": None,
        "cancelado_por": None,
        "cancelado_em": None,
        "requer_aprovacao": False,
        "aprovado_por": None,
        "aprovado_em": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by_id": user["id"],
        "created_by_nome": user.get("name", ""),
        "log_auditoria": [{"acao": "po_criada", "por_id": user["id"], "por_nome": user.get("name", ""), "em": now_iso()}],
    }

    await db.compras_pos.insert_one(doc)

    if demandas_reservadas:
        await db.compras_demandas.update_many(
            {"id": {"$in": demandas_reservadas}, "tenant_id": tenant_id, "po_id": po_id},
            {"$set": {"status": "po_emitida", "po_numero": doc.get("numero_po"), "updated_at": now_iso()}},
        )

    doc.pop("_id", None)
    return doc


@compras_router.get("/pos")
async def listar_pos(
    request: Request,
    status: Optional[str] = Query(None),
    fornecedor_id: Optional[str] = Query(None),
    urgente: Optional[bool] = Query(None),
    origem: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        query["status"] = status
    if fornecedor_id:
        query["fornecedor_id"] = fornecedor_id
    if origem:
        query["origem"] = origem

    total = await db.compras_pos.count_documents(query)
    docs = await db.compras_pos.find(query, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)

    hoje = _today_iso()
    result = []
    for d in docs:
        d_out = dict(d)
        des = d.get("data_entrega_solicitada")
        d_out["urgente"] = bool(des and des < hoje and d.get("status") not in {"recebida", "encerrada", "cancelada"})
        if urgente is not None and d_out["urgente"] != urgente:
            continue
        result.append(d_out)

    return {"pos": result, "total": total, "limit": limit, "offset": offset}


@compras_router.get("/pos/{po_id}")
async def detalhar_po(po_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    doc = await _get_po_or_404(po_id, user["tenant_id"])
    hoje = _today_iso()
    doc["urgente"] = bool(
        doc.get("data_entrega_solicitada") and doc["data_entrega_solicitada"] < hoje
        and doc.get("status") not in {"recebida", "encerrada", "cancelada"}
    )
    return doc


@compras_router.put("/pos/{po_id}")
async def atualizar_po(po_id: str, data: POUpdate, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    po = await _get_po_or_404(po_id, tenant_id)
    if po["status"] != "rascunho":
        raise HTTPException(status_code=400, detail="PO imutável após emissão — cancele e emita nova PO.")

    payload = data.dict(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    updates: Dict[str, Any] = {"updated_at": now_iso()}
    for field in ("data_entrega_solicitada", "prazo_pagamento_texto", "prazo_pagamento_dias"):
        if field in payload:
            updates[field] = payload[field]

    if "itens" in payload and payload["itens"] is not None:
        itens_doc = []
        for it in payload["itens"]:
            valor_total_item = float(it["quantidade_solicitada"]) * float(it["preco_unitario"]) + float(it.get("frete_rateado", 0))
            itens_doc.append({
                "id": new_id(),
                "item_id": it["item_id"],
                "item_descricao": it.get("item_descricao", ""),
                "quantidade_solicitada": float(it["quantidade_solicitada"]),
                "unidade_compra": it["unidade_compra"],
                "preco_unitario": float(it["preco_unitario"]),
                "frete_rateado": float(it.get("frete_rateado", 0)),
                "valor_total_item": round(valor_total_item, 2),
                "condicao_comercial_id": it.get("condicao_comercial_id"),
                "quantidade_recebida": 0.0,
                "status_cq_lote": None,
            })
        updates["itens"] = itens_doc
        updates["valor_total_po"] = round(sum(i["valor_total_item"] for i in itens_doc), 2)

    log_entry = {"acao": "po_rascunho_editada", "por_id": user["id"], "por_nome": user.get("name", ""), "em": now_iso()}
    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": tenant_id},
        {"$set": updates, "$push": {"log_auditoria": log_entry}},
    )
    return await _get_po_or_404(po_id, tenant_id)


@compras_router.post("/pos/{po_id}/emitir")
async def emitir_po(po_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    po = await _get_po_or_404(po_id, tenant_id)
    if po["status"] != "rascunho":
        raise HTTPException(status_code=400, detail=f"Só é possível emitir PO em rascunho. Status: '{po['status']}'.")

    forn = await db.compras_fornecedores.find_one({"id": po["fornecedor_id"], "tenant_id": tenant_id}, {"_id": 0})
    status_hom = (forn or {}).get("homologacao", {}).get("status", "nao_iniciada")

    if status_hom == "reprovado":
        raise HTTPException(
            status_code=400,
            detail={"error": "hard_stop_fornecedor_reprovado", "message": "Fornecedor reprovado não pode receber Pedidos de Compra."},
        )

    log_entries = [{"acao": "po_emitida", "por_id": user["id"], "por_nome": user.get("name", ""), "em": now_iso()}]
    alerta_homologacao = None
    if status_hom != "homologado":
        alerta_homologacao = f"ALERTA: Fornecedor com status de homologação '{status_hom}'. PO emitida com ressalva."
        log_entries.append({"acao": "alerta_homologacao_incompleta", "status_homologacao": status_hom, "por_id": user["id"], "por_nome": user.get("name", ""), "em": now_iso()})

    numero_po = po.get("numero_po") or await _gerar_numero_po(tenant_id)
    agora = now_iso()

    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": tenant_id},
        {
            "$set": {"status": "emitida", "numero_po": numero_po, "data_emissao": agora, "fornecedor_homologado": status_hom == "homologado", "updated_at": agora},
            "$push": {"log_auditoria": {"$each": log_entries}},
        },
    )

    po_emitida = await _get_po_or_404(po_id, tenant_id)
    await create_workflow_task(
        tenant_id=tenant_id,
        entity_type="compras_po",
        entity_id=po_id,
        title=f"CMP-04 Aguardar Confirmação — {numero_po} ({po_emitida['fornecedor_nome']})",
        description=(
            f"PO {numero_po} emitida para {po_emitida['fornecedor_nome']}. "
            f"Valor: R$ {po_emitida['valor_total_po']:.2f}. SLA: 2 dias úteis."
        ),
        category="compras",
        blocking=False,
        due_in_days=2,
        created_by=user,
        metadata={"task_type": "standard", "module_origin": "compras"},
    )

    result = dict(po_emitida)
    if alerta_homologacao:
        result["_alerta"] = alerta_homologacao
    return result


@compras_router.get("/pos/{po_id}/pdf")
async def gerar_pdf_po(po_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    po = await _get_po_or_404(po_id, user["tenant_id"])
    numero_po = po.get("numero_po") or po_id

    buf = io.BytesIO()
    doc_pdf = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    t_st  = ParagraphStyle("T", parent=styles["Title"], fontSize=18, spaceAfter=4, textColor=rl_colors.HexColor("#0A0A0B"))
    h2_st = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceAfter=6, spaceBefore=12, textColor=rl_colors.HexColor("#0A0A0B"))
    n_st  = ParagraphStyle("N", parent=styles["Normal"], fontSize=9, spaceAfter=3, leading=13)
    s_st  = ParagraphStyle("S", parent=styles["Normal"], fontSize=7, textColor=rl_colors.HexColor("#737373"))

    elems = [
        Paragraph("Kuryos Cosméticos — Pedido de Compra", t_st),
        Paragraph(f"N° {numero_po} — Emitido em {(po.get('data_emissao') or 'Rascunho')[:10]}", n_st),
        Spacer(1, 5*mm),
        Paragraph("Fornecedor", h2_st),
        Paragraph(f"<b>Razão Social:</b> {po['fornecedor_nome']}", n_st),
        Paragraph(f"<b>CNPJ:</b> {po.get('fornecedor_cnpj', '—')}", n_st),
        Spacer(1, 4*mm),
        Paragraph("Itens do Pedido", h2_st),
    ]

    tbl_data = [["Item", "Qtd", "Un", "Preço Unit.", "Frete", "Total"]]
    for it in po.get("itens", []):
        tbl_data.append([
            it.get("item_descricao") or it.get("item_id", "—"),
            f"{it.get('quantidade_solicitada', 0):.3f}",
            it.get("unidade_compra", ""),
            f"R$ {it.get('preco_unitario', 0):.4f}",
            f"R$ {it.get('frete_rateado', 0):.2f}",
            f"R$ {it.get('valor_total_item', 0):.2f}",
        ])
    tbl_data.append(["", "", "", "", "TOTAL:", f"R$ {po.get('valor_total_po', 0):.2f}"])

    tbl = Table(tbl_data, colWidths=[75*mm, 18*mm, 14*mm, 25*mm, 18*mm, 25*mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), rl_colors.HexColor("#0A0A0B")),
        ("TEXTCOLOR", (0,0), (-1,0), rl_colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"),
        ("GRID", (0,0), (-1,-2), 0.4, rl_colors.HexColor("#E5E5E5")),
        ("FONTNAME", (4,-1), (-1,-1), "Helvetica-Bold"),
        ("TOPPADDING", (0,-1), (-1,-1), 8),
        ("LINEABOVE", (4,-1), (-1,-1), 0.8, rl_colors.HexColor("#0A0A0B")),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING", (0,0), (-1,0), 6),
    ]))
    elems.append(tbl)
    elems += [
        Spacer(1, 4*mm),
        Paragraph("Condições Comerciais", h2_st),
        Paragraph(f"<b>Prazo de Pagamento:</b> {po.get('prazo_pagamento_texto', '—')}", n_st),
        Paragraph(f"<b>Entrega Solicitada:</b> {po.get('data_entrega_solicitada') or '—'}", n_st),
        Spacer(1, 10*mm),
        Paragraph("Este documento representa o pedido oficial da Kuryos Cosméticos. Qualquer alteração deverá ser formalizada previamente.", s_st),
        Paragraph(f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC — {user.get('name', '')}", s_st),
    ]
    doc_pdf.build(elems)
    buf.seek(0)

    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": user["tenant_id"]},
        {"$set": {"compartilhamento.pdf_enviado": True, "compartilhamento.pdf_enviado_em": now_iso()}},
    )
    fname = f"PO_{numero_po.replace('-', '_')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@compras_router.get("/pos/{po_id}/whatsapp")
async def whatsapp_po(po_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    po = await _get_po_or_404(po_id, user["tenant_id"])
    numero_po = po.get("numero_po") or f"(rascunho {po_id[:8]})"

    linhas = [
        f"*Pedido de Compra — Kuryos Cosméticos*",
        f"N° {numero_po}",
        f"Data: {(po.get('data_emissao') or now_iso())[:10]}",
        f"Fornecedor: {po['fornecedor_nome']}",
        "",
        "*Itens:*",
    ]
    for it in po.get("itens", []):
        desc = it.get("item_descricao") or it.get("item_id", "—")
        linhas.append(
            f"• {desc}: {it.get('quantidade_solicitada', 0):.3f} {it.get('unidade_compra', '')} "
            f"× R$ {it.get('preco_unitario', 0):.4f} = R$ {it.get('valor_total_item', 0):.2f}"
        )
    linhas += [
        "",
        f"*Total: R$ {po.get('valor_total_po', 0):.2f}*",
        f"Prazo de Pagamento: {po.get('prazo_pagamento_texto', '—')}",
        f"Entrega Solicitada: {po.get('data_entrega_solicitada') or '—'}",
        "",
        "Por favor, confirmar disponibilidade, prazo e enviar NF.",
        "_Kuryos Cosméticos — Departamento de Compras_",
    ]

    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": user["tenant_id"]},
        {"$set": {"compartilhamento.whatsapp_texto_gerado": True}},
    )
    return {"numero_po": numero_po, "texto": "\n".join(linhas)}


@compras_router.post("/pos/{po_id}/confirmar")
async def confirmar_po(po_id: str, data: POConfirmarInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    po = await _get_po_or_404(po_id, tenant_id)
    if po["status"] != "emitida":
        raise HTTPException(status_code=400, detail=f"Só é possível confirmar PO emitida. Status: '{po['status']}'.")

    log_entry = {"acao": "po_confirmada", "data_entrega_confirmada": data.data_entrega_confirmada,
                 "por_id": user["id"], "por_nome": user.get("name", ""), "em": now_iso()}
    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": tenant_id},
        {"$set": {"status": "confirmada", "data_entrega_confirmada": data.data_entrega_confirmada, "updated_at": now_iso()},
         "$push": {"log_auditoria": log_entry}},
    )

    try:
        due_days = max(1, (datetime.fromisoformat(data.data_entrega_confirmada).date() - datetime.now(timezone.utc).date()).days)
    except (ValueError, AttributeError):
        due_days = 7

    po_conf = await _get_po_or_404(po_id, tenant_id)
    await create_workflow_task(
        tenant_id=tenant_id,
        entity_type="compras_po",
        entity_id=po_id,
        title=f"CMP-05 Acompanhar Entrega — {po_conf.get('numero_po', po_id)} ({po_conf['fornecedor_nome']})",
        description=f"PO confirmada. Entrega prevista: {data.data_entrega_confirmada}. Registre a NF ao receber.",
        category="compras",
        blocking=False,
        due_in_days=max(due_days, 1),
        created_by=user,
        metadata={"task_type": "standard", "module_origin": "compras"},
    )
    return po_conf


@compras_router.post("/pos/{po_id}/cancelar")
async def cancelar_po(po_id: str, data: POCancelarInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    if not data.motivo.strip():
        raise HTTPException(status_code=422, detail="motivo é obrigatório para cancelar a PO.")

    po = await _get_po_or_404(po_id, tenant_id)
    if po["status"] in {"recebida", "encerrada", "cancelada"}:
        raise HTTPException(status_code=400, detail=f"PO com status '{po['status']}' não pode ser cancelada.")

    agora = now_iso()
    log_entry = {"acao": "po_cancelada", "motivo": data.motivo.strip(), "por_id": user["id"], "por_nome": user.get("name", ""), "em": agora}
    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": tenant_id},
        {"$set": {"status": "cancelada", "cancelado_motivo": data.motivo.strip(), "cancelado_por": user.get("name", ""), "cancelado_em": agora, "updated_at": agora},
         "$push": {"log_auditoria": log_entry}},
    )
    return await _get_po_or_404(po_id, tenant_id)


@compras_router.post("/pos/{po_id}/receber-parcial")
async def receber_parcial_po(po_id: str, data: POReceberParcialInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_WRITE)
    tenant_id = user["tenant_id"]

    po = await _get_po_or_404(po_id, tenant_id)
    if po["status"] not in {"emitida", "confirmada", "parcialmente_recebida"}:
        raise HTTPException(status_code=400, detail=f"Recebimento não permitido para PO com status '{po['status']}'.")

    recebidos_map = {r.item_id: float(r.quantidade_recebida) for r in data.itens_recebidos}
    itens = po.get("itens", [])
    divergencias: List[str] = []

    for it in itens:
        iid = it.get("item_id")
        if iid in recebidos_map:
            nova_rec = float(it.get("quantidade_recebida", 0)) + recebidos_map[iid]
            it["quantidade_recebida"] = nova_rec
            sol = float(it.get("quantidade_solicitada", 0))
            if nova_rec < sol - 0.001:
                divergencias.append(f"{it.get('item_descricao', iid)}: solicitado {sol:.3f}, recebido {nova_rec:.3f}")

    novo_status = "recebida" if _todos_itens_recebidos(itens) else "parcialmente_recebida"
    nf_entry = {
        "nf_id": new_id(), "nf_numero": data.nf_numero, "nf_data": data.nf_data,
        "status_cq": None,
        "recebido_por_id": user["id"], "recebido_por_nome": user.get("name", ""), "recebido_em": now_iso(),
    }
    log_entry = {"acao": "recebimento_registrado", "nf_numero": data.nf_numero,
                 "itens": [{"item_id": r.item_id, "qtd": r.quantidade_recebida} for r in data.itens_recebidos],
                 "por_id": user["id"], "por_nome": user.get("name", ""), "em": now_iso()}

    await db.compras_pos.update_one(
        {"id": po_id, "tenant_id": tenant_id},
        {"$set": {"itens": itens, "status": novo_status, "updated_at": now_iso()},
         "$push": {"nfs_vinculadas": nf_entry, "log_auditoria": log_entry}},
    )

    po_atualizada = await _get_po_or_404(po_id, tenant_id)
    await _verificar_gatilho_financeiro(po_atualizada, tenant_id)

    if divergencias:
        await create_workflow_task(
            tenant_id=tenant_id,
            entity_type="compras_po",
            entity_id=po_id,
            title=f"CMP-06 Divergência no Recebimento — {po_atualizada.get('numero_po', po_id)}",
            description=(
                f"Divergências na NF {data.nf_numero}:\n"
                + "\n".join(f"  • {d}" for d in divergencias)
                + "\nVerifique com o fornecedor."
            ),
            category="compras",
            blocking=False,
            due_in_days=2,
            created_by=user,
            metadata={"task_type": "standard", "module_origin": "compras"},
        )

    return {**po_atualizada, "divergencias": divergencias, "nf_registrada": nf_entry}


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 6 — ESTOQUE PROJETADO (4 camadas)
# ══════════════════════════════════════════════════════════════════════════════

async def _ler_estoque_aprovado(tenant_id: str) -> Dict[str, float]:
    """CAMADA 1 — Estoque WMS de lotes aprovados pelo CQ, mapeado por item_id."""
    raw = await db.estoque_items.find({"tenant_id": tenant_id, "tipo_item": "mp"}, {"_id": 0}).to_list(5000)
    por_item: Dict[str, float] = {}
    for ei in raw:
        ref = ei.get("mp_id") or ei.get("codigo") or ei.get("id")
        if not ref:
            continue
        aprovado = await _estoque_item_disponivel_para_mrp(tenant_id, ei)
        por_item[ref] = por_item.get(ref, 0) + (float(ei.get("quantidade_atual", 0)) if aprovado else 0.0)
    return por_item


async def _ler_bom_kickoff(tenant_id: str, projeto_id: str) -> List[Dict[str, Any]]:
    """Lê BOM do Kickoff aprovado e mapeia codigo_interno → compras_itens.id."""
    kickoff = await db.kickoffs.find_one(
        {"tenant_id": tenant_id, "projeto_id": projeto_id, "status": "aprovado"}, {"_id": 0, "bom": 1}
    )
    if not kickoff:
        return []
    resultado: List[Dict[str, Any]] = []
    for linha in kickoff.get("bom", []):
        codigo = linha.get("codigo_interno")
        qtd_un = float(linha.get("quantidade_por_unidade") or 0)
        if not codigo or qtd_un <= 0:
            continue
        ci = await db.compras_itens.find_one({"tenant_id": tenant_id, "codigo_interno": codigo}, {"_id": 0, "id": 1})
        if ci:
            resultado.append({"item_id": ci["id"], "quantidade_por_unidade": qtd_un})
    return resultado


@compras_router.get("/estoque-projetado")
async def estoque_projetado(
    request: Request,
    horizonte_dias: int = Query(90, ge=7, le=365),
    categoria: Optional[str] = Query(None),
    apenas_criticos: bool = Query(False),
):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    hoje = datetime.now(timezone.utc).date()

    # CAMADA 1
    estoque_wms = await _ler_estoque_aprovado(tenant_id)

    # CAMADA 2 — demanda firme (OPs abertas sem BOM estruturado → reservado para integração futura)
    demanda_ops: Dict[str, float] = {}

    # CAMADA 3 — demanda projetada: projetos CRM aprovados sem OP
    projetos = await db.crm_projects.find({"tenant_id": tenant_id, "stage": "pedido_aprovado"}, {"_id": 0}).to_list(200)
    demanda_projetada: Dict[str, float] = {}
    origem_projetada: Dict[str, List[dict]] = {}

    for proj in projetos:
        proj_id = proj["id"]
        op_existente = await db.orders.find_one(
            {"tenant_id": tenant_id, "client_card_id": proj.get("crm_card_id"), "status": {"$nin": ["cancelado"]}}
        )
        if op_existente:
            continue

        bom_items = await _ler_bom_kickoff(tenant_id, proj_id)
        kickoff = await db.kickoffs.find_one(
            {"tenant_id": tenant_id, "projeto_id": proj_id, "status": "aprovado"}, {"_id": 0, "bloco2": 1}
        )
        tem_kickoff = kickoff is not None
        volume = int(((kickoff or {}).get("bloco2") or {}).get("volume_primeiro_pedido") or proj.get("volume_estimado_pedido") or 0)
        data_ent = (((kickoff or {}).get("bloco2") or {}).get("data_entrega_contratada") or proj.get("prazo_prometido_cliente"))

        if not volume or not bom_items:
            continue

        for bi in bom_items:
            iid = bi["item_id"]
            qtd = bi["quantidade_por_unidade"] * volume
            demanda_projetada[iid] = demanda_projetada.get(iid, 0) + qtd
            origem_projetada.setdefault(iid, []).append({
                "projeto_id": proj_id,
                "projeto_nome": proj.get("nome_projeto", ""),
                "cliente": proj.get("cliente_nome", ""),
                "volume_unidades": volume,
                "data_entrega": data_ent,
                "tem_kickoff": tem_kickoff,
                "tem_sku": bool(proj.get("sku_id")),
            })

    # CAMADA 4 — suprimento em trânsito
    pos_transito = await db.compras_pos.find(
        {"tenant_id": tenant_id, "status": {"$in": ["emitida", "confirmada", "parcialmente_recebida"]}}, {"_id": 0}
    ).to_list(1000)
    suprimento: Dict[str, float] = {}
    for po in pos_transito:
        for it in po.get("itens", []):
            iid = it.get("item_id")
            if not iid:
                continue
            saldo = float(it.get("quantidade_solicitada", 0)) - float(it.get("quantidade_recebida", 0))
            suprimento[iid] = suprimento.get(iid, 0) + max(0, saldo)

    # Consolidar
    todos_ids = set(list(estoque_wms) + list(demanda_ops) + list(demanda_projetada) + list(suprimento))
    resultado: List[dict] = []

    for iid in todos_ids:
        ci = await db.compras_itens.find_one({"id": iid, "tenant_id": tenant_id}, {"_id": 0})
        if not ci:
            continue
        if categoria and ci.get("categoria") != categoria:
            continue

        est_atual = estoque_wms.get(iid, 0.0)
        dem_f = demanda_ops.get(iid, 0.0)
        dem_p = demanda_projetada.get(iid, 0.0)
        sup = suprimento.get(iid, 0.0)
        est_min = float(ci.get("estoque_minimo") or 0)

        saldo_firme = est_atual - dem_f + sup
        saldo_cons = est_atual - dem_f - dem_p + sup

        if saldo_cons < 0:
            risco = "ruptura"
        elif saldo_cons < est_min:
            risco = "critico"
        elif saldo_firme < est_min and dem_p > 0:
            risco = "atencao"
        else:
            risco = "ok"

        if apenas_criticos and risco == "ok":
            continue

        resultado.append({
            "item_id": iid,
            "descricao": ci.get("descricao", ""),
            "categoria": ci.get("categoria", ""),
            "unidade": ci.get("unidade_compra", ""),
            "estoque_atual": round(est_atual, 4),
            "demanda_firme": round(dem_f, 4),
            "demanda_projetada": round(dem_p, 4),
            "suprimento_transito": round(sup, 4),
            "saldo_firme": round(saldo_firme, 4),
            "saldo_conservador": round(saldo_cons, 4),
            "estoque_minimo": est_min,
            "risco": risco,
            "lead_time_dias": ci.get("lead_time_dias"),
            "ultimo_preco_pago": ci.get("ultimo_preco_pago"),
            "tem_po_transito": sup > 0,
            "pedidos_origem_projetada": origem_projetada.get(iid, []),
        })

    _ord_risco = {"ruptura": 0, "critico": 1, "atencao": 2, "ok": 3}
    resultado.sort(key=lambda x: (_ord_risco[x["risco"]], x["descricao"]))

    resumo = {k: sum(1 for r in resultado if r["risco"] == k) for k in ("ruptura", "critico", "atencao", "ok")}
    resumo["total_itens"] = len(resultado)

    return {"horizonte_dias": horizonte_dias, "data_calculo": hoje.isoformat(), "resumo": resumo, "itens": resultado}


@compras_router.get("/estoque-projetado/{item_id}")
async def estoque_projetado_item(item_id: str, request: Request,
                                  horizonte_dias: int = Query(90, ge=7, le=365)):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]

    ci = await db.compras_itens.find_one({"id": item_id, "tenant_id": tenant_id}, {"_id": 0})
    if not ci:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    hoje = datetime.now(timezone.utc).date()
    est_atual = (await _ler_estoque_aprovado(tenant_id)).get(item_id, 0.0)
    timeline: List[dict] = []

    # OPs abertas
    ops = await db.orders.find(
        {"tenant_id": tenant_id, "status": {"$in": ["confirmado", "em_producao"]}}, {"_id": 0}
    ).to_list(200)
    for op in ops:
        for ins in op.get("insumos", []):
            if ci.get("codigo_interno", "") in ins.get("item", ""):
                timeline.append({
                    "data": (op.get("data_pedido") or op.get("created_at", ""))[:10],
                    "tipo": "op_aberta",
                    "descricao": f"OP {op.get('numero_pedido', op['id'][:8])}",
                    "quantidade": 0,
                    "status": op.get("status"),
                })

    # Projetos CRM aprovados
    projetos = await db.crm_projects.find({"tenant_id": tenant_id, "stage": "pedido_aprovado"}, {"_id": 0}).to_list(100)
    for proj in projetos:
        bom_items = await _ler_bom_kickoff(tenant_id, proj["id"])
        bom_map = {b["item_id"]: b["quantidade_por_unidade"] for b in bom_items}
        if item_id not in bom_map:
            continue
        kickoff = await db.kickoffs.find_one(
            {"tenant_id": tenant_id, "projeto_id": proj["id"], "status": "aprovado"}, {"_id": 0, "bloco2": 1}
        )
        tem_kickoff = kickoff is not None
        volume = int(((kickoff or {}).get("bloco2") or {}).get("volume_primeiro_pedido") or proj.get("volume_estimado_pedido") or 0)
        data_ent = (((kickoff or {}).get("bloco2") or {}).get("data_entrega_contratada") or proj.get("prazo_prometido_cliente"))
        if not volume:
            continue
        timeline.append({
            "data": (data_ent or "9999-99-99")[:10],
            "tipo": "pedido_crm",
            "descricao": f"Projeto: {proj.get('nome_projeto', '')} — {proj.get('cliente_nome', '')}",
            "quantidade": round(bom_map[item_id] * volume, 4),
            "status": "pedido_aprovado",
            "tem_op": False,
            "tem_kickoff": tem_kickoff,
            "data_entrega_contratada": data_ent,
        })

    # POs em trânsito
    pos = await db.compras_pos.find(
        {"tenant_id": tenant_id, "status": {"$in": ["emitida", "confirmada", "parcialmente_recebida"]}, "itens.item_id": item_id},
        {"_id": 0}
    ).to_list(100)
    for po in pos:
        for it in po.get("itens", []):
            if it.get("item_id") != item_id:
                continue
            saldo = float(it.get("quantidade_solicitada", 0)) - float(it.get("quantidade_recebida", 0))
            if saldo <= 0:
                continue
            data_ev = po.get("data_entrega_confirmada") or po.get("data_entrega_solicitada") or ""
            timeline.append({
                "data": data_ev[:10] if data_ev else "9999-99-99",
                "tipo": "po_transito",
                "descricao": f"{po.get('numero_po', po['id'][:8])} — {po['fornecedor_nome']}",
                "quantidade": round(saldo, 4),
                "status": po["status"],
                "data_entrega_confirmada": po.get("data_entrega_confirmada"),
            })

    timeline.sort(key=lambda x: x["data"])

    # Saldo acumulado por data
    saldo_corrente = est_atual
    saldo_por_data: List[dict] = []
    for ev in timeline:
        saldo_corrente = saldo_corrente + ev["quantidade"] if ev["tipo"] == "po_transito" else saldo_corrente - ev["quantidade"]
        saldo_por_data.append({"data": ev["data"], "saldo_apos": round(saldo_corrente, 4)})

    # Sugestão de compra
    lead = int(ci.get("lead_time_dias") or 0)
    est_min = float(ci.get("estoque_minimo") or 0)
    dem_total = sum(ev["quantidade"] for ev in timeline if ev["tipo"] in {"pedido_crm", "op_aberta"})
    sup_total = sum(ev["quantidade"] for ev in timeline if ev["tipo"] == "po_transito")
    saldo_final = est_atual - dem_total + sup_total
    sugestao_compra = None
    if saldo_final < est_min or saldo_final < 0:
        necessidade = max(0.0, est_min - saldo_final + float(ci.get("estoque_seguranca") or 0))
        ev_risco = next((ev for ev in timeline if ev["tipo"] in {"pedido_crm", "op_aberta"}), None)
        data_lim, urgente_flag, motivo = None, False, "Estoque projetado abaixo do mínimo"
        if ev_risco:
            try:
                dn = datetime.fromisoformat(ev_risco["data"]).date()
                dl = dn - timedelta(days=lead + 2)
                data_lim = dl.isoformat()
                urgente_flag = dl < hoje
                motivo = f"{ev_risco.get('descricao', '')} — estoque abaixo do mínimo em {ev_risco['data']}"
            except (ValueError, AttributeError):
                pass
        sugestao_compra = {"quantidade_sugerida": round(necessidade, 4), "data_limite_pedido": data_lim, "urgente": urgente_flag, "motivo": motivo}

    # Fornecedores disponíveis
    conds = await db.compras_condicoes_comerciais.find(
        {"tenant_id": tenant_id, "item_id": item_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    forn_visto: set = set()
    fornecedores_disp: List[dict] = []
    for c in conds:
        fid = c.get("fornecedor_id")
        if fid in forn_visto:
            continue
        forn_visto.add(fid)
        forn = await db.compras_fornecedores.find_one({"id": fid, "tenant_id": tenant_id}, {"_id": 0, "razao_social": 1, "homologacao.status": 1})
        fornecedores_disp.append({
            "fornecedor_id": fid,
            "nome": (forn or {}).get("razao_social", ""),
            "homologado": (forn or {}).get("homologacao", {}).get("status") == "homologado",
            "ultimo_preco": c.get("preco_unitario"),
            "prazo_entrega_dias": c.get("prazo_entrega_dias_uteis"),
            "moq": c.get("moq"),
            "cotacao_valida_ate": c.get("valido_ate"),
        })
    fornecedores_disp.sort(key=lambda x: x.get("ultimo_preco") or float("inf"))

    return {
        "item": ci,
        "estoque_atual": round(est_atual, 4),
        "timeline_demanda": timeline,
        "saldo_por_data": saldo_por_data,
        "sugestao_compra": sugestao_compra,
        "fornecedores_disponiveis": fornecedores_disp,
        "historico_precos": conds[:6],
    }


# ══════════════════════════════════════════════════════════════════════════════
#   PASSO 7 — DASHBOARD DE COMPRAS
# ══════════════════════════════════════════════════════════════════════════════

@compras_router.get("/dashboard")
async def dashboard_compras(request: Request):
    user = await get_current_user(request)
    require_roles(user, _CMP_READ)
    tenant_id = user["tenant_id"]
    hoje = _today_iso()
    sete_dias = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    trinta_dias = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    inicio_mes = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    fim_mes = (datetime.now(timezone.utc).replace(day=28) + timedelta(days=4)).replace(day=1).date().isoformat()

    # ── 1. Visão Operacional ───────────────────────────────────────────────────
    dois_dias_atras = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

    pos_aguardando = await db.compras_pos.find(
        {"tenant_id": tenant_id, "status": "emitida", "data_emissao": {"$lte": dois_dias_atras}},
        {"_id": 0, "id": 1, "numero_po": 1, "fornecedor_nome": 1, "valor_total_po": 1, "data_emissao": 1},
    ).to_list(50)

    pos_entrega_proxima = await db.compras_pos.find(
        {"tenant_id": tenant_id, "status": "confirmada",
         "data_entrega_confirmada": {"$gte": hoje, "$lte": sete_dias}},
        {"_id": 0, "id": 1, "numero_po": 1, "fornecedor_nome": 1, "valor_total_po": 1, "data_entrega_confirmada": 1},
    ).to_list(50)

    pos_atrasadas = await db.compras_pos.find(
        {"tenant_id": tenant_id, "status": "confirmada", "data_entrega_confirmada": {"$lt": hoje}},
        {"_id": 0, "id": 1, "numero_po": 1, "fornecedor_nome": 1, "valor_total_po": 1, "data_entrega_confirmada": 1},
    ).to_list(50)

    # Itens urgentes MRP: demandas urgentes sem PO
    demandas_urgentes = await db.compras_demandas.find(
        {"tenant_id": tenant_id, "urgente": True, "status": "pendente",
         "data_limite_pedido": {"$lte": hoje}},
        {"_id": 0, "id": 1, "item_descricao": 1, "quantidade": 1, "data_limite_pedido": 1},
    ).to_list(50)

    # ── 2. Visão Fornecedores ─────────────────────────────────────────────────
    # POs ativas com fornecedores não homologados
    pos_ativas_ids = [p["fornecedor_id"] async for p in db.compras_pos.find(
        {"tenant_id": tenant_id, "status": {"$in": ["emitida", "confirmada", "parcialmente_recebida"]}},
        {"fornecedor_id": 1, "_id": 0},
    )]
    sem_hom_com_po = await db.compras_fornecedores.find(
        {"tenant_id": tenant_id, "id": {"$in": list(set(pos_ativas_ids))},
         "homologacao.status": {"$nin": ["homologado"]}},
        {"_id": 0, "id": 1, "codigo_interno": 1, "razao_social": 1, "homologacao.status": 1},
    ).to_list(20)

    hom_vencendo = await db.compras_fornecedores.find(
        {"tenant_id": tenant_id, "homologacao.status": "homologado",
         "homologacao.proxima_reavaliacao": {"$lte": trinta_dias, "$gte": hoje}},
        {"_id": 0, "id": 1, "codigo_interno": 1, "razao_social": 1, "homologacao.proxima_reavaliacao": 1},
    ).to_list(20)

    suspensos_rncs = await db.compras_fornecedores.find(
        {"tenant_id": tenant_id, "homologacao.status": "suspenso",
         "homologacao.historico_rncs_criticas_12m": {"$gte": 3}},
        {"_id": 0, "id": 1, "codigo_interno": 1, "razao_social": 1, "homologacao.historico_rncs_criticas_12m": 1},
    ).to_list(20)

    # Itens com menos de 3 fornecedores homologados
    todos_itens = await db.compras_itens.find({"tenant_id": tenant_id}, {"_id": 0, "id": 1, "descricao": 1, "fornecedores_homologados": 1}).to_list(500)
    itens_poucos_forns = [
        {"item_id": i["id"], "descricao": i.get("descricao", ""), "qtd_fornecedores": len(i.get("fornecedores_homologados", []))}
        for i in todos_itens if len(i.get("fornecedores_homologados", [])) < 3
    ]

    # ── 3. Visão Estoque/Reposição ────────────────────────────────────────────
    estoque_wms = await _ler_estoque_aprovado(tenant_id)
    pos_transito_items: Dict[str, float] = {}
    async for po in db.compras_pos.find(
        {"tenant_id": tenant_id, "status": {"$in": ["emitida", "confirmada", "parcialmente_recebida"]}},
        {"itens": 1, "_id": 0},
    ):
        for it in po.get("itens", []):
            iid = it.get("item_id")
            if iid:
                saldo = float(it.get("quantidade_solicitada", 0)) - float(it.get("quantidade_recebida", 0))
                pos_transito_items[iid] = pos_transito_items.get(iid, 0) + max(0, saldo)

    abaixo_minimo_sem_po: List[dict] = []
    for ci in todos_itens:
        est_min = float((await db.compras_itens.find_one({"id": ci["id"], "tenant_id": tenant_id}, {"_id": 0, "estoque_minimo": 1}) or {}).get("estoque_minimo") or 0)
        if est_min <= 0:
            continue
        est_atual = estoque_wms.get(ci["id"], 0.0)
        em_transito = pos_transito_items.get(ci["id"], 0.0)
        if est_atual < est_min and em_transito == 0:
            abaixo_minimo_sem_po.append({"item_id": ci["id"], "descricao": ci.get("descricao", ""), "estoque_atual": round(est_atual, 3), "estoque_minimo": est_min})

    pos_saldo_aberto = await db.compras_pos.find(
        {"tenant_id": tenant_id, "status": "parcialmente_recebida"},
        {"_id": 0, "id": 1, "numero_po": 1, "fornecedor_nome": 1, "valor_total_po": 1},
    ).to_list(30)

    # ── 4. Visão Financeira ───────────────────────────────────────────────────
    aguardando_pgto = await db.compras_pos.find(
        {"tenant_id": tenant_id, "gatilho_financeiro_acionado": True,
         "status": {"$nin": ["cancelada"]}},
        {"_id": 0, "id": 1, "numero_po": 1, "fornecedor_nome": 1, "valor_total_po": 1, "data_vencimento_pagamento": 1},
    ).to_list(100)

    vencendo_7d = [p for p in aguardando_pgto if p.get("data_vencimento_pagamento") and hoje <= p["data_vencimento_pagamento"] <= sete_dias]
    total_semana = sum(p.get("valor_total_po", 0) for p in vencendo_7d)
    total_mes = sum(
        p.get("valor_total_po", 0) for p in aguardando_pgto
        if p.get("data_vencimento_pagamento") and inicio_mes <= p["data_vencimento_pagamento"] < fim_mes
    )

    # Top fornecedores por volume (POs emitidas + confirmadas + recebidas)
    pipeline_forn: Dict[str, float] = {}
    async for po in db.compras_pos.find(
        {"tenant_id": tenant_id, "status": {"$nin": ["cancelada", "rascunho"]}},
        {"fornecedor_id": 1, "fornecedor_nome": 1, "valor_total_po": 1, "_id": 0},
    ):
        fid = po.get("fornecedor_id", "")
        pipeline_forn.setdefault(fid, {"fornecedor_id": fid, "fornecedor_nome": po.get("fornecedor_nome", ""), "total": 0.0})
        pipeline_forn[fid]["total"] += float(po.get("valor_total_po", 0))
    top_forns = sorted(pipeline_forn.values(), key=lambda x: x["total"], reverse=True)[:5]

    # ── 5. Resumo estoque projetado ────────────────────────────────────────────
    ep_resumo = {"ruptura": 0, "critico": 0, "atencao": 0, "ok": 0}
    todos_ci = await db.compras_itens.find({"tenant_id": tenant_id}, {"_id": 0, "id": 1, "estoque_minimo": 1}).to_list(500)
    for ci in todos_ci:
        iid = ci["id"]
        est_min = float(ci.get("estoque_minimo") or 0)
        est = estoque_wms.get(iid, 0.0)
        trans = pos_transito_items.get(iid, 0.0)
        saldo = est + trans
        if saldo < 0:
            ep_resumo["ruptura"] += 1
        elif saldo < est_min:
            ep_resumo["critico"] += 1
        else:
            ep_resumo["ok"] += 1

    return {
        "visao_operacional": {
            "pos_aguardando_confirmacao": pos_aguardando,
            "pos_entrega_proximos_7_dias": pos_entrega_proxima,
            "pos_atrasadas": pos_atrasadas,
            "itens_urgentes_mrp": demandas_urgentes,
        },
        "visao_fornecedores": {
            "sem_homologacao_com_po_ativa": sem_hom_com_po,
            "homologacao_vencendo_30_dias": hom_vencendo,
            "suspensos_por_rncs": suspensos_rncs,
            "itens_menos_3_fornecedores": itens_poucos_forns[:10],
        },
        "visao_estoque_reposicao": {
            "abaixo_minimo_sem_po": abaixo_minimo_sem_po[:20],
            "em_quarentena_rota_critica": [],
            "pos_saldo_aberto": pos_saldo_aberto,
        },
        "visao_financeira": {
            "aguardando_pagamento": aguardando_pgto,
            "vencendo_proximos_7_dias": vencendo_7d,
            "total_a_pagar_semana": round(total_semana, 2),
            "total_a_pagar_mes": round(total_mes, 2),
            "top_fornecedores_volume": top_forns,
        },
        "estoque_projetado_resumo": ep_resumo,
    }
