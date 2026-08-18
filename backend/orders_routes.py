"""
Orders Module (Pedidos) - Production Order management
- Auto-creates order when PD request transitions to APPROVED
- Generates "Ordem de Produção" PDF (Kuryos layout)
- Visible to all roles
"""
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import io
import logging
import math
import hashlib
import re
import mimetypes
import os
import uuid
from pathlib import Path

from cq_routes import (
    cq_verificar_assepsia_manipulacao,
    cq_verificar_assepsia_envase,
    cq_verificar_setup_linha,
)

logger = logging.getLogger(__name__)

orders_router = APIRouter(prefix="/api/orders")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_orders(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def new_id():
    return new_id_func()


def now_iso():
    return now_iso_func()


# ============ STATUS ============
ORDER_STATUSES = ["rascunho", "confirmado", "em_producao", "concluido", "cancelado"]
ORDER_STATUS_LABELS = {
    "rascunho": "Rascunho",
    "confirmado": "Confirmado",
    "em_producao": "Em Produção",
    "concluido": "Concluído",
    "cancelado": "Cancelado",
}


# ============ CONSTANTS ============
TIPOS_SERVICO = ["producao", "reposicao", "retrabalho"]
NIVEIS_FORMALIZACAO = [1, 2, 3]
CONDICAO_PGTO_RE = r"^\d{3}/\d{3}/\d{3}$"

# Spec Section 1.6 — 12 fixed insumo categories
CATEGORIAS_INSUMO = [
    "Arte / Aprovação de arte",
    "Cadastro ANVISA / Notificação",
    "Rótulos / Gravação",
    "Frascos / Potes",
    "Tampas / Sobretampa",
    "Cartucho",
    "Válvulas",
    "Celofane / Sleeve",
    "Display",
    "Caixa de embarque",
    "Essência / Fragrância",
    "Matérias-primas específicas",
]

ORDER_ATTACHMENT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}
ORDER_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024

# Statuses that make the order immutable (RN-PI-05)
STATUSES_IMUTAVEL = {"confirmado", "em_producao", "concluido"}

# Alçadas de aprovação comercial por desconto total (RN-PI-10)
# desconto_pct ≤ TIER_AUTO     → aprovacao_comercial = "nao_necessaria"
# TIER_AUTO < pct ≤ TIER_GERENTE → aprovacao_comercial = "pendente", nivel = "gerente_vendas"  (roles: sales_ops, admin)
# pct > TIER_GERENTE             → aprovacao_comercial = "pendente", nivel = "diretoria"        (roles: admin only)
TIER_AUTO = 5.0
TIER_GERENTE = 25.0


# ============ MODELS ============
class OrderItem(BaseModel):
    sku_id: Optional[str] = None
    pd_request_id: Optional[str] = None
    pd_concluido: bool = False
    codigo_kuryos: str = ""
    codigo_cliente: str = ""
    item: str
    prazo_entrega: str = ""
    valor_unitario: float = 0.0
    valor_unitario_currency: str = "BRL"
    desconto_percentual: float = 0.0      # RN-PI-10: 0–100 %
    qtd: float = 0
    valor_total: float = 0.0
    tipo_servico: str = "producao"   # per-item type: producao | reposicao | retrabalho


class OrderInsumo(BaseModel):
    item: str = ""
    especificacoes: str = ""
    quantidade: str = ""
    arte: bool = False
    anvisa: bool = False
    rotulo: bool = False
    frasco: bool = False
    tampa: bool = False


class InsumoChecklistItem(BaseModel):
    """Structured insumo checklist — one entry per category (spec Section 1.6)."""
    categoria: str
    ativo: bool = False                        # whether this category applies
    origem: str = "kuryos"                     # kuryos | cliente
    status: str = "pendente"                   # pendente | em_andamento | confirmado | recebido
    responsavel: str = ""                      # who follows up when origem=cliente
    data_prevista: Optional[str] = None
    observacoes: str = ""


class ClienteData(BaseModel):
    nome: str = ""
    razao_social: str = ""
    cnpj: str = ""
    cidade_uf: str = ""
    responsavel: str = ""
    telefone: str = ""
    email: str = ""


class FreteData(BaseModel):
    tipo: str = "FOB"  # FOB or CIF
    endereco: str = ""
    cidade_uf: str = ""
    prazo_coleta: str = ""


class CondicoesData(BaseModel):
    prazo: str = ""
    forma_pgto: str = ""
    condicao_pagamento: str = "000/000/000"    # RN-PI-08: NNN/NNN/NNN


class OrderCreate(BaseModel):
    pd_request_id: Optional[str] = None
    kickoff_id: Optional[str] = None          # Gap A: optional FK to kickoffs collection
    client_card_id: Optional[str] = None
    numero_pedido: Optional[str] = None
    pedido_cliente_ref: Optional[str] = None
    gerador_origem: Optional[str] = None
    allow_duplicate: bool = False
    data_pedido: Optional[str] = None
    tipo_servico: str = "producao"             # producao | reposicao | retrabalho
    nivel_formalizacao: int = 1                # 1 | 2 | 3
    cliente: ClienteData = Field(default_factory=ClienteData)
    frete: FreteData = Field(default_factory=FreteData)
    items: List[OrderItem] = []
    condicoes: CondicoesData = Field(default_factory=CondicoesData)
    insumos: List[OrderInsumo] = []
    checklist_insumos: List[InsumoChecklistItem] = []
    observacoes: str = ""


class DirectOrderCreate(BaseModel):
    """A12: Pedido Direto — cliente e SKU já existentes, pula lead→projeto→amostra."""
    cliente_id: str
    sku_id: str
    qtd: float
    valor_unitario: Optional[float] = None    # se omitido, usa o preço cadastrado no SKU
    valor_unitario_currency: Optional[str] = None  # se omitido, usa a moeda cadastrada no SKU (BRL/USD)
    prazo_entrega: str = ""
    tipo_servico: str = "producao"             # producao | reposicao | retrabalho
    nivel_formalizacao: int = 1                # 1 | 2 | 3
    pedido_cliente_ref: Optional[str] = None
    allow_duplicate: bool = False
    frete: FreteData = Field(default_factory=FreteData)
    condicoes: CondicoesData = Field(default_factory=CondicoesData)
    observacoes: str = ""


class OrderUpdate(BaseModel):
    kickoff_id: Optional[str] = None          # Gap A: allow linking/unlinking kickoff
    numero_pedido: Optional[str] = None
    data_pedido: Optional[str] = None
    status: Optional[str] = None
    tipo_servico: Optional[str] = None
    nivel_formalizacao: Optional[int] = None
    cliente: Optional[ClienteData] = None
    frete: Optional[FreteData] = None
    items: Optional[List[OrderItem]] = None
    condicoes: Optional[CondicoesData] = None
    insumos: Optional[List[OrderInsumo]] = None
    checklist_insumos: Optional[List[InsumoChecklistItem]] = None
    observacoes: Optional[str] = None
    cgi_status: Optional[str] = None          # "pendente" | "assinado"
    # Client approval fields (RN-PI-04)
    aprovacao_cliente: Optional[str] = None   # pendente | aprovado
    aprovacao_cliente_obs: Optional[str] = None
    aprovacao_cliente_em: Optional[str] = None
    justificativa: Optional[str] = None        # R21: required to edit locked fields


# ===== OP MODELS =====
class OPItem(BaseModel):
    item: str = ""
    codigo_kuryos: str = ""
    qtd_planejada: float = 0
    qtd_produzida: float = 0
    lote: str = ""
    prazo_sla: str = ""


class OPCreate(BaseModel):
    pedido_id: str
    items: List[OPItem] = []
    observacoes: str = ""


class OPUpdate(BaseModel):
    status: Optional[str] = None  # "aberta" | "em_processo" | "pausada" | "concluida" | "cancelada"
    items: Optional[List[OPItem]] = None
    observacoes: Optional[str] = None
    linha_id: Optional[str] = None
    linha_nome: Optional[str] = None
    pcp_numero: Optional[str] = None


OP_STATUSES = ["aberta", "em_processo", "pausada", "concluida", "cancelada"]


class OPReworkCreate(BaseModel):
    motivo: str
    anotacoes: str = ""
    item_idx: Optional[int] = None
    prioridade: str = "normal"


# ===== R15: REPRODUZIR MODELS =====
class ItemOverride(BaseModel):
    codigo_kuryos: str = ""
    valor_unitario: Optional[float] = None
    prazo_entrega: Optional[str] = None
    qtd: Optional[float] = None


class ReproduzirInput(BaseModel):
    items_override: List[ItemOverride] = []
    endereco_entrega: Optional[str] = None
    observacoes: Optional[str] = None


# ============ HELPERS ============
async def _generate_order_number(tenant_id: str) -> str:
    """Generate order number in format MM_NN (e.g. 02_07) - sequential per month"""
    now = datetime.now(timezone.utc)
    month_str = f"{now.month:02d}"
    # Count orders for this tenant in this month
    start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
    count = await db.orders.count_documents({
        "tenant_id": tenant_id,
        "created_at": {"$gte": start_of_month},
    })
    seq = count + 1
    return f"{month_str}_{seq:02d}"


def _calculate_totals(items: List[Dict[str, Any]]) -> Dict[str, float]:
    """Recalculate item totals (applying per-item discount) and return order-level aggregates."""
    total_bruto = 0.0
    total_desconto = 0.0
    for it in items:
        valor_bruto = round((it.get("valor_unitario") or 0) * (it.get("qtd") or 0), 2)
        desc_pct = max(0.0, min(100.0, float(it.get("desconto_percentual") or 0)))
        valor_desc = round(valor_bruto * desc_pct / 100, 2)
        valor_liq = round(valor_bruto - valor_desc, 2)
        it["valor_desconto"] = valor_desc
        it["valor_total"] = valor_liq
        total_bruto += valor_bruto
        total_desconto += valor_desc
    total_liquido = round(total_bruto - total_desconto, 2)
    desc_pct_medio = round((total_desconto / total_bruto * 100) if total_bruto > 0 else 0.0, 2)
    return {
        "total_pedido": total_liquido,
        "total_bruto": round(total_bruto, 2),
        "total_desconto": round(total_desconto, 2),
        "desconto_pct_medio": desc_pct_medio,
    }


def _normalize_key_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _order_duplicate_fingerprint(
    cliente: Dict[str, Any],
    items: List[Dict[str, Any]],
    data_pedido: Optional[str],
    pedido_cliente_ref: Optional[str] = None,
) -> str:
    """Stable same-day fingerprint to block accidental duplicate order creation."""
    client_key = _digits_only(cliente.get("cnpj")) or _normalize_key_text(
        cliente.get("razao_social") or cliente.get("nome")
    )
    ref_key = _normalize_key_text(pedido_cliente_ref) or str(data_pedido or "")[:10]
    item_keys = []
    for item in items:
        code = _normalize_key_text(item.get("codigo_kuryos") or item.get("sku_id") or "")
        name = _normalize_key_text(item.get("item"))
        qty = round(float(item.get("qtd") or 0), 4)
        unit = round(float(item.get("valor_unitario") or 0), 4)
        item_keys.append(f"{code}:{name}:{qty}:{unit}")
    basis = "|".join([client_key, ref_key, *sorted(item_keys)])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _is_generator_order(order: Dict[str, Any]) -> bool:
    return order.get("origem") == "gerador" or bool(order.get("gerador_origem"))


