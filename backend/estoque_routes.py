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
