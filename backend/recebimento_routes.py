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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from contextvars import ContextVar
from collections import defaultdict
import logging

from pymongo.errors import OperationFailure

from stock_ledger import append_lot_ledger_event
from rbac import RECEIVING_WRITE_ROLES, require_roles

logger = logging.getLogger(__name__)

recebimento_router = APIRouter(prefix="/api/recebimento")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None
_receiving_session: ContextVar[Any] = ContextVar("receiving_mongo_session", default=None)
_SESSION_METHODS = {
    "aggregate", "bulk_write", "count_documents", "delete_many", "delete_one", "distinct",
    "find", "find_one", "find_one_and_delete", "find_one_and_replace", "find_one_and_update",
    "insert_many", "insert_one", "replace_one", "update_many", "update_one",
}


class _SessionCollectionProxy:
    def __init__(self, collection):
        self._collection = collection

    def __getattr__(self, name):
        attr = getattr(self._collection, name)
        if name not in _SESSION_METHODS or not callable(attr):
            return attr

        def call(*args, **kwargs):
            session = _receiving_session.get()
            if session is not None and "session" not in kwargs:
                kwargs["session"] = session
            return attr(*args, **kwargs)

        return call


class _SessionDatabaseProxy:
    def __init__(self, database):
        self._database = database

    def __getattr__(self, name):
        if name in {"client", "name", "codec_options", "read_preference", "write_concern"}:
            return getattr(self._database, name)
        return _SessionCollectionProxy(getattr(self._database, name))

    def __getitem__(self, name):
        return _SessionCollectionProxy(self._database[name])


def init_recebimento(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = _SessionDatabaseProxy(database)
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


async def _enforce_recebimento_write_rbac(request: Request):
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        require_roles(await get_current_user(request), RECEIVING_WRITE_ROLES)


recebimento_router.dependencies.append(Depends(_enforce_recebimento_write_rbac))


async def create_recebimento_indexes():
    await db.recebimentos.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.recebimentos.create_index([("tenant_id", 1), ("po_id", 1)])
    await db.recebimentos.create_index([("tenant_id", 1), ("recebimento_key", 1)], unique=True, sparse=True)
    await db.recebimentos.create_index([("tenant_id", 1), ("idempotency_key", 1)], unique=True, sparse=True)
    await db.recebimento_estornos.create_index([("tenant_id", 1), ("idempotency_key", 1)], unique=True)
    await db.recebimento_estornos.create_index([("tenant_id", 1), ("recebimento_id", 1), ("created_at", -1)])
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
RECEIVING_INTERNAL_LOT_FLAG = "receiving_internal_lot_v2"


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
    lote_interno: Optional[str] = None
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
    idempotency_key: Optional[str] = None
    items: List[RecebimentoItem]
    checklist_geral: List[RecebimentoChecklistItem] = Field(default_factory=list)
    agendamento_id: Optional[str] = None
    observacoes: str = ""


class RecebimentoEstornoItem(BaseModel):
    estoque_item_id: str
    quantidade: float = Field(gt=0)


class RecebimentoEstornoInput(BaseModel):
    tipo: str = "cancelamento"  # correcao | cancelamento | devolucao_fornecedor | devolucao_cliente
    motivo: str
    idempotency_key: str
    items: List[RecebimentoEstornoItem] = Field(default_factory=list)


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


async def _receiving_feature_enabled(tenant_id: str, flag: str) -> bool:
    if not hasattr(db, "tenant_settings"):
        return False
    settings = await db.tenant_settings.find_one({"tenant_id": tenant_id}, {"_id": 0})
    return bool(((settings or {}).get("features") or {}).get(flag))


def _recebimento_item_key(item: RecebimentoItem) -> str:
    parts = [
        item.po_item_id or "",
        item.mp_id or "",
        item.codigo or "",
        item.nome or "",
        str(float(item.quantidade or 0)),
        item.unidade or "",
        item.lote or "",
        item.validade or "",
        item.endereco_id or "",
        "cliente" if item.origem_cliente else "kuryos",
        item.pedido_id or "",
    ]
    return "|".join(str(part).strip().lower() for part in parts)


def _recebimento_key(data: RecebimentoCreate) -> str:
    explicit = (data.idempotency_key or "").strip()
    if explicit:
        return explicit
    items_key = "#".join(sorted(_recebimento_item_key(item) for item in data.items))
    parts = [
        data.po_id or "",
        data.po_numero or "",
        data.fornecedor_id or "",
        data.fornecedor_nome or "",
        data.numero_nf or "",
        data.data_nf or "",
        items_key,
    ]
    return "|".join(str(part).strip().lower() for part in parts)


async def _next_lote_interno(tenant_id: str, offset: int = 0) -> str:
    year = (now_iso() or "")[:4] or str(datetime.now(timezone.utc).year)
    count = await db.recebimentos.count_documents({"tenant_id": tenant_id})
    return f"AK-{year}-{count + offset + 1:06d}"


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
                "lote_interno": i.get("lote_interno"),
            }
            for i in recebimento.get("items", [])
        ],
        "recebimento_key": recebimento.get("recebimento_key"),
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