def _order_generator_steps(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    pdf_meta = order.get("pdf") or {}
    attachments = order.get("attachments") or []
    ap_com = order.get("aprovacao_comercial") or "nao_necessaria"
    return [
        {
            "key": "anexo_cliente",
            "label": "Anexo do cliente",
            "done": bool(attachments),
            "count": len(attachments),
        },
        {
            "key": "pdf",
            "label": "PDF do pedido",
            "done": bool(pdf_meta.get("generated_at")),
            "generated_at": pdf_meta.get("generated_at"),
            "filename": pdf_meta.get("filename"),
        },
        {
            "key": "aprovacao_cliente",
            "label": "Aprovacao do cliente",
            "done": order.get("aprovacao_cliente") == "aprovado",
            "status": order.get("aprovacao_cliente") or "pendente",
        },
        {
            "key": "aprovacao_comercial",
            "label": "Aprovacao comercial",
            "done": ap_com in {"nao_necessaria", "aprovada"},
            "status": ap_com,
        },
        {
            "key": "op",
            "label": "OP",
            "done": bool(order.get("op_id")),
            "op_id": order.get("op_id"),
        },
    ]


def _order_generator_status(order: Dict[str, Any]) -> Dict[str, Any]:
    steps = _order_generator_steps(order)
    done = sum(1 for step in steps if step["done"])
    return {
        "order_id": order.get("id"),
        "numero_pedido": order.get("numero_pedido"),
        "status": order.get("status"),
        "cliente": (order.get("cliente") or {}).get("razao_social") or (order.get("cliente") or {}).get("nome"),
        "steps": steps,
        "completed_steps": done,
        "total_steps": len(steps),
        "progress_pct": round((done / len(steps) * 100) if steps else 0, 1),
        "pending": [step["key"] for step in steps if not step["done"]],
    }


def _orders_upload_root() -> Path:
    default_root = Path(__file__).parent / "uploads"
    return Path(os.environ.get("UPLOAD_DIR", str(default_root))) / "orders"


def _safe_attachment_filename(filename: str) -> str:
    name = Path(filename or "anexo").name.strip() or "anexo"
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name)[:180]


async def _assert_no_duplicate_order(
    *,
    tenant_id: str,
    duplicate_fingerprint: str,
) -> None:
    existing = await db.orders.find_one(
        {
            "tenant_id": tenant_id,
            "duplicate_fingerprint": duplicate_fingerprint,
            "status": {"$nin": ["cancelado", "concluido"]},
        },
        {"_id": 0, "id": 1, "numero_pedido": 1, "status": 1},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Pedido duplicado bloqueado. Ja existe o pedido #{existing.get('numero_pedido')} em status {existing.get('status')}.",
                "order_id": existing.get("id"),
                "numero_pedido": existing.get("numero_pedido"),
            },
        )


async def _approved_pd_for_sku(sku_doc: Dict[str, Any], tenant_id: str) -> Optional[Dict[str, Any]]:
    sample_id = sku_doc.get("amostra_id")
    if not sample_id:
        return None
    base_query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "linked_amostra_id": sample_id,
        "status": {"$in": ["APPROVED", "COMPLETED", "aprovado", "concluido"]},
    }
    variation_id = sku_doc.get("amostra_variacao_id")
    queries = []
    if variation_id:
        exact = dict(base_query)
        exact["linked_variacao_id"] = variation_id
        queries.append(exact)
    queries.append(base_query)

    for query in queries:
        docs = await db.pd_requests.find(query, {"_id": 0}).sort("updated_at", -1).to_list(1)
        if docs:
            return docs[0]
    return None


