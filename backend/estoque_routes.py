"""
Estoque Routes - Módulo de Controle de Estoque (4 setores + Kardex imutável)
Setores: MANIPULACAO (MP FORMULACAO), ROTULAGEM (MP ROTULO), LOGISTICA (MP EMBALAGEM), FABRICA (LotePA)
"""

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import logging

from cq_routes import cq_verificar_lote_aprovado, cq_verificar_liberacao_palete

logger = logging.getLogger(__name__)

estoque_router = APIRouter(prefix="/api/estoque")

# ============ MODULE STATE ============
db = None
_get_current_user = None
_new_id = None
_now_iso = None


def init_estoque(database, get_user_fn, new_id_fn, now_iso_fn):
    global db, _get_current_user, _new_id, _now_iso
    db = database
    _get_current_user = get_user_fn
    _new_id = new_id_fn
    _now_iso = now_iso_fn
    logger.info("Estoque module initialized")


async def create_estoque_indexes():
    await db.wms_enderecos.create_index([("tenant_id", 1), ("codigo", 1)], unique=True)
    await db.wms_enderecos.create_index([("tenant_id", 1), ("setor", 1), ("status", 1)])
    await db.estoque_saldos_lote.create_index([("tenant_id", 1), ("item_id", 1), ("lote", 1), ("endereco_id", 1)])
    await db.estoque_saldos_lote.create_index([("tenant_id", 1), ("endereco_id", 1), ("quantidade", 1)])
    await db.estoque_movimentos_lote.create_index([("tenant_id", 1), ("created_at", -1)])


# ============ CONSTANTS ============

SETORES = ["MANIPULACAO", "ROTULAGEM", "LOGISTICA", "FABRICA", "DEVOLUCAO"]

SETOR_LABELS = {
    "MANIPULACAO": "Matérias-Primas (Manipulação)",
    "ROTULAGEM": "Rótulos (Rotulagem)",
    "LOGISTICA": "Insumos / Embalagens (Logística)",
    "FABRICA": "Produto Acabado (Fábrica)",
    "DEVOLUCAO": "Devoluções / Quarentena Especial",
}

# Tipos de MP vinculados a cada setor (para validação semântica)
SETOR_TIPO_MP = {
    "MANIPULACAO": "FORMULACAO",
    "ROTULAGEM": "ROTULO",
    "LOGISTICA": "EMBALAGEM",
    # FABRICA e DEVOLUCAO aceitam ambos os tipos
}

# Regex pattern for structured address GAL-B-04-1
import re
_LOC_PATTERN = re.compile(r"^[A-Z]{2,5}-[A-Z]-\d{2}-\d+$", re.IGNORECASE)

TIPOS_MOVIMENTO = [
    "ENTRADA_RECEBIMENTO",    # ↑  Entrada por aprovação de lote (CQ)
    "SAIDA_CONSUMO_OP",       # ↓  Saída por consumo em Ordem de Produção
    "SAIDA_EXPEDICAO",        # ↓  Saída por expedição de carga
    "AJUSTE_ENTRADA",         # ↑  Ajuste manual (recontagem, devolução interna)
    "AJUSTE_SAIDA",           # ↓  Ajuste manual (descarte, quebra, amostra)
    "AMOSTRA",                # ↓  Coleta de amostra para análise CQ
    "TRANSFERENCIA_ENTRADA",  # ↑  Transferência entre setores (entrada)
    "TRANSFERENCIA_SAIDA",    # ↓  Transferência entre setores (saída)
]

MOVIMENTOS_ENTRADA = {"ENTRADA_RECEBIMENTO", "AJUSTE_ENTRADA", "TRANSFERENCIA_ENTRADA"}
MOVIMENTOS_SAIDA = {"SAIDA_CONSUMO_OP", "SAIDA_EXPEDICAO", "AJUSTE_SAIDA", "AMOSTRA", "TRANSFERENCIA_SAIDA"}
MOVIMENTOS_COM_MOTIVO_OBRIGATORIO = {"AJUSTE_ENTRADA", "AJUSTE_SAIDA"}

TIPO_ITEM_VALORES = ["mp", "produto_acabado"]


# ============ PYDANTIC MODELS ============

POSICOES_CQ = ["livre", "quarentena", "aprovado", "reprovado"]

class EstoqueItemCreate(BaseModel):
    tipo_item: str  # "mp" | "produto_acabado"
    setor: str      # MANIPULACAO | ROTULAGEM | LOGISTICA | FABRICA | DEVOLUCAO
    nome: str
    codigo: str = ""
    mp_id: Optional[str] = None
    produto_id: Optional[str] = None
    unidade: str = "un"
    estoque_minimo: float = 0
    localizacao: str = ""              # Free text fallback
    localizacao_estruturada: str = ""  # Format: GAL-B-04-1 (galeria-corredor-prateleira-posição)
    lote: str = ""
    validade: Optional[str] = None
    observacoes: str = ""
    posicao_cq: str = "livre"


class EstoqueItemUpdate(BaseModel):
    nome: Optional[str] = None
    codigo: Optional[str] = None
    unidade: Optional[str] = None
    estoque_minimo: Optional[float] = None
    localizacao: Optional[str] = None
    localizacao_estruturada: Optional[str] = None
    lote: Optional[str] = None
    validade: Optional[str] = None
    observacoes: Optional[str] = None
    posicao_cq: Optional[str] = None


class MovimentoCreate(BaseModel):
    item_id: str
    tipo: str                           # ver TIPOS_MOVIMENTO
    quantidade: float
    motivo: str = ""
    referencia: str = ""                # ID da OP, lote, etc
    documento: str = ""                 # NF, requisição, etc


class TransferenciaCreate(BaseModel):
    item_origem_id: str
    setor_destino: str
    quantidade: float
    motivo: str = ""
    # Se item destino não existir, será criado automaticamente espelhando origem


class WMSEnderecoCreate(BaseModel):
    predio: str = "P01"
    rua: str
    nivel: str
    posicao: str
    setor: str = "LOGISTICA"
    tipo: str = "porta_palete"
    status: str = "livre"
    capacidade_paletes: int = 1
    capacidade_unidades: float = 0
    observacoes: str = ""


