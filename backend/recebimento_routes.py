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
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
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


async def create_recebimento_indexes():
    await db.recebimentos.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.recebimentos.create_index([("tenant_id", 1), ("po_id", 1)])
    await db.recebimento_agendamentos.create_index([("tenant_id", 1), ("data", 1), ("status", 1)])
    await db.wms_paletes.create_index([("tenant_id", 1), ("recebimento_id", 1)])
    await db.wms_paletes.create_index([("tenant_id", 1), ("etiqueta_codigo", 1)], unique=True)


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
class RecebimentoChecklistItem(BaseModel):
    codigo: str
    descricao: str
    obrigatorio: bool = True
    status: str = "pendente"  # pendente | ok | divergente | nao_aplicavel
    observacao: str = ""


class RecebimentoPaleteInput(BaseModel):
    quantidade_paletes: int = 1
    volumes_por_palete: Optional[float] = None
    peso_bruto: Optional[float] = None
    dimensoes: str = ""
    observacoes: str = ""


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
    po_item_id: Optional[str] = None
    endereco_id: Optional[str] = None
    endereco_codigo: str = ""
    checklist: List[RecebimentoChecklistItem] = Field(default_factory=list)
    palete: Optional[RecebimentoPaleteInput] = None


class RecebimentoCreate(BaseModel):
    po_id: Optional[str] = None
    po_numero: Optional[str] = None
    fornecedor_id: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    numero_nf: str
    data_nf: str                     # YYYY-MM-DD
    items: List[RecebimentoItem]
    checklist_geral: List[RecebimentoChecklistItem] = Field(default_factory=list)
    agendamento_id: Optional[str] = None
    observacoes: str = ""


class SLAConfig(BaseModel):
    FORMULACAO: int = 3
    ROTULO: int = 2
    EMBALAGEM: int = 2


class AgendamentoRecebimentoCreate(BaseModel):
    tipo: str = "entrega"  # coleta | entrega
    titulo: str = ""
    fornecedor_id: Optional[str] = None
    fornecedor_nome: str = ""
    po_id: Optional[str] = None
    po_numero: str = ""
    data: str
    hora_inicio: str = ""
    hora_fim: str = ""
    doca: str = ""
    transportadora: str = ""
    placa: str = ""
    motorista: str = ""
    status: str = "agendado"  # agendado | confirmado | em_recebimento | concluido | cancelado
    observacoes: str = ""


class AgendamentoRecebimentoUpdate(BaseModel):
    tipo: Optional[str] = None
    titulo: Optional[str] = None
    fornecedor_id: Optional[str] = None
    fornecedor_nome: Optional[str] = None
    po_id: Optional[str] = None
    po_numero: Optional[str] = None
    data: Optional[str] = None
    hora_inicio: Optional[str] = None
    hora_fim: Optional[str] = None
    doca: Optional[str] = None
    transportadora: Optional[str] = None
    placa: Optional[str] = None
    motorista: Optional[str] = None
    status: Optional[str] = None
    observacoes: Optional[str] = None


# ===== HELPERS =====
async def _check_urgente(tid: str, item_nome: str) -> bool:
    """RN-REC-00B: True if item is blocking a scheduled OP within 14 days."""
    deadline = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()[:10]
    today = datetime.now(timezone.utc).isoformat()[:10]
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


def _default_checklist_item(item: RecebimentoItem) -> List[dict]:
    base = [
        ("nf", "NF recebida e legivel", True),
        ("po", "PO conferida contra a entrega", True),
        ("quantidade", "Quantidade fisica conferida", True),
        ("lote_validade", "Lote e validade informados", True),
        ("integridade", "Embalagem sem avaria", True),
        ("certificado", "Certificado/laudo anexado quando aplicavel", False),
    ]
    custom = [c.model_dump() for c in item.checklist]
    if custom:
        return custom
    return [
        {
            "codigo": codigo,
            "descricao": descricao,
            "obrigatorio": obrigatorio,
            "status": "ok" if codigo not in {"lote_validade"} or item.lote else "pendente",
            "observacao": "",
        }
        for codigo, descricao, obrigatorio in base
    ]