async def _resolver_endereco_recebimento(
    tenant_id: str,
    setor: str,
    endereco_id: Optional[str],
    endereco_codigo: str,
) -> tuple[str, str]:
    if endereco_id:
        endereco = await db.wms_enderecos.find_one(
            {"id": endereco_id, "tenant_id": tenant_id}, {"_id": 0}
        )
        if not endereco:
            raise HTTPException(status_code=404, detail=f"Endereco WMS nao encontrado: {endereco_id}")
        return endereco["id"], endereco.get("codigo", endereco_codigo)

    codigo = endereco_codigo.strip() or f"REC-{setor}-QUARENTENA"
    endereco = await db.wms_enderecos.find_one(
        {"tenant_id": tenant_id, "codigo": codigo}, {"_id": 0}
    )
    if not endereco:
        endereco = {
            "id": f"recebimento-{tenant_id}-{setor}".lower(),
            "tenant_id": tenant_id,
            "codigo": codigo,
            "setor": setor,
            "predio": "REC",
            "rua": setor[:12],
            "nivel": "0",
            "posicao": "0",
            "tipo": "quarentena_recebimento",
            "status": "livre",
            "descricao": f"Quarentena automatica de recebimento - {setor}",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.wms_enderecos.update_one(
            {"tenant_id": tenant_id, "codigo": codigo}, {"$setOnInsert": endereco}, upsert=True
        )
        endereco = await db.wms_enderecos.find_one(
            {"tenant_id": tenant_id, "codigo": codigo}, {"_id": 0}
        )
    return endereco["id"], endereco.get("codigo", codigo)


async def _registrar_saldo_wms_lote(item_doc: dict, endereco_id: Optional[str], endereco_codigo: str, qtd: float, user: dict, recebimento_id: str):
    if not endereco_id:
        return None
    endereco = await db.wms_enderecos.find_one({"id": endereco_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not endereco:
        raise HTTPException(status_code=404, detail=f"Endereco WMS nao encontrado: {endereco_id}")
    lote = item_doc.get("lote_interno") or item_doc.get("lote") or item_doc.get("numero_lote_fornecedor") or "SEM-LOTE"
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
            "lote_interno": item_doc.get("lote_interno"),
            "lote_fornecedor": item_doc.get("lote") or item_doc.get("numero_lote_fornecedor"),
            "validade": item_doc.get("validade"),
            "endereco_id": endereco_id,
            "endereco_codigo": endereco_codigo or endereco.get("codigo", ""),
            "setor": endereco.get("setor", item_doc.get("setor", "")),
            "quantidade": 0.0,
            "quantidade_atual": 0.0,
            "unidade": item_doc.get("unidade", "kg"),
            "posicao_cq": "quarentena",
            "cq_status": "quarentena",
            "cq_lote_id": item_doc.get("lote_id"),
            "cq_ra_id": item_doc.get("ra_id"),
            "status": "quarentena",
            "quantidade_reservada": 0.0,
            "recebimento_id": recebimento_id,
            "origem_cliente": bool(item_doc.get("origem_cliente")),
            "proprietario_tipo": item_doc.get("proprietario_tipo", "kuryos"),
            "proprietario_cliente_id": item_doc.get("proprietario_cliente_id"),
            "pedido_id_exclusivo": item_doc.get("pedido_id_exclusivo"),
            "consumo_restrito": bool(item_doc.get("consumo_restrito")),
            "created_at": now,
            "updated_at": now,
        }
        await db.estoque_saldos_lote.insert_one(saldo)
    await db.estoque_saldos_lote.update_one(
        {"id": saldo["id"], "tenant_id": user["tenant_id"]},
        {"$set": {
            "quantidade": novo,
            "quantidade_atual": novo,
            "status": "quarentena",
            "posicao_cq": "quarentena",
            "cq_status": "quarentena",
            "cq_lote_id": item_doc.get("lote_id"),
            "cq_ra_id": item_doc.get("ra_id"),
            "updated_at": now,
        }},
    )
    await db.wms_enderecos.update_one(
        {"id": endereco_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "ocupado", "updated_at": now}},
    )
    saldo_atualizado = await db.estoque_saldos_lote.find_one({"id": saldo["id"], "tenant_id": user["tenant_id"]}, {"_id": 0})
    if hasattr(db, "estoque_movimentos_lote"):
        await append_lot_ledger_event(
            db,
            new_id_fn=new_id,
            now_iso_fn=now_iso,
            tenant_id=user["tenant_id"],
            saldo=saldo_atualizado,
            natureza="movimento",
            evento="ENTRADA_RECEBIMENTO",
            quantidade=float(qtd),
            quantidade_delta=float(qtd),
            quantidade_antes=atual,
            quantidade_depois=novo,
            motivo=f"Recebimento {recebimento_id}",
            documento=item_doc.get("numero_nf", ""),
            referencia=recebimento_id,
            usuario=user,
            idempotency_key=f"recebimento:{recebimento_id}:{saldo['id']}",
            metadata={
                "ra_id": item_doc.get("ra_id"),
                "lote_id": item_doc.get("lote_id"),
                "origem_cliente": bool(item_doc.get("origem_cliente")),
                "proprietario_cliente_id": item_doc.get("proprietario_cliente_id"),
                "pedido_id_exclusivo": item_doc.get("pedido_id_exclusivo"),
            },
        )
    return saldo_atualizado


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
            "lote_interno": item_doc.get("lote_interno"),
            "lote_fornecedor": item_doc.get("lote", ""),
            "endereco_id": item_doc.get("endereco_id"),
            "endereco_codigo": item_doc.get("endereco_codigo", ""),
            "origem_cliente": bool(item_doc.get("origem_cliente")),
            "proprietario_tipo": item_doc.get("proprietario_tipo", "kuryos"),
            "proprietario_cliente_id": item_doc.get("proprietario_cliente_id"),
            "pedido_id_exclusivo": item_doc.get("pedido_id_exclusivo"),
            "consumo_restrito": bool(item_doc.get("consumo_restrito")),
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
    return await registrar_recebimento_unificado(data, user, origem="recebimento")


def _transaction_not_supported(exc: OperationFailure) -> bool:
    return exc.code in {20, 263, 303} or "Transaction numbers are only allowed" in str(exc)


async def _compensar_recebimento_falho(
    entrada_id: str,
    tenant_id: str,
    po_snapshot: Optional[dict],
    agendamento_snapshot: Optional[dict],
    error: Exception,
) -> None:
    """Best-effort saga rollback for Mongo standalone environments."""
    saldos = await db.estoque_saldos_lote.find(
        {"tenant_id": tenant_id, "recebimento_id": entrada_id}, {"_id": 0}
    ).to_list(10000)
    endereco_ids = {saldo.get("endereco_id") for saldo in saldos if saldo.get("endereco_id")}
    await db.estoque_movimentos_lote.delete_many({"tenant_id": tenant_id, "referencia": entrada_id})
    await db.wms_paletes.delete_many({"tenant_id": tenant_id, "recebimento_id": entrada_id})
    await db.cq_registros_analise.delete_many({"tenant_id": tenant_id, "recebimento_id": entrada_id})
    await db.estoque_movimentos.delete_many({"tenant_id": tenant_id, "referencia": entrada_id})
    await db.estoque_saldos_lote.delete_many({"tenant_id": tenant_id, "recebimento_id": entrada_id})
    await db.estoque_items.delete_many({"tenant_id": tenant_id, "recebimento_id": entrada_id})
    await db.recebimentos.delete_many({"tenant_id": tenant_id, "id": entrada_id})
    if po_snapshot:
        await db.compras_pos.replace_one(
            {"id": po_snapshot["id"], "tenant_id": tenant_id},
            po_snapshot,
            upsert=True,
        )
    if agendamento_snapshot:
        await db.recebimento_agendamentos.replace_one(
            {"id": agendamento_snapshot["id"], "tenant_id": tenant_id},
            agendamento_snapshot,
            upsert=True,
        )
    for endereco_id in endereco_ids:
        remaining = await db.estoque_saldos_lote.count_documents(
            {"tenant_id": tenant_id, "endereco_id": endereco_id, "quantidade": {"$gt": 0}}
        )
        if not remaining:
            await db.wms_enderecos.update_one(
                {"tenant_id": tenant_id, "id": endereco_id},
                {"$set": {"status": "livre", "updated_at": now_iso()}},
            )
    await db.audit_logs.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "action": "recebimento_compensado_por_falha",
        "entity_type": "recebimento",
        "entity_id": entrada_id,
        "error": str(error),
        "timestamp": now_iso(),
    })