class WMSEnderecoUpdate(BaseModel):
    predio: Optional[str] = None
    rua: Optional[str] = None
    nivel: Optional[str] = None
    posicao: Optional[str] = None
    setor: Optional[str] = None
    tipo: Optional[str] = None
    status: Optional[str] = None
    capacidade_paletes: Optional[int] = None
    capacidade_unidades: Optional[float] = None
    observacoes: Optional[str] = None


class WMSGerarEnderecos(BaseModel):
    predios: int = Field(1, ge=1, le=20)
    ruas_por_predio: int = Field(1, ge=1, le=50)
    niveis_por_rua: int = Field(1, ge=1, le=20)
    posicoes_por_nivel: int = Field(1, ge=1, le=100)
    setor: str = "LOGISTICA"
    tipo: str = "porta_palete"
    capacidade_paletes: int = Field(1, ge=0)
    capacidade_unidades: float = Field(0, ge=0)


class AjusteSaldoLoteCreate(BaseModel):
    item_id: str
    lote: str
    endereco_id: str
    quantidade: float
    modo: str = "absoluto"  # absoluto | entrada | saida
    motivo: str
    documento: str = ""
    validade: Optional[str] = None


class TransferenciaLoteCreate(BaseModel):
    item_id: str
    lote: str
    endereco_origem_id: str
    endereco_destino_id: str
    quantidade: float
    motivo: str = ""
    documento: str = ""


# ============ HELPERS ============

def _serialize(doc: dict) -> dict:
    if doc:
        doc.pop("_id", None)
    return doc


async def _log_movimento(
    item: dict, tipo: str, quantidade: float,
    motivo: str, referencia: str, documento: str,
    user: dict, quantidade_antes: float, quantidade_depois: float
):
    """Registra movimento imutável no Kardex"""
    mov = {
        "id": _new_id(),
        "tenant_id": item["tenant_id"],
        "item_id": item["id"],
        "setor": item["setor"],
        "tipo_item": item["tipo_item"],
        "nome_item": item["nome"],
        "codigo_item": item.get("codigo", ""),
        "lote": item.get("lote", ""),
        "tipo": tipo,
        "direcao": "entrada" if tipo in MOVIMENTOS_ENTRADA else "saida",
        "quantidade": quantidade,
        "unidade": item.get("unidade", "un"),
        "quantidade_antes": quantidade_antes,
        "quantidade_depois": quantidade_depois,
        "motivo": motivo,
        "referencia": referencia,
        "documento": documento,
        "usuario": user["name"],
        "usuario_id": user["id"],
        "created_at": _now_iso(),
    }
    await db.estoque_movimentos.insert_one(mov)
    return _serialize(mov)