def _checklist_status(checklist: List[dict]) -> str:
    if any(c.get("status") == "divergente" for c in checklist):
        return "divergente"
    pendentes = [
        c for c in checklist
        if c.get("obrigatorio", True) and c.get("status") not in {"ok", "nao_aplicavel"}
    ]
    return "pendente" if pendentes else "ok"


async def _get_po_if_any(po_id: Optional[str], tenant_id: str) -> Optional[dict]:
    if not po_id:
        return None
    po = await db.compras_pos.find_one({"id": po_id, "tenant_id": tenant_id}, {"_id": 0})
    if not po:
        raise HTTPException(status_code=404, detail="PO nao encontrada para recebimento")
    if po.get("status") not in {"emitida", "confirmada", "parcialmente_recebida", "aprovada", "em_entrega"}:
        raise HTTPException(status_code=422, detail=f"PO com status '{po.get('status')}' nao permite recebimento")
    return po


def _match_po_item(po: Optional[dict], item: RecebimentoItem) -> Optional[dict]:
    if not po:
        return None
    itens = po.get("itens") or []
    for po_item in itens:
        if item.po_item_id and po_item.get("id") == item.po_item_id:
            return po_item
    for po_item in itens:
        if item.mp_id and po_item.get("item_id") == item.mp_id:
            return po_item
    for po_item in itens:
        if item.codigo and item.codigo in {po_item.get("item_codigo"), po_item.get("codigo_interno")}:
            return po_item
    nome = (item.nome or "").strip().lower()
    if nome:
        for po_item in itens:
            if nome == (po_item.get("item_descricao") or "").strip().lower():
                return po_item
    return None


def _todos_po_itens_recebidos(itens: List[dict]) -> bool:
    return all(
        float(it.get("quantidade_recebida", 0)) >= float(it.get("quantidade_solicitada", 0))
        for it in itens
    )


async def _atualizar_po_recebimento_item_a_item(po: dict, recebimento: dict, user: dict) -> List[str]:
    itens_po = [dict(it) for it in (po.get("itens") or [])]
    divergencias: List[str] = []
    for recebido in recebimento.get("items", []):
        po_item_id = recebido.get("po_item_id")
        if not po_item_id:
            divergencias.append(f"{recebido.get('nome')}: sem item de PO vinculado")
            continue
        po_item = next((it for it in itens_po if it.get("id") == po_item_id), None)
        if not po_item:
            divergencias.append(f"{recebido.get('nome')}: item de PO nao encontrado")
            continue
        anterior = float(po_item.get("quantidade_recebida", 0))
        nova = anterior + float(recebido.get("quantidade", 0))
        po_item["quantidade_recebida"] = nova
        solicitado = float(po_item.get("quantidade_solicitada", 0))
        if nova > solicitado + 0.001:
            divergencias.append(f"{po_item.get('item_descricao', po_item_id)}: recebido acima do solicitado")
        po_item["status_cq_lote"] = "quarentena"

    novo_status = "recebida" if _todos_po_itens_recebidos(itens_po) else "parcialmente_recebida"
    nf_entry = {
        "nf_id": recebimento["id"],
        "nf_numero": recebimento.get("numero_nf"),
        "nf_data": recebimento.get("data_nf"),
        "status_cq": "quarentena",
        "recebido_por_id": user["id"],
        "recebido_por_nome": user.get("name", ""),
        "recebido_em": now_iso(),
        "itens": [
            {
                "po_item_id": i.get("po_item_id"),
                "item_id": i.get("mp_id"),
                "quantidade_recebida": i.get("quantidade"),
                "lote": i.get("lote"),
            }
            for i in recebimento.get("items", [])
        ],
    }
    log_entry = {
        "acao": "recebimento_granular_registrado",
        "recebimento_id": recebimento["id"],
        "nf_numero": recebimento.get("numero_nf"),
        "por_id": user["id"],
        "por_nome": user.get("name", ""),
        "em": now_iso(),
    }
    await db.compras_pos.update_one(
        {"id": po["id"], "tenant_id": user["tenant_id"]},
        {
            "$set": {"itens": itens_po, "status": novo_status, "updated_at": now_iso()},
            "$push": {"nfs_vinculadas": nf_entry, "log_auditoria": log_entry},
        },
    )
    return divergencias