async def _enrich_items_from_skus(
    items: List[Dict[str, Any]],
    tenant_id: str,
    *,
    require_known_sku: bool = False,
    require_pd_completed: bool = False,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for raw_item in items:
        item = dict(raw_item)
        codigo = (item.get("codigo_kuryos") or "").strip()
        if not codigo or codigo.lower() in {"a definir", "na", "n/a"}:
            enriched.append(item)
            continue

        sku_doc = await db.skus.find_one(
            {"codigo_interno": codigo, "tenant_id": tenant_id},
            {"_id": 0},
        )
        if not sku_doc:
            if require_known_sku:
                raise HTTPException(status_code=404, detail=f"SKU '{codigo}' nao encontrado no cadastro.")
            enriched.append(item)
            continue

        if sku_doc.get("status") != "ativo":
            raise HTTPException(
                status_code=400,
                detail=f"SKU '{sku_doc.get('codigo_interno')}' nao esta ativo (status: {sku_doc.get('status')}).",
            )

        pd_req = await _approved_pd_for_sku(sku_doc, tenant_id)
        if require_pd_completed and not pd_req:
            raise HTTPException(
                status_code=422,
                detail=f"SKU '{sku_doc.get('codigo_interno')}' nao possui P&D concluido/aprovado vinculado.",
            )

        item["sku_id"] = sku_doc.get("id")
        item["codigo_kuryos"] = sku_doc.get("codigo_interno") or codigo
        item["pd_request_id"] = pd_req.get("id") if pd_req else item.get("pd_request_id")
        item["pd_concluido"] = bool(pd_req)
        item["produto_pai_id"] = sku_doc.get("produto_pai_id")
        item["sku_cliente_id"] = sku_doc.get("cliente_id")
        if not item.get("item"):
            item["item"] = sku_doc.get("nome_produto") or codigo
        if not item.get("valor_unitario") and sku_doc.get("preco_unitario"):
            item["valor_unitario"] = float(sku_doc.get("preco_unitario") or 0)
            item["valor_unitario_currency"] = sku_doc.get("preco_unitario_currency") or item.get("valor_unitario_currency") or "BRL"
        enriched.append(item)
    return enriched


def _eval_aprovacao_comercial(totals: Dict[str, float], existing: Optional[Dict] = None) -> Dict[str, Any]:
    """Determine aprovacao_comercial status based on order discount. (RN-PI-10)"""
    pct = totals.get("desconto_pct_medio", 0.0)
    if pct <= TIER_AUTO:
        return {"aprovacao_comercial": "nao_necessaria", "aprovacao_comercial_nivel": None}
    # Keep existing approval if already approved at the right level
    if existing:
        cur = existing.get("aprovacao_comercial")
        if cur == "aprovada":
            return {"aprovacao_comercial": "aprovada",
                    "aprovacao_comercial_nivel": existing.get("aprovacao_comercial_nivel")}
    nivel = "gerente_vendas" if pct <= TIER_GERENTE else "diretoria"
    return {"aprovacao_comercial": "pendente", "aprovacao_comercial_nivel": nivel}


async def _validate_kickoff_fk(kickoff_id: Optional[str], tenant_id: str) -> None:
    """Gap A: validate that kickoff_id references an existing kickoff for this tenant."""
    if not kickoff_id:
        return
    doc = await db.kickoffs.find_one({"id": kickoff_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Kickoff '{kickoff_id}' não encontrado (Gap A).")


async def _enrich_from_crm(client_card_id: Optional[str], tenant_id: str) -> Dict[str, Any]:
    """Pull client data from CRM card if available"""
    cliente = {
        "nome": "", "razao_social": "", "cnpj": "",
        "cidade_uf": "", "responsavel": "", "telefone": "", "email": "",
    }
    if not client_card_id:
        return cliente

    card = await db.cards.find_one({"id": client_card_id, "tenant_id": tenant_id}, {"_id": 0})
    if not card:
        return cliente

    cliente["nome"] = card.get("nome_cliente", "") or ""
    # Try to pull CRM client data
    crm_client_id = card.get("crm_client_id") or card.get("cliente_id")
    crm_client = None
    if crm_client_id:
        crm_client = await db.crm_clients.find_one({"id": crm_client_id, "tenant_id": tenant_id}, {"_id": 0})

    if crm_client:
        cliente["razao_social"] = crm_client.get("nome_empresa", "") or cliente["nome"]
        cliente["cnpj"] = crm_client.get("cnpj", "")
        cidade = crm_client.get("cidade", "") or crm_client.get("regiao", "")
        uf = crm_client.get("uf", "") or crm_client.get("estado", "")
        cliente["cidade_uf"] = f"{cidade}/{uf}" if cidade and uf else (cidade or uf)
        contato = crm_client.get("contato_principal") or {}
        cliente["responsavel"] = contato.get("nome", "")
        cliente["telefone"] = contato.get("whatsapp", "")
        cliente["email"] = contato.get("email", "")
    else:
        # Fallback to card-level fields
        cliente["razao_social"] = card.get("razao_social", "") or card.get("nome_cliente", "")
        cliente["cnpj"] = card.get("cnpj", "")
        cliente["responsavel"] = card.get("responsavel", "") or card.get("contato_nome", "")
        cliente["telefone"] = card.get("telefone", "") or card.get("contato_whatsapp", "")
        cliente["email"] = card.get("email", "") or card.get("contato_email", "")

    return cliente


async def _enrich_from_crm_client(cliente_id: str, tenant_id: str) -> Dict[str, Any]:
    """A12: monta ClienteData direto de um crm_clients existente (Pedido Direto não
    passa por db.cards/lead — o cliente já está fechado)."""
    cliente = {
        "nome": "", "razao_social": "", "cnpj": "",
        "cidade_uf": "", "responsavel": "", "telefone": "", "email": "",
    }
    crm_client = await db.crm_clients.find_one({"id": cliente_id, "tenant_id": tenant_id}, {"_id": 0})
    if not crm_client:
        return cliente
    cliente["nome"] = crm_client.get("nome_empresa", "")
    cliente["razao_social"] = crm_client.get("nome_empresa", "")
    cliente["cnpj"] = crm_client.get("cnpj", "")
    cidade = crm_client.get("cidade", "") or crm_client.get("regiao", "")
    uf = crm_client.get("uf", "") or crm_client.get("estado", "")
    cliente["cidade_uf"] = f"{cidade}/{uf}" if cidade and uf else (cidade or uf)
    contato = crm_client.get("contato_principal") or {}
    cliente["responsavel"] = contato.get("nome", "")
    cliente["telefone"] = contato.get("whatsapp", "")
    cliente["email"] = contato.get("email", "")
    return cliente


async def _build_items_from_pd(pd_request_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """Build initial order items from the PD request + samples + formula"""
    pd_req = await db.pd_requests.find_one({"id": pd_request_id, "tenant_id": tenant_id}, {"_id": 0})
    if not pd_req:
        return []

    items: List[Dict[str, Any]] = []
    project_name = pd_req.get("commercial_name") or pd_req.get("project_name") or ""
    volume = pd_req.get("volume") or ""
    sku = pd_req.get("sku") or pd_req.get("internal_code") or ""
    item_label = f"{project_name} {volume}".strip() if volume else project_name

    items.append({
        "codigo_kuryos": sku,
        "codigo_cliente": "",
        "item": item_label,
        "prazo_entrega": "20 Dias",
        "valor_unitario": 0.0,
        "qtd": 0,
        "valor_total": 0.0,
    })
    return items


async def auto_create_order_on_pd_approval(pd_request_id: str, user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Called from pd_routes.py when PD transitions to APPROVED. Idempotent."""
    if db is None:
        return None
    tenant_id = user["tenant_id"]
    # Idempotency: skip if already exists
    existing = await db.orders.find_one({"pd_request_id": pd_request_id, "tenant_id": tenant_id}, {"_id": 0})
    if existing:
        return existing

    pd_req = await db.pd_requests.find_one({"id": pd_request_id, "tenant_id": tenant_id}, {"_id": 0})
    if not pd_req:
        return None

    cliente = await _enrich_from_crm(pd_req.get("client_card_id"), tenant_id)
    items = await _build_items_from_pd(pd_request_id, tenant_id)
    numero = await _generate_order_number(tenant_id)

    # Gap A: auto-link kickoff if the PD request's project has one
    kickoff_id = None
    crm_proj_id = pd_req.get("crm_project_id")
    if crm_proj_id:
        proj = await db.crm_projects.find_one({"id": crm_proj_id, "tenant_id": tenant_id}, {"_id": 0, "kickoff_id": 1})
        kickoff_id = proj.get("kickoff_id") if proj else None

    checklist_default = [{"categoria": c, "ativo": False, "origem": "kuryos", "status": "pendente", "responsavel": "", "data_prevista": None, "observacoes": ""} for c in CATEGORIAS_INSUMO]
    totals = _calculate_totals(items)
    ap_comercial = _eval_aprovacao_comercial(totals)
    order = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "pd_request_id": pd_request_id,
        "kickoff_id": kickoff_id,
        "client_card_id": pd_req.get("client_card_id"),
        "numero_pedido": numero,
        "data_pedido": now_iso(),
        "status": "rascunho",
        "tipo_servico": "producao",
        "nivel_formalizacao": 1,
        "project_name": pd_req.get("project_name", ""),
        "cliente": cliente,
        "frete": {
            "tipo": "FOB",
            "endereco": "",
            "cidade_uf": cliente.get("cidade_uf", ""),
            "prazo_coleta": "Até 5 dias úteis após confirmação da produção",
        },
        "items": items,
        "condicoes": {
            "prazo": "30 dias",
            "forma_pgto": "Boleto + Depósito",
            "condicao_pagamento": "030/000/000",
        },
        "insumos": [],
        "checklist_insumos": checklist_default,
        "total_pedido": totals["total_pedido"],
        "total_bruto": totals["total_bruto"],
        "total_desconto": totals["total_desconto"],
        "desconto_pct_medio": totals["desconto_pct_medio"],
        "observacoes": "",
        "attachments": [],
        "pdf": {"status": "nao_gerado"},
        "cgi_status": "pendente",
        "cgi_assinado_em": None,
        "cgi_assinado_por": None,
        "aprovacao_cliente": "pendente",
        "aprovacao_cliente_obs": "",
        "aprovacao_cliente_em": None,
        "aprovacao_comercial": ap_comercial["aprovacao_comercial"],
        "aprovacao_comercial_nivel": ap_comercial["aprovacao_comercial_nivel"],
        "aprovacao_comercial_por": None,
        "aprovacao_comercial_em": None,
        "aprovacao_comercial_obs": "",
        "op_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "auto_created": True,
        "origem": "pipeline",
    }
    await db.orders.insert_one(order)
    order.pop("_id", None)
    logger.info(f"Order auto-created for PD {pd_request_id}: {numero}")
    return order


# ============ ROUTES ============
@orders_router.get("")
async def list_orders(request: Request, status: Optional[str] = None, q: Optional[str] = None):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if q:
        query["$or"] = [
            {"numero_pedido": {"$regex": q, "$options": "i"}},
            {"cliente.nome": {"$regex": q, "$options": "i"}},
            {"cliente.razao_social": {"$regex": q, "$options": "i"}},
            {"project_name": {"$regex": q, "$options": "i"}},
        ]
    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return orders


@orders_router.get("/generated/status")
async def generated_orders_status(request: Request):
    user = await get_current_user(request)
    query = {
        "tenant_id": user["tenant_id"],
        "$or": [
            {"origem": "gerador"},
            {"gerador_origem": {"$exists": True, "$nin": ["", None]}},
        ],
    }
    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    statuses = [_order_generator_status(order) for order in orders]
    return {
        "total": len(statuses),
        "com_anexo": sum(1 for st in statuses if "anexo_cliente" not in st["pending"]),
        "pdf_gerado": sum(1 for st in statuses if "pdf" not in st["pending"]),
        "aguardando_cliente": sum(1 for st in statuses if "aprovacao_cliente" in st["pending"]),
        "aguardando_comercial": sum(1 for st in statuses if "aprovacao_comercial" in st["pending"]),
        "com_op": sum(1 for st in statuses if "op" not in st["pending"]),
        "orders": statuses[:50],
    }


@orders_router.get("/{order_id}")
async def get_order(order_id: str, request: Request):
    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return order


@orders_router.get("/reorder/{client_card_id}")
async def get_reorder_draft(client_card_id: str, request: Request):
    """Return a pre-populated draft order based on the most recent order for a CRM client card."""
    user = await get_current_user(request)
    last_order = await db.orders.find_one(
        {"client_card_id": client_card_id, "tenant_id": user["tenant_id"]},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not last_order:
        raise HTTPException(status_code=404, detail="Nenhum pedido anterior encontrado para este cliente")

    numero = await _generate_order_number(user["tenant_id"])
    draft = {
        **last_order,
        "id": None,
        "numero_pedido": numero,
        "data_pedido": now_iso(),
        "status": "rascunho",
        "observacoes": "",
        "auto_created": False,
        "is_reorder_draft": True,
        "reorder_from": last_order["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    }
    return draft


async def _create_order_document(
    data: OrderCreate,
    user: Dict[str, Any],
    *,
    origem: str = "pipeline",
    require_known_sku: bool = False,
    require_pd_completed_skus: bool = False,
) -> Dict[str, Any]:
    """Corpo comum de criação de pedido — usado tanto pelo fluxo normal (POST /orders,
    vindo de pd_request/kickoff) quanto pelo Pedido Direto (POST /orders/direct, A12),
    para garantir que os dois entrem exatamente no mesmo ciclo de vida (checklist,
    totais, alçada de aprovação comercial, imutabilidade pós-confirmação etc.)."""
    import re

    if data.tipo_servico not in TIPOS_SERVICO:
        raise HTTPException(status_code=400, detail=f"tipo_servico inválido. Permitidos: {TIPOS_SERVICO}")

    condicoes = data.condicoes.model_dump()
    cpgto = condicoes.get("condicao_pagamento", "")
    if cpgto and not re.match(CONDICAO_PGTO_RE, cpgto):
        raise HTTPException(status_code=400, detail="condicao_pagamento deve ter formato NNN/NNN/NNN (RN-PI-08)")

    # Gap A: validate kickoff FK if provided
    await _validate_kickoff_fk(data.kickoff_id, user["tenant_id"])

    cliente = data.cliente.model_dump()
    if data.client_card_id and not cliente.get("razao_social"):
        cliente = await _enrich_from_crm(data.client_card_id, user["tenant_id"])

    items = [it.model_dump() for it in data.items]
    if data.pd_request_id and not items:
        items = await _build_items_from_pd(data.pd_request_id, user["tenant_id"])
    items = await _enrich_items_from_skus(
        items,
        user["tenant_id"],
        require_known_sku=require_known_sku,
        require_pd_completed=require_pd_completed_skus,
    )
    if origem in {"gerador", "direto"}:
        usable_items = [it for it in items if (it.get("item") or "").strip()]
        if not usable_items:
            raise HTTPException(status_code=400, detail="Inclua pelo menos um item no pedido.")
        for it in usable_items:
            if float(it.get("qtd") or 0) <= 0:
                raise HTTPException(status_code=400, detail=f"Item '{it.get('item')}' precisa ter quantidade maior que zero.")
        items = usable_items

    # Build default checklist if not provided
    checklist = [c.model_dump() for c in data.checklist_insumos] if data.checklist_insumos else \
        [{"categoria": c, "ativo": False, "origem": "kuryos", "status": "pendente", "responsavel": "", "data_prevista": None, "observacoes": ""} for c in CATEGORIAS_INSUMO]

    numero = data.numero_pedido or await _generate_order_number(user["tenant_id"])
    totals = _calculate_totals(items)
    ap_comercial = _eval_aprovacao_comercial(totals)
    duplicate_fingerprint = _order_duplicate_fingerprint(
        cliente,
        items,
        data.data_pedido or now_iso(),
        data.pedido_cliente_ref,
    )
    if not data.allow_duplicate:
        await _assert_no_duplicate_order(
            tenant_id=user["tenant_id"],
            duplicate_fingerprint=duplicate_fingerprint,
        )

    order = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "pd_request_id": data.pd_request_id,
        "kickoff_id": data.kickoff_id,
        "client_card_id": data.client_card_id,
        "pedido_cliente_ref": data.pedido_cliente_ref or "",
        "gerador_origem": data.gerador_origem or "",
        "duplicate_fingerprint": duplicate_fingerprint,
        "numero_pedido": numero,
        "data_pedido": data.data_pedido or now_iso(),
        "status": "rascunho",
        "tipo_servico": data.tipo_servico,
        "nivel_formalizacao": data.nivel_formalizacao,
        "project_name": "",
        "cliente": cliente,
        "frete": data.frete.model_dump(),
        "items": items,
        "condicoes": condicoes,
        "insumos": [it.model_dump() for it in data.insumos],
        "checklist_insumos": checklist,
        "total_pedido": totals["total_pedido"],
        "total_bruto": totals["total_bruto"],
        "total_desconto": totals["total_desconto"],
        "desconto_pct_medio": totals["desconto_pct_medio"],
        "observacoes": data.observacoes,
        "attachments": [],
        "pdf": {"status": "nao_gerado"},
        "cgi_status": "pendente",
        "cgi_assinado_em": None,
        "cgi_assinado_por": None,
        "aprovacao_cliente": "pendente",
        "aprovacao_cliente_obs": "",
        "aprovacao_cliente_em": None,
        # Gap B: aprovacao_comercial
        "aprovacao_comercial": ap_comercial["aprovacao_comercial"],
        "aprovacao_comercial_nivel": ap_comercial["aprovacao_comercial_nivel"],
        "aprovacao_comercial_por": None,
        "aprovacao_comercial_em": None,
        "aprovacao_comercial_obs": "",
        "op_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "auto_created": False,
        # A12: rastreia pedidos criados sem passar por lead→projeto→amostra
        "origem": origem,
    }
    await db.orders.insert_one(order)
    order.pop("_id", None)
    return order


@orders_router.post("")
async def create_order(data: OrderCreate, request: Request):
    user = await get_current_user(request)
    return await _create_order_document(data, user, origem="pipeline")


@orders_router.post("/generator")
async def create_generator_order(data: OrderCreate, request: Request):
    """Create an order from the web generator, enriching SKU/P&D data when available."""
    user = await get_current_user(request)
    return await _create_order_document(
        data,
        user,
        origem="gerador",
        require_known_sku=False,
        require_pd_completed_skus=False,
    )


@orders_router.post("/direct")
async def create_direct_order(data: DirectOrderCreate, request: Request):
    """A12: cria pedido direto para cliente+SKU já cadastrados, sem lead→projeto→amostra.
    Reaproveita _create_order_document — o pedido direto entra no mesmo ciclo de vida
    (checklist, totais, alçada de aprovação comercial, CGI, imutabilidade) dos demais."""
    user = await get_current_user(request)

    cliente_doc = await db.crm_clients.find_one({"id": data.cliente_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not cliente_doc:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    sku_doc = await db.skus.find_one({"id": data.sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not sku_doc:
        raise HTTPException(status_code=404, detail="SKU não encontrado")
    if sku_doc.get("status") != "ativo":
        raise HTTPException(
            status_code=400,
            detail=f"SKU '{sku_doc.get('codigo_interno')}' não está ativo (status: {sku_doc.get('status')}) — não é possível criar pedido direto para um produto descontinuado.",
        )
    if sku_doc.get("cliente_id") != data.cliente_id:
        raise HTTPException(status_code=400, detail="Este SKU não pertence ao cliente selecionado.")

    if data.qtd <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser maior que zero")

    cliente = await _enrich_from_crm_client(data.cliente_id, user["tenant_id"])
    valor_unitario = data.valor_unitario if data.valor_unitario is not None else float(sku_doc.get("preco_unitario") or 0.0)
    if valor_unitario <= 0:
        raise HTTPException(
            status_code=400,
            detail="SKU sem preço unitário cadastrado — informe valor_unitario ou cadastre o preço no SKU antes de criar o pedido direto.",
        )
    # Bugfix pos-auditoria: a moeda do SKU (preco_unitario_currency) nunca era lida nem
    # repassada — o pedido sempre gravava BRL mesmo quando o SKU/override era em USD.
    valor_unitario_currency = data.valor_unitario_currency or sku_doc.get("preco_unitario_currency") or "BRL"

    item = OrderItem(
        sku_id=sku_doc.get("id"),
        codigo_kuryos=sku_doc.get("codigo_interno", ""),
        pd_concluido=False,
        item=sku_doc.get("nome_produto", ""),
        prazo_entrega=data.prazo_entrega,
        valor_unitario=valor_unitario,
        valor_unitario_currency=valor_unitario_currency,
        qtd=data.qtd,
        valor_total=round(valor_unitario * data.qtd, 2),
        tipo_servico=data.tipo_servico,
    )

    order_data = OrderCreate(
        tipo_servico=data.tipo_servico,
        nivel_formalizacao=data.nivel_formalizacao,
        pedido_cliente_ref=data.pedido_cliente_ref,
        allow_duplicate=data.allow_duplicate,
        cliente=ClienteData(**cliente),
        frete=data.frete,
        items=[item],
        condicoes=data.condicoes,
        observacoes=data.observacoes,
    )
    return await _create_order_document(
        order_data,
        user,
        origem="direto",
        require_known_sku=True,
        require_pd_completed_skus=False,
    )


@orders_router.put("/{order_id}")
async def update_order(order_id: str, data: OrderUpdate, request: Request):
    import re
    user = await get_current_user(request)
    existing = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    update_fields: Dict[str, Any] = {}
    payload = data.model_dump(exclude_unset=True)

    if "status" in payload and payload["status"] not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status inválido. Permitidos: {ORDER_STATUSES}")

    # Gap A: validate kickoff FK if being set
    if "kickoff_id" in payload:
        await _validate_kickoff_fk(payload["kickoff_id"], user["tenant_id"])

    # RN-PI-01: CGI must be signed before confirming
    if payload.get("status") == "confirmado":
        if existing.get("cgi_status", "pendente") != "assinado":
            raise HTTPException(status_code=422, detail="CGI não assinado. Assine o Contrato Geral de Industrialização antes de confirmar o pedido. (RN-PI-01)")
        # RN-PI-10: commercial approval must be resolved before confirming
        if existing.get("aprovacao_comercial") == "pendente":
            nivel = existing.get("aprovacao_comercial_nivel", "gerente_vendas")
            raise HTTPException(status_code=422, detail=f"Aprovação comercial pendente (desconto > {TIER_AUTO}%). Requer aprovação de {nivel.replace('_', ' ')} antes de confirmar. (RN-PI-10)")

    # RN-PI-05 + R21: confirmed/em_producao/concluido orders are immutable — only allowed fields
    IMMUTABLE_BLOCK = {"items", "cliente", "frete", "condicoes", "insumos", "numero_pedido", "data_pedido", "tipo_servico", "nivel_formalizacao"}
    if existing.get("status") in STATUSES_IMUTAVEL:
        blocked = IMMUTABLE_BLOCK & set(payload.keys())
        if blocked:
            justificativa = (payload.get("justificativa") or "").strip()
            if not justificativa:
                raise HTTPException(
                    status_code=422,
                    detail=f"Pedido {existing['status']} é imutável (RN-PI-05). Campos bloqueados: {sorted(blocked)}. Forneça uma justificativa para editar campos comerciais. (R21)"
                )
            # R21: write audit log entry
            old_vals = {k: existing.get(k) for k in blocked}
            new_vals = {k: payload.get(k) for k in blocked}
            audit_entry = {
                "id": new_id(),
                "tenant_id": user["tenant_id"],
                "order_id": order_id,
                "order_numero": existing.get("numero_pedido", ""),
                "user_id": user["id"],
                "user_name": user.get("name", ""),
                "action": "edit_locked",
                "fields_changed": sorted(blocked),
                "old_values": old_vals,
                "new_values": new_vals,
                "justificativa": justificativa,
                "created_at": now_iso(),
            }
            await db.order_audit_log.insert_one(audit_entry)

    # CQ hard stops — verify CK prerequisites before starting production
    if payload.get("status") == "em_producao":
        op_tipo = existing.get("tipo", "")
        if op_tipo == "manipulacao":
            await cq_verificar_assepsia_manipulacao(db, user["tenant_id"], order_id)
        elif op_tipo == "envase":
            await cq_verificar_assepsia_envase(db, user["tenant_id"], order_id)
            await cq_verificar_setup_linha(db, user["tenant_id"], order_id)

    # Validate NNN/NNN/NNN if condicoes.condicao_pagamento is provided
    if "condicoes" in payload and payload["condicoes"]:
        cpgto = payload["condicoes"].get("condicao_pagamento", "")
        if cpgto and not re.match(CONDICAO_PGTO_RE, cpgto):
            raise HTTPException(status_code=400, detail="condicao_pagamento deve ter formato NNN/NNN/NNN (RN-PI-08)")

    for key in ("kickoff_id", "numero_pedido", "data_pedido", "status", "observacoes", "cgi_status",
                "tipo_servico", "nivel_formalizacao",
                "aprovacao_cliente", "aprovacao_cliente_obs", "aprovacao_cliente_em"):
        if key in payload:
            update_fields[key] = payload[key]

    for key in ("cliente", "frete", "condicoes"):
        if key in payload and payload[key] is not None:
            update_fields[key] = payload[key]

    if "items" in payload and payload["items"] is not None:
        items = payload["items"]
        update_fields["items"] = items
        totals = _calculate_totals(items)
        update_fields["total_pedido"] = totals["total_pedido"]
        update_fields["total_bruto"] = totals["total_bruto"]
        update_fields["total_desconto"] = totals["total_desconto"]
        update_fields["desconto_pct_medio"] = totals["desconto_pct_medio"]
        # Re-evaluate commercial approval tier (RN-PI-10)
        ap = _eval_aprovacao_comercial(totals, existing)
        update_fields["aprovacao_comercial"] = ap["aprovacao_comercial"]
        update_fields["aprovacao_comercial_nivel"] = ap["aprovacao_comercial_nivel"]
        # Reset approval if discount increased beyond previous approval
        if ap["aprovacao_comercial"] == "pendente":
            update_fields["aprovacao_comercial_por"] = None
            update_fields["aprovacao_comercial_em"] = None

    if "insumos" in payload and payload["insumos"] is not None:
        update_fields["insumos"] = payload["insumos"]

    if "checklist_insumos" in payload and payload["checklist_insumos"] is not None:
        update_fields["checklist_insumos"] = payload["checklist_insumos"]

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # R19: Auto-create followups when order first transitions to concluido
    if payload.get("status") == "concluido" and existing.get("status") != "concluido":
        if not existing.get("followups"):
            now_dt = datetime.now(timezone.utc)
            marcos_dias = [("1m", 30), ("3m", 90), ("6m", 180)]
            update_fields["followups"] = [
                {"marco": marco, "vence_em": (now_dt + timedelta(days=dias)).isoformat(), "notificado": False}
                for marco, dias in marcos_dias
            ]

    update_fields["updated_at"] = now_iso()
    await db.orders.update_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"$set": update_fields})
    updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return updated


@orders_router.post("/{order_id}/aprovar-cliente")
async def aprovar_cliente(order_id: str, request: Request):
    """Register client approval (RN-PI-04) — sets aprovacao_cliente=aprovado."""
    from pydantic import BaseModel as PM
    class AprovBody(PM):
        observacoes: str = ""

    user = await get_current_user(request)
    body_raw = await request.json()
    obs = body_raw.get("observacoes", "")
    existing = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    now = now_iso()
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "aprovacao_cliente": "aprovado",
            "aprovacao_cliente_obs": obs,
            "aprovacao_cliente_em": now,
            "aprovacao_cliente_por": user["name"],
            "updated_at": now,
        }}
    )
    return await db.orders.find_one({"id": order_id}, {"_id": 0})


@orders_router.post("/{order_id}/aprovar-comercial")
async def aprovar_comercial(order_id: str, request: Request):
    """Register commercial approval (RN-PI-10) — required when order discount exceeds TIER_AUTO.
    Requires role: sales_ops (desconto ≤ TIER_GERENTE) or admin (desconto > TIER_GERENTE)."""
    user = await get_current_user(request)
    body = await request.json()
    obs = body.get("observacoes", "")
    existing = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    if existing.get("aprovacao_comercial") == "nao_necessaria":
        raise HTTPException(status_code=400, detail="Este pedido não requer aprovação comercial (desconto dentro do limite automático).")
    # Role check: diretoria level requires admin; gerente level requires sales_ops or admin
    nivel = existing.get("aprovacao_comercial_nivel", "gerente_vendas")
    roles_ok = {"admin"} if nivel == "diretoria" else {"sales_ops", "admin"}
    if user.get("role") not in roles_ok:
        raise HTTPException(status_code=403, detail=f"Aprovação de nível '{nivel}' requer role: {sorted(roles_ok)}.")
    now = now_iso()
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "aprovacao_comercial": "aprovada",
            "aprovacao_comercial_obs": obs,
            "aprovacao_comercial_em": now,
            "aprovacao_comercial_por": user.get("name", ""),
            "updated_at": now,
        }}
    )
    return await db.orders.find_one({"id": order_id}, {"_id": 0})


@orders_router.post("/{order_id}/rejeitar-comercial")
async def rejeitar_comercial(order_id: str, request: Request):
    """Reject the commercial approval request (RN-PI-10)."""
    user = await get_current_user(request)
    body = await request.json()
    obs = body.get("observacoes", "")
    existing = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    nivel = existing.get("aprovacao_comercial_nivel", "gerente_vendas")
    roles_ok = {"admin"} if nivel == "diretoria" else {"sales_ops", "admin"}
    if user.get("role") not in roles_ok:
        raise HTTPException(status_code=403, detail=f"Rejeição de nível '{nivel}' requer role: {sorted(roles_ok)}.")
    now = now_iso()
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "aprovacao_comercial": "rejeitada",
            "aprovacao_comercial_obs": obs,
            "aprovacao_comercial_em": now,
            "aprovacao_comercial_por": user.get("name", ""),
            "updated_at": now,
        }}
    )
    return await db.orders.find_one({"id": order_id}, {"_id": 0})


@orders_router.delete("/{order_id}")
async def delete_order(order_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.orders.delete_one({"id": order_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return {"message": "Pedido removido"}


# ============ CGI SIGN (RN-PI-01) ============
@orders_router.post("/{order_id}/sign-cgi")
async def sign_cgi(order_id: str, request: Request):
    """Mark the CGI (Contrato Geral de Industrialização) as signed for this order."""
    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "cgi_status": "assinado",
            "cgi_assinado_em": now_iso(),
            "cgi_assinado_por": user.get("name", ""),
            "updated_at": now_iso(),
        }},
    )
    updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return updated


# ============ OP — CREATE FROM ORDER ============
async def _generate_op_number(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    year = now.year
    count = await db.ops.count_documents({"tenant_id": tenant_id, "created_at": {"$gte": f"{year}-01-01"}})
    return f"OP-{year}-{count + 1:03d}"


def _formula_items_total_pct(items: List[Dict[str, Any]]) -> float:
    return round(sum(float(item.get("percentage") or item.get("percentual_mm") or 0) for item in items), 4)


def _normalise_formula_status(value: Any) -> str:
    return str(value or "").strip().lower()


async def _find_latest_pd_formula(development_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    formulas = await db.pd_formulas.find(
        {"development_id": development_id, "tenant_id": tenant_id},
        {"_id": 0},
    ).sort("version", -1).to_list(1)
    return formulas[0] if formulas else None


async def _resolve_pd_request_for_op_item(
    item: Dict[str, Any],
    order: Dict[str, Any],
    tenant_id: str,
) -> Optional[Dict[str, Any]]:
    if order.get("pd_request_id"):
        return await db.pd_requests.find_one(
            {"id": order["pd_request_id"], "tenant_id": tenant_id},
            {"_id": 0},
        )

    codigo = (item.get("codigo_kuryos") or "").strip()
    if not codigo:
        return None

    sku = await db.skus.find_one(
        {"codigo_interno": codigo, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not sku or not sku.get("amostra_id"):
        return None

    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "linked_amostra_id": sku["amostra_id"],
        "status": {"$in": ["APPROVED", "COMPLETED"]},
    }
    if sku.get("amostra_variacao_id"):
        query["linked_variacao_id"] = sku["amostra_variacao_id"]
    requests = await db.pd_requests.find(query, {"_id": 0}).sort("updated_at", -1).to_list(1)
    return requests[0] if requests else None


async def _build_op_technical_snapshot_for_item(
    item: Dict[str, Any],
    order: Dict[str, Any],
    tenant_id: str,
) -> Dict[str, Any]:
    codigo = (item.get("codigo_kuryos") or "").strip()
    bloqueios: List[str] = []
    alertas: List[str] = []
    pd_req = await _resolve_pd_request_for_op_item(item, order, tenant_id)

    if not pd_req:
        return {
            "codigo_kuryos": codigo,
            "item": item.get("item", ""),
            "apto_operacao": False,
            "pd_request_id": None,
            "formula_id": None,
            "formula_versao": None,
            "formula_status": None,
            "total_percentual": 0,
            "itens_formula": [],
            "bloqueios": ["PD concluido/aprovado nao encontrado para este SKU"],
            "alertas": [],
        }

    pd_status = pd_req.get("status")
    if pd_status not in ("APPROVED", "COMPLETED"):
        bloqueios.append(f"PD nao concluido/aprovado: {pd_status or 'sem status'}")

    dev = await db.pd_developments.find_one(
        {"pd_request_id": pd_req["id"], "tenant_id": tenant_id},
        {"_id": 0},
    )
    formula = await _find_latest_pd_formula(dev["id"], tenant_id) if dev else None
    if not dev or not formula:
        bloqueios.append("Formula de P&D nao encontrada")
        return {
            "codigo_kuryos": codigo,
            "item": item.get("item", ""),
            "apto_operacao": False,
            "pd_request_id": pd_req["id"],
            "formula_id": None,
            "formula_versao": None,
            "formula_status": None,
            "total_percentual": 0,
            "itens_formula": [],
            "bloqueios": bloqueios,
            "alertas": alertas,
        }

    approval = await db.pd_approvals.find_one({"development_id": dev["id"]}, {"_id": 0})
    if not (approval and approval.get("approved_by_internal") and approval.get("approved_by_client")):
        bloqueios.append("Formula sem aprovacao interna e comercial/cliente registrada")

    formula_status = _normalise_formula_status(formula.get("status"))
    if formula_status and formula_status not in {"aprovada", "aprovado", "approved"}:
        alertas.append(f"Status da formula: {formula.get('status')}")

    formula_items = await db.pd_formula_items.find({"formula_id": formula["id"]}, {"_id": 0}).to_list(500)
    if not formula_items:
        bloqueios.append("Formula sem itens")

    total_pct = _formula_items_total_pct(formula_items)
    if formula_items and not math.isclose(total_pct, 100.0, abs_tol=0.01):
        bloqueios.append(f"Formula soma {total_pct}% em vez de 100%")

    missing_phase = [
        it.get("ingredient_name") or it.get("mp_codigo") or "item sem nome"
        for it in formula_items
        if not (it.get("phase") or it.get("fase"))
    ]
    if missing_phase:
        bloqueios.append(f"Itens sem fase de manipulacao: {', '.join(missing_phase[:5])}")

    ficha = await db.pd_ficha_tecnica.find_one(
        {"pd_request_id": pd_req["id"], "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not ficha:
        alertas.append("Ficha tecnica operacional ainda nao revisada/salva")

    public_items = [
        {
            "ingredient_name": it.get("ingredient_name") or it.get("mp_codigo") or "",
            "percentage": it.get("percentage") or it.get("percentual_mm") or 0,
            "phase": it.get("phase") or it.get("fase") or "",
            "function": it.get("function") or "",
            "fornecedor": it.get("fornecedor") or "",
            "catalog_id": it.get("catalog_id"),
        }
        for it in formula_items
    ]

    return {
        "codigo_kuryos": codigo,
        "item": item.get("item", ""),
        "apto_operacao": len(bloqueios) == 0,
        "pd_request_id": pd_req["id"],
        "formula_id": formula["id"],
        "formula_versao": formula.get("version"),
        "formula_status": formula.get("status"),
        "formula_nome": formula.get("name"),
        "total_percentual": total_pct,
        "itens_formula": public_items,
        "bloqueios": bloqueios,
        "alertas": alertas,
    }


async def _build_op_technical_snapshot(order: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    reviews = [
        await _build_op_technical_snapshot_for_item(item, order, tenant_id)
        for item in (order.get("items") or [])
    ]
    bloqueios = [
        f"{review.get('codigo_kuryos') or review.get('item')}: {reason}"
        for review in reviews
        for reason in review.get("bloqueios", [])
    ]
    alertas = [
        f"{review.get('codigo_kuryos') or review.get('item')}: {reason}"
        for review in reviews
        for reason in review.get("alertas", [])
    ]
    requires_technical_review = bool(order.get("pd_request_id") or order.get("origem") in {"direto", "reproducao"})
    return {
        "apto_operacao": len(bloqueios) == 0,
        "revisao_obrigatoria": requires_technical_review,
        "bloqueios": bloqueios,
        "alertas": alertas,
        "items": reviews,
        "snapshot_at": now_iso(),
    }


def _technical_review_blocks_operation(op: Dict[str, Any]) -> List[str]:
    tecnico = op.get("tecnico") or {}
    if not tecnico.get("revisao_obrigatoria"):
        return []
    return list(tecnico.get("bloqueios") or []) if not tecnico.get("apto_operacao") else []


@orders_router.post("/{order_id}/create-op")
async def create_op_from_order(order_id: str, request: Request):
    """Convert a confirmed PI into an Ordem de Produção."""
    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    if order.get("status") not in ("confirmado", "em_producao"):
        raise HTTPException(status_code=422, detail="OP só pode ser gerada a partir de um pedido Confirmado.")
    if order.get("op_id"):
        existing_op = await db.ops.find_one({"id": order["op_id"]}, {"_id": 0})
        if existing_op:
            return existing_op

    tecnico = await _build_op_technical_snapshot(order, user["tenant_id"])
    if tecnico["revisao_obrigatoria"] and tecnico["bloqueios"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "OP bloqueada: revise P&D/ficha tecnica antes de emitir.",
                "bloqueios": tecnico["bloqueios"],
                "alertas": tecnico["alertas"],
            },
        )

    numero_op = await _generate_op_number(user["tenant_id"])
    op_items = [
        {
            "item": it.get("item", ""),
            "codigo_kuryos": it.get("codigo_kuryos", ""),
            "qtd_planejada": it.get("qtd", 0),
            "qtd_produzida": 0,
            "lote": "",
            "prazo_sla": it.get("prazo_entrega", ""),
        }
        for it in (order.get("items") or [])
    ]
    op = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "numero_op": numero_op,
        "pedido_id": order_id,
        "numero_pedido": order.get("numero_pedido", ""),
        "cliente_nome": order.get("cliente", {}).get("nome") or order.get("cliente", {}).get("razao_social", ""),
        "project_name": order.get("project_name", ""),
        "status": "aberta",
        "items": op_items,
        "tecnico": tecnico,
        "observacoes": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    }
    await db.ops.insert_one(op)
    op.pop("_id", None)
    # Link back to the order
    await db.orders.update_one({"id": order_id}, {"$set": {"op_id": op["id"], "status": "em_producao", "updated_at": now_iso()}})
    return op


# ============ R15: REPRODUZIR PEDIDO ============
@orders_router.post("/{order_id}/reproduzir")
async def reproduzir_pedido(order_id: str, data: ReproduzirInput, request: Request):
    """Clone an existing locked order and immediately create a new OP (R15)."""
    import copy
    user = await get_current_user(request)
    if user.get("role") not in {"admin", "vendedor", "sales_ops"}:
        raise HTTPException(status_code=403, detail="Permissão negada. Apenas Comercial e Admin podem reproduzir pedidos.")

    original = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not original:
        raise HTTPException(status_code=404, detail="Pedido original não encontrado")
    if original.get("status") not in STATUSES_IMUTAVEL:
        raise HTTPException(status_code=422, detail="Só é possível reproduzir pedidos Confirmados, Em Produção ou Concluídos.")

    # Clone items applying overrides keyed by codigo_kuryos
    items = copy.deepcopy(original.get("items", []))
    override_map = {ov.codigo_kuryos: ov for ov in data.items_override if ov.codigo_kuryos}
    for it in items:
        ov = override_map.get(it.get("codigo_kuryos", ""))
        if ov:
            if ov.valor_unitario is not None:
                it["valor_unitario"] = ov.valor_unitario
            if ov.prazo_entrega is not None:
                it["prazo_entrega"] = ov.prazo_entrega
            if ov.qtd is not None:
                it["qtd"] = ov.qtd

    totals = _calculate_totals(items)
    ap_comercial = _eval_aprovacao_comercial(totals)
    numero = await _generate_order_number(user["tenant_id"])

    frete = copy.deepcopy(original.get("frete", {}))
    if data.endereco_entrega is not None:
        frete["endereco"] = data.endereco_entrega

    checklist_default = [
        {"categoria": c, "ativo": False, "origem": "kuryos", "status": "pendente",
         "responsavel": "", "data_prevista": None, "observacoes": ""}
        for c in CATEGORIAS_INSUMO
    ]
    ts = now_iso()
    new_order = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "pd_request_id": original.get("pd_request_id"),
        "kickoff_id": original.get("kickoff_id"),
        "client_card_id": original.get("client_card_id"),
        "numero_pedido": numero,
        "data_pedido": ts,
        "status": "confirmado",
        "tipo_servico": original.get("tipo_servico", "producao"),
        "nivel_formalizacao": original.get("nivel_formalizacao", 1),
        "project_name": original.get("project_name", ""),
        "cliente": copy.deepcopy(original.get("cliente", {})),
        "frete": frete,
        "items": items,
        "condicoes": copy.deepcopy(original.get("condicoes", {})),
        "insumos": [],
        "checklist_insumos": checklist_default,
        "total_pedido": totals["total_pedido"],
        "total_bruto": totals["total_bruto"],
        "total_desconto": totals["total_desconto"],
        "desconto_pct_medio": totals["desconto_pct_medio"],
        "observacoes": data.observacoes or "",
        "cgi_status": "assinado",
        "cgi_assinado_em": ts,
        "cgi_assinado_por": user.get("name", ""),
        "aprovacao_cliente": "aprovado",
        "aprovacao_cliente_obs": f"Reprodução do pedido #{original.get('numero_pedido', '')}",
        "aprovacao_cliente_em": ts,
        "aprovacao_cliente_por": user.get("name", ""),
        "aprovacao_comercial": ap_comercial["aprovacao_comercial"],
        "aprovacao_comercial_nivel": ap_comercial["aprovacao_comercial_nivel"],
        "aprovacao_comercial_por": None,
        "aprovacao_comercial_em": None,
        "aprovacao_comercial_obs": "",
        "op_id": None,
        "reproducao_de": order_id,
        "followups": [],
        "created_at": ts,
        "updated_at": ts,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "auto_created": False,
        "origem": "reproducao",
    }
    tecnico = await _build_op_technical_snapshot(new_order, user["tenant_id"])
    if tecnico["revisao_obrigatoria"] and tecnico["bloqueios"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Reproducao bloqueada: revise P&D/ficha tecnica antes de emitir OP.",
                "bloqueios": tecnico["bloqueios"],
                "alertas": tecnico["alertas"],
            },
        )

    await db.orders.insert_one(new_order)
    new_order.pop("_id", None)

    # Immediately create the OP
    numero_op = await _generate_op_number(user["tenant_id"])
    op_items = [
        {
            "item": it.get("item", ""),
            "codigo_kuryos": it.get("codigo_kuryos", ""),
            "qtd_planejada": it.get("qtd", 0),
            "qtd_produzida": 0,
            "lote": "",
            "prazo_sla": it.get("prazo_entrega", ""),
        }
        for it in items
    ]
    op = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "numero_op": numero_op,
        "pedido_id": new_order["id"],
        "numero_pedido": numero,
        "cliente_nome": new_order["cliente"].get("nome") or new_order["cliente"].get("razao_social", ""),
        "project_name": new_order.get("project_name", ""),
        "status": "aberta",
        "items": op_items,
        "tecnico": tecnico,
        "observacoes": "",
        "created_at": ts,
        "updated_at": ts,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
    }
    await db.ops.insert_one(op)
    op.pop("_id", None)

    # Link OP to new order and set status to em_producao
    await db.orders.update_one(
        {"id": new_order["id"]},
        {"$set": {"op_id": op["id"], "status": "em_producao", "updated_at": ts}}
    )
    new_order["op_id"] = op["id"]
    new_order["status"] = "em_producao"

    return {"order": new_order, "op": op}


# ============ ORDER ATTACHMENTS ============
@orders_router.get("/{order_id}/attachments")
async def list_order_attachments(order_id: str, request: Request):
    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "attachments": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    return order.get("attachments") or []


@orders_router.post("/{order_id}/attachments")
async def upload_order_attachment(order_id: str, request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "id": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")

    data = await file.read()
    if len(data) > ORDER_ATTACHMENT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (max 10MB)")

    original_filename = _safe_attachment_filename(file.filename or "anexo")
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "bin"
    if ext not in ORDER_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(sorted(ORDER_ATTACHMENT_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Tipo de arquivo nao permitido. Permitidos: {allowed}")

    attachment_id = new_id()
    stored_name = f"{attachment_id}.{ext}"
    relative_path = Path(user["tenant_id"]) / order_id / stored_name
    target_path = _orders_upload_root() / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)

    content_type = file.content_type or mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    attachment = {
        "id": attachment_id,
        "original_filename": original_filename,
        "content_type": content_type,
        "size": len(data),
        "storage_path": str(relative_path).replace("\\", "/"),
        "download_url": f"/api/orders/{order_id}/attachments/{attachment_id}/download",
        "uploaded_by": user["id"],
        "uploaded_by_name": user.get("name", ""),
        "uploaded_at": now_iso(),
    }
    await db.orders.update_one(
        {"id": order_id, "tenant_id": user["tenant_id"]},
        {"$push": {"attachments": attachment}, "$set": {"updated_at": now_iso()}},
    )
    return attachment


@orders_router.get("/{order_id}/attachments/{attachment_id}/download")
async def download_order_attachment(order_id: str, attachment_id: str, request: Request):
    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "attachments": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")

    attachment = next((item for item in (order.get("attachments") or []) if item.get("id") == attachment_id), None)
    if not attachment:
        raise HTTPException(status_code=404, detail="Anexo nao encontrado")

    path = _orders_upload_root() / attachment.get("storage_path", "")
    try:
        resolved_root = _orders_upload_root().resolve()
        resolved_path = path.resolve()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Arquivo do anexo nao encontrado")
    if resolved_root not in resolved_path.parents and resolved_path != resolved_root:
        raise HTTPException(status_code=400, detail="Caminho de anexo invalido")
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo do anexo nao encontrado")

    data = resolved_path.read_bytes()
    filename = _safe_attachment_filename(attachment.get("original_filename") or "anexo")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=attachment.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============ PDF GENERATION ============
@orders_router.get("/{order_id}/pdf")
async def export_order_pdf(order_id: str, request: Request):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    user = await get_current_user(request)
    order = await db.orders.find_one({"id": order_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"Ordem de Produção {order.get('numero_pedido', '')}",
    )

    KURYOS_BLUE = rl_colors.HexColor("#1F2C5C")
    HEADER_GRAY = rl_colors.HexColor("#F5F5F8")
    DARK_BLUE = rl_colors.HexColor("#2A3A77")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "OrderTitle", parent=styles["Title"],
        fontSize=18, fontName="Helvetica-Bold",
        textColor=rl_colors.black, alignment=TA_CENTER, spaceAfter=2,
    )
    section_num = ParagraphStyle(
        "SectionNum", parent=styles["Normal"],
        fontSize=10, fontName="Helvetica-Bold", textColor=KURYOS_BLUE,
    )
    section_title = ParagraphStyle(
        "SectionTitle", parent=styles["Normal"],
        fontSize=10, fontName="Helvetica-Bold", textColor=KURYOS_BLUE, leftIndent=0,
    )
    cell_label = ParagraphStyle(  # noqa: F841 - kept for future use
        "CellLabel", parent=styles["Normal"],
        fontSize=8.5, fontName="Helvetica-Bold", textColor=rl_colors.black,
    )
    cell_value = ParagraphStyle(  # noqa: F841 - kept for future use
        "CellValue", parent=styles["Normal"],
        fontSize=9, fontName="Helvetica", textColor=rl_colors.black, alignment=TA_CENTER,
    )
    note_style = ParagraphStyle(
        "Note", parent=styles["Normal"],
        fontSize=7.5, fontName="Helvetica", textColor=rl_colors.HexColor("#444444"),
    )

    elements: List[Any] = []

    # ===== TITLE + LOGO =====
    title_table = Table([
        [Paragraph("<u><b>ORDEM DE PRODUÇÃO</b></u>", title_style),
         Paragraph('<font color="#1F2C5C" size="22"><b>KURYOS</b></font><br/><font size="6" color="#1F2C5C">INDÚSTRIA DE COSMÉTICOS</font>',
                   ParagraphStyle("logo", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=22))],
    ], colWidths=[120 * mm, 60 * mm])
    title_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    elements.append(title_table)
    elements.append(Spacer(1, 4 * mm))

    # ===== Helper to render section with numbered header =====
    def render_section(num: str, title: str, rows: List[List[str]], col_widths: List[float] = None):
        # Header
        hdr = Table([[Paragraph(f"<b>{num})</b>", section_num),
                     Paragraph(f"<b>{title}</b>", section_title)]],
                    colWidths=[10 * mm, 170 * mm])
        hdr.setStyle(TableStyle([
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(hdr)
        # Body
        if rows:
            t = Table(rows, colWidths=col_widths or [40 * mm, 140 * mm])
            t.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.6, rl_colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, rl_colors.HexColor("#999999")),
                ("BACKGROUND", (0, 0), (0, -1), HEADER_GRAY),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ]))
            elements.append(t)
        elements.append(Spacer(1, 4 * mm))

    # ===== 1) INFORMAÇÕES INICIAIS =====
    data_pedido_str = ""
    try:
        if order.get("data_pedido"):
            dp = datetime.fromisoformat(order["data_pedido"].replace("Z", "+00:00"))
            data_pedido_str = dp.strftime("%d/%m/%Y")
    except Exception:
        data_pedido_str = order.get("data_pedido", "")

    render_section("1", "INFORMAÇÕES INICIAIS", [
        ["Cliente", order.get("cliente", {}).get("nome", "") or "-"],
        ["# Pedido", order.get("numero_pedido", "") or "-"],
        ["# Pedido Cliente", order.get("pedido_cliente_ref", "") or "-"],
        ["Data", data_pedido_str or "-"],
    ])

    # ===== 2) DADOS DO CLIENTE =====
    cliente = order.get("cliente", {})
    render_section("2", "DADOS DO CLIENTE", [
        ["Razão Social", cliente.get("razao_social", "") or "-"],
        ["CNPJ", cliente.get("cnpj", "") or "-"],
        ["Cidade / UF", cliente.get("cidade_uf", "") or "-"],
        ["Responsável", cliente.get("responsavel", "") or "-"],
        ["Telefone", cliente.get("telefone", "") or "-"],
        ["e-mail", cliente.get("email", "") or "-"],
    ])

    # ===== 3) FRETE =====
    frete = order.get("frete", {})
    render_section("3", "FRETE", [
        ["Tipo de Frete", frete.get("tipo", "FOB") or "-"],
        ["Endereço", frete.get("endereco", "") or "-"],
        ["Cidade / UF", frete.get("cidade_uf", "") or "-"],
        ["Prazo p/ Coleta", frete.get("prazo_coleta", "") or "-"],
    ])

    # ===== 4) PEDIDO =====
    elements.append(Table([[Paragraph("<b>4)</b>", section_num),
                            Paragraph("<b>PEDIDO</b>", section_title)]],
                          colWidths=[10 * mm, 170 * mm]))

    items_header = ["#", "Código Kuryos", "Código Cliente", "Item", "Prazo de Entrega²",
                    "Valor Unitário", "Qtd.", "Valor Total"]
    items_rows = [items_header]
    items_list = order.get("items", []) or []
    total = 0.0
    for idx, it in enumerate(items_list, start=1):
        valor_unit = it.get("valor_unitario", 0) or 0
        qtd = it.get("qtd", 0) or 0
        valor_total = it.get("valor_total") or (valor_unit * qtd)
        total += valor_total
        items_rows.append([
            str(idx),
            it.get("codigo_kuryos", "") or "-",
            it.get("codigo_cliente", "") or "-",
            it.get("item", "") or "-",
            it.get("prazo_entrega", "") or "-",
            f"R$ {valor_unit:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            f"{qtd:,.0f}".replace(",", "."),
            f"R$ {valor_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        ])

    items_rows.append(["", "", "", "", "", "", "Total do Pedido",
                       f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])

    items_table = Table(items_rows,
                        colWidths=[8 * mm, 24 * mm, 24 * mm, 50 * mm, 24 * mm, 22 * mm, 14 * mm, 24 * mm])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BOX", (0, 0), (-1, -2), 0.6, rl_colors.black),
        ("INNERGRID", (0, 0), (-1, -2), 0.3, rl_colors.HexColor("#999999")),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (0, 1), (-1, -2), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (6, -1), (-1, -1), 0.6, rl_colors.black),
        ("BOX", (6, -1), (-1, -1), 0.6, rl_colors.black),
        ("FONTNAME", (6, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (7, -1), (7, -1), "RIGHT"),
        ("ALIGN", (6, -1), (6, -1), "RIGHT"),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    # ===== 5) CONDIÇÕES DE PRAZO E PAGAMENTO =====
    cond = order.get("condicoes", {})
    render_section("5", "CONDIÇÕES DE PRAZO E PAGAMENTO", [
        ["Prazo", cond.get("prazo", "") or "-"],
        ["Forma de Pgto", cond.get("forma_pgto", "") or "-"],
    ])

    attachments = order.get("attachments", []) or []
    if _is_generator_order(order) or attachments:
        attachment_names = ", ".join([att.get("original_filename", "") for att in attachments if att.get("original_filename")])
        render_section("5.1", "RASTREIO DO GERADOR", [
            ["Origem", order.get("gerador_origem") or order.get("origem") or "-"],
            ["Anexos do Cliente", attachment_names or "-"],
            ["Aprovacao Cliente", order.get("aprovacao_cliente") or "-"],
            ["Aprovacao Comercial", order.get("aprovacao_comercial") or "-"],
        ])

    # ===== 6) INSUMOS A SEREM ENVIADOS =====
    elements.append(Table([[Paragraph("<b>6)</b>", section_num),
                            Paragraph("<b>INSUMOS À SEREM ENVIADOS</b>", section_title)]],
                          colWidths=[10 * mm, 170 * mm]))
    insumos = order.get("insumos", []) or []
    insumos_rows = [["#", "Item", "Especificações³", "Quantidade"]]
    if insumos:
        for idx, ins in enumerate(insumos, start=1):
            insumos_rows.append([
                str(idx),
                ins.get("item", "") or "-",
                ins.get("especificacoes", "") or "-",
                ins.get("quantidade", "") or "-",
            ])
    else:
        insumos_rows.append(["1", "-", "-", "-"])

    insumos_table = Table(insumos_rows, colWidths=[10 * mm, 70 * mm, 70 * mm, 30 * mm])
    insumos_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.6, rl_colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, rl_colors.HexColor("#999999")),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (0, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(insumos_table)
    elements.append(Spacer(1, 6 * mm))

    # ===== FOOTNOTES =====
    elements.append(HRFlowable(width="100%", thickness=0.3, color=rl_colors.HexColor("#999999"), dash=[2, 2]))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "1. Após a confirmação da produção por parte da Kuryos, uma vez não retirado o material indicado no prazo, será cobrado o valor de posição de pallets, no valor de R$ 40,00 / dia.",
        note_style))
    elements.append(Paragraph(
        "2. Prazo de entrega passa a contar no momento da confirmação de recebimento e aprovação de todos os insumos referentes ao pedido, sendo este <b>full service</b> ou <b>terceirização</b>.",
        note_style))
    elements.append(Paragraph(
        "3. [Material] / [Altura x Largura ou Diâmetro x Profundidade] (em milímetros) / [Capacidade]",
        note_style))

    pdf.build(elements)
    buffer.seek(0)
    filename = f"ordem_producao_{order.get('numero_pedido', order_id)}.pdf"
    generated_at = now_iso()
    await db.orders.update_one(
        {"id": order_id, "tenant_id": user["tenant_id"]},
        {"$set": {
            "pdf": {
                "status": "gerado",
                "filename": filename,
                "generated_at": generated_at,
                "generated_by": user["id"],
                "generated_by_name": user.get("name", ""),
                "download_url": f"/api/orders/{order_id}/pdf",
            },
            "updated_at": generated_at,
        }},
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============ OPS ROUTER ============
ops_router = APIRouter(prefix="/api/ops")


@ops_router.get("")
async def list_ops(request: Request, status: Optional[str] = None, q: Optional[str] = None):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if q:
        query["$or"] = [
            {"numero_op": {"$regex": q, "$options": "i"}},
            {"cliente_nome": {"$regex": q, "$options": "i"}},
            {"project_name": {"$regex": q, "$options": "i"}},
        ]
    ops = await db.ops.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return ops


@ops_router.get("/{op_id}")
async def get_op(op_id: str, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")
    return op


@ops_router.put("/{op_id}")
async def update_op(op_id: str, data: OPUpdate, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")
    payload = data.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] not in OP_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status inválido. Permitidos: {OP_STATUSES}")
    if payload.get("status") in {"em_processo", "concluida"}:
        bloqueios = _technical_review_blocks_operation(op)
        if bloqueios:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "OP bloqueada por pendencias tecnicas do P&D/ficha tecnica.",
                    "bloqueios": bloqueios,
                },
            )
    update_fields: Dict[str, Any] = {k: v for k, v in payload.items() if v is not None or k == "observacoes"}
    update_fields["updated_at"] = now_iso()
    await db.ops.update_one({"id": op_id}, {"$set": update_fields})
    updated = await db.ops.find_one({"id": op_id}, {"_id": 0})

    # On conclusion: compute un/h and push to SKU production history (RN-SK-05)
    if payload.get("status") == "concluida":
        await _record_op_producao_to_sku(updated)

    return updated


async def _record_op_producao_to_sku(op: dict):
    """Calculate un/h from apontamentos and push result into SKU medias_producao."""
    try:
        from workflow_engine import recalc_sku_averages
        apontamentos = op.get("apontamentos") or []
        if not apontamentos:
            return
        total_produzido = sum(a.get("qtd_produzida", 0) for a in apontamentos)
        if total_produzido <= 0:
            return

        horarios = sorted([a["horario"] for a in apontamentos if a.get("horario")])
        duracao_h = 0.0
        if len(horarios) >= 2:
            from datetime import datetime, timezone
            t0 = datetime.fromisoformat(horarios[0].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(horarios[-1].replace("Z", "+00:00"))
            raw_h = (t1 - t0).total_seconds() / 3600
            pause_h = sum(p.get("duracao_min", 0) for p in (op.get("pausas") or [])) / 60
            duracao_h = max(raw_h - pause_h, 0.0)

        if duracao_h <= 0:
            return
        unh = round(total_produzido / duracao_h, 1)

        # Resolve sku_id via codigo_kuryos on first OP item
        items = op.get("items") or []
        codigo_kuryos = items[0].get("codigo_kuryos", "") if items else ""
        if not codigo_kuryos:
            return
        sku = await db.skus.find_one(
            {"codigo_interno": codigo_kuryos, "tenant_id": op["tenant_id"]}, {"_id": 0}
        )
        if not sku:
            return

        await db.skus.update_one(
            {"id": sku["id"]},
            {"$push": {"medias_producao.historico_producao": {
                "op_id": op["id"],
                "op_numero": op.get("numero_op"),
                "data": now_iso(),
                "qtd_produzida": total_produzido,
                "duracao_h": round(duracao_h, 2),
                "unh": unh,
            }}}
        )
        await recalc_sku_averages(op["tenant_id"], sku["id"])
    except Exception:
        pass  # Non-critical — don't fail the OP update


# ─── Apontamento de produção ─────────────────────────────────────────────────
def _pd_request_id_from_op(op: Dict[str, Any], order: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if order and order.get("pd_request_id"):
        return order["pd_request_id"]
    tecnico = op.get("tecnico") or {}
    for review in tecnico.get("items") or []:
        if review.get("pd_request_id"):
            return review["pd_request_id"]
    return None


def _append_rework_note(notes: List[Dict[str, Any]], origem: str, texto: Any, **extra: Any) -> None:
    if texto is None:
        return
    if isinstance(texto, (list, tuple)):
        texto = " | ".join(str(part).strip() for part in texto if str(part).strip())
    elif isinstance(texto, dict):
        texto = "; ".join(f"{key}: {value}" for key, value in texto.items() if value not in (None, ""))
    else:
        texto = str(texto).strip()
    if not texto:
        return
    note = {"origem": origem, "texto": texto}
    note.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    notes.append(note)


def _event_rework_text(event: Dict[str, Any]) -> str:
    fields = [
        event.get("tipo") or event.get("acao") or event.get("status"),
        event.get("motivo"),
        event.get("observacao") or event.get("observacoes"),
        event.get("message") or event.get("mensagem"),
    ]
    return " - ".join(str(field).strip() for field in fields if str(field or "").strip())


def _collect_op_rework_notes(
    op: Dict[str, Any],
    data: OPReworkCreate,
    order: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    _append_rework_note(notes, "solicitacao_retrabalho", data.anotacoes, prioridade=data.prioridade)
    _append_rework_note(notes, "observacoes_op", op.get("observacoes"), op_numero=op.get("numero_op"))

    if order:
        cliente = order.get("cliente") or {}
        _append_rework_note(
            notes,
            "pedido_comercial",
            {
                "pedido": order.get("numero_pedido") or order.get("pedido_cliente_ref") or order.get("id"),
                "cliente": cliente.get("nome") or order.get("cliente_nome"),
                "observacoes": order.get("observacoes"),
            },
            pedido_id=order.get("id"),
        )
        for idx, item in enumerate(order.get("items") or []):
            if data.item_idx is not None and idx != data.item_idx:
                continue
            _append_rework_note(
                notes,
                "item_pedido",
                {
                    "item": item.get("item"),
                    "codigo_kuryos": item.get("codigo_kuryos"),
                    "qtd": item.get("qtd"),
                    "prazo": item.get("prazo_entrega"),
                },
                item_idx=idx,
            )

    tecnico = op.get("tecnico") or {}
    _append_rework_note(notes, "ficha_tecnica_bloqueios", tecnico.get("bloqueios"))
    _append_rework_note(notes, "ficha_tecnica_alertas", tecnico.get("alertas"))
    for review in tecnico.get("items") or []:
        _append_rework_note(
            notes,
            "snapshot_tecnico_item",
            {
                "item": review.get("item"),
                "pd_request_id": review.get("pd_request_id"),
                "formula_id": review.get("formula_id"),
                "formula_versao": review.get("formula_versao"),
                "formula_status": review.get("formula_status"),
                "total_percentual": review.get("total_percentual"),
                "bloqueios": " | ".join(review.get("bloqueios") or []),
                "alertas": " | ".join(review.get("alertas") or []),
            },
        )

    for hist in op.get("historico") or []:
        _append_rework_note(
            notes,
            "historico_op",
            _event_rework_text(hist),
            em=hist.get("em") or hist.get("created_at") or hist.get("data"),
        )

    for apontamento in op.get("apontamentos") or []:
        texto = apontamento.get("observacoes") or {
            "qtd_produzida": apontamento.get("qtd_produzida"),
            "turno": apontamento.get("turno"),
        }
        _append_rework_note(
            notes,
            "apontamento",
            texto,
            em=apontamento.get("horario") or apontamento.get("em"),
            item=apontamento.get("item_nome"),
        )
    for perda in op.get("perdas") or []:
        _append_rework_note(
            notes,
            "perda",
            perda.get("motivo") or perda.get("observacoes"),
            em=perda.get("em"),
            item=perda.get("item_nome"),
            quantidade=perda.get("quantidade"),
            unidade=perda.get("unidade"),
        )
    for pausa in op.get("pausas") or []:
        _append_rework_note(
            notes,
            "pausa",
            pausa.get("motivo") or pausa.get("observacoes"),
            em=pausa.get("horario_inicio"),
            tipo=pausa.get("tipo"),
        )
    for checklist in op.get("checklist") or []:
        _append_rework_note(
            notes,
            "checklist_op",
            checklist.get("observacoes") or checklist.get("status") or checklist.get("item"),
            item=checklist.get("item") or checklist.get("categoria"),
            status=checklist.get("status"),
        )
    return notes


async def _mark_pd_request_rework_from_op(
    *,
    pd_request_id: str,
    update_doc: Dict[str, Any],
    user: Dict[str, Any],
    motivo: str,
) -> None:
    pd_req = await db.pd_requests.find_one({"id": pd_request_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not pd_req:
        return

    now = update_doc["created_at"]
    old_status = pd_req.get("status")
    set_fields = {
        "rework_pending_from_op": True,
        "last_rework_update_id": update_doc["id"],
        "last_rework_op_id": update_doc["op_id"],
        "last_rework_reason": motivo,
        "updated_at": now,
    }
    if old_status != "REJECTED":
        set_fields["status"] = "REJECTED"

    await db.pd_requests.update_one(
        {"id": pd_request_id, "tenant_id": user["tenant_id"]},
        {"$set": set_fields},
    )

    if old_status != "REJECTED":
        await db.pd_request_status_history.insert_one({
            "id": new_id(),
            "pd_request_id": pd_request_id,
            "from_status": old_status,
            "to_status": "REJECTED",
            "changed_by": user["id"],
            "changed_by_name": user.get("name", ""),
            "comment": f"Retrabalho enviado pela OP {update_doc.get('op_numero') or update_doc.get('op_id')}: {motivo}",
            "created_at": now,
        })

    card_event = {
        "de": None,
        "para": "retrabalho_interno",
        "data": now,
        "usuario": user.get("name", ""),
        "usuario_id": user["id"],
        "observacao": f"Retrabalho de OP enviado ao P&D: {motivo}",
        "pd_update_id": update_doc["id"],
        "op_id": update_doc["op_id"],
    }
    await db.pd_cards.update_many(
        {"pd_request_id": pd_request_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status_pd": "retrabalho_interno", "updated_at": now}, "$push": {"historico_movimentacoes": card_event}},
    )


@ops_router.post("/{op_id}/rework")
async def send_op_rework_to_pd(op_id: str, data: OPReworkCreate, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP nÃ£o encontrada")
    if len((data.motivo or "").strip()) < 5:
        raise HTTPException(status_code=400, detail="Informe o motivo do retrabalho com pelo menos 5 caracteres.")

    order = None
    if op.get("pedido_id"):
        order = await db.orders.find_one({"id": op["pedido_id"], "tenant_id": user["tenant_id"]}, {"_id": 0})
    pd_request_id = _pd_request_id_from_op(op, order)
    if not pd_request_id:
        raise HTTPException(status_code=422, detail="Nao foi possivel localizar o P&D vinculado a esta OP.")

    now = now_iso()
    update_doc = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "pd_request_id": pd_request_id,
        "source": "pcp_op_rework",
        "op_id": op["id"],
        "op_numero": op.get("numero_op"),
        "motivo": data.motivo.strip(),
        "prioridade": data.prioridade,
        "item_idx": data.item_idx,
        "anotacoes": _collect_op_rework_notes(op, data, order),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "status": "pendente_pd",
    }
    await db.pd_updates.insert_one(update_doc)
    await _mark_pd_request_rework_from_op(
        pd_request_id=pd_request_id,
        update_doc=update_doc,
        user=user,
        motivo=data.motivo.strip(),
    )

    event = {
        "id": new_id(),
        "tipo": "retrabalho_enviado_pd",
        "motivo": data.motivo.strip(),
        "pd_request_id": pd_request_id,
        "pd_update_id": update_doc["id"],
        "por": user.get("name", ""),
        "em": now,
    }
    await db.ops.update_one(
        {"id": op_id, "tenant_id": user["tenant_id"]},
        {"$push": {"historico": event}, "$set": {"updated_at": now}},
    )
    update_doc.pop("_id", None)
    return update_doc


class ApontamentoCreate(BaseModel):
    item_idx: int = 0
    qtd_produzida: float
    turno: str = "integral"     # manha | tarde | noite | integral
    horario: Optional[str] = None
    observacoes: str = ""


@ops_router.post("/{op_id}/apontar")
async def apontar_producao(op_id: str, data: ApontamentoCreate, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")
    if op["status"] not in ("em_processo", "aberta"):
        raise HTTPException(status_code=422, detail="Apontamento só é permitido em OPs abertas ou em processo")
    if data.qtd_produzida <= 0:
        raise HTTPException(status_code=400, detail="Quantidade produzida deve ser positiva")

    items = list(op.get("items", []))
    if data.item_idx >= len(items):
        raise HTTPException(status_code=400, detail=f"item_idx {data.item_idx} inválido")

    now = now_iso()
    apontamento = {
        "id": new_id(),
        "item_idx": data.item_idx,
        "item_nome": items[data.item_idx].get("item", ""),
        "qtd_produzida": data.qtd_produzida,
        "turno": data.turno,
        "horario": data.horario or now,
        "observacoes": data.observacoes,
        "por": user["name"],
        "em": now,
    }

    # Accumulate qtd_produzida on the item
    items[data.item_idx]["qtd_produzida"] = (
        float(items[data.item_idx].get("qtd_produzida") or 0) + data.qtd_produzida
    )

    await db.ops.update_one(
        {"id": op_id},
        {
            "$push": {"apontamentos": apontamento},
            "$set": {"items": items, "updated_at": now},
        }
    )
    return await db.ops.find_one({"id": op_id}, {"_id": 0})


# ─── Pausa / Retomada ─────────────────────────────────────────────────────────
class PausaCreate(BaseModel):
    motivo: str
    tipo: str = "outro"   # manutencao | falta_material | almoco | outro
    horario_inicio: Optional[str] = None


@ops_router.post("/{op_id}/pausar")
async def pausar_op(op_id: str, data: PausaCreate, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")
    if op["status"] != "em_processo":
        raise HTTPException(status_code=422, detail="Só é possível pausar OPs em processo")
    # Check no open pause
    pausas = op.get("pausas", [])
    if any(p.get("horario_fim") is None for p in pausas):
        raise HTTPException(status_code=409, detail="Há uma pausa em aberto — retome antes de pausar novamente")

    now = now_iso()
    pausa = {
        "id": new_id(),
        "tipo": data.tipo,
        "motivo": data.motivo,
        "horario_inicio": data.horario_inicio or now,
        "horario_fim": None,
        "duracao_min": None,
        "por": user["name"],
        "em": now,
    }
    await db.ops.update_one(
        {"id": op_id},
        {"$push": {"pausas": pausa}, "$set": {"status": "pausada", "updated_at": now}}
    )
    return await db.ops.find_one({"id": op_id}, {"_id": 0})


@ops_router.post("/{op_id}/retomar")
async def retomar_op(op_id: str, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")
    if op["status"] != "pausada":
        raise HTTPException(status_code=422, detail="OP não está pausada")

    now = now_iso()
    pausas = list(op.get("pausas", []))
    # Close the open pause
    for p in reversed(pausas):
        if p.get("horario_fim") is None:
            from datetime import datetime, timezone
            try:
                inicio = datetime.fromisoformat(p["horario_inicio"].replace("Z", "+00:00"))
                fim = datetime.now(timezone.utc)
                p["duracao_min"] = int((fim - inicio).total_seconds() / 60)
            except Exception:
                p["duracao_min"] = None
            p["horario_fim"] = now
            break

    await db.ops.update_one(
        {"id": op_id},
        {"$set": {"pausas": pausas, "status": "em_processo", "updated_at": now}}
    )
    return await db.ops.find_one({"id": op_id}, {"_id": 0})


# ─── Registro de perdas ───────────────────────────────────────────────────────
class PerdaCreate(BaseModel):
    item_idx: int = 0
    tipo: str = "processo"    # processo | material | embalagem | outro
    quantidade: float
    unidade: str = "un"
    motivo: str = ""


@ops_router.post("/{op_id}/perda")
async def registrar_perda(op_id: str, data: PerdaCreate, request: Request):
    user = await get_current_user(request)
    op = await db.ops.find_one({"id": op_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")
    if data.quantidade <= 0:
        raise HTTPException(status_code=400, detail="Quantidade de perda deve ser positiva")

    items = list(op.get("items", []))
    item_nome = items[data.item_idx].get("item", "") if data.item_idx < len(items) else ""

    now = now_iso()
    perda = {
        "id": new_id(),
        "item_idx": data.item_idx,
        "item_nome": item_nome,
        "tipo": data.tipo,
        "quantidade": data.quantidade,
        "unidade": data.unidade,
        "motivo": data.motivo,
        "por": user["name"],
        "em": now,
    }
    await db.ops.update_one(
        {"id": op_id},
        {"$push": {"perdas": perda}, "$set": {"updated_at": now}}
    )
    return await db.ops.find_one({"id": op_id}, {"_id": 0})