async def _get_item_or_404(item_id: str, tenant_id: str) -> dict:
    item = await db.estoque_items.find_one(
        {"id": item_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item de estoque não encontrado")
    return item


def _item_cq_position(item: dict) -> str:
    return item.get("posicao_cq") or item.get("cq_status") or "livre"


def _wms_codigo(predio: str, rua: str, nivel: str, posicao: str) -> str:
    return "-".join(
        [
            str(predio or "P01").strip().upper(),
            str(rua or "").strip().upper(),
            str(nivel or "").strip().upper(),
            str(posicao or "").strip().upper(),
        ]
    )


def _numeric_code(prefix: str, number: int, width: int = 2) -> str:
    return f"{prefix}{number:0{width}d}"


def _saldo_quantidade(saldo: Optional[dict]) -> float:
    if not saldo:
        return 0.0
    if saldo.get("quantidade") is not None:
        return float(saldo.get("quantidade") or 0)
    return float(saldo.get("quantidade_atual") or 0)


async def _get_wms_endereco_or_404(endereco_id: str, tenant_id: str) -> dict:
    endereco = await db.wms_enderecos.find_one(
        {"id": endereco_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not endereco:
        raise HTTPException(status_code=404, detail="Endereco WMS nao encontrado")
    if endereco.get("status") == "inativo":
        raise HTTPException(status_code=422, detail="Endereco WMS inativo")
    return endereco


async def _get_saldo_lote(item_id: str, lote: str, endereco_id: str, tenant_id: str) -> Optional[dict]:
    return await db.estoque_saldos_lote.find_one(
        {
            "tenant_id": tenant_id,
            "item_id": item_id,
            "lote": lote,
            "endereco_id": endereco_id,
            "status": {"$ne": "zerado"},
        },
        {"_id": 0},
    )


async def _log_movimento_lote(
    saldo: dict,
    tipo: str,
    quantidade: float,
    motivo: str,
    documento: str,
    user: dict,
    quantidade_antes: float,
    quantidade_depois: float,
    referencia: str = "",
):
    movimento = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "saldo_lote_id": saldo.get("id"),
        "item_id": saldo.get("item_id"),
        "item_nome": saldo.get("item_nome", ""),
        "codigo_item": saldo.get("codigo_item", ""),
        "lote": saldo.get("lote", ""),
        "endereco_id": saldo.get("endereco_id"),
        "endereco_codigo": saldo.get("endereco_codigo", ""),
        "setor": saldo.get("setor", ""),
        "tipo": tipo,
        "direcao": "entrada" if tipo.endswith("_ENTRADA") or tipo == "AJUSTE_ENTRADA" or float(quantidade_depois) >= float(quantidade_antes) else "saida",
        "quantidade": float(quantidade),
        "unidade": saldo.get("unidade", "un"),
        "quantidade_antes": float(quantidade_antes),
        "quantidade_depois": float(quantidade_depois),
        "motivo": motivo,
        "documento": documento,
        "referencia": referencia,
        "usuario": user["name"],
        "usuario_id": user["id"],
        "created_at": _now_iso(),
    }
    await db.estoque_movimentos_lote.insert_one(movimento)
    return _serialize(movimento)


async def _assert_saida_liberada_por_cq(item: dict, tipo_movimento: str):
    if tipo_movimento not in MOVIMENTOS_SAIDA:
        return

    posicao_cq = _item_cq_position(item)
    if posicao_cq in {"quarentena", "reprovado"}:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "hard_stop_estoque_sem_liberacao_cq",
                "message": f"Item '{item.get('nome', item.get('id'))}' esta em {posicao_cq}. Saida bloqueada ate liberacao de CQ.",
            },
        )

    lote_id = item.get("cq_lote_id")
    if lote_id:
        await cq_verificar_lote_aprovado(db, item["tenant_id"], lote_id)
        if tipo_movimento == "SAIDA_EXPEDICAO":
            await cq_verificar_liberacao_palete(db, item["tenant_id"], lote_id)

# ============ ITEMS CRUD ============

@estoque_router.post("/items")
async def create_item(data: EstoqueItemCreate, request: Request):
    """Cria novo item de estoque. Único por (mp_id|produto_id) + setor."""
    user = await _get_current_user(request)

    if data.setor not in SETORES:
        raise HTTPException(status_code=400, detail=f"Setor inválido. Valores: {SETORES}")
    if data.tipo_item not in TIPO_ITEM_VALORES:
        raise HTTPException(status_code=400, detail=f"tipo_item inválido: {data.tipo_item}")

    # Validação semântica: tipo_item por setor
    if data.setor == "FABRICA" and data.tipo_item != "produto_acabado":
        raise HTTPException(status_code=400, detail="Setor FABRICA só aceita produto_acabado")
    if data.setor not in ("FABRICA", "DEVOLUCAO") and data.tipo_item != "mp":
        raise HTTPException(status_code=400, detail=f"Setor {data.setor} só aceita MPs (tipo_item=mp)")

    # Validate structured location format if provided
    if data.localizacao_estruturada and not _LOC_PATTERN.match(data.localizacao_estruturada):
        raise HTTPException(
            status_code=400,
            detail="Formato de localização inválido. Use: GAL-B-04-1 (sigla-corredor-prateleira-posição)"
        )

    # Unicidade: um item por (mp_id|produto_id) + setor
    dup_query = {"tenant_id": user["tenant_id"], "setor": data.setor}
    if data.mp_id:
        dup_query["mp_id"] = data.mp_id
    elif data.produto_id:
        dup_query["produto_id"] = data.produto_id
    else:
        # Sem ref — permitir mas alertar por nome
        dup_query["nome"] = data.nome
        dup_query["mp_id"] = None
        dup_query["produto_id"] = None

    existing = await db.estoque_items.find_one(dup_query)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Já existe um item deste tipo no setor {SETOR_LABELS[data.setor]}. Use movimentação de entrada."
        )

    now = _now_iso()
    item_id = _new_id()
    item = {
        "id": item_id,
        "tenant_id": user["tenant_id"],
        "tipo_item": data.tipo_item,
        "setor": data.setor,
        "nome": data.nome,
        "codigo": data.codigo,
        "mp_id": data.mp_id,
        "produto_id": data.produto_id,
        "unidade": data.unidade,
        "quantidade_atual": 0,
        "estoque_minimo": data.estoque_minimo,
        "localizacao": data.localizacao,
        "lote": data.lote,
        "validade": data.validade,
        "observacoes": data.observacoes,
        "posicao_cq": data.posicao_cq if data.posicao_cq in POSICOES_CQ else "livre",
        "localizacao_estruturada": data.localizacao_estruturada,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.estoque_items.insert_one(item)
    logger.info(f"Created estoque_item {item_id} setor={data.setor} nome={data.nome}")
    return _serialize(item)


@estoque_router.get("/items")
async def list_items(
    request: Request,
    setor: Optional[str] = None,
    tipo_item: Optional[str] = None,
    search: Optional[str] = None,
    only_low_stock: bool = False,
    posicao_cq: Optional[str] = None,
):
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if setor:
        query["setor"] = setor
    if tipo_item:
        query["tipo_item"] = tipo_item
    if search:
        query["$or"] = [
            {"nome": {"$regex": search, "$options": "i"}},
            {"codigo": {"$regex": search, "$options": "i"}},
            {"lote": {"$regex": search, "$options": "i"}},
        ]

    if posicao_cq:
        query["posicao_cq"] = posicao_cq
    items = await db.estoque_items.find(query, {"_id": 0}).sort("nome", 1).to_list(5000)
    if only_low_stock:
        items = [i for i in items if i.get("quantidade_atual", 0) <= i.get("estoque_minimo", 0) and i.get("estoque_minimo", 0) > 0]
    return items


@estoque_router.get("/items/{item_id}")
async def get_item(item_id: str, request: Request):
    user = await _get_current_user(request)
    return await _get_item_or_404(item_id, user["tenant_id"])


@estoque_router.put("/items/{item_id}")
async def update_item(item_id: str, data: EstoqueItemUpdate, request: Request):
    user = await _get_current_user(request)
    item = await _get_item_or_404(item_id, user["tenant_id"])

    update_fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    update_fields["updated_at"] = _now_iso()

    await db.estoque_items.update_one({"id": item_id}, {"$set": update_fields})
    updated = await db.estoque_items.find_one({"id": item_id}, {"_id": 0})
    return updated


@estoque_router.delete("/items/{item_id}")
async def delete_item(item_id: str, request: Request):
    """Deleta item apenas se quantidade_atual = 0 (integridade do kardex)"""
    user = await _get_current_user(request)
    item = await _get_item_or_404(item_id, user["tenant_id"])

    if item.get("quantidade_atual", 0) > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir: saldo = {item['quantidade_atual']} {item.get('unidade', '')}. Zere o saldo antes."
        )

    await db.estoque_items.delete_one({"id": item_id, "tenant_id": user["tenant_id"]})
    # Movimentos são preservados (kardex imutável)
    logger.info(f"Deleted estoque_item {item_id}")
    return {"deleted": item_id}


@estoque_router.patch("/items/{item_id}/posicao")
async def update_posicao_cq(item_id: str, request: Request):
    """Atualiza posição CQ do item: quarentena → aprovado | reprovado."""
    user = await _get_current_user(request)
    body = await request.json()
    nova_posicao = body.get("posicao_cq")
    if nova_posicao not in POSICOES_CQ:
        raise HTTPException(status_code=400, detail=f"Posição inválida. Permitidas: {POSICOES_CQ}")
    item = await _get_item_or_404(item_id, user["tenant_id"])
    await db.estoque_items.update_one(
        {"id": item_id},
        {"$set": {"posicao_cq": nova_posicao, "updated_at": _now_iso()}}
    )
    updated = await db.estoque_items.find_one({"id": item_id}, {"_id": 0})
    return updated



# ============ MOVIMENTOS (KARDEX - APPEND ONLY) ============

