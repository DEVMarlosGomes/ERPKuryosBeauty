"""
Recebimento de Materiais — entrada de NF vinculada à PO.
Fluxo:
  1. Recebimento criado → cada item vai para estoque em posicao_cq="quarentena"
  2. RA CQ criada automaticamente (recepcao_mp ou recepcao_embalagem)
  3. CQ aprova → WMS posicao_cq="aprovado"; CQ reprova → posicao_cq="reprovado"

Regras de Negócio:
  RN-REC-00: SLA configurável por tipo de insumo (FORMULACAO/ROTULO/EMBALAGEM)
  RN-REC-00B: URGENTE se insumo está bloqueando OP nos próximos 14 dias
  RN-REC-01: Liberar CQ → atualiza checklist MRP automaticamente
  RN-REC-02: Reprova CQ → abre RNC automaticamente
  RN-REC-03: Auto-vincular PO por fornecedor + insumo (1 match = auto; N > 1 = lista)
  RN-REC-04: Insumo de origem cliente → link direto ao PI
  RN-REC-05: Registro imutável (sem DELETE) com who/when/qty/link
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

recebimento_router = APIRouter(prefix="/api/recebimento")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_recebimento(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def new_id():
    return new_id_func()


def now_iso():
    return now_iso_func()


# ===== MAPS =====
_TIPO_MP_TO_SETOR = {
    "FORMULACAO": "MANIPULACAO",
    "ROTULO": "ROTULAGEM",
    "EMBALAGEM": "LOGISTICA",
}

_TIPO_MP_TO_RA_TIPO = {
    "FORMULACAO": "recepcao_mp",
    "ROTULO": "recepcao_embalagem",
    "EMBALAGEM": "recepcao_embalagem",
}

# Default SLA in business days per tipo_mp
_DEFAULT_SLA = {"FORMULACAO": 3, "ROTULO": 2, "EMBALAGEM": 2}


# ===== MODELS =====
class RecebimentoItem(BaseModel):
    nome: str
    codigo: str = ""
    tipo_mp: str = "FORMULACAO"
    quantidade: float
    unidade: str = "kg"
    lote: str = ""
    validade: Optional[str] = None
    mp_id: Optional[str] = None
    origem_cliente: bool = False     # RN-REC-04: insumo cedido pelo cliente
    pedido_id: Optional[str] = None  # RN-REC-04: pedido de origem


class RecebimentoCreate(BaseModel):
    po_id: Optional[str] = None
    po_numero: Optional[str] = None
    fornecedor_id: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    numero_nf: str
    data_nf: str                     # YYYY-MM-DD
    items: List[RecebimentoItem]
    observacoes: str = ""


class SLAConfig(BaseModel):
    FORMULACAO: int = 3
    ROTULO: int = 2
    EMBALAGEM: int = 2


# ===== HELPERS =====
async def _check_urgente(tid: str, item_nome: str) -> bool:
    """RN-REC-00B: True if item is blocking a scheduled OP within 14 days."""
    deadline = (datetime.utcnow() + timedelta(days=14)).isoformat()[:10]
    today = datetime.utcnow().isoformat()[:10]
    ops = await db.ops.find(
        {
            "tenant_id": tid,
            "status": {"$in": ["pendente", "liberada", "em_producao"]},
            "data_prevista": {"$lte": deadline, "$gte": today},
        },
        {"_id": 0, "insumos": 1},
    ).to_list(300)
    nome_lower = item_nome.lower()
    for op in ops:
        for ins in op.get("insumos") or []:
            if nome_lower in (ins.get("nome") or "").lower():
                return True
    return False


async def _get_sla(tid: str) -> dict:
    cfg = await db.recebimento_sla_config.find_one({"tenant_id": tid}, {"_id": 0})
    if cfg:
        return cfg
    return {**_DEFAULT_SLA, "tenant_id": tid}


# ===== ROUTES =====

# ---- SLA Config ----
@recebimento_router.get("/sla-config")
async def get_sla_config(request: Request):
    """RN-REC-00: Get CQ SLA days by material type."""
    user = await get_current_user(request)
    return await _get_sla(user["tenant_id"])


@recebimento_router.put("/sla-config")
async def update_sla_config(data: SLAConfig, request: Request):
    """RN-REC-00: Update CQ SLA days by material type."""
    user = await get_current_user(request)
    tid = user["tenant_id"]
    cfg = {
        "tenant_id": tid,
        "FORMULACAO": data.FORMULACAO,
        "ROTULO": data.ROTULO,
        "EMBALAGEM": data.EMBALAGEM,
        "updated_at": now_iso(),
    }
    await db.recebimento_sla_config.update_one(
        {"tenant_id": tid}, {"$set": cfg}, upsert=True
    )
    return cfg


# ---- PO Auto-link Suggestion ----
@recebimento_router.get("/sugerir-po")
async def sugerir_po(
    request: Request,
    item_nome: Optional[str] = None,
    fornecedor_id: Optional[str] = None,
):
    """RN-REC-03: Suggest open POs matching fornecedor + item name."""
    user = await get_current_user(request)
    tid = user["tenant_id"]

    query: Dict[str, Any] = {
        "tenant_id": tid,
        "status": {"$in": ["aprovada", "em_entrega"]},
    }
    if fornecedor_id:
        query["fornecedor_id"] = fornecedor_id

    pos = await db.compras_pos.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)

    if item_nome:
        nome_lower = item_nome.lower()
        pos = [
            po for po in pos
            if any(
                nome_lower in (it.get("nome") or "").lower()
                for it in (po.get("items") or po.get("itens") or [])
            )
        ]

    return pos[:10]


# ---- URGENT Check ----
@recebimento_router.get("/check-urgente")
async def check_urgente(request: Request, item_nome: str):
    """RN-REC-00B: Check if an insumo is blocking a scheduled OP in the next 14 days."""
    user = await get_current_user(request)
    urgente = await _check_urgente(user["tenant_id"], item_nome)
    return {"urgente": urgente, "item_nome": item_nome}


# ---- List / Get ----
@recebimento_router.get("/entradas")
async def list_entradas(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if q:
        query["$or"] = [
            {"numero_nf": {"$regex": q, "$options": "i"}},
            {"fornecedor_nome": {"$regex": q, "$options": "i"}},
            {"po_numero": {"$regex": q, "$options": "i"}},
        ]
    entradas = await db.recebimentos.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return entradas


@recebimento_router.get("/entradas/{entrada_id}")
async def get_entrada(entrada_id: str, request: Request):
    user = await get_current_user(request)
    entrada = await db.recebimentos.find_one({"id": entrada_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not entrada:
        raise HTTPException(status_code=404, detail="Recebimento não encontrado")
    return entrada


# ---- Create ----
@recebimento_router.post("/entradas")
async def create_entrada(data: RecebimentoCreate, request: Request):
    """
    Registra entrada de NF (RN-REC-05: imutável):
    - Cria/atualiza itens no estoque com posicao_cq=quarentena
    - Marca URGENTE se insumo bloqueia OP nos próximos 14 dias (RN-REC-00B)
    - Cria RA no CQ para cada item
    - Aplica SLA ao prazo da RA (RN-REC-00)
    - Cria registro imutável do recebimento
    """
    user = await get_current_user(request)
    tid = user["tenant_id"]

    if not data.items:
        raise HTTPException(status_code=400, detail="Informe ao menos um item")

    now = now_iso()
    entrada_id = new_id()
    sla = await _get_sla(tid)
    items_processados = []

    for item in data.items:
        setor = _TIPO_MP_TO_SETOR.get(item.tipo_mp, "MANIPULACAO")
        ra_tipo = _TIPO_MP_TO_RA_TIPO.get(item.tipo_mp, "recepcao_mp")
        urgente = await _check_urgente(tid, item.nome)

        # SLA deadline
        sla_days = sla.get(item.tipo_mp, 3)
        data_limite_cq = (datetime.utcnow() + timedelta(days=sla_days)).isoformat()[:10]
        lote_id = new_id()
        ra_id = new_id()

        # 1) Find or create estoque item
        query_estoque: Dict[str, Any] = {"tenant_id": tid, "setor": setor, "cq_lote_id": lote_id}
        if item.mp_id:
            query_estoque["mp_id"] = item.mp_id
        else:
            query_estoque["nome"] = item.nome
            query_estoque["mp_id"] = None
        if item.lote:
            query_estoque["lote"] = item.lote

        estoque_item = await db.estoque_items.find_one(query_estoque, {"_id": 0})
        estoque_item_id = None

        if estoque_item:
            estoque_item_id = estoque_item["id"]
            if estoque_item.get("posicao_cq") not in ("aprovado",):
                await db.estoque_items.update_one(
                    {"id": estoque_item_id},
                    {
                        "$set": {
                            "posicao_cq": "quarentena",
                            "cq_status": "quarentena",
                            "cq_lote_id": lote_id,
                            "cq_ra_id": ra_id,
                            "prazo_analise_qualidade": data_limite_cq,
                            "lote": item.lote or estoque_item.get("lote", ""),
                            "updated_at": now,
                        }
                    }
                )
        else:
            estoque_item_id = new_id()
            new_item = {
                "id": estoque_item_id,
                "tenant_id": tid,
                "tipo_item": "mp",
                "setor": setor,
                "nome": item.nome,
                "codigo": item.codigo,
                "mp_id": item.mp_id,
                "produto_id": None,
                "unidade": item.unidade,
                "quantidade_atual": 0,
                "estoque_minimo": 0,
                "localizacao": "",
                "lote": item.lote,
                "validade": item.validade,
                "observacoes": "",
                "posicao_cq": "quarentena",
                "cq_status": "quarentena",
                "cq_lote_id": lote_id,
                "cq_ra_id": ra_id,
                "prazo_analise_qualidade": data_limite_cq,
                "created_by": user["id"],
                "created_by_name": user["name"],
                "created_at": now,
                "updated_at": now,
            }
            await db.estoque_items.insert_one(new_item)

        # 2) WMS entry movement
        estoque_item_full = await db.estoque_items.find_one({"id": estoque_item_id}, {"_id": 0})
        if estoque_item_full:
            qty_antes = estoque_item_full.get("quantidade_atual", 0)
            qty_depois = qty_antes + item.quantidade
            await db.estoque_items.update_one(
                {"id": estoque_item_id},
                {"$set": {"quantidade_atual": qty_depois, "updated_at": now}}
            )
            mov = {
                "id": new_id(),
                "tenant_id": tid,
                "item_id": estoque_item_id,
                "setor": setor,
                "tipo_item": "mp",
                "nome_item": item.nome,
                "codigo_item": item.codigo,
                "lote": item.lote,
                "tipo": "ENTRADA_RECEBIMENTO",
                "direcao": "entrada",
                "quantidade": item.quantidade,
                "unidade": item.unidade,
                "quantidade_antes": qty_antes,
                "quantidade_depois": qty_depois,
                "motivo": f"Recebimento NF {data.numero_nf}",
                "referencia": entrada_id,
                "documento": data.numero_nf,
                "usuario": user["name"],
                "usuario_id": user["id"],
                "created_at": now,
            }
            await db.estoque_movimentos.insert_one(mov)

        # 3) Create RA in CQ with SLA deadline
        lote_numero = item.lote or f"L{now[:10].replace('-', '')}"
        ra = {
            "id": ra_id,
            "tenant_id": tid,
            "lote_id": lote_id,
            "lote_numero": lote_numero,
            "tipo": ra_tipo,
            "status": "rascunho",
            "item_id": estoque_item_id,
            "item_nome": item.nome,
            "item_tipo": item.tipo_mp,
            "fornecedor_id": data.fornecedor_id,
            "fornecedor_nome": data.fornecedor_nome,
            "nf_numero": data.numero_nf,
            "nf_data": data.data_nf,
            "quantidade_recebida": item.quantidade,
            "unidade": item.unidade,
            "numero_lote_fornecedor": item.lote,
            "data_validade_fornecedor": item.validade,
            "data_limite_cq": data_limite_cq,
            "urgente": urgente,
            "parametros": [],
            "recebimento_id": entrada_id,
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        await db.cq_registros_analise.insert_one(ra)

        items_processados.append({
            **item.model_dump(),
            "estoque_item_id": estoque_item_id,
            "setor": setor,
            "ra_id": ra["id"],
            "ra_status": "rascunho",
            "lote_id": lote_id,
            "urgente": urgente,
            "data_limite_cq": data_limite_cq,
        })

    # 4) Create immutable recebimento record (RN-REC-05)
    entrada = {
        "id": entrada_id,
        "tenant_id": tid,
        "po_id": data.po_id,
        "po_numero": data.po_numero,
        "fornecedor_id": data.fornecedor_id,
        "fornecedor_nome": data.fornecedor_nome or "",
        "numero_nf": data.numero_nf,
        "data_nf": data.data_nf,
        "status": "quarentena",
        "items": items_processados,
        "tem_urgente": any(i.get("urgente") for i in items_processados),
        "observacoes": data.observacoes,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.recebimentos.insert_one(entrada)
    entrada.pop("_id", None)
    logger.info(f"Recebimento {entrada_id} criado: NF={data.numero_nf} itens={len(items_processados)} urgente={entrada['tem_urgente']}")
    return entrada


# ---- RN-REC-05: No DELETE ----
@recebimento_router.delete("/entradas/{entrada_id}")
async def delete_blocked(entrada_id: str):
    raise HTTPException(
        status_code=405,
        detail="Registros de recebimento são imutáveis. Exclusão não permitida (RN-REC-05)."
    )