async def registrar_recebimento_unificado(
    data: RecebimentoCreate,
    user: Dict[str, Any],
    origem: str = "recebimento",
) -> Dict[str, Any]:
    """Runs the unified receipt atomically, with saga compensation on standalone Mongo."""
    tid = user["tenant_id"]
    entrada_id = new_id()
    po_snapshot = await db.compras_pos.find_one(
        {"id": data.po_id, "tenant_id": tid}, {"_id": 0}
    ) if data.po_id else None
    agendamento_snapshot = await db.recebimento_agendamentos.find_one(
        {"id": data.agendamento_id, "tenant_id": tid}, {"_id": 0}
    ) if data.agendamento_id else None

    mongo_client = getattr(db, "client", None)
    if mongo_client and hasattr(mongo_client, "start_session"):
        try:
            async with await mongo_client.start_session() as session:
                async with session.start_transaction():
                    token = _receiving_session.set(session)
                    try:
                        return await _registrar_recebimento_core(data, user, origem, entrada_id)
                    finally:
                        _receiving_session.reset(token)
        except OperationFailure as exc:
            if not _transaction_not_supported(exc):
                raise
            logger.warning("Mongo sem suporte a transacao; recebimento %s usara saga compensatoria", entrada_id)
    else:
        logger.debug("Cliente Mongo sem sessoes; recebimento %s usara saga compensatoria", entrada_id)

    try:
        return await _registrar_recebimento_core(data, user, origem, entrada_id)
    except Exception as exc:
        await _compensar_recebimento_falho(entrada_id, tid, po_snapshot, agendamento_snapshot, exc)
        raise