@estoque_router.post("/movimentos")
async def create_movimento(data: MovimentoCreate, request: Request):
    """Cria movimento no kardex. Saldo nunca pode ficar negativo."""
    user = await _get_current_user(request)

    if data.tipo not in TIPOS_MOVIMENTO:
        raise HTTPException(status_code=400, detail=f"Tipo de movimento inválido. Valores: {TIPOS_MOVIMENTO}")

    if data.quantidade <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser > 0")

    # Motivo obrigatório para ajustes
    if data.tipo in MOVIMENTOS_COM_MOTIVO_OBRIGATORIO and not data.motivo.strip():
        raise HTTPException(
            status_code=400,
            detail="Motivo é obrigatório para ajustes manuais (rastreabilidade)"
        )

    # Transferências só via endpoint próprio
    if data.tipo in ("TRANSFERENCIA_ENTRADA", "TRANSFERENCIA_SAIDA"):
        raise HTTPException(
            status_code=400,
            detail="Transferências devem ser registradas via POST /api/estoque/transferencias"
        )

    item = await _get_item_or_404(data.item_id, user["tenant_id"])

    # CQ hard stops — check lote status before any movement
    await _assert_saida_liberada_por_cq(item, data.tipo)

    quantidade_antes = item.get("quantidade_atual", 0)
    delta = data.quantidade if data.tipo in MOVIMENTOS_ENTRADA else -data.quantidade
    quantidade_depois = quantidade_antes + delta

    # Saldo nunca negativo
    if quantidade_depois < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente: atual={quantidade_antes} {item.get('unidade')}, tentativa de saída={data.quantidade}"
        )

    # Atualizar item
    await db.estoque_items.update_one(
        {"id": data.item_id},
        {"$set": {"quantidade_atual": quantidade_depois, "updated_at": _now_iso()}}
    )

    # Registrar movimento (imutável)
    mov = await _log_movimento(
        item=item,
        tipo=data.tipo,
        quantidade=data.quantidade,
        motivo=data.motivo,
        referencia=data.referencia,
        documento=data.documento,
        user=user,
        quantidade_antes=quantidade_antes,
        quantidade_depois=quantidade_depois,
    )

    updated_item = await db.estoque_items.find_one({"id": data.item_id}, {"_id": 0})
    return {
        "movimento": mov,
        "item": updated_item,
    }


