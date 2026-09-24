"""
Retrabalho — rework de lotes reprovados pelo CQ.
Categorias:
  RT-1: Retrabalho Interno — reprocessamento no próprio lote (lote + sufixo R)
  RT-2: Retrabalho com Substituição — novo lote criado
  RT-3: Devolução ao Fornecedor — exige comprovante de devolução física

Fluxo:
  RNC com decisão "retrabalho" → criar Ordem de Retrabalho (RT) vinculada à RNC
  Produção executa → em_retrabalho → aguardando_cq → liberado/reprovado_cq
  Ao concluir, nova RA é criada automaticamente para re-inspeção CQ

Regras de Negócio:
  RN-RT-01: Toda RT exige RNC vinculada (sem RNC = bloqueio)
  RN-RT-02: Métricas por categoria (RT-1, RT-2, RT-3) separadas
  RN-RT-03: Saldo do pedido mostra "X un em retrabalho"
  RN-RT-04: RT-3 exige devolucao_id (comprovante físico) antes de RNC
  RN-RT-05: Custo acumulado por pedido
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from stock_ledger import append_lot_ledger_event
from rbac import REWORK_WRITE_ROLES, require_roles

logger = logging.getLogger(__name__)

retrabalho_router = APIRouter(prefix="/api/retrabalho")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_retrabalho(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


async def _enforce_retrabalho_write_rbac(request: Request):
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        require_roles(await get_current_user(request), REWORK_WRITE_ROLES)


retrabalho_router.dependencies.append(Depends(_enforce_retrabalho_write_rbac))


async def create_retrabalho_indexes():
    await db.retrabalho_ordens.create_index([("tenant_id", 1), ("idempotency_key", 1)], unique=True, sparse=True)
    await db.devolucoes_cliente.create_index([("tenant_id", 1), ("idempotency_key", 1)], unique=True)
    await db.devolucoes_cliente.create_index([("tenant_id", 1), ("expedicao_original_id", 1), ("status", 1)])


def new_id():
    return new_id_func()


def now_iso():
    return now_iso_func()


RT_STATUSES = ["pendente", "em_retrabalho", "aguardando_cq", "liberado", "reprovado_cq", "reexpedido", "cancelado"]
RT_CATEGORIAS = ["RT-1", "RT-2", "RT-3"]

STATUS_TRANSITIONS = {
    "pendente":      ["em_retrabalho", "cancelado"],
    # A ida para aguardando_cq ocorre somente pelo endpoint /concluir, que
    # cria obrigatoriamente a RA de reinspecao na mesma operacao.
    "em_retrabalho": ["cancelado"],
    "aguardando_cq": [],
    "liberado":      ["reexpedido"],
    "reprovado_cq":  [],
    "reexpedido":    [],
    "cancelado":     [],
}


# ===== MODELS =====
class RTCreate(BaseModel):
    categoria: str = "RT-1"              # "RT-1" | "RT-2" | "RT-3"
    rnc_id: str                          # Obrigatório — RN-RT-01
    op_id: Optional[str] = None          # OP original vinculada (PCP)
    lote_id: Optional[str] = None
    lote_numero: Optional[str] = None
    produto_nome: str
    problema_descrito: str
    instrucoes_retrabalho: str = ""
    responsavel_id: Optional[str] = None
    responsavel_nome: Optional[str] = None
    data_limite: Optional[str] = None    # YYYY-MM-DD
    custo_estimado: float = 0.0
    devolucao_id: Optional[str] = None   # RT-3: comprovante de devolução física
    observacoes: str = ""
    quantidade: float = 0.0
    unidade: str = "un"
    saldo_lote_id: Optional[str] = None
    estoque_item_id: Optional[str] = None
    devolucao_cliente_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class RTUpdate(BaseModel):
    instrucoes_retrabalho: Optional[str] = None
    responsavel_id: Optional[str] = None
    responsavel_nome: Optional[str] = None
    data_limite: Optional[str] = None
    custo_estimado: Optional[float] = None
    observacoes: Optional[str] = None
    status: Optional[str] = None


class RTConcluir(BaseModel):
    observacoes_conclusao: str = ""
    criar_ra: bool = True


class DevolucaoClienteCreate(BaseModel):
    expedicao_id: str
    item_index: int = Field(default=0, ge=0)
    quantidade: float = Field(gt=0)
    motivo: str = Field(min_length=5)
    observacoes: str = ""
    idempotency_key: str = Field(min_length=8, max_length=160)
    criar_retrabalho: bool = True


class ReexpedicaoCreate(BaseModel):
    endereco_entrega: str = ""
    transportadora: str = ""
    previsao_entrega: Optional[str] = None
    observacoes: str = ""
    idempotency_key: str = Field(min_length=8, max_length=160)


# ===== HELPERS =====
async def _next_rt_numero(tenant_id: str) -> str:
    count = await db.retrabalho_ordens.count_documents({"tenant_id": tenant_id})
    return f"RT-{str(count + 1).zfill(5)}"


# ===== ROUTES =====
@retrabalho_router.get("/ordens")
async def list_ordens(
    request: Request,
    status: Optional[str] = None,
    categoria: Optional[str] = None,
    q: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if categoria:
        query["categoria"] = categoria
    if q:
        query["$or"] = [
            {"numero_rt": {"$regex": q, "$options": "i"}},
            {"produto_nome": {"$regex": q, "$options": "i"}},
            {"lote_numero": {"$regex": q, "$options": "i"}},
            {"rnc_numero": {"$regex": q, "$options": "i"}},
        ]
    ordens = await db.retrabalho_ordens.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return ordens


@retrabalho_router.get("/ordens/{rt_id}")
async def get_ordem(rt_id: str, request: Request):
    user = await get_current_user(request)
    rt = await db.retrabalho_ordens.find_one({"id": rt_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not rt:
        raise HTTPException(status_code=404, detail="Ordem de Retrabalho não encontrada")
    return rt


@retrabalho_router.post("/ordens")
async def create_ordem(data: RTCreate, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]

    if data.idempotency_key:
        existing = await db.retrabalho_ordens.find_one(
            {"tenant_id": tid, "idempotency_key": data.idempotency_key}, {"_id": 0}
        )
        if existing:
            existing["idempotent_replay"] = True
            return existing

    if data.categoria not in RT_CATEGORIAS:
        raise HTTPException(status_code=400, detail=f"Categoria inválida. Use: {', '.join(RT_CATEGORIAS)}")
    if not data.produto_nome.strip():
        raise HTTPException(status_code=400, detail="Nome do produto obrigatório")
    if not data.problema_descrito.strip():
        raise HTTPException(status_code=400, detail="Descreva o problema identificado")

    # RN-RT-01: RNC is mandatory for every RT
    rnc = await db.cq_rncs.find_one({"id": data.rnc_id, "tenant_id": tid}, {"_id": 0})
    if not rnc:
        raise HTTPException(
            status_code=400,
            detail="RNC não encontrada. Toda Ordem de Retrabalho exige RNC vinculada (RN-RT-01)"
        )

    # RN-RT-04: RT-3 requires physical return proof before creating the RT
    if data.categoria == "RT-3" and not data.devolucao_id:
        raise HTTPException(
            status_code=400,
            detail="RT-3 (Devolução ao Fornecedor) exige comprovante de devolução física antes de criar a RT (RN-RT-04)"
        )

    # Lote numbering: RT-1 keeps original lote + 'R' suffix
    lote_numero = data.lote_numero
    if data.categoria == "RT-1" and lote_numero and not lote_numero.endswith("R"):
        lote_numero = f"{lote_numero}R"

    # Resolve OP context for saldo tracking (RN-RT-03)
    op_ref = {}
    if data.op_id:
        op = await db.ops.find_one({"id": data.op_id, "tenant_id": tid}, {"_id": 0})
        if op:
            op_ref = {
                "op_numero": op.get("numero_op", ""),
                "pedido_id": op.get("pedido_id", ""),
                "pedido_numero": op.get("pedido_numero", ""),
            }

    numero_rt = await _next_rt_numero(tid)
    now = now_iso()
    rt_id = new_id()

    saldo = None
    if data.saldo_lote_id:
        saldo = await db.estoque_saldos_lote.find_one(
            {"id": data.saldo_lote_id, "tenant_id": tid}, {"_id": 0}
        )
    elif data.lote_id:
        saldos = await db.estoque_saldos_lote.find(
            {"tenant_id": tid, "$or": [{"lote_id": data.lote_id}, {"cq_lote_id": data.lote_id}]}, {"_id": 0}
        ).to_list(2)
        saldo = saldos[0] if len(saldos) == 1 else None

    rt = {
        "id": rt_id,
        "tenant_id": tid,
        "numero_rt": numero_rt,
        "categoria": data.categoria,
        "rnc_id": data.rnc_id,
        "rnc_numero": rnc.get("numero_rnc", ""),
        "op_id": data.op_id,
        **op_ref,
        "lote_id": data.lote_id,
        "lote_numero": lote_numero,
        "produto_nome": data.produto_nome.strip(),
        "problema_descrito": data.problema_descrito.strip(),
        "instrucoes_retrabalho": data.instrucoes_retrabalho,
        "responsavel_id": data.responsavel_id or user["id"],
        "responsavel_nome": data.responsavel_nome or user["name"],
        "data_limite": data.data_limite,
        "custo_estimado": data.custo_estimado,
        "devolucao_id": data.devolucao_id,
        "devolucao_cliente_id": data.devolucao_cliente_id,
        "estoque_item_id": data.estoque_item_id or (saldo or {}).get("item_id"),
        "saldo_lote_id": data.saldo_lote_id or (saldo or {}).get("id"),
        "quantidade": data.quantidade or (rnc.get("quantidade_afetada") or 0),
        "unidade": data.unidade or rnc.get("unidade") or "un",
        "idempotency_key": data.idempotency_key,
        "status": "pendente",
        "nova_ra_id": None,
        "nova_ra_numero": None,
        "observacoes": data.observacoes,
        "historico": [{"de": None, "para": "pendente", "por": user["name"], "em": now}],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.retrabalho_ordens.insert_one(rt)
    rt.pop("_id", None)
    logger.info(f"RT {numero_rt} ({data.categoria}) criada por {user['name']} — RNC: {rnc.get('numero_rnc', '')}")
    return rt


@retrabalho_router.put("/ordens/{rt_id}")
async def update_ordem(rt_id: str, data: RTUpdate, request: Request):
    user = await get_current_user(request)
    rt = await db.retrabalho_ordens.find_one({"id": rt_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not rt:
        raise HTTPException(status_code=404, detail="RT não encontrada")

    now = now_iso()
    updates: Dict[str, Any] = {"updated_at": now}
    historico = list(rt.get("historico", []))

    payload = data.model_dump(exclude_unset=True)

    if "status" in payload:
        novo_status = payload["status"]
        if novo_status not in RT_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status inválido: {novo_status}")
        allowed = STATUS_TRANSITIONS.get(rt["status"], [])
        if novo_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Transição {rt['status']} → {novo_status} não permitida"
            )
        historico.append({"de": rt["status"], "para": novo_status, "por": user["name"], "em": now})
        updates["status"] = novo_status
        updates["historico"] = historico

    for field in ("instrucoes_retrabalho", "responsavel_id", "responsavel_nome",
                  "data_limite", "custo_estimado", "observacoes"):
        if field in payload and payload[field] is not None:
            updates[field] = payload[field]

    await db.retrabalho_ordens.update_one({"id": rt_id}, {"$set": updates})
    return await db.retrabalho_ordens.find_one({"id": rt_id}, {"_id": 0})


@retrabalho_router.post("/ordens/{rt_id}/concluir")
async def concluir_ordem(rt_id: str, data: RTConcluir, request: Request):
    """Marca RT como concluída e cria nova RA para re-inspeção CQ."""
    user = await get_current_user(request)
    tid = user["tenant_id"]
    rt = await db.retrabalho_ordens.find_one({"id": rt_id, "tenant_id": tid}, {"_id": 0})
    if not rt:
        raise HTTPException(status_code=404, detail="RT não encontrada")
    if rt["status"] not in ("pendente", "em_retrabalho"):
        raise HTTPException(status_code=422, detail=f"RT já está em status '{rt['status']}'")
    if not data.criar_ra:
        raise HTTPException(status_code=422, detail="A reinspecao CQ e obrigatoria para concluir o retrabalho.")

    now = now_iso()
    historico = list(rt.get("historico", []))
    historico.append({"de": rt["status"], "para": "aguardando_cq", "por": user["name"], "em": now})

    nova_ra_id = None
    nova_ra_numero = None

    if data.criar_ra:
        count = await db.cq_registros_analise.count_documents({"tenant_id": tid})
        nova_ra_numero = f"RA-{str(count + 1).zfill(5)}"
        nova_ra_id = new_id()
        nova_ra = {
            "id": nova_ra_id,
            "tenant_id": tid,
            "numero_ra": nova_ra_numero,
            "lote_id": rt.get("lote_id") or new_id(),
            "lote_numero": rt.get("lote_numero", ""),
            "tipo": "produto_acabado",
            "status": "rascunho",
            "origem_rt_id": rt_id,
            "origem_rt_numero": rt.get("numero_rt", ""),
            "categoria_rt": rt.get("categoria", ""),
            "produto_nome": rt.get("produto_nome", ""),
            "item_id": rt.get("estoque_item_id"),
            "item_nome": rt.get("produto_nome", ""),
            "item_tipo": "produto_acabado",
            "quantidade_recebida": rt.get("quantidade", 0),
            "unidade": rt.get("unidade", "un"),
            "resultado_geral": None,
            "analista_id": user["id"],
            "analista_nome": user.get("name", ""),
            "data_analise": None,
            "fotos_file_ids": [],
            "rnc_id": rt.get("rnc_id"),
            "log_auditoria": [],
            "parametros": [],
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        await db.cq_registros_analise.insert_one(nova_ra)
        await db.cq_status_lote.insert_one({
            "id": new_id(), "tenant_id": tid, "lote_id": nova_ra["lote_id"],
            "lote_numero": nova_ra.get("lote_numero", ""), "status_anterior": "reprovado",
            "status_novo": "em_analise", "motivo": f"Reinspecao do retrabalho {rt.get('numero_rt', '')}",
            "ra_id": nova_ra_id, "alterado_por_id": user["id"],
            "alterado_por_nome": user.get("name", ""), "created_at": now,
        })
        logger.info(f"Nova RA {nova_ra_numero} criada para re-inspeção RT {rt['numero_rt']}")

    updates = {
        "status": "aguardando_cq",
        "historico": historico,
        "nova_ra_id": nova_ra_id,
        "nova_ra_numero": nova_ra_numero,
        "observacoes_conclusao": data.observacoes_conclusao,
        "updated_at": now,
    }
    await db.retrabalho_ordens.update_one({"id": rt_id}, {"$set": updates})
    if rt.get("devolucao_cliente_id"):
        await db.devolucoes_cliente.update_one(
            {"id": rt["devolucao_cliente_id"], "tenant_id": tid},
            {"$set": {"status": "aguardando_cq", "ra_reinspecao_id": nova_ra_id, "updated_at": now}},
        )
    return await db.retrabalho_ordens.find_one({"id": rt_id}, {"_id": 0})


async def _endereco_devolucao(tenant_id: str) -> Dict[str, Any]:
    codigo = "DEV-QUARENTENA"
    endereco = await db.wms_enderecos.find_one(
        {"tenant_id": tenant_id, "codigo": codigo}, {"_id": 0}
    )
    if endereco:
        return endereco
    endereco = {
        "id": f"devolucao-{tenant_id}".lower(), "tenant_id": tenant_id, "codigo": codigo,
        "setor": "DEVOLUCAO", "predio": "DEV", "rua": "QUARENTENA", "nivel": "0", "posicao": "0",
        "tipo": "quarentena_devolucao", "status": "livre",
        "descricao": "Quarentena de devolucoes de cliente", "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.wms_enderecos.update_one(
        {"tenant_id": tenant_id, "codigo": codigo}, {"$setOnInsert": endereco}, upsert=True
    )
    return await db.wms_enderecos.find_one(
        {"tenant_id": tenant_id, "codigo": codigo}, {"_id": 0}
    )


async def _saldo_original_expedicao(item: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if item.get("saldo_lote_id"):
        query["id"] = item["saldo_lote_id"]
    else:
        query["item_id"] = item.get("estoque_item_id")
        query["lote"] = item.get("lote")
    saldos = await db.estoque_saldos_lote.find(query, {"_id": 0}).to_list(2)
    if len(saldos) != 1:
        raise HTTPException(status_code=409, detail="Nao foi possivel identificar unicamente o lote original expedido.")
    return saldos[0]


@retrabalho_router.get("/devolucoes")
async def listar_devolucoes(request: Request, status: Optional[str] = None):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    rows = await db.devolucoes_cliente.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    ids = [row["id"] for row in rows if row.get("id")]
    notas = await db.faturamento_notas.find(
        {"tenant_id": user["tenant_id"], "devolucao_cliente_id": {"$in": ids}}, {"_id": 0}
    ).to_list(1000) if ids else []
    notas_por_devolucao = {nota.get("devolucao_cliente_id"): nota for nota in notas}
    for row in rows:
        nota = notas_por_devolucao.get(row.get("id"))
        if nota:
            row["nf_reexpedicao"] = {
                "id": nota.get("id"), "numero_interno": nota.get("numero_interno"),
                "numero_nfe": nota.get("numero_nfe"), "chave_acesso": nota.get("chave_acesso"),
                "status": nota.get("status"), "fiscal_status": nota.get("fiscal_status"),
            }
    return rows


@retrabalho_router.post("/devolucoes", status_code=201)
async def registrar_devolucao_cliente(data: DevolucaoClienteCreate, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    existing = await db.devolucoes_cliente.find_one(
        {"tenant_id": tid, "idempotency_key": data.idempotency_key}, {"_id": 0}
    )
    if existing and existing.get("status") != "processando":
        existing["idempotent_replay"] = True
        return existing

    exp = await db.expedicao_ordens.find_one(
        {"id": data.expedicao_id, "tenant_id": tid}, {"_id": 0}
    )
    if not exp:
        raise HTTPException(status_code=404, detail="Expedicao original nao encontrada.")
    if exp.get("status") not in {"expedido", "entregue"}:
        raise HTTPException(status_code=422, detail="Devolucao exige expedicao confirmada ou entregue.")
    items = exp.get("items") or []
    if data.item_index >= len(items):
        raise HTTPException(status_code=422, detail="Item da expedicao invalido.")
    exp_item = items[data.item_index]
    devolucoes = await db.devolucoes_cliente.find(
        {"tenant_id": tid, "expedicao_original_id": exp["id"], "item_index": data.item_index,
         "status": {"$ne": "cancelada"}}, {"_id": 0}
    ).to_list(1000)
    ja_devolvido = sum(float(row.get("quantidade") or 0) for row in devolucoes)
    if ja_devolvido + data.quantidade > float(exp_item.get("quantidade") or 0) + 0.000001:
        raise HTTPException(status_code=409, detail="Quantidade devolvida excede a quantidade expedida para este item.")

    original_saldo = await _saldo_original_expedicao(exp_item, tid)
    now = now_iso()
    devolucao_id = (existing or {}).get("id") or new_id()
    lote_id = (existing or {}).get("lote_id") or new_id()
    estoque_item_id = (existing or {}).get("estoque_item_id") or new_id()
    saldo_id = (existing or {}).get("saldo_lote_id") or new_id()
    rnc_id = (existing or {}).get("rnc_id") or new_id()
    rt_id = (existing or {}).get("rt_id") or (new_id() if data.criar_retrabalho else None)
    lote = f"{original_saldo.get('lote') or exp_item.get('lote') or 'SEM-LOTE'}-DEV-{devolucao_id[:6].upper()}"

    base_doc = {
        "id": devolucao_id, "tenant_id": tid, "idempotency_key": data.idempotency_key,
        "status": "processando", "expedicao_original_id": exp["id"],
        "expedicao_original_numero": exp.get("numero_exp", ""), "item_index": data.item_index,
        "order_id": exp.get("order_id"), "order_numero": exp.get("order_numero"),
        "cliente_id": exp.get("cliente_id"), "cliente_nome": exp.get("cliente_nome", ""),
        "produto_nome": exp_item.get("produto_nome", ""), "sku": exp_item.get("sku", ""),
        "quantidade": float(data.quantidade), "unidade": exp_item.get("unidade", "un"),
        "lote_original": original_saldo.get("lote", ""), "lote": lote, "lote_id": lote_id,
        "estoque_item_id": estoque_item_id, "saldo_lote_id": saldo_id, "rnc_id": rnc_id, "rt_id": rt_id,
        "motivo": data.motivo.strip(), "observacoes": data.observacoes,
        "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
    }
    await db.devolucoes_cliente.update_one(
        {"tenant_id": tid, "idempotency_key": data.idempotency_key}, {"$setOnInsert": base_doc}, upsert=True
    )
    endereco = await _endereco_devolucao(tid)
    item_doc = {
        "id": estoque_item_id, "tenant_id": tid, "tipo_item": "produto_acabado", "setor": "DEVOLUCAO",
        "nome": exp_item.get("produto_nome", ""), "codigo": exp_item.get("sku", ""), "unidade": exp_item.get("unidade", "un"),
        "quantidade_atual": float(data.quantidade), "lote": lote, "localizacao": endereco.get("codigo", ""),
        "localizacao_estruturada": endereco.get("codigo", ""), "posicao_cq": "quarentena",
        "cq_status": "quarentena", "cq_lote_id": lote_id, "devolucao_cliente_id": devolucao_id,
        "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
    }
    await db.estoque_items.update_one(
        {"id": estoque_item_id, "tenant_id": tid}, {"$setOnInsert": item_doc}, upsert=True
    )
    saldo_doc = {
        "id": saldo_id, "tenant_id": tid, "item_id": estoque_item_id, "item_nome": exp_item.get("produto_nome", ""),
        "codigo_item": exp_item.get("sku", ""), "tipo_item": "produto_acabado", "setor": "DEVOLUCAO",
        "lote": lote, "lote_id": lote_id, "cq_lote_id": lote_id, "endereco_id": endereco["id"],
        "endereco_codigo": endereco.get("codigo", ""), "quantidade": float(data.quantidade),
        "quantidade_atual": float(data.quantidade), "quantidade_reservada": 0.0, "unidade": exp_item.get("unidade", "un"),
        "status": "quarentena", "posicao_cq": "quarentena", "cq_status": "quarentena",
        "wms_quarantine_physical": True, "devolucao_cliente_id": devolucao_id,
        "created_at": now, "updated_at": now,
    }
    await db.estoque_saldos_lote.update_one(
        {"id": saldo_id, "tenant_id": tid}, {"$setOnInsert": saldo_doc}, upsert=True
    )
    ledger_key = f"devolucao-cliente:{devolucao_id}"
    if not await db.estoque_movimentos_lote.find_one({"tenant_id": tid, "idempotency_key": ledger_key}, {"_id": 0}):
        await append_lot_ledger_event(
            db, new_id_fn=new_id, now_iso_fn=now_iso, tenant_id=tid, saldo=saldo_doc,
            natureza="movimento", evento="ENTRADA_DEVOLUCAO_CLIENTE", quantidade=data.quantidade,
            quantidade_delta=data.quantidade, quantidade_antes=0, quantidade_depois=data.quantidade,
            motivo=data.motivo, documento=exp.get("numero_exp", ""), referencia=devolucao_id,
            usuario=user, idempotency_key=ledger_key,
            metadata={"expedicao_original_id": exp["id"], "lote_original": original_saldo.get("lote")},
        )

    numero_rnc = f"RNC-DEV-{devolucao_id[:8].upper()}"
    rnc = {
        "id": rnc_id, "numero_rnc": numero_rnc, "tenant_id": tid, "status": "aberta",
        "classificacao": "maior", "origem": "devolucao_cliente", "descricao": data.motivo,
        "lote_id": lote_id, "lote_numero": lote, "item_nome": exp_item.get("produto_nome", ""),
        "quantidade_afetada": float(data.quantidade), "unidade": exp_item.get("unidade", "un"),
        "disposicao_imediata": "reprocesso" if data.criar_retrabalho else "devolucao",
        "responsavel_id": user["id"], "responsavel_nome": user.get("name", ""),
        "devolucao_cliente_id": devolucao_id, "created_at": now, "updated_at": now, "log_auditoria": [],
    }
    await db.cq_rncs.update_one({"id": rnc_id, "tenant_id": tid}, {"$setOnInsert": rnc}, upsert=True)

    if data.criar_retrabalho:
        numero_rt = f"RT-DEV-{devolucao_id[:8].upper()}"
        rt = {
            "id": rt_id, "tenant_id": tid, "numero_rt": numero_rt, "categoria": "RT-2",
            "rnc_id": rnc_id, "rnc_numero": numero_rnc, "op_id": None, "order_id": exp.get("order_id"),
            "lote_id": lote_id, "lote_numero": lote, "produto_nome": exp_item.get("produto_nome", ""),
            "problema_descrito": data.motivo, "instrucoes_retrabalho": "Reprocessar devolucao e encaminhar para reinspecao CQ.",
            "responsavel_id": user["id"], "responsavel_nome": user.get("name", ""),
            "devolucao_cliente_id": devolucao_id, "estoque_item_id": estoque_item_id, "saldo_lote_id": saldo_id,
            "quantidade": float(data.quantidade), "unidade": exp_item.get("unidade", "un"),
            "status": "pendente", "nova_ra_id": None, "nova_ra_numero": None,
            "idempotency_key": f"devolucao:{devolucao_id}", "historico": [{"de": None, "para": "pendente", "por": user.get("name", ""), "em": now}],
            "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
        }
        await db.retrabalho_ordens.update_one({"id": rt_id, "tenant_id": tid}, {"$setOnInsert": rt}, upsert=True)

    final_status = "aguardando_retrabalho" if data.criar_retrabalho else "em_quarentena"
    await db.devolucoes_cliente.update_one(
        {"id": devolucao_id, "tenant_id": tid},
        {"$set": {"status": final_status, "endereco_id": endereco["id"],
                  "endereco_codigo": endereco.get("codigo", ""), "updated_at": now}},
    )
    return await db.devolucoes_cliente.find_one({"id": devolucao_id, "tenant_id": tid}, {"_id": 0})


@retrabalho_router.post("/devolucoes/{devolucao_id}/gerar-reexpedicao", status_code=201)
async def gerar_reexpedicao_devolucao(devolucao_id: str, data: ReexpedicaoCreate, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    devolucao = await db.devolucoes_cliente.find_one({"id": devolucao_id, "tenant_id": tid}, {"_id": 0})
    if not devolucao:
        raise HTTPException(status_code=404, detail="Devolucao nao encontrada.")
    if devolucao.get("reexpedicao_id"):
        exp = await db.expedicao_ordens.find_one({"id": devolucao["reexpedicao_id"], "tenant_id": tid}, {"_id": 0})
        if exp:
            exp["idempotent_replay"] = True
            return exp
    if devolucao.get("status") != "liberado_cq":
        raise HTTPException(status_code=422, detail="Reexpedicao bloqueada ate aprovacao da reinspecao pelo CQ.")
    saldo = await db.estoque_saldos_lote.find_one(
        {"id": devolucao["saldo_lote_id"], "tenant_id": tid}, {"_id": 0}
    )
    if not saldo or float(saldo.get("quantidade") or 0) < float(devolucao.get("quantidade") or 0):
        raise HTTPException(status_code=409, detail="Saldo devolvido insuficiente para reexpedicao.")
    original = await db.expedicao_ordens.find_one(
        {"id": devolucao["expedicao_original_id"], "tenant_id": tid}, {"_id": 0}
    )
    now = now_iso()
    exp_id = new_id()
    count = await db.expedicao_ordens.count_documents({"tenant_id": tid})
    exp = {
        "id": exp_id, "tenant_id": tid, "numero_exp": f"EXP-{count + 1:05d}",
        "order_id": devolucao.get("order_id"), "order_numero": devolucao.get("order_numero"),
        "cliente_nome": devolucao.get("cliente_nome", ""), "cliente_id": devolucao.get("cliente_id"),
        "endereco_entrega": data.endereco_entrega or (original or {}).get("endereco_entrega", ""),
        "transportadora": data.transportadora, "previsao_entrega": data.previsao_entrega,
        "status": "pendente", "conferencia": None, "devolucao_cliente_id": devolucao_id,
        "tipo_expedicao": "reexpedicao_retrabalho", "idempotency_key_origem": data.idempotency_key,
        "items": [{
            "produto_nome": devolucao.get("produto_nome", ""), "sku": devolucao.get("sku", ""),
            "quantidade": float(devolucao.get("quantidade") or 0), "unidade": devolucao.get("unidade", "un"),
            "lote": devolucao.get("lote", ""), "estoque_item_id": devolucao.get("estoque_item_id"),
            "saldo_lote_id": devolucao.get("saldo_lote_id"), "lote_id": devolucao.get("lote_id"),
            "volumes": 1, "peso_unitario": 0,
        }],
        "observacoes": data.observacoes or f"Reexpedicao da devolucao {devolucao_id}",
        "historico": [{"de": None, "para": "pendente", "por": user.get("name", ""), "em": now}],
        "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
    }
    await db.expedicao_ordens.insert_one(exp)
    await db.devolucoes_cliente.update_one(
        {"id": devolucao_id, "tenant_id": tid},
        {"$set": {"status": "aguardando_reexpedicao", "reexpedicao_id": exp_id,
                  "reexpedicao_numero": exp["numero_exp"], "updated_at": now}},
    )
    exp.pop("_id", None)
    return exp


@retrabalho_router.delete("/ordens/{rt_id}")
async def delete_blocked(rt_id: str):
    raise HTTPException(status_code=405, detail="Exclusão de Ordens de Retrabalho não é permitida. Cancele a ordem.")


@retrabalho_router.get("/metricas")
async def retrabalho_metricas(request: Request):
    """RN-RT-02: Métricas separadas por categoria RT-1/RT-2/RT-3."""
    user = await get_current_user(request)
    tid = user["tenant_id"]

    result = {}
    for cat in RT_CATEGORIAS:
        agg = await db.retrabalho_ordens.aggregate([
            {"$match": {"tenant_id": tid, "categoria": cat}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "custo": {"$sum": "$custo_estimado"},
            }},
        ]).to_list(20)

        status_counts = {a["_id"]: a["count"] for a in agg}
        custo_total = sum(a["custo"] for a in agg)
        result[cat] = {
            "total": sum(a["count"] for a in agg),
            "em_aberto": sum(status_counts.get(status, 0) for status in ("pendente", "em_retrabalho", "aguardando_cq")),
            "pendente": status_counts.get("pendente", 0),
            "em_retrabalho": status_counts.get("em_retrabalho", 0),
            "aguardando_cq": status_counts.get("aguardando_cq", 0),
            "liberado": status_counts.get("liberado", 0),
            "reprovado_cq": status_counts.get("reprovado_cq", 0),
            "reexpedido": status_counts.get("reexpedido", 0),
            "custo_total": round(custo_total, 2),
        }
    return result


@retrabalho_router.get("/dashboard")
async def retrabalho_dashboard(request: Request):
    """Summary counts for CQ Dashboard integration."""
    user = await get_current_user(request)
    tid = user["tenant_id"]
    pendente = await db.retrabalho_ordens.count_documents({"tenant_id": tid, "status": "pendente"})
    em_retrabalho = await db.retrabalho_ordens.count_documents({"tenant_id": tid, "status": "em_retrabalho"})
    aguardando_cq = await db.retrabalho_ordens.count_documents({"tenant_id": tid, "status": "aguardando_cq"})
    liberado = await db.retrabalho_ordens.count_documents({"tenant_id": tid, "status": "liberado"})
    reprovado_cq = await db.retrabalho_ordens.count_documents({"tenant_id": tid, "status": "reprovado_cq"})
    reexpedido = await db.retrabalho_ordens.count_documents({"tenant_id": tid, "status": "reexpedido"})

    agg = await db.retrabalho_ordens.aggregate([
        {"$match": {"tenant_id": tid}},
        {"$group": {"_id": None, "custo_total": {"$sum": "$custo_estimado"}}},
    ]).to_list(1)
    custo_total = round(agg[0]["custo_total"] if agg else 0.0, 2)

    return {
        "pendente": pendente,
        "em_retrabalho": em_retrabalho,
        "aguardando_cq": aguardando_cq,
        "liberado": liberado,
        "reprovado_cq": reprovado_cq,
        "reexpedido": reexpedido,
        "total_ativos": pendente + em_retrabalho + aguardando_cq,
        "custo_total": custo_total,
    }
