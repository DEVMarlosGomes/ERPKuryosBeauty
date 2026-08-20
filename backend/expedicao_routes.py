"""
Expedição — saída de produto acabado para o cliente.
Fluxo:
  1. PI (Pedido de Industrialização) concluído → criar Ordem de Expedição (EXP)
  2. Separação e embalagem → status preparando
  3. Despacho confirmado → status expedido → SAIDA_EXPEDICAO no WMS
  4. Entrega confirmada → status entregue
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from cq_routes import cq_verificar_liberacao_palete, cq_verificar_lote_aprovado

logger = logging.getLogger(__name__)

expedicao_router = APIRouter(prefix="/api/expedicao")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_expedicao(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def _new_id():
    return new_id_func()


def _now():
    return now_iso_func()


EXP_STATUSES = ["pendente", "preparando", "conferido", "expedido", "entregue", "cancelado"]

STATUS_TRANSITIONS = {
    "pendente":    ["preparando", "cancelado"],
    "preparando":  ["conferido", "cancelado"],
    "conferido":   ["expedido", "cancelado"],
    "expedido":    ["entregue"],
    "entregue":    [],
    "cancelado":   [],
}


async def _assert_liberado_para_expedicao(est: dict, item: dict, tenant_id: str):
    posicao_cq = est.get("posicao_cq") or est.get("cq_status") or "livre"
    if posicao_cq in {"quarentena", "reprovado"}:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "hard_stop_expedicao_sem_liberacao_cq",
                "message": f"Produto '{item.get('produto_nome', est.get('nome', est.get('id')))}' esta em {posicao_cq}. Expedicao bloqueada.",
            },
        )

    lote_id = est.get("cq_lote_id") or item.get("lote_id")
    if lote_id:
        await cq_verificar_lote_aprovado(db, tenant_id, lote_id)
        await cq_verificar_liberacao_palete(db, tenant_id, lote_id)


# ===== MODELS =====
class ExpItem(BaseModel):
    produto_nome: str
    sku: str = ""
    quantidade: float
    unidade: str = "un"
    lote: str = ""
    numero_serie: str = ""
    estoque_item_id: Optional[str] = None
    volumes: int = 1          # número de caixas/volumes deste item
    peso_unitario: float = 0  # kg por volume


class ExpCreate(BaseModel):
    order_id: Optional[str] = None
    order_numero: Optional[str] = None
    cliente_nome: str
    cliente_id: Optional[str] = None
    endereco_entrega: str = ""
    transportadora: str = ""
    previsao_entrega: Optional[str] = None
    numero_nf_saida: str = ""   # NF fiscal de saída
    items: List[ExpItem]
    observacoes: str = ""


class ExpUpdate(BaseModel):
    status: Optional[str] = None
    transportadora: Optional[str] = None
    endereco_entrega: Optional[str] = None
    previsao_entrega: Optional[str] = None
    data_expedicao: Optional[str] = None
    data_entrega: Optional[str] = None
    codigo_rastreio: Optional[str] = None
    numero_nf_saida: Optional[str] = None
    observacoes: Optional[str] = None


class ConferenciaItem(BaseModel):
    produto_nome: str
    quantidade_conferida: float
    lote_conferido: str = ""
    ok: bool = True
    divergencia: str = ""


class ConferenciaCreate(BaseModel):
    items: List[ConferenciaItem]
    conferente_nome: str = ""
    observacoes: str = ""


# ===== SEQUENCE =====
async def _next_exp_numero(tenant_id: str) -> str:
    count = await db.expedicao_ordens.count_documents({"tenant_id": tenant_id})
    return f"EXP-{str(count + 1).zfill(5)}"


# ===== ROUTES =====
@expedicao_router.get("/ordens")
async def list_ordens(
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
            {"numero_exp": {"$regex": q, "$options": "i"}},
            {"cliente_nome": {"$regex": q, "$options": "i"}},
            {"order_numero": {"$regex": q, "$options": "i"}},
        ]
    ordens = await db.expedicao_ordens.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return ordens


@expedicao_router.get("/ordens/{exp_id}")
async def get_ordem(exp_id: str, request: Request):
    user = await get_current_user(request)
    exp = await db.expedicao_ordens.find_one({"id": exp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="Ordem de Expedição não encontrada")
    return exp


@expedicao_router.post("/ordens")
async def create_ordem(data: ExpCreate, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]

    if not data.items:
        raise HTTPException(status_code=400, detail="Informe ao menos um item")
    if not data.cliente_nome.strip():
        raise HTTPException(status_code=400, detail="Nome do cliente obrigatório")

    numero_exp = await _next_exp_numero(tid)
    now = _now()
    exp_id = _new_id()

    # Enrich from PI if provided
    pi_ref = {}
    if data.order_id:
        pi = await db.orders.find_one({"id": data.order_id, "tenant_id": tid}, {"_id": 0})
        if pi:
            pi_ref = {
                "order_numero": pi.get("numero_pedido", data.order_numero or ""),
                "project_name": pi.get("project_name", ""),
            }

    exp = {
        "id": exp_id,
        "tenant_id": tid,
        "numero_exp": numero_exp,
        "order_id": data.order_id,
        "order_numero": pi_ref.get("order_numero") or data.order_numero,
        "project_name": pi_ref.get("project_name", ""),
        "cliente_nome": data.cliente_nome.strip(),
        "cliente_id": data.cliente_id,
        "endereco_entrega": data.endereco_entrega,
        "transportadora": data.transportadora,
        "previsao_entrega": data.previsao_entrega,
        "data_expedicao": None,
        "data_entrega": None,
        "codigo_rastreio": None,
        "numero_nf_saida": data.numero_nf_saida,
        "status": "pendente",
        "conferencia": None,
        "items": [i.model_dump() for i in data.items],
        "observacoes": data.observacoes,
        "historico": [{"de": None, "para": "pendente", "por": user["name"], "em": now}],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.expedicao_ordens.insert_one(exp)
    exp.pop("_id", None)

    # Update PI status if linked and still concluido
    if data.order_id:
        await db.orders.update_one(
            {"id": data.order_id, "tenant_id": tid},
            {"$set": {"exp_id": exp_id, "exp_numero": numero_exp, "updated_at": now}}
        )

    logger.info(f"EXP {numero_exp} criada por {user['name']}")
    return exp


@expedicao_router.put("/ordens/{exp_id}")
async def update_ordem(exp_id: str, data: ExpUpdate, request: Request):
    user = await get_current_user(request)
    exp = await db.expedicao_ordens.find_one({"id": exp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="EXP não encontrada")

    now = _now()
    updates: Dict[str, Any] = {"updated_at": now}
    historico = list(exp.get("historico", []))
    payload = data.model_dump(exclude_unset=True)

    if "status" in payload:
        novo_status = payload["status"]
        if novo_status not in EXP_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status inválido: {novo_status}")
        allowed = STATUS_TRANSITIONS.get(exp["status"], [])
        if novo_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Transição {exp['status']} → {novo_status} não permitida"
            )
        historico.append({"de": exp["status"], "para": novo_status, "por": user["name"], "em": now})
        updates["status"] = novo_status
        updates["historico"] = historico

        # When expedido: register WMS exit for each item with estoque_item_id
        if novo_status == "expedido":
            data_exp = payload.get("data_expedicao") or now[:10]
            updates["data_expedicao"] = data_exp
            for item in exp.get("items", []):
                eid = item.get("estoque_item_id")
                if not eid:
                    continue
                est = await db.estoque_items.find_one({"id": eid, "tenant_id": user["tenant_id"]}, {"_id": 0})
                if not est:
                    raise HTTPException(status_code=404, detail=f"Item de estoque nao encontrado para expedicao: {eid}")
                qty_antes = est.get("quantidade_atual", 0)
                qty_saida = float(item.get("quantidade", 0))
                if qty_saida > qty_antes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Saldo insuficiente para expedir {item.get('produto_nome', eid)}: atual={qty_antes}, saida={qty_saida}",
                    )
                await _assert_liberado_para_expedicao(est, item, user["tenant_id"])
                qty_depois = qty_antes - qty_saida
                await db.estoque_items.update_one(
                    {"id": eid},
                    {"$set": {"quantidade_atual": qty_depois, "updated_at": now}}
                )
                mov = {
                    "id": _new_id(),
                    "tenant_id": user["tenant_id"],
                    "item_id": eid,
                    "setor": est.get("setor", "FABRICA"),
                    "tipo_item": "produto_acabado",
                    "nome_item": item.get("produto_nome", ""),
                    "codigo_item": item.get("sku", ""),
                    "lote": item.get("lote", ""),
                    "tipo": "SAIDA_EXPEDICAO",
                    "direcao": "saida",
                    "quantidade": qty_saida,
                    "unidade": item.get("unidade", "un"),
                    "quantidade_antes": qty_antes,
                    "quantidade_depois": qty_depois,
                    "motivo": f"Expedição {exp['numero_exp']}",
                    "referencia": exp_id,
                    "documento": exp.get("numero_exp", ""),
                    "usuario": user["name"],
                    "usuario_id": user["id"],
                    "created_at": now,
                }
                await db.estoque_movimentos.insert_one(mov)

        if novo_status == "entregue":
            updates["data_entrega"] = payload.get("data_entrega") or now[:10]

    for field in ("transportadora", "endereco_entrega", "previsao_entrega",
                  "codigo_rastreio", "numero_nf_saida", "observacoes", "data_expedicao", "data_entrega"):
        if field in payload and payload[field] is not None:
            updates[field] = payload[field]

    await db.expedicao_ordens.update_one({"id": exp_id}, {"$set": updates})
    return await db.expedicao_ordens.find_one({"id": exp_id}, {"_id": 0})


@expedicao_router.post("/ordens/{exp_id}/conferir")
async def conferir_ordem(exp_id: str, data: ConferenciaCreate, request: Request):
    """Realiza a conferência física dos itens — prepara → conferido."""
    user = await get_current_user(request)
    tid = user["tenant_id"]
    exp = await db.expedicao_ordens.find_one({"id": exp_id, "tenant_id": tid}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="EXP não encontrada")
    if exp["status"] != "preparando":
        raise HTTPException(
            status_code=422,
            detail=f"Conferência só é possível quando status = 'preparando' (atual: {exp['status']})"
        )

    tem_divergencia = any(not item.ok for item in data.items)
    now = _now()
    historico = list(exp.get("historico", []))
    historico.append({"de": "preparando", "para": "conferido", "por": user["name"], "em": now,
                      "nota": "com divergências" if tem_divergencia else "OK"})

    conferencia_record = {
        "conferente_nome": data.conferente_nome or user["name"],
        "conferente_id": user["id"],
        "data_conferencia": now,
        "tem_divergencia": tem_divergencia,
        "observacoes": data.observacoes,
        "items": [i.model_dump() for i in data.items],
    }

    await db.expedicao_ordens.update_one({"id": exp_id}, {"$set": {
        "status": "conferido",
        "conferencia": conferencia_record,
        "historico": historico,
        "updated_at": now,
    }})
    return await db.expedicao_ordens.find_one({"id": exp_id}, {"_id": 0})


@expedicao_router.get("/ordens/{exp_id}/romaneio")
async def romaneio(exp_id: str, request: Request):
    """Retorna dados estruturados para impressão do romaneio / packing list."""
    user = await get_current_user(request)
    exp = await db.expedicao_ordens.find_one({"id": exp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="EXP não encontrada")

    items = exp.get("items", [])
    total_volumes = sum(int(i.get("volumes", 1)) for i in items)
    peso_total = sum(
        float(i.get("volumes", 1)) * float(i.get("peso_unitario", 0))
        for i in items
    )

    return {
        "numero_exp": exp["numero_exp"],
        "numero_nf_saida": exp.get("numero_nf_saida", ""),
        "cliente_nome": exp["cliente_nome"],
        "endereco_entrega": exp.get("endereco_entrega", ""),
        "transportadora": exp.get("transportadora", ""),
        "previsao_entrega": exp.get("previsao_entrega"),
        "data_expedicao": exp.get("data_expedicao"),
        "codigo_rastreio": exp.get("codigo_rastreio", ""),
        "status": exp["status"],
        "items": [
            {
                "produto_nome": i.get("produto_nome", ""),
                "sku": i.get("sku", ""),
                "lote": i.get("lote", ""),
                "quantidade": i.get("quantidade", 0),
                "unidade": i.get("unidade", "un"),
                "volumes": i.get("volumes", 1),
                "peso_unitario": i.get("peso_unitario", 0),
                "peso_total_item": float(i.get("volumes", 1)) * float(i.get("peso_unitario", 0)),
            }
            for i in items
        ],
        "totais": {
            "total_itens": len(items),
            "total_volumes": total_volumes,
            "peso_total_kg": round(peso_total, 3),
        },
        "conferencia": exp.get("conferencia"),
        "order_numero": exp.get("order_numero", ""),
        "observacoes": exp.get("observacoes", ""),
    }


@expedicao_router.delete("/ordens/{exp_id}")
async def delete_blocked(exp_id: str):
    raise HTTPException(status_code=405, detail="Exclusão de Ordens de Expedição não é permitida. Cancele a ordem.")


@expedicao_router.get("/dashboard")
async def expedicao_dashboard(request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    pendente = await db.expedicao_ordens.count_documents({"tenant_id": tid, "status": "pendente"})
    preparando = await db.expedicao_ordens.count_documents({"tenant_id": tid, "status": "preparando"})
    conferido = await db.expedicao_ordens.count_documents({"tenant_id": tid, "status": "conferido"})
    expedido = await db.expedicao_ordens.count_documents({"tenant_id": tid, "status": "expedido"})
    return {
        "pendente": pendente,
        "preparando": preparando,
        "conferido": conferido,
        "expedido": expedido,
        "total_ativos": pendente + preparando + conferido + expedido,
    }