async def _registrar_recebimento_core(
    data: RecebimentoCreate,
    user: Dict[str, Any],
    origem: str,
    entrada_id: str,
) -> Dict[str, Any]:
    """Nucleo unico usado por Logistica e pelo recebimento iniciado na PO."""
    tid = user["tenant_id"]

    if not data.items:
        raise HTTPException(status_code=400, detail="Informe ao menos um item")

    receiving_v2 = True
    recebimento_key = _recebimento_key(data)
    idempotency_key = (data.idempotency_key or recebimento_key).strip()
    if recebimento_key:
        existing = await db.recebimentos.find_one(
            {"tenant_id": tid, "recebimento_key": recebimento_key},
            {"_id": 0},
        )
        if existing:
            existing["idempotent_replay"] = True
            return existing

    now = now_iso()
    sla = await _get_sla(tid)
    po = await _get_po_if_any(data.po_id, tid)
    items_processados = []
    ownership_by_index: Dict[int, dict] = {}

    # Validate every client-owned material before the first stock mutation.
    for item_index, item in enumerate(data.items):
        if not item.origem_cliente:
            if item.pedido_id:
                raise HTTPException(status_code=422, detail=f"Item '{item.nome}': pedido_id exige origem_cliente=true")
            ownership_by_index[item_index] = {
                "proprietario_tipo": "kuryos",
                "proprietario_cliente_id": None,
                "pedido_id_exclusivo": None,
                "consumo_restrito": False,
            }
            continue
        if not item.pedido_id:
            raise HTTPException(status_code=422, detail=f"Item '{item.nome}': pedido_id obrigatorio para material do cliente")
        order = await db.orders.find_one(
            {"id": item.pedido_id, "tenant_id": tid, "status": {"$ne": "cancelado"}},
            {"_id": 0, "id": 1, "cliente_id": 1},
        )
        if not order:
            raise HTTPException(status_code=404, detail=f"Pedido do material do cliente nao encontrado: {item.pedido_id}")
        if not order.get("cliente_id"):
            raise HTTPException(status_code=409, detail=f"Pedido {item.pedido_id} nao possui cliente_id resolvido")
        ownership_by_index[item_index] = {
            "proprietario_tipo": "cliente",
            "proprietario_cliente_id": order["cliente_id"],
            "pedido_id_exclusivo": order["id"],
            "consumo_restrito": True,
        }

    for item_index, item in enumerate(data.items):
        ownership = ownership_by_index[item_index]
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
        lote_interno = (item.lote_interno or "").strip() if receiving_v2 else None
        if receiving_v2 and not lote_interno:
            lote_interno = await _next_lote_interno(tid, item_index)

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
                            "lote_interno": lote_interno,
                            "lote_fornecedor": item.lote,
                            "recebimento_id": entrada_id,
                            **ownership,
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
                "lote_interno": lote_interno,
                "lote_fornecedor": item.lote,
                "validade": item.validade,
                "observacoes": "",
                "posicao_cq": "quarentena",
                "cq_status": "quarentena",
                "cq_lote_id": lote_id,
                "cq_ra_id": ra_id,
                "prazo_analise_qualidade": data_limite_cq,
                "recebimento_id": entrada_id,
                **ownership,
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
                "lote_interno": lote_interno,
                "lote_fornecedor": item.lote,
                "tipo": "ENTRADA_RECEBIMENTO",
                "direcao": "entrada",
                "quantidade": item.quantidade,
                "unidade": item.unidade,
                "quantidade_antes": qty_antes,
                "quantidade_depois": qty_depois,
                "motivo": f"Recebimento NF {data.numero_nf}",
                "referencia": entrada_id,
                "documento": data.numero_nf,
                "origem_cliente": item.origem_cliente,
                **ownership,
                "usuario": user["name"],
                "usuario_id": user["id"],
                "created_at": now,
            }
            await db.estoque_movimentos.insert_one(mov)

        # 3) Create RA in CQ with SLA deadline
        lote_numero = lote_interno or item.lote or f"L{now[:10].replace('-', '')}"
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
            "lote_interno": lote_interno,
            "numero_lote_fornecedor": item.lote,
            "data_validade_fornecedor": item.validade,
            "data_limite_cq": data_limite_cq,
            "urgente": urgente,
            "checklist_recebimento": checklist,
            "checklist_status": checklist_status,
            "parametros": [],
            "recebimento_id": entrada_id,
            "origem_cliente": item.origem_cliente,
            **ownership,
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
            "lote_interno": lote_interno,
            "lote_fornecedor": item.lote,
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
            **ownership,
        }
        endereco_id, endereco_codigo = await _resolver_endereco_recebimento(
            tid, setor, item.endereco_id, item.endereco_codigo
        )
        item_processado["endereco_id"] = endereco_id
        item_processado["endereco_codigo"] = endereco_codigo
        saldo_wms = await _registrar_saldo_wms_lote(
            item_processado, endereco_id, endereco_codigo, item.quantidade, user, entrada_id
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
        "recebimento_key": recebimento_key,
        "idempotency_key": idempotency_key,
        "receiving_internal_lot_v2": bool(receiving_v2),
        "origem_registro": origem,
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


_ESTORNO_TIPOS = {"correcao", "cancelamento", "devolucao_fornecedor", "devolucao_cliente"}


async def _snapshot_estorno_state(entrada: dict, tenant_id: str) -> dict:
    item_ids = [item.get("estoque_item_id") for item in entrada.get("items") or [] if item.get("estoque_item_id")]
    ra_ids = [item.get("ra_id") for item in entrada.get("items") or [] if item.get("ra_id")]

    async def docs(collection, query):
        return await collection.find(query, {"_id": 0}).to_list(10000)

    return {
        "recebimento": dict(entrada),
        "estoque_items": await docs(db.estoque_items, {"tenant_id": tenant_id, "id": {"$in": item_ids}}) if item_ids else [],
        "saldos": await docs(db.estoque_saldos_lote, {"tenant_id": tenant_id, "recebimento_id": entrada["id"]}),
        "paletes": await docs(db.wms_paletes, {"tenant_id": tenant_id, "recebimento_id": entrada["id"]}),
        "ras": await docs(db.cq_registros_analise, {"tenant_id": tenant_id, "id": {"$in": ra_ids}}) if ra_ids else [],
        "po": await db.compras_pos.find_one(
            {"tenant_id": tenant_id, "id": entrada.get("po_id")}, {"_id": 0}
        ) if entrada.get("po_id") else None,
    }


async def _compensar_estorno_falho(snapshot: dict, tenant_id: str, estorno_id: str, error: Exception) -> None:
    """Restores pre-reversal state when Mongo transactions are unavailable."""
    await db.recebimento_estornos.delete_many({"tenant_id": tenant_id, "id": estorno_id})
    await db.estoque_movimentos.delete_many({"tenant_id": tenant_id, "referencia": estorno_id})
    await db.estoque_movimentos_lote.delete_many({"tenant_id": tenant_id, "referencia": estorno_id})

    recebimento = snapshot["recebimento"]
    await db.recebimentos.replace_one(
        {"tenant_id": tenant_id, "id": recebimento["id"]}, recebimento, upsert=True
    )
    for collection_name, documents in (
        ("estoque_items", snapshot["estoque_items"]),
        ("estoque_saldos_lote", snapshot["saldos"]),
        ("wms_paletes", snapshot["paletes"]),
        ("cq_registros_analise", snapshot["ras"]),
    ):
        collection = getattr(db, collection_name)
        for document in documents:
            await collection.replace_one(
                {"tenant_id": tenant_id, "id": document["id"]}, document, upsert=True
            )
    if snapshot.get("po"):
        await db.compras_pos.replace_one(
            {"tenant_id": tenant_id, "id": snapshot["po"]["id"]}, snapshot["po"], upsert=True
        )
    await db.audit_logs.insert_one({
        "id": new_id(), "tenant_id": tenant_id, "action": "estorno_recebimento_compensado_por_falha",
        "entity_type": "recebimento_estorno", "entity_id": estorno_id,
        "recebimento_id": recebimento["id"], "error": str(error), "timestamp": now_iso(),
    })


async def _estornar_recebimento_core(entrada: dict, data: RecebimentoEstornoInput, user: dict, estorno_id: str) -> dict:
    tid = user["tenant_id"]
    if data.tipo not in _ESTORNO_TIPOS:
        raise HTTPException(status_code=422, detail=f"Tipo de estorno invalido: {data.tipo}")
    if not data.motivo.strip():
        raise HTTPException(status_code=422, detail="Motivo obrigatorio para estorno/devolucao")
    existing = await db.recebimento_estornos.find_one(
        {"tenant_id": tid, "idempotency_key": data.idempotency_key}, {"_id": 0}
    )
    if existing:
        return {**existing, "idempotent_replay": True}

    requested = {item.estoque_item_id: float(item.quantidade) for item in data.items}
    receipt_items = [dict(item) for item in entrada.get("items") or []]
    selected = []
    for item in receipt_items:
        estoque_item_id = item.get("estoque_item_id")
        original = float(item.get("quantidade") or 0)
        already_reversed = float(item.get("quantidade_estornada") or 0)
        remaining_original = round(max(original - already_reversed, 0), 6)
        quantity = requested.get(estoque_item_id, remaining_original if not requested else 0)
        if quantity <= 0:
            continue
        if quantity > remaining_original + 0.000001:
            raise HTTPException(status_code=409, detail=f"Quantidade de estorno excede o recebido para {item.get('nome')}")
        if data.tipo == "devolucao_cliente" and not item.get("origem_cliente"):
            raise HTTPException(status_code=409, detail=f"Item {item.get('nome')} nao pertence ao cliente")
        if data.tipo == "devolucao_fornecedor" and item.get("origem_cliente"):
            raise HTTPException(status_code=409, detail=f"Material do cliente deve usar devolucao_cliente: {item.get('nome')}")
        saldo_id = (item.get("saldo_wms") or {}).get("id")
        saldo = await db.estoque_saldos_lote.find_one(
            {"tenant_id": tid, "id": saldo_id}, {"_id": 0}
        ) if saldo_id else await db.estoque_saldos_lote.find_one(
            {"tenant_id": tid, "recebimento_id": entrada["id"], "item_id": estoque_item_id}, {"_id": 0}
        )
        if not saldo:
            raise HTTPException(status_code=409, detail=f"Saldo por lote nao encontrado para {item.get('nome')}")
        available = float(saldo.get("quantidade") if saldo.get("quantidade") is not None else saldo.get("quantidade_atual") or 0)
        reserved = float(saldo.get("quantidade_reservada") or 0)
        if reserved > 0:
            raise HTTPException(status_code=409, detail=f"Lote de {item.get('nome')} possui reserva ativa")
        if quantity > available + 0.000001:
            raise HTTPException(status_code=409, detail=f"Saldo insuficiente para estornar {item.get('nome')}; disponivel={available}")
        selected.append((item, saldo, quantity, available, already_reversed))

    receipt_item_ids = {item.get("estoque_item_id") for item in receipt_items}
    if requested and set(requested) - receipt_item_ids:
        raise HTTPException(status_code=404, detail="Um ou mais itens informados nao pertencem ao recebimento")
    if not selected:
        raise HTTPException(status_code=409, detail="Recebimento sem quantidade remanescente para estorno")

    now = now_iso()
    estorno_items = []
    for item, saldo, quantity, available, already_reversed in selected:
        new_balance = round(available - quantity, 6)
        await db.estoque_saldos_lote.update_one(
            {"id": saldo["id"], "tenant_id": tid},
            {"$set": {"quantidade": new_balance, "quantidade_atual": new_balance,
                      "status": "zerado" if new_balance <= 0 else saldo.get("status", "quarentena"), "updated_at": now}},
        )
        stock = await db.estoque_items.find_one({"id": item["estoque_item_id"], "tenant_id": tid}, {"_id": 0})
        stock_before = float((stock or {}).get("quantidade_atual") or 0)
        stock_after = round(max(stock_before - quantity, 0), 6)
        await db.estoque_items.update_one(
            {"id": item["estoque_item_id"], "tenant_id": tid},
            {"$set": {"quantidade_atual": stock_after, "updated_at": now}},
        )
        await db.estoque_movimentos.insert_one({
            "id": new_id(), "tenant_id": tid, "item_id": item["estoque_item_id"],
            "setor": item.get("setor"), "tipo_item": "mp", "nome_item": item.get("nome"),
            "codigo_item": item.get("codigo"), "lote": item.get("lote"), "lote_interno": item.get("lote_interno"),
            "tipo": "ESTORNO_RECEBIMENTO", "direcao": "saida", "quantidade": quantity,
            "unidade": item.get("unidade"), "quantidade_antes": stock_before, "quantidade_depois": stock_after,
            "motivo": data.motivo.strip(), "referencia": estorno_id, "recebimento_id_origem": entrada["id"],
            "documento": entrada.get("numero_nf"), "destino": data.tipo,
            "usuario": user.get("name", ""), "usuario_id": user.get("id"), "created_at": now,
        })
        await append_lot_ledger_event(
            db, new_id_fn=new_id, now_iso_fn=now_iso, tenant_id=tid,
            saldo={**saldo, "quantidade": new_balance, "quantidade_atual": new_balance},
            natureza="movimento", evento="ESTORNO_RECEBIMENTO", quantidade=quantity,
            quantidade_delta=-quantity, quantidade_antes=available, quantidade_depois=new_balance,
            motivo=data.motivo.strip(), documento=entrada.get("numero_nf", ""), referencia=estorno_id,
            usuario=user, idempotency_key=f"estorno-recebimento:{estorno_id}:{saldo['id']}",
            metadata={"recebimento_id_origem": entrada["id"], "tipo_estorno": data.tipo},
        )
        new_reversed = round(already_reversed + quantity, 6)
        item["quantidade_estornada"] = new_reversed
        item["quantidade_remanescente"] = round(max(float(item.get("quantidade") or 0) - new_reversed, 0), 6)
        item["ultimo_estorno_id"] = estorno_id
        pallet_status = "devolvido" if data.tipo.startswith("devolucao") else "estornado"
        await db.wms_paletes.update_many(
            {"tenant_id": tid, "recebimento_id": entrada["id"], "estoque_item_id": item["estoque_item_id"]},
            {"$set": {"status": pallet_status if item["quantidade_remanescente"] <= 0 else "parcialmente_estornado", "updated_at": now}},
        )
        await db.cq_registros_analise.update_one(
            {"tenant_id": tid, "id": item.get("ra_id")},
            {"$set": {"recebimento_estornado": True, "recebimento_estorno_id": estorno_id, "updated_at": now}},
        )
        estorno_items.append({"estoque_item_id": item["estoque_item_id"], "saldo_lote_id": saldo["id"],
                              "quantidade": quantity, "unidade": item.get("unidade"), "nome": item.get("nome")})

    fully_reversed = all(float(item.get("quantidade_remanescente", item.get("quantidade") or 0)) <= 0 for item in receipt_items)
    receipt_status = (
        "devolvido_cliente" if data.tipo == "devolucao_cliente" and fully_reversed else
        "devolvido_fornecedor" if data.tipo == "devolucao_fornecedor" and fully_reversed else
        "estornado" if fully_reversed else "parcialmente_estornado"
    )
    estorno = {"id": estorno_id, "tenant_id": tid, "recebimento_id": entrada["id"],
               "idempotency_key": data.idempotency_key, "tipo": data.tipo, "motivo": data.motivo.strip(),
               "status": "concluido", "items": estorno_items, "created_by": user.get("id"),
               "created_by_name": user.get("name", ""), "created_at": now}
    await db.recebimento_estornos.insert_one(estorno)
    await db.recebimentos.update_one(
        {"id": entrada["id"], "tenant_id": tid},
        {"$set": {"items": receipt_items, "status": receipt_status, "updated_at": now}, "$push": {"estornos": estorno}},
    )

    if entrada.get("po_id"):
        po = await db.compras_pos.find_one({"id": entrada["po_id"], "tenant_id": tid}, {"_id": 0})
        if po:
            po_items = [dict(item) for item in po.get("itens") or []]
            reversed_by_po_item = defaultdict(float)
            for receipt_item, _saldo, quantity, _available, _already in selected:
                if receipt_item.get("po_item_id"):
                    reversed_by_po_item[receipt_item["po_item_id"]] += quantity
            for po_item in po_items:
                if po_item.get("id") in reversed_by_po_item:
                    po_item["quantidade_recebida"] = round(max(float(po_item.get("quantidade_recebida") or 0) - reversed_by_po_item[po_item["id"]], 0), 6)
            any_received = any(float(item.get("quantidade_recebida") or 0) > 0 for item in po_items)
            await db.compras_pos.update_one(
                {"id": po["id"], "tenant_id": tid},
                {"$set": {"itens": po_items, "status": "parcialmente_recebida" if any_received else "confirmada", "updated_at": now},
                 "$push": {"log_auditoria": {"acao": "recebimento_estornado", "recebimento_id": entrada["id"],
                                               "estorno_id": estorno_id, "motivo": data.motivo.strip(),
                                               "por_id": user.get("id"), "por_nome": user.get("name", ""), "em": now}}},
            )
    return estorno


@recebimento_router.post("/entradas/{entrada_id}/estornar")
async def estornar_entrada(entrada_id: str, data: RecebimentoEstornoInput, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    entrada = await db.recebimentos.find_one({"id": entrada_id, "tenant_id": tid}, {"_id": 0})
    if not entrada:
        raise HTTPException(status_code=404, detail="Recebimento nao encontrado")
    if not data.idempotency_key.strip():
        raise HTTPException(status_code=422, detail="idempotency_key obrigatoria")
    estorno_id = new_id()
    snapshot = None
    mongo_client = getattr(db, "client", None)
    if mongo_client and hasattr(mongo_client, "start_session"):
        try:
            async with await mongo_client.start_session() as session:
                async with session.start_transaction():
                    token = _receiving_session.set(session)
                    try:
                        return await _estornar_recebimento_core(entrada, data, user, estorno_id)
                    finally:
                        _receiving_session.reset(token)
        except OperationFailure as exc:
            if not _transaction_not_supported(exc):
                raise
            logger.warning("Mongo sem transacao; estorno %s executado com saga compensatoria", estorno_id)
    snapshot = await _snapshot_estorno_state(entrada, tid)
    try:
        return await _estornar_recebimento_core(entrada, data, user, estorno_id)
    except Exception as exc:
        await _compensar_estorno_falho(snapshot, tid, estorno_id, exc)
        raise


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
