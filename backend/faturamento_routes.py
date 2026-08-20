"""
Faturamento — emissão e controle de Notas Fiscais de saída.
Fluxo:
  1. PI concluído ou EXP expedida → criar NF (rascunho)
  2. Emitir NF → status emitida (número NF-e + chave de acesso registrados)
  3. Gerar Duplicatas → Contas a Receber com parcelas por condição de pagamento
  4. Acompanhar pagamento das duplicatas: aberta → paga | vencida | protestada
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import re
from datetime import datetime, timedelta, date

logger = logging.getLogger(__name__)

faturamento_router = APIRouter(prefix="/api/faturamento")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_faturamento(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def _new_id():
    return new_id_func()


def _now():
    return now_iso_func()


NF_STATUSES = ["rascunho", "emitida", "cancelada"]
PGTO_STATUSES = ["aguardando", "pago_parcial", "pago", "vencido"]
DUP_STATUSES = ["aberta", "paga", "vencida", "protestada", "cancelada"]

NF_TRANSITIONS = {
    "rascunho": ["emitida", "cancelada"],
    "emitida":  ["cancelada"],
    "cancelada": [],
}


# ===== HELPERS =====

def _parse_parcelas(condicao: str, valor_total: float, data_emissao: Optional[str]) -> list:
    """
    Parse a payment condition string and return list of (due_date_str, valor) tuples.
    Examples: "à vista" → 1x; "30/60/90" → 3x; "30 dias" → 1x in 30d; "2x 30/60" → 2x
    """
    cond = (condicao or "").strip().lower()
    try:
        base = datetime.fromisoformat(data_emissao) if data_emissao else datetime.now()
    except Exception:
        base = datetime.now()

    if not cond or cond in ("à vista", "a vista", "avista", "0"):
        return [(base.date().isoformat(), round(valor_total, 2))]

    numbers = [int(x) for x in re.findall(r'\d+', cond) if 1 <= int(x) <= 360]
    if not numbers:
        return [(base.date().isoformat(), round(valor_total, 2))]

    n = len(numbers)
    base_parcel = round(valor_total / n, 2)
    result = []
    for i, days in enumerate(numbers):
        due = (base + timedelta(days=days)).date().isoformat()
        valor = base_parcel if i < n - 1 else round(valor_total - base_parcel * (n - 1), 2)
        result.append((due, valor))
    return result


async def _auto_mark_vencidas(tid: str):
    today = date.today().isoformat()
    await db.faturamento_duplicatas.update_many(
        {"tenant_id": tid, "status": "aberta", "data_vencimento": {"$lt": today}},
        {"$set": {"status": "vencida", "updated_at": _now()}}
    )


async def _assert_expedicao_pronta_para_nf(tid: str, exp_id: Optional[str]) -> Optional[dict]:
    if not exp_id:
        return None

    exp = await db.expedicao_ordens.find_one({"id": exp_id, "tenant_id": tid}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="Ordem de Expedicao nao encontrada para faturamento")
    if exp.get("status") not in {"expedido", "entregue"}:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "hard_stop_nf_expedicao_nao_liberada",
                "message": f"NF so pode ser gerada para EXP expedida ou entregue. Status atual: {exp.get('status')}",
            },
        )

    for item in exp.get("items", []):
        eid = item.get("estoque_item_id")
        if not eid:
            continue
        est = await db.estoque_items.find_one({"id": eid, "tenant_id": tid}, {"_id": 0})
        if not est:
            raise HTTPException(status_code=404, detail=f"Item de estoque nao encontrado para NF: {eid}")
        posicao_cq = est.get("posicao_cq") or est.get("cq_status") or "livre"
        if posicao_cq in {"quarentena", "reprovado"}:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "hard_stop_nf_item_sem_liberacao_cq",
                    "message": f"Item '{item.get('produto_nome', eid)}' esta em {posicao_cq}. Faturamento bloqueado.",
                },
            )
    return exp


# ===== NF MODELS =====
class NFCreate(BaseModel):
    order_id: Optional[str] = None
    order_numero: Optional[str] = None
    exp_id: Optional[str] = None
    exp_numero: Optional[str] = None
    cliente_nome: str
    cliente_id: Optional[str] = None
    cliente_cnpj: str = ""
    valor_produtos: float = 0.0
    valor_frete: float = 0.0
    valor_impostos: float = 0.0
    valor_total: float = 0.0
    forma_pagamento: str = ""
    condicao_pagamento: str = ""
    data_emissao: Optional[str] = None
    data_vencimento: Optional[str] = None
    observacoes: str = ""


class NFUpdate(BaseModel):
    status: Optional[str] = None
    numero_nfe: Optional[str] = None
    chave_acesso: Optional[str] = None
    valor_total: Optional[float] = None
    valor_frete: Optional[float] = None
    valor_impostos: Optional[float] = None
    forma_pagamento: Optional[str] = None
    condicao_pagamento: Optional[str] = None
    data_vencimento: Optional[str] = None
    status_pagamento: Optional[str] = None
    valor_pago: Optional[float] = None
    data_pagamento: Optional[str] = None
    observacoes: Optional[str] = None


# ===== DUPLICATA MODELS =====
class DuplicataCreate(BaseModel):
    nf_id: str
    nf_numero: Optional[str] = None
    cliente_nome: str
    cliente_cnpj: str = ""
    cliente_id: Optional[str] = None
    numero_parcela: int = 1
    total_parcelas: int = 1
    valor: float
    data_emissao: Optional[str] = None
    data_vencimento: str
    forma_pagamento: str = ""
    observacoes: str = ""


class DuplicataUpdate(BaseModel):
    status: Optional[str] = None
    valor_pago: Optional[float] = None
    data_pagamento: Optional[str] = None
    forma_pagamento: Optional[str] = None
    data_protesto: Optional[str] = None
    observacoes: Optional[str] = None


# ===== NF SEQUENCE =====
async def _next_nf_interno(tenant_id: str) -> str:
    count = await db.faturamento_notas.count_documents({"tenant_id": tenant_id})
    return f"NF-{str(count + 1).zfill(6)}"


# ===== NF ROUTES =====
@faturamento_router.get("/notas")
async def list_notas(
    request: Request,
    status: Optional[str] = None,
    status_pagamento: Optional[str] = None,
    q: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if status_pagamento:
        query["status_pagamento"] = status_pagamento
    if q:
        query["$or"] = [
            {"numero_interno": {"$regex": q, "$options": "i"}},
            {"numero_nfe": {"$regex": q, "$options": "i"}},
            {"cliente_nome": {"$regex": q, "$options": "i"}},
            {"order_numero": {"$regex": q, "$options": "i"}},
        ]
    notas = await db.faturamento_notas.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return notas


@faturamento_router.get("/notas/{nf_id}")
async def get_nota(nf_id: str, request: Request):
    user = await get_current_user(request)
    nf = await db.faturamento_notas.find_one({"id": nf_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not nf:
        raise HTTPException(status_code=404, detail="Nota Fiscal não encontrada")
    return nf


@faturamento_router.post("/notas")
async def create_nota(data: NFCreate, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]

    if not data.cliente_nome.strip():
        raise HTTPException(status_code=400, detail="Nome do cliente obrigatório")

    numero_interno = await _next_nf_interno(tid)
    now = _now()
    nf_id = _new_id()

    pi_ref = {}
    if data.order_id:
        pi = await db.orders.find_one({"id": data.order_id, "tenant_id": tid}, {"_id": 0})
        if pi:
            pi_ref["order_numero"] = pi.get("numero_pedido", data.order_numero or "")
            if not data.valor_total and pi.get("total_pedido"):
                data.valor_total = float(pi["total_pedido"])
                data.valor_produtos = data.valor_total

    exp_ref = await _assert_expedicao_pronta_para_nf(tid, data.exp_id)

    valor_total = data.valor_total or (data.valor_produtos + data.valor_frete + data.valor_impostos)

    nf = {
        "id": nf_id,
        "tenant_id": tid,
        "numero_interno": numero_interno,
        "numero_nfe": None,
        "chave_acesso": None,
        "order_id": data.order_id,
        "order_numero": pi_ref.get("order_numero") or data.order_numero,
        "exp_id": data.exp_id,
        "exp_numero": (exp_ref or {}).get("numero_exp") or data.exp_numero,
        "cliente_nome": data.cliente_nome.strip(),
        "cliente_id": data.cliente_id,
        "cliente_cnpj": data.cliente_cnpj,
        "valor_produtos": data.valor_produtos,
        "valor_frete": data.valor_frete,
        "valor_impostos": data.valor_impostos,
        "valor_total": valor_total,
        "forma_pagamento": data.forma_pagamento,
        "condicao_pagamento": data.condicao_pagamento,
        "data_emissao": data.data_emissao or now[:10],
        "data_vencimento": data.data_vencimento,
        "status": "rascunho",
        "status_pagamento": "aguardando",
        "valor_pago": 0.0,
        "data_pagamento": None,
        "duplicatas_geradas": False,
        "total_parcelas": 0,
        "observacoes": data.observacoes,
        "historico": [{"de": None, "para": "rascunho", "por": user["name"], "em": now}],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.faturamento_notas.insert_one(nf)
    nf.pop("_id", None)

    if data.order_id:
        await db.orders.update_one(
            {"id": data.order_id, "tenant_id": tid},
            {"$set": {"nf_id": nf_id, "nf_numero": numero_interno, "updated_at": now}}
        )

    logger.info(f"NF {numero_interno} criada por {user['name']}")
    return nf


@faturamento_router.put("/notas/{nf_id}")
async def update_nota(nf_id: str, data: NFUpdate, request: Request):
    user = await get_current_user(request)
    nf = await db.faturamento_notas.find_one({"id": nf_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not nf:
        raise HTTPException(status_code=404, detail="NF não encontrada")

    now = _now()
    updates: Dict[str, Any] = {"updated_at": now}
    historico = list(nf.get("historico", []))
    payload = data.model_dump(exclude_unset=True)

    if "status" in payload:
        novo_status = payload["status"]
        if novo_status not in NF_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status inválido: {novo_status}")
        allowed = NF_TRANSITIONS.get(nf["status"], [])
        if novo_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Transição {nf['status']} → {novo_status} não permitida"
            )
        if novo_status == "emitida":
            await _assert_expedicao_pronta_para_nf(user["tenant_id"], nf.get("exp_id"))
        historico.append({"de": nf["status"], "para": novo_status, "por": user["name"], "em": now})
        updates["status"] = novo_status
        updates["historico"] = historico

    if "status_pagamento" in payload:
        sp = payload["status_pagamento"]
        if sp not in PGTO_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status de pagamento inválido: {sp}")
        updates["status_pagamento"] = sp

    for field in ("numero_nfe", "chave_acesso", "valor_total", "valor_frete", "valor_impostos",
                  "forma_pagamento", "condicao_pagamento", "data_vencimento",
                  "valor_pago", "data_pagamento", "observacoes"):
        if field in payload and payload[field] is not None:
            updates[field] = payload[field]

    await db.faturamento_notas.update_one({"id": nf_id}, {"$set": updates})
    return await db.faturamento_notas.find_one({"id": nf_id}, {"_id": 0})


@faturamento_router.delete("/notas/{nf_id}")
async def delete_blocked(nf_id: str):
    raise HTTPException(status_code=405, detail="Exclusão de NF não é permitida. Cancele a nota.")


@faturamento_router.post("/notas/{nf_id}/gerar-duplicatas")
async def gerar_duplicatas(nf_id: str, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]

    nf = await db.faturamento_notas.find_one({"id": nf_id, "tenant_id": tid}, {"_id": 0})
    if not nf:
        raise HTTPException(status_code=404, detail="NF não encontrada")
    if nf["status"] != "emitida":
        raise HTTPException(status_code=422, detail="Duplicatas só podem ser geradas para NFs emitidas")

    # Remove existing open/vencida duplicatas (allow re-generation)
    await db.faturamento_duplicatas.delete_many(
        {"nf_id": nf_id, "tenant_id": tid, "status": {"$in": ["aberta", "vencida"]}}
    )

    parcelas = _parse_parcelas(
        nf.get("condicao_pagamento", ""),
        nf.get("valor_total", 0),
        nf.get("data_emissao"),
    )

    now = _now()
    nf_num = nf.get("numero_nfe") or nf.get("numero_interno")
    total_p = len(parcelas)
    dups = []

    for i, (due_date, valor) in enumerate(parcelas):
        dup = {
            "id": _new_id(),
            "tenant_id": tid,
            "nf_id": nf_id,
            "nf_numero": nf_num,
            "order_id": nf.get("order_id"),
            "order_numero": nf.get("order_numero"),
            "cliente_nome": nf["cliente_nome"],
            "cliente_cnpj": nf.get("cliente_cnpj", ""),
            "cliente_id": nf.get("cliente_id"),
            "numero_parcela": i + 1,
            "total_parcelas": total_p,
            "label": f"{i + 1}/{total_p}",
            "valor": valor,
            "valor_pago": 0.0,
            "data_emissao": nf.get("data_emissao"),
            "data_vencimento": due_date,
            "status": "aberta",
            "forma_pagamento": nf.get("forma_pagamento", ""),
            "data_pagamento": None,
            "data_protesto": None,
            "observacoes": "",
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        dups.append(dup)

    if dups:
        await db.faturamento_duplicatas.insert_many([{**d} for d in dups])
        for d in dups:
            d.pop("_id", None)

    await db.faturamento_notas.update_one(
        {"id": nf_id, "tenant_id": tid},
        {"$set": {"duplicatas_geradas": True, "total_parcelas": total_p, "updated_at": now}}
    )

    logger.info(f"NF {nf_num}: {total_p} duplicata(s) gerada(s) por {user['name']}")
    return dups


# ===== DUPLICATA ROUTES =====

@faturamento_router.get("/duplicatas/dashboard")
async def duplicatas_dashboard(request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    await _auto_mark_vencidas(tid)

    today = date.today().isoformat()
    in_30 = (date.today() + timedelta(days=30)).isoformat()

    em_aberto = await db.faturamento_duplicatas.count_documents({"tenant_id": tid, "status": "aberta"})
    vencidas = await db.faturamento_duplicatas.count_documents({"tenant_id": tid, "status": "vencida"})
    a_vencer_30 = await db.faturamento_duplicatas.count_documents({
        "tenant_id": tid, "status": "aberta",
        "data_vencimento": {"$gte": today, "$lte": in_30}
    })

    pipe_aberto = [
        {"$match": {"tenant_id": tid, "status": {"$in": ["aberta", "vencida"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$valor"}}}
    ]
    agg_aberto = await db.faturamento_duplicatas.aggregate(pipe_aberto).to_list(1)

    pipe_venc = [
        {"$match": {"tenant_id": tid, "status": "vencida"}},
        {"$group": {"_id": None, "total": {"$sum": "$valor"}}}
    ]
    agg_venc = await db.faturamento_duplicatas.aggregate(pipe_venc).to_list(1)

    return {
        "em_aberto": em_aberto,
        "vencidas": vencidas,
        "a_vencer_30_dias": a_vencer_30,
        "total_em_aberto": round(agg_aberto[0]["total"] if agg_aberto else 0.0, 2),
        "total_vencido": round(agg_venc[0]["total"] if agg_venc else 0.0, 2),
    }


@faturamento_router.get("/duplicatas")
async def list_duplicatas(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
    venc_ate: Optional[str] = None,
):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    await _auto_mark_vencidas(tid)

    query: Dict[str, Any] = {"tenant_id": tid}
    if status and status != "all":
        query["status"] = status
    if q:
        query["$or"] = [
            {"nf_numero": {"$regex": q, "$options": "i"}},
            {"cliente_nome": {"$regex": q, "$options": "i"}},
            {"order_numero": {"$regex": q, "$options": "i"}},
        ]
    if venc_ate:
        query.setdefault("data_vencimento", {})
        query["data_vencimento"]["$lte"] = venc_ate

    dups = await db.faturamento_duplicatas.find(query, {"_id": 0}).sort("data_vencimento", 1).to_list(500)
    return dups


@faturamento_router.post("/duplicatas")
async def create_duplicata(data: DuplicataCreate, request: Request):
    user = await get_current_user(request)
    now = _now()
    dup = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "nf_id": data.nf_id,
        "nf_numero": data.nf_numero,
        "order_id": None,
        "order_numero": None,
        "cliente_nome": data.cliente_nome,
        "cliente_cnpj": data.cliente_cnpj,
        "cliente_id": data.cliente_id,
        "numero_parcela": data.numero_parcela,
        "total_parcelas": data.total_parcelas,
        "label": f"{data.numero_parcela}/{data.total_parcelas}",
        "valor": data.valor,
        "valor_pago": 0.0,
        "data_emissao": data.data_emissao or now[:10],
        "data_vencimento": data.data_vencimento,
        "status": "aberta",
        "forma_pagamento": data.forma_pagamento,
        "data_pagamento": None,
        "data_protesto": None,
        "observacoes": data.observacoes,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.faturamento_duplicatas.insert_one(dup)
    dup.pop("_id", None)
    return dup


@faturamento_router.put("/duplicatas/{dup_id}")
async def update_duplicata(dup_id: str, data: DuplicataUpdate, request: Request):
    user = await get_current_user(request)
    dup = await db.faturamento_duplicatas.find_one({"id": dup_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not dup:
        raise HTTPException(status_code=404, detail="Duplicata não encontrada")

    now = _now()
    payload = data.model_dump(exclude_unset=True)
    updates: Dict[str, Any] = {"updated_at": now}

    if "status" in payload:
        if payload["status"] not in DUP_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status inválido: {payload['status']}")
        updates["status"] = payload["status"]

    for field in ("valor_pago", "data_pagamento", "forma_pagamento", "data_protesto", "observacoes"):
        if field in payload and payload[field] is not None:
            updates[field] = payload[field]

    # Auto-resolve status based on valor_pago
    if "valor_pago" in updates:
        if updates["valor_pago"] >= dup["valor"]:
            updates["status"] = "paga"
            if "data_pagamento" not in updates:
                updates["data_pagamento"] = now[:10]

    await db.faturamento_duplicatas.update_one({"id": dup_id}, {"$set": updates})
    return await db.faturamento_duplicatas.find_one({"id": dup_id}, {"_id": 0})


# ===== DASHBOARD (NFs) =====
@faturamento_router.get("/dashboard")
async def faturamento_dashboard(request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    emitidas = await db.faturamento_notas.count_documents({"tenant_id": tid, "status": "emitida"})
    aguardando = await db.faturamento_notas.count_documents({"tenant_id": tid, "status_pagamento": "aguardando"})
    vencidas = await db.faturamento_notas.count_documents({"tenant_id": tid, "status_pagamento": "vencido"})
    pipeline = [
        {"$match": {"tenant_id": tid, "status": "emitida", "status_pagamento": {"$in": ["aguardando", "pago_parcial"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$valor_total"}, "pago": {"$sum": "$valor_pago"}}}
    ]
    agg = await db.faturamento_notas.aggregate(pipeline).to_list(1)
    total_ar = agg[0]["total"] if agg else 0.0
    total_pago = agg[0]["pago"] if agg else 0.0
    return {
        "emitidas": emitidas,
        "aguardando_pagamento": aguardando,
        "vencidas": vencidas,
        "total_a_receber": round(total_ar - total_pago, 2),
    }