async def _registrar_saldo_wms_lote(item_doc: dict, endereco_id: Optional[str], endereco_codigo: str, qtd: float, user: dict, recebimento_id: str):
    if not endereco_id:
        return None
    endereco = await db.wms_enderecos.find_one({"id": endereco_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not endereco:
        raise HTTPException(status_code=404, detail=f"Endereco WMS nao encontrado: {endereco_id}")
    lote = item_doc.get("lote") or item_doc.get("numero_lote_fornecedor") or "SEM-LOTE"
    query = {
        "tenant_id": user["tenant_id"],
        "item_id": item_doc["estoque_item_id"],
        "lote": lote,
        "endereco_id": endereco_id,
    }
    saldo = await db.estoque_saldos_lote.find_one(query, {"_id": 0})
    atual = float((saldo or {}).get("quantidade", 0))
    novo = atual + float(qtd)
    now = now_iso()
    if not saldo:
        saldo = {
            "id": new_id(),
            "tenant_id": user["tenant_id"],
            "item_id": item_doc["estoque_item_id"],
            "item_nome": item_doc.get("nome", ""),
            "codigo_item": item_doc.get("codigo", ""),
            "tipo_item": "mp",
            "lote": lote,
            "validade": item_doc.get("validade"),
            "endereco_id": endereco_id,
            "endereco_codigo": endereco_codigo or endereco.get("codigo", ""),
            "setor": endereco.get("setor", item_doc.get("setor", "")),
            "quantidade": 0.0,
            "quantidade_atual": 0.0,
            "unidade": item_doc.get("unidade", "kg"),
            "posicao_cq": "quarentena",
            "status": "quarentena",
            "recebimento_id": recebimento_id,
            "created_at": now,
            "updated_at": now,
        }
        await db.estoque_saldos_lote.insert_one(saldo)
    await db.estoque_saldos_lote.update_one(
        {"id": saldo["id"], "tenant_id": user["tenant_id"]},
        {"$set": {"quantidade": novo, "quantidade_atual": novo, "status": "quarentena", "updated_at": now}},
    )
    await db.wms_enderecos.update_one(
        {"id": endereco_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "ocupado", "updated_at": now}},
    )
    return await db.estoque_saldos_lote.find_one({"id": saldo["id"], "tenant_id": user["tenant_id"]}, {"_id": 0})


async def _criar_paletes(item_doc: dict, palete_data: Optional[RecebimentoPaleteInput], user: dict, recebimento_id: str) -> List[dict]:
    cfg = palete_data or RecebimentoPaleteInput()
    total = max(1, int(cfg.quantidade_paletes or 1))
    docs = []
    for idx in range(1, total + 1):
        palete_id = new_id()
        etiqueta = f"PAL-{now_iso()[:10].replace('-', '')}-{palete_id[:8].upper()}"
        doc = {
            "id": palete_id,
            "tenant_id": user["tenant_id"],
            "recebimento_id": recebimento_id,
            "estoque_item_id": item_doc.get("estoque_item_id"),
            "item_nome": item_doc.get("nome", ""),
            "codigo_item": item_doc.get("codigo", ""),
            "lote": item_doc.get("lote", ""),
            "endereco_id": item_doc.get("endereco_id"),
            "endereco_codigo": item_doc.get("endereco_codigo", ""),
            "etiqueta_codigo": etiqueta,
            "capa_palete": {
                "codigo": f"CAPA-{etiqueta}",
                "fornecedor": item_doc.get("fornecedor_nome", ""),
                "nf": item_doc.get("numero_nf", ""),
                "status_cq": "quarentena",
                "volumes_por_palete": cfg.volumes_por_palete,
                "peso_bruto": cfg.peso_bruto,
                "dimensoes": cfg.dimensoes,
                "observacoes": cfg.observacoes,
            },
            "sequencia": idx,
            "total_paletes": total,
            "status": "quarentena",
            "impresso_em": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.wms_paletes.insert_one(doc)
        docs.append({k: v for k, v in doc.items() if k != "_id"})
    return docs


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
        "status": {"$in": ["emitida", "confirmada", "parcialmente_recebida", "aprovada", "em_entrega"]},
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


# ---- Agendamentos Logistica ----
@recebimento_router.get("/agendamentos")
async def list_agendamentos(
    request: Request,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    tipo: Optional[str] = None,
    status: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if tipo:
        query["tipo"] = tipo
    if status:
        query["status"] = status
    if data_inicio or data_fim:
        data_query = {}
        if data_inicio:
            data_query["$gte"] = data_inicio
        if data_fim:
            data_query["$lte"] = data_fim
        query["data"] = data_query
    docs = await db.recebimento_agendamentos.find(query, {"_id": 0}).sort("data", 1).to_list(1000)
    return {"agendamentos": docs, "total": len(docs)}


@recebimento_router.post("/agendamentos", status_code=201)
async def create_agendamento(data: AgendamentoRecebimentoCreate, request: Request):
    user = await get_current_user(request)
    if data.tipo not in {"coleta", "entrega"}:
        raise HTTPException(status_code=422, detail="Tipo deve ser coleta ou entrega")
    if data.status not in {"agendado", "confirmado", "em_recebimento", "concluido", "cancelado"}:
        raise HTTPException(status_code=422, detail="Status de agendamento invalido")
    now = now_iso()
    po = await _get_po_if_any(data.po_id, user["tenant_id"]) if data.po_id else None
    doc = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "tipo": data.tipo,
        "titulo": data.titulo or f"{data.tipo.title()} {data.po_numero or data.fornecedor_nome or data.data}",
        "fornecedor_id": data.fornecedor_id or (po or {}).get("fornecedor_id"),
        "fornecedor_nome": data.fornecedor_nome or (po or {}).get("fornecedor_nome", ""),
        "po_id": data.po_id,
        "po_numero": data.po_numero or (po or {}).get("numero_po", ""),
        "data": data.data,
        "hora_inicio": data.hora_inicio,
        "hora_fim": data.hora_fim,
        "doca": data.doca,
        "transportadora": data.transportadora,
        "placa": data.placa,
        "motorista": data.motorista,
        "status": data.status,
        "observacoes": data.observacoes,
        "recebimento_id": None,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.recebimento_agendamentos.insert_one(doc)
    doc.pop("_id", None)
    return doc


@recebimento_router.put("/agendamentos/{agendamento_id}")
async def update_agendamento(agendamento_id: str, data: AgendamentoRecebimentoUpdate, request: Request):
    user = await get_current_user(request)
    existing = await db.recebimento_agendamentos.find_one({"id": agendamento_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")
    payload = data.model_dump(exclude_unset=True)
    if "tipo" in payload and payload["tipo"] not in {"coleta", "entrega"}:
        raise HTTPException(status_code=422, detail="Tipo deve ser coleta ou entrega")
    if "status" in payload and payload["status"] not in {"agendado", "confirmado", "em_recebimento", "concluido", "cancelado"}:
        raise HTTPException(status_code=422, detail="Status de agendamento invalido")
    payload["updated_at"] = now_iso()
    await db.recebimento_agendamentos.update_one({"id": agendamento_id, "tenant_id": user["tenant_id"]}, {"$set": payload})
    return await db.recebimento_agendamentos.find_one({"id": agendamento_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@recebimento_router.delete("/agendamentos/{agendamento_id}")
async def cancel_agendamento(agendamento_id: str, request: Request):
    user = await get_current_user(request)
    existing = await db.recebimento_agendamentos.find_one({"id": agendamento_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")
    await db.recebimento_agendamentos.update_one(
        {"id": agendamento_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "cancelado", "updated_at": now_iso()}},
    )
    return {"cancelado": agendamento_id}


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
    po = await _get_po_if_any(data.po_id, tid)
    items_processados = []

    for item in data.items:
        po_item = _match_po_item(po, item)
        if po and not po_item:
            raise HTTPException(status_code=422, detail=f"Item '{item.nome}' nao encontrado na PO informada")
        po_item_id = (po_item or {}).get("id") or item.po_item_id
        item_mp_id = item.mp_id or (po_item or {}).get("item_id")
        item_codigo = item.codigo or (po_item or {}).get("item_codigo") or (po_item or {}).get("codigo_interno") or ""
        checklist = _default_checklist_item(item)
        checklist_status = _checklist_status(checklist)

        setor = _TIPO_MP_TO_SETOR.get(item.tipo_mp, "MANIPULACAO")
        ra_tipo = _TIPO_MP_TO_RA_TIPO.get(item.tipo_mp, "recepcao_mp")
        urgente = await _check_urgente(tid, item.nome)

        # SLA deadline
        sla_days = sla.get(item.tipo_mp, 3)
        data_limite_cq = (datetime.now(timezone.utc) + timedelta(days=sla_days)).isoformat()[:10]
        lote_id = new_id()
        ra_id = new_id()

        # 1) Find or create estoque item
        query_estoque: Dict[str, Any] = {"tenant_id": tid, "setor": setor, "cq_lote_id": lote_id}
        if item_mp_id:
            query_estoque["mp_id"] = item_mp_id
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
                "codigo": item_codigo,
                "mp_id": item_mp_id,
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
                "codigo_item": item_codigo,
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
            "checklist_recebimento": checklist,
            "checklist_status": checklist_status,
            "parametros": [],
            "recebimento_id": entrada_id,
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        await db.cq_registros_analise.insert_one(ra)

        item_processado = {
            **item.model_dump(),
            "codigo": item_codigo,
            "mp_id": item_mp_id,
            "po_item_id": po_item_id,
            "po_item_descricao": (po_item or {}).get("item_descricao", ""),
            "numero_nf": data.numero_nf,
            "fornecedor_nome": data.fornecedor_nome or "",
            "estoque_item_id": estoque_item_id,
            "setor": setor,
            "ra_id": ra["id"],
            "ra_status": "rascunho",
            "lote_id": lote_id,
            "urgente": urgente,
            "data_limite_cq": data_limite_cq,
            "checklist": checklist,
            "checklist_status": checklist_status,
        }
        saldo_wms = await _registrar_saldo_wms_lote(
            item_processado, item.endereco_id, item.endereco_codigo, item.quantidade, user, entrada_id
        )
        paletes = await _criar_paletes(item_processado, item.palete, user, entrada_id)
        item_processado["saldo_wms"] = saldo_wms
        item_processado["paletes"] = paletes
        items_processados.append(item_processado)

    # 4) Create immutable recebimento record (RN-REC-05)
    checklist_geral = [c.model_dump() for c in data.checklist_geral]
    status_checklists = [i.get("checklist_status") for i in items_processados]
    entrada_status = "divergente" if "divergente" in status_checklists else "quarentena"
    entrada = {
        "id": entrada_id,
        "tenant_id": tid,
        "po_id": data.po_id,
        "po_numero": data.po_numero,
        "agendamento_id": data.agendamento_id,
        "fornecedor_id": data.fornecedor_id,
        "fornecedor_nome": data.fornecedor_nome or "",
        "numero_nf": data.numero_nf,
        "data_nf": data.data_nf,
        "status": entrada_status,
        "items": items_processados,
        "checklist_geral": checklist_geral,
        "checklist_status": _checklist_status(checklist_geral) if checklist_geral else ("divergente" if entrada_status == "divergente" else "ok"),
        "tem_urgente": any(i.get("urgente") for i in items_processados),
        "integracao_po": {"status": "nao_aplicavel", "divergencias": []},
        "observacoes": data.observacoes,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.recebimentos.insert_one(entrada)
    divergencias_po: List[str] = []
    if po:
        divergencias_po = await _atualizar_po_recebimento_item_a_item(po, entrada, user)
        integracao_po = {"status": "divergente" if divergencias_po else "sincronizado", "divergencias": divergencias_po}
        await db.recebimentos.update_one(
            {"id": entrada_id, "tenant_id": tid},
            {"$set": {"integracao_po": integracao_po, "updated_at": now_iso()}},
        )
        entrada["integracao_po"] = integracao_po
    if data.agendamento_id:
        await db.recebimento_agendamentos.update_one(
            {"id": data.agendamento_id, "tenant_id": tid},
            {"$set": {"status": "em_recebimento", "recebimento_id": entrada_id, "updated_at": now_iso()}},
        )
    entrada.pop("_id", None)
    logger.info(f"Recebimento {entrada_id} criado: NF={data.numero_nf} itens={len(items_processados)} urgente={entrada['tem_urgente']}")
    return entrada


@recebimento_router.get("/entradas/{entrada_id}/etiquetas")
async def listar_etiquetas_entrada(entrada_id: str, request: Request):
    user = await get_current_user(request)
    entrada = await db.recebimentos.find_one({"id": entrada_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not entrada:
        raise HTTPException(status_code=404, detail="Recebimento nao encontrado")
    paletes = await db.wms_paletes.find(
        {"tenant_id": user["tenant_id"], "recebimento_id": entrada_id}, {"_id": 0}
    ).sort("sequencia", 1).to_list(1000)
    return {"recebimento_id": entrada_id, "paletes": paletes, "total": len(paletes)}


@recebimento_router.post("/paletes/{palete_id}/imprimir")
async def marcar_palete_impresso(palete_id: str, request: Request):
    user = await get_current_user(request)
    palete = await db.wms_paletes.find_one({"id": palete_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not palete:
        raise HTTPException(status_code=404, detail="Palete nao encontrado")
    await db.wms_paletes.update_one(
        {"id": palete_id, "tenant_id": user["tenant_id"]},
        {"$set": {"impresso_em": now_iso(), "impresso_por_id": user["id"], "impresso_por_nome": user.get("name", ""), "updated_at": now_iso()}},
    )
    return await db.wms_paletes.find_one({"id": palete_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@recebimento_router.get("/agendamentos/calendario")
async def calendario_agendamentos(
    request: Request,
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    tipo: Optional[str] = None,
    status: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if inicio or fim:
        data_query: Dict[str, Any] = {}
        if inicio:
            data_query["$gte"] = inicio
        if fim:
            data_query["$lte"] = fim
        query["data"] = data_query
    if tipo:
        query["tipo"] = tipo
    if status:
        query["status"] = status
    docs = await db.recebimento_agendamentos.find(query, {"_id": 0}).sort("data", 1).to_list(2000)
    por_data: Dict[str, List[dict]] = {}
    for doc in docs:
        por_data.setdefault(doc.get("data", ""), []).append(doc)
    return {"agendamentos": docs, "por_data": por_data, "total": len(docs)}


@recebimento_router.get("/agendamentos/{agendamento_id}")
async def detalhar_agendamento(agendamento_id: str, request: Request):
    user = await get_current_user(request)
    doc = await db.recebimento_agendamentos.find_one({"id": agendamento_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado")
    return doc


# ---- RN-REC-05: No DELETE ----
@recebimento_router.delete("/entradas/{entrada_id}")
async def delete_blocked(entrada_id: str):
    raise HTTPException(
        status_code=405,
        detail="Registros de recebimento são imutáveis. Exclusão não permitida (RN-REC-05)."
    )