@estoque_router.post("/transferencias")
async def create_transferencia(data: TransferenciaCreate, request: Request):
    """Transfere quantidade entre setores (2 movimentos: SAIDA + ENTRADA).
    Se não existir item destino no setor destino, cria um espelho do origem."""
    user = await _get_current_user(request)

    if data.setor_destino not in SETORES:
        raise HTTPException(status_code=400, detail=f"Setor destino inválido")

    if data.quantidade <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser > 0")

    origem = await _get_item_or_404(data.item_origem_id, user["tenant_id"])
    await _assert_saida_liberada_por_cq(origem, "TRANSFERENCIA_SAIDA")
    if origem["setor"] == data.setor_destino:
        raise HTTPException(status_code=400, detail="Setor destino é igual ao origem")

    # Validação semântica: setor de destino precisa aceitar este tipo_item
    if data.setor_destino == "FABRICA" and origem["tipo_item"] != "produto_acabado":
        raise HTTPException(status_code=400, detail="Setor FABRICA só aceita produto_acabado")
    if data.setor_destino != "FABRICA" and origem["tipo_item"] != "mp":
        raise HTTPException(status_code=400, detail=f"Setor {data.setor_destino} só aceita MPs")

    qty_origem_antes = origem.get("quantidade_atual", 0)
    if data.quantidade > qty_origem_antes:
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente no origem: {qty_origem_antes} {origem.get('unidade')}"
        )

    # Buscar item destino (mesmo mp_id ou produto_id no setor destino)
    dest_query = {"tenant_id": user["tenant_id"], "setor": data.setor_destino}
    if origem.get("mp_id"):
        dest_query["mp_id"] = origem["mp_id"]
    elif origem.get("produto_id"):
        dest_query["produto_id"] = origem["produto_id"]
    else:
        dest_query["nome"] = origem["nome"]
    if origem.get("lote"):
        dest_query["lote"] = origem["lote"]

    destino = await db.estoque_items.find_one(dest_query, {"_id": 0})
    now = _now_iso()

    # Criar item destino se não existir
    if not destino:
        dest_id = _new_id()
        destino = {
            "id": dest_id,
            "tenant_id": user["tenant_id"],
            "tipo_item": origem["tipo_item"],
            "setor": data.setor_destino,
            "nome": origem["nome"],
            "codigo": origem.get("codigo", ""),
            "mp_id": origem.get("mp_id"),
            "produto_id": origem.get("produto_id"),
            "unidade": origem.get("unidade", "un"),
            "quantidade_atual": 0,
            "estoque_minimo": 0,
            "localizacao": "",
            "lote": origem.get("lote", ""),
            "validade": origem.get("validade"),
            "posicao_cq": origem.get("posicao_cq", "livre"),
            "cq_status": origem.get("cq_status"),
            "cq_lote_id": origem.get("cq_lote_id"),
            "cq_ra_id": origem.get("cq_ra_id"),
            "prazo_analise_qualidade": origem.get("prazo_analise_qualidade"),
            "observacoes": f"Criado automaticamente por transferência de {SETOR_LABELS.get(origem['setor'], origem['setor'])}",
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        await db.estoque_items.insert_one(destino)
        destino.pop("_id", None)

    # Atualizar quantidades
    qty_origem_depois = qty_origem_antes - data.quantidade
    qty_dest_antes = destino.get("quantidade_atual", 0)
    qty_dest_depois = qty_dest_antes + data.quantidade

    await db.estoque_items.update_one(
        {"id": origem["id"]},
        {"$set": {"quantidade_atual": qty_origem_depois, "updated_at": now}}
    )
    await db.estoque_items.update_one(
        {"id": destino["id"]},
        {"$set": {"quantidade_atual": qty_dest_depois, "updated_at": now}}
    )

    # Registrar 2 movimentos (pares)
    ref = f"TRANSF-{_new_id()[:8]}"
    mov_saida = await _log_movimento(
        item=origem, tipo="TRANSFERENCIA_SAIDA",
        quantidade=data.quantidade, motivo=data.motivo or f"Transferência para {SETOR_LABELS.get(data.setor_destino)}",
        referencia=ref, documento=destino["id"], user=user,
        quantidade_antes=qty_origem_antes, quantidade_depois=qty_origem_depois
    )
    mov_entrada = await _log_movimento(
        item=destino, tipo="TRANSFERENCIA_ENTRADA",
        quantidade=data.quantidade, motivo=data.motivo or f"Transferência de {SETOR_LABELS.get(origem['setor'])}",
        referencia=ref, documento=origem["id"], user=user,
        quantidade_antes=qty_dest_antes, quantidade_depois=qty_dest_depois
    )

    return {
        "referencia": ref,
        "mov_saida": mov_saida,
        "mov_entrada": mov_entrada,
        "item_origem": await db.estoque_items.find_one({"id": origem["id"]}, {"_id": 0}),
        "item_destino": await db.estoque_items.find_one({"id": destino["id"]}, {"_id": 0}),
    }


# ============ WMS ENDERECOS / LOTES ============

@estoque_router.get("/wms/enderecos")
async def listar_wms_enderecos(
    request: Request,
    setor: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
):
    user = await _get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if setor:
        query["setor"] = setor
    if status:
        query["status"] = status
    if q:
        query["$or"] = [
            {"codigo": {"$regex": q, "$options": "i"}},
            {"predio": {"$regex": q, "$options": "i"}},
            {"rua": {"$regex": q, "$options": "i"}},
        ]
    enderecos = await db.wms_enderecos.find(query, {"_id": 0}).sort("codigo", 1).to_list(10000)
    return {"enderecos": enderecos, "total": len(enderecos)}


@estoque_router.post("/wms/enderecos", status_code=201)
async def criar_wms_endereco(data: WMSEnderecoCreate, request: Request):
    user = await _get_current_user(request)
    if data.setor not in SETORES:
        raise HTTPException(status_code=422, detail=f"Setor invalido. Valores: {SETORES}")
    codigo = _wms_codigo(data.predio, data.rua, data.nivel, data.posicao)
    existing = await db.wms_enderecos.find_one(
        {"tenant_id": user["tenant_id"], "codigo": codigo}, {"_id": 0}
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Endereco WMS ja cadastrado: {codigo}")
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "codigo": codigo,
        "predio": data.predio.strip().upper(),
        "rua": data.rua.strip().upper(),
        "nivel": data.nivel.strip().upper(),
        "posicao": data.posicao.strip().upper(),
        "setor": data.setor,
        "tipo": data.tipo,
        "status": data.status,
        "capacidade_paletes": int(data.capacidade_paletes),
        "capacidade_unidades": float(data.capacidade_unidades),
        "ocupacao_atual": 0.0,
        "ocupacao_paletes": 0,
        "observacoes": data.observacoes,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.wms_enderecos.insert_one(doc)
    return _serialize(doc)


@estoque_router.post("/wms/enderecos/gerar", status_code=201)
async def gerar_wms_enderecos(data: WMSGerarEnderecos, request: Request):
    user = await _get_current_user(request)
    if data.setor not in SETORES:
        raise HTTPException(status_code=422, detail=f"Setor invalido. Valores: {SETORES}")

    created = []
    skipped = []
    now = _now_iso()
    for predio_n in range(1, data.predios + 1):
        predio = _numeric_code("P", predio_n)
        for rua_n in range(1, data.ruas_por_predio + 1):
            rua = _numeric_code("R", rua_n)
            for nivel_n in range(1, data.niveis_por_rua + 1):
                nivel = _numeric_code("N", nivel_n)
                for pos_n in range(1, data.posicoes_por_nivel + 1):
                    posicao = _numeric_code("P", pos_n)
                    codigo = _wms_codigo(predio, rua, nivel, posicao)
                    existing = await db.wms_enderecos.find_one(
                        {"tenant_id": user["tenant_id"], "codigo": codigo}, {"_id": 0}
                    )
                    if existing:
                        skipped.append(codigo)
                        continue
                    doc = {
                        "id": _new_id(),
                        "tenant_id": user["tenant_id"],
                        "codigo": codigo,
                        "predio": predio,
                        "rua": rua,
                        "nivel": nivel,
                        "posicao": posicao,
                        "setor": data.setor,
                        "tipo": data.tipo,
                        "status": "livre",
                        "capacidade_paletes": int(data.capacidade_paletes),
                        "capacidade_unidades": float(data.capacidade_unidades),
                        "ocupacao_atual": 0.0,
                        "ocupacao_paletes": 0,
                        "observacoes": "Gerado automaticamente",
                        "created_by": user["id"],
                        "created_by_name": user["name"],
                        "created_at": now,
                        "updated_at": now,
                    }
                    await db.wms_enderecos.insert_one(doc)
                    created.append(_serialize(doc))

    return {"enderecos": created, "created": len(created), "skipped": skipped, "skipped_count": len(skipped)}


@estoque_router.put("/wms/enderecos/{endereco_id}")
async def atualizar_wms_endereco(endereco_id: str, data: WMSEnderecoUpdate, request: Request):
    user = await _get_current_user(request)
    existing = await _get_wms_endereco_or_404(endereco_id, user["tenant_id"])
    payload = data.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    if "setor" in payload and payload["setor"] not in SETORES:
        raise HTTPException(status_code=422, detail=f"Setor invalido. Valores: {SETORES}")

    next_parts = {
        "predio": payload.get("predio", existing.get("predio")),
        "rua": payload.get("rua", existing.get("rua")),
        "nivel": payload.get("nivel", existing.get("nivel")),
        "posicao": payload.get("posicao", existing.get("posicao")),
    }
    payload["codigo"] = _wms_codigo(**next_parts)
    payload["updated_at"] = _now_iso()
    await db.wms_enderecos.update_one(
        {"id": endereco_id, "tenant_id": user["tenant_id"]}, {"$set": payload}
    )
    return await db.wms_enderecos.find_one({"id": endereco_id, "tenant_id": user["tenant_id"]}, {"_id": 0})


@estoque_router.delete("/wms/enderecos/{endereco_id}")
async def inativar_wms_endereco(endereco_id: str, request: Request):
    user = await _get_current_user(request)
    await _get_wms_endereco_or_404(endereco_id, user["tenant_id"])
    saldos_endereco = await db.estoque_saldos_lote.find(
        {"tenant_id": user["tenant_id"], "endereco_id": endereco_id, "status": {"$ne": "zerado"}}, {"_id": 0}
    ).to_list(5000)
    saldo = next((s for s in saldos_endereco if _saldo_quantidade(s) > 0), None)
    if saldo:
        raise HTTPException(status_code=409, detail="Endereco possui saldo. Transfira ou ajuste o lote antes de inativar.")
    await db.wms_enderecos.update_one(
        {"id": endereco_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "inativo", "updated_at": _now_iso()}},
    )
    return {"inactivated": endereco_id}


@estoque_router.get("/wms/planta")
async def planta_wms(request: Request, setor: Optional[str] = None):
    user = await _get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"], "status": {"$ne": "inativo"}}
    if setor:
        query["setor"] = setor
    enderecos = await db.wms_enderecos.find(query, {"_id": 0}).sort("codigo", 1).to_list(10000)
    saldos_raw = await db.estoque_saldos_lote.find(
        {"tenant_id": user["tenant_id"], "status": {"$ne": "zerado"}}, {"_id": 0}
    ).to_list(20000)
    saldos = [s for s in saldos_raw if _saldo_quantidade(s) > 0]
    por_endereco: Dict[str, List[dict]] = {}
    for saldo in saldos:
        por_endereco.setdefault(saldo.get("endereco_id"), []).append(saldo)

    planta: Dict[str, Dict[str, Dict[str, List[dict]]]] = {}
    for endereco in enderecos:
        predio = endereco.get("predio", "P01")
        rua = endereco.get("rua", "")
        nivel = endereco.get("nivel", "")
        celula = {**endereco, "saldos": por_endereco.get(endereco["id"], [])}
        planta.setdefault(predio, {}).setdefault(rua, {}).setdefault(nivel, []).append(celula)

    ocupados = len([e for e in enderecos if por_endereco.get(e["id"])])
    return {
        "planta": planta,
        "enderecos": enderecos,
        "total_enderecos": len(enderecos),
        "enderecos_ocupados": ocupados,
        "enderecos_livres": max(0, len(enderecos) - ocupados),
    }


async def _recalcular_ocupacao_endereco(endereco_id: str, tenant_id: str):
    saldos_raw = await db.estoque_saldos_lote.find(
        {"tenant_id": tenant_id, "endereco_id": endereco_id, "status": {"$ne": "zerado"}}, {"_id": 0}
    ).to_list(10000)
    saldos = [s for s in saldos_raw if _saldo_quantidade(s) > 0]
    ocupacao = sum(_saldo_quantidade(s) for s in saldos)
    paletes = len({s.get("palete_id") for s in saldos if s.get("palete_id")})
    status = "ocupado" if ocupacao > 0 else "livre"
    await db.wms_enderecos.update_one(
        {"id": endereco_id, "tenant_id": tenant_id},
        {"$set": {"ocupacao_atual": ocupacao, "ocupacao_paletes": paletes, "status": status, "updated_at": _now_iso()}},
    )


@estoque_router.get("/wms/saldos")
async def listar_saldos_lote(
    request: Request,
    item_id: Optional[str] = None,
    lote: Optional[str] = None,
    endereco_id: Optional[str] = None,
    setor: Optional[str] = None,
    somente_com_saldo: bool = True,
):
    user = await _get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if item_id:
        query["item_id"] = item_id
    if lote:
        query["lote"] = lote
    if endereco_id:
        query["endereco_id"] = endereco_id
    if setor:
        query["setor"] = setor
    saldos = await db.estoque_saldos_lote.find(query, {"_id": 0}).sort("updated_at", -1).to_list(20000)
    if somente_com_saldo:
        saldos = [s for s in saldos if _saldo_quantidade(s) > 0]
    return {"saldos": saldos, "total": len(saldos)}


@estoque_router.post("/wms/saldos/ajustar")
async def ajustar_saldo_lote(data: AjusteSaldoLoteCreate, request: Request):
    user = await _get_current_user(request)
    if not data.motivo.strip():
        raise HTTPException(status_code=422, detail="Motivo obrigatorio para ajuste de lote")
    if data.quantidade < 0:
        raise HTTPException(status_code=422, detail="Quantidade nao pode ser negativa")
    if data.modo not in {"absoluto", "entrada", "saida"}:
        raise HTTPException(status_code=422, detail="Modo invalido. Use: absoluto, entrada ou saida")

    item = await _get_item_or_404(data.item_id, user["tenant_id"])
    endereco = await _get_wms_endereco_or_404(data.endereco_id, user["tenant_id"])
    saldo = await _get_saldo_lote(data.item_id, data.lote, data.endereco_id, user["tenant_id"])
    atual = _saldo_quantidade(saldo)
    if data.modo == "absoluto":
        novo = float(data.quantidade)
        delta = novo - atual
    elif data.modo == "entrada":
        novo = atual + float(data.quantidade)
        delta = float(data.quantidade)
    else:
        if data.quantidade > atual:
            raise HTTPException(status_code=409, detail=f"Saldo insuficiente no lote/endereco: {atual}")
        novo = atual - float(data.quantidade)
        delta = -float(data.quantidade)

    now = _now_iso()
    if not saldo:
        saldo = {
            "id": _new_id(),
            "tenant_id": user["tenant_id"],
            "item_id": item["id"],
            "item_nome": item.get("nome", ""),
            "codigo_item": item.get("codigo", ""),
            "tipo_item": item.get("tipo_item", ""),
            "lote": data.lote,
            "validade": data.validade or item.get("validade"),
            "endereco_id": endereco["id"],
            "endereco_codigo": endereco.get("codigo", ""),
            "setor": endereco.get("setor", item.get("setor")),
            "quantidade": 0.0,
            "quantidade_atual": 0.0,
            "unidade": item.get("unidade", "un"),
            "posicao_cq": item.get("posicao_cq", "livre"),
            "status": "disponivel",
            "created_at": now,
            "updated_at": now,
        }
        await db.estoque_saldos_lote.insert_one(saldo)

    await db.estoque_saldos_lote.update_one(
        {"id": saldo["id"], "tenant_id": user["tenant_id"]},
        {"$set": {"quantidade": novo, "quantidade_atual": novo, "status": "zerado" if novo == 0 else "disponivel", "updated_at": now}},
    )
    item_qtd = float(item.get("quantidade_atual", 0)) + delta
    if item_qtd < -0.0001:
        raise HTTPException(status_code=409, detail="Ajuste deixaria saldo agregado negativo")
    await db.estoque_items.update_one(
        {"id": item["id"], "tenant_id": user["tenant_id"]},
        {"$set": {"quantidade_atual": max(0.0, item_qtd), "updated_at": now}},
    )
    saldo_atualizado = await db.estoque_saldos_lote.find_one({"id": saldo["id"], "tenant_id": user["tenant_id"]}, {"_id": 0})
    movimento = await _log_movimento_lote(
        saldo_atualizado,
        "AJUSTE_ENTRADA" if delta >= 0 else "AJUSTE_SAIDA",
        abs(delta),
        data.motivo,
        data.documento,
        user,
        atual,
        novo,
    )
    await _recalcular_ocupacao_endereco(data.endereco_id, user["tenant_id"])
    return {"saldo": saldo_atualizado, "movimento": movimento}


@estoque_router.post("/wms/transferencias-lote")
async def transferir_lote_endereco(data: TransferenciaLoteCreate, request: Request):
    user = await _get_current_user(request)
    if data.quantidade <= 0:
        raise HTTPException(status_code=422, detail="Quantidade deve ser maior que zero")
    if data.endereco_origem_id == data.endereco_destino_id:
        raise HTTPException(status_code=422, detail="Endereco destino igual ao origem")

    item = await _get_item_or_404(data.item_id, user["tenant_id"])
    await _assert_saida_liberada_por_cq(item, "TRANSFERENCIA_SAIDA")
    origem_end = await _get_wms_endereco_or_404(data.endereco_origem_id, user["tenant_id"])
    destino_end = await _get_wms_endereco_or_404(data.endereco_destino_id, user["tenant_id"])
    origem = await _get_saldo_lote(data.item_id, data.lote, data.endereco_origem_id, user["tenant_id"])
    if not origem:
        raise HTTPException(status_code=404, detail="Saldo de origem nao encontrado")
    origem_qtd = _saldo_quantidade(origem)
    if data.quantidade > origem_qtd:
        raise HTTPException(status_code=409, detail=f"Saldo insuficiente no endereco origem: {origem_qtd}")

    destino = await _get_saldo_lote(data.item_id, data.lote, data.endereco_destino_id, user["tenant_id"])
    now = _now_iso()
    if not destino:
        destino = {
            "id": _new_id(),
            "tenant_id": user["tenant_id"],
            "item_id": item["id"],
            "item_nome": item.get("nome", origem.get("item_nome", "")),
            "codigo_item": item.get("codigo", origem.get("codigo_item", "")),
            "tipo_item": item.get("tipo_item", origem.get("tipo_item", "")),
            "lote": data.lote,
            "validade": origem.get("validade") or item.get("validade"),
            "endereco_id": destino_end["id"],
            "endereco_codigo": destino_end.get("codigo", ""),
            "setor": destino_end.get("setor", item.get("setor")),
            "quantidade": 0.0,
            "quantidade_atual": 0.0,
            "unidade": origem.get("unidade", item.get("unidade", "un")),
            "posicao_cq": origem.get("posicao_cq", item.get("posicao_cq", "livre")),
            "status": "disponivel",
            "created_at": now,
            "updated_at": now,
        }
        await db.estoque_saldos_lote.insert_one(destino)

    ref = f"WMS-TRANSF-{_new_id()[:8]}"
    origem_novo = origem_qtd - float(data.quantidade)
    destino_antes = _saldo_quantidade(destino)
    destino_novo = destino_antes + float(data.quantidade)

    await db.estoque_saldos_lote.update_one(
        {"id": origem["id"], "tenant_id": user["tenant_id"]},
        {"$set": {"quantidade": origem_novo, "quantidade_atual": origem_novo, "status": "zerado" if origem_novo == 0 else "disponivel", "updated_at": now}},
    )
    await db.estoque_saldos_lote.update_one(
        {"id": destino["id"], "tenant_id": user["tenant_id"]},
        {"$set": {"quantidade": destino_novo, "quantidade_atual": destino_novo, "status": "disponivel", "updated_at": now}},
    )
    origem_atualizada = await db.estoque_saldos_lote.find_one({"id": origem["id"], "tenant_id": user["tenant_id"]}, {"_id": 0})
    destino_atualizado = await db.estoque_saldos_lote.find_one({"id": destino["id"], "tenant_id": user["tenant_id"]}, {"_id": 0})
    mov_saida = await _log_movimento_lote(origem_atualizada, "TRANSFERENCIA_SAIDA", data.quantidade, data.motivo, data.documento, user, origem_qtd, origem_novo, ref)
    mov_entrada = await _log_movimento_lote(destino_atualizado, "TRANSFERENCIA_ENTRADA", data.quantidade, data.motivo, data.documento, user, destino_antes, destino_novo, ref)
    await _recalcular_ocupacao_endereco(origem_end["id"], user["tenant_id"])
    await _recalcular_ocupacao_endereco(destino_end["id"], user["tenant_id"])
    return {"referencia": ref, "origem": origem_atualizada, "destino": destino_atualizado, "mov_saida": mov_saida, "mov_entrada": mov_entrada}


@estoque_router.get("/wms/relatorio-saldos")
async def relatorio_saldos_lote(request: Request, setor: Optional[str] = None):
    user = await _get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"], "status": {"$ne": "zerado"}}
    if setor:
        query["setor"] = setor
    saldos_raw = await db.estoque_saldos_lote.find(query, {"_id": 0}).sort("endereco_codigo", 1).to_list(50000)
    saldos = [s for s in saldos_raw if _saldo_quantidade(s) > 0]
    total_por_item: Dict[str, float] = {}
    total_por_endereco: Dict[str, float] = {}
    total_por_lote: Dict[str, float] = {}
    for saldo in saldos:
        qtd = _saldo_quantidade(saldo)
        total_por_item[saldo.get("item_id", "")] = total_por_item.get(saldo.get("item_id", ""), 0) + qtd
        total_por_endereco[saldo.get("endereco_codigo", "")] = total_por_endereco.get(saldo.get("endereco_codigo", ""), 0) + qtd
        lote_key = f"{saldo.get('item_id', '')}|{saldo.get('lote', '')}"
        total_por_lote[lote_key] = total_por_lote.get(lote_key, 0) + qtd
    return {
        "base": "estoque_saldos_lote",
        "saldos": saldos,
        "total_linhas": len(saldos),
        "total_quantidade": round(sum(_saldo_quantidade(s) for s in saldos), 6),
        "total_por_item": total_por_item,
        "total_por_endereco": total_por_endereco,
        "total_por_lote": total_por_lote,
    }


@estoque_router.get("/kardex/{item_id}")
async def get_kardex(item_id: str, request: Request, limit: int = 500):
    """Retorna histórico imutável de movimentos de um item"""
    user = await _get_current_user(request)
    await _get_item_or_404(item_id, user["tenant_id"])
    movs = await db.estoque_movimentos.find(
        {"item_id": item_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return movs


@estoque_router.get("/movimentos")
async def list_movimentos(
    request: Request,
    setor: Optional[str] = None,
    tipo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    limit: int = 500,
):
    """Lista geral de movimentos com filtros (para relatórios)"""
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if setor:
        query["setor"] = setor
    if tipo:
        query["tipo"] = tipo
    if data_inicio or data_fim:
        dt = {}
        if data_inicio:
            dt["$gte"] = data_inicio
        if data_fim:
            dt["$lte"] = data_fim
        query["created_at"] = dt

    movs = await db.estoque_movimentos.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return movs


# ============ DASHBOARD ============

@estoque_router.get("/dashboard")
async def estoque_dashboard(request: Request):
    """Resumo por setor + alertas de estoque mínimo"""
    user = await _get_current_user(request)
    t_id = user["tenant_id"]

    items_all = await db.estoque_items.find({"tenant_id": t_id}, {"_id": 0}).to_list(10000)

    by_setor = {}
    low_stock = []
    expiring_soon = []
    today = datetime.now(timezone.utc).date()
    for item in items_all:
        setor = item.get("setor", "?")
        by_setor.setdefault(setor, {"total_items": 0, "total_quantidade": 0})
        by_setor[setor]["total_items"] += 1
        by_setor[setor]["total_quantidade"] += item.get("quantidade_atual", 0)

        # Alerta de baixo estoque
        if item.get("estoque_minimo", 0) > 0 and item.get("quantidade_atual", 0) <= item["estoque_minimo"]:
            low_stock.append(item)

        # Alerta de validade próxima (30 dias)
        validade = item.get("validade")
        if validade:
            try:
                val_date = datetime.fromisoformat(validade).date() if "T" not in validade else datetime.fromisoformat(validade.replace("Z", "+00:00")).date()
                days_left = (val_date - today).days
                if 0 <= days_left <= 30:
                    expiring_soon.append({**item, "days_left": days_left})
            except Exception:
                pass

    # Movimentos das últimas 24h
    last_24h = await db.estoque_movimentos.count_documents({
        "tenant_id": t_id,
        "created_at": {"$gte": (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).isoformat()}
    })

    # Obsolescência: itens sem movimento nos últimos 90 dias
    cutoff_90 = (datetime.now(timezone.utc).replace(tzinfo=None) - __import__("datetime").timedelta(days=90)).isoformat()
    itens_ids_com_mov = await db.estoque_movimentos.distinct(
        "item_id",
        {"tenant_id": t_id, "created_at": {"$gte": cutoff_90}}
    )
    obsoletos = [
        i for i in items_all
        if i.get("quantidade_atual", 0) > 0
        and i["id"] not in itens_ids_com_mov
    ]

    return {
        "setores": [
            {
                "setor": s,
                "label": SETOR_LABELS.get(s, s),
                "total_items": by_setor.get(s, {}).get("total_items", 0),
                "total_quantidade": by_setor.get(s, {}).get("total_quantidade", 0),
            } for s in SETORES
        ],
        "alertas": {
            "baixo_estoque": low_stock,
            "validade_proxima": expiring_soon,
            "obsoletos": obsoletos[:20],
        },
        "movimentos_hoje": last_24h,
        "total_items": len(items_all),
    }


@estoque_router.get("/options")
async def get_options():
    return {
        "setores": SETORES,
        "setor_labels": SETOR_LABELS,
        "tipos_movimento": TIPOS_MOVIMENTO,
        "movimentos_entrada": list(MOVIMENTOS_ENTRADA),
        "movimentos_saida": list(MOVIMENTOS_SAIDA),
        "tipos_item": TIPO_ITEM_VALORES,
    }


@estoque_router.get("/alertas/obsolescencia")
async def alertas_obsolescencia(request: Request, dias: int = 90):
    """Items with saldo > 0 but no movement in the last N days."""
    user = await _get_current_user(request)
    t_id = user["tenant_id"]
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    itens_ativos_ids = await db.estoque_movimentos.distinct(
        "item_id",
        {"tenant_id": t_id, "created_at": {"$gte": cutoff}}
    )
    items = await db.estoque_items.find(
        {"tenant_id": t_id, "quantidade_atual": {"$gt": 0}},
        {"_id": 0}
    ).to_list(10000)
    obsoletos = [i for i in items if i["id"] not in itens_ativos_ids]
    return {"dias_sem_movimento": dias, "total": len(obsoletos), "items": obsoletos}


@estoque_router.get("/fifo-sugestao")
async def fifo_sugestao(request: Request, nome: str, setor: Optional[str] = None):
    """
    Returns all lots of an item sorted by validade ASC (FIFO).
    Operator should consume from top of list first.
    """
    user = await _get_current_user(request)
    query: Dict[str, Any] = {
        "tenant_id": user["tenant_id"],
        "nome": {"$regex": nome, "$options": "i"},
        "quantidade_atual": {"$gt": 0},
        "posicao_cq": "aprovado",
    }
    if setor:
        query["setor"] = setor
    items = await db.estoque_items.find(query, {"_id": 0}).to_list(100)
    # Sort by validade (None = infinite = last)
    items.sort(key=lambda x: x.get("validade") or "9999-99-99")
    return {"fifo_order": items, "total_lotes": len(items)}
