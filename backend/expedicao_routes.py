"""
Expedição — saída de produto acabado para o cliente.
Fluxo:
  1. PI (Pedido de Industrialização) concluído → criar Ordem de Expedição (EXP)
  2. Separação e embalagem → status preparando
  3. Despacho confirmado → status expedido → SAIDA_EXPEDICAO no WMS
  4. Entrega confirmada → status entregue
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from cq_routes import cq_verificar_liberacao_palete, cq_verificar_lote_aprovado
from stock_ledger import baixar_saldo_lote_expedicao, estornar_saida_expedicao
from rbac import SHIPPING_WRITE_ROLES, require_roles

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


async def _enforce_expedicao_write_rbac(request: Request):
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        require_roles(await get_current_user(request), SHIPPING_WRITE_ROLES)


expedicao_router.dependencies.append(Depends(_enforce_expedicao_write_rbac))


def _new_id():
    return new_id_func()


def _now():
    return now_iso_func()


EXP_STATUSES = ["pendente", "preparando", "conferido", "expedido", "entregue", "cancelado"]
COMMERCIAL_PARTIAL_FULFILLMENT_FLAG = "commercial_partial_fulfillment_v2"

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


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _feature_enabled(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


async def _commercial_feature_enabled(tenant_id: str, flag: str) -> bool:
    if not hasattr(db, "tenant_settings"):
        return False
    settings = await db.tenant_settings.find_one({"tenant_id": tenant_id}, {"_id": 0})
    return _feature_enabled(((settings or {}).get("features") or {}).get(flag))


async def _require_commercial_feature(tenant_id: str, flag: str) -> None:
    if await _commercial_feature_enabled(tenant_id, flag):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "message": "Funcionalidade comercial em rollout controlado.",
            "feature": flag,
        },
    )


def _ensure_order_item_ids(items: List[Dict[str, Any]]) -> bool:
    changed = False
    used = {str(item.get("id")) for item in items if item.get("id")}
    for idx, item in enumerate(items):
        if item.get("id"):
            continue
        candidate = f"item-{idx + 1}"
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"item-{idx + 1}-{suffix}"
        item["id"] = candidate
        used.add(candidate)
        changed = True
    return changed


async def _order_with_item_ids(order: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    items = [dict(item) for item in (order.get("items") or [])]
    if _ensure_order_item_ids(items):
        await db.orders.update_one(
            {"id": order["id"], "tenant_id": tenant_id},
            {"$set": {"items": items, "updated_at": _now()}},
        )
        order = dict(order)
        order["items"] = items
    return order


def _order_item_identity(item: Dict[str, Any]) -> str:
    return str(item.get("id") or item.get("order_item_id") or item.get("sales_order_item_id") or "").strip()


def _match_order_item_id(exp_item: Dict[str, Any], order_items: List[Dict[str, Any]]) -> Optional[str]:
    explicit = _order_item_identity(exp_item)
    if explicit:
        return explicit
    exp_sku = str(exp_item.get("sku") or exp_item.get("codigo_kuryos") or "").strip().lower()
    exp_name = str(exp_item.get("produto_nome") or exp_item.get("item") or "").strip().lower()
    for item in order_items:
        sku = str(item.get("codigo_kuryos") or item.get("sku") or "").strip().lower()
        name = str(item.get("item") or item.get("produto_nome") or item.get("descricao") or "").strip().lower()
        if exp_sku and sku and exp_sku == sku:
            return _order_item_identity(item)
        if exp_name and name and exp_name == name:
            return _order_item_identity(item)
    return None


async def _produced_by_order_item(tenant_id: str, order_id: str) -> Dict[str, float]:
    produced: Dict[str, float] = {}
    if not hasattr(db, "ops"):
        return produced
    ops = await db.ops.find(
        {"tenant_id": tenant_id, "pedido_id": order_id, "status": {"$nin": ["cancelada", "cancelado"]}},
        {"_id": 0},
    ).to_list(5000)
    for op in ops:
        op_order_item_id = str(op.get("sales_order_item_id") or "").strip()
        for idx, item in enumerate(op.get("items") or []):
            item_id = str(item.get("order_item_id") or op_order_item_id or "").strip()
            if not item_id:
                item_id = f"item-{idx + 1}"
            produced[item_id] = round(produced.get(item_id, 0.0) + _as_float(item.get("qtd_produzida")), 6)
    return produced


async def _expedition_quantities_by_order_item(
    tenant_id: str,
    order_id: str,
    exclude_exp_id: str = "",
) -> Dict[str, Dict[str, float]]:
    totals: Dict[str, Dict[str, float]] = {}
    if not hasattr(db, "expedicao_ordens"):
        return totals
    exps = await db.expedicao_ordens.find(
        {"tenant_id": tenant_id, "order_id": order_id, "status": {"$ne": "cancelado"}},
        {"_id": 0},
    ).to_list(5000)
    for exp in exps:
        if exclude_exp_id and exp.get("id") == exclude_exp_id:
            continue
        confirmed = exp.get("status") in {"expedido", "entregue"}
        for item in exp.get("items") or []:
            item_id = _order_item_identity(item)
            if not item_id:
                continue
            bucket = totals.setdefault(item_id, {"planejada": 0.0, "expedida": 0.0})
            qty = _as_float(item.get("quantidade"))
            bucket["planejada"] = round(bucket["planejada"] + qty, 6)
            if confirmed:
                bucket["expedida"] = round(bucket["expedida"] + qty, 6)
    return totals


async def _order_fiscal_snapshot(tenant_id: str, order: Dict[str, Any]) -> Dict[str, Any]:
    notas = []
    if hasattr(db, "faturamento_notas"):
        notas = await db.faturamento_notas.find(
            {"tenant_id": tenant_id, "order_id": order.get("id"), "status": {"$ne": "cancelada"}},
            {"_id": 0},
        ).to_list(1000)
    valor_nf = round(sum(_as_float(nf.get("valor_produtos") or nf.get("valor_total")) for nf in notas), 2)
    total_pedido = _as_float(order.get("total_pedido"))
    frete = order.get("frete") or {}
    aditivos = order.get("aditivos") or order.get("addenda") or []
    cancelamentos = order.get("cancelamentos") or []
    historico = order.get("historico") or []
    cancel_hist = [h for h in historico if h.get("para") == "cancelado" or h.get("status") == "cancelado"]
    return {
        "percentual_nf": round(min((valor_nf / total_pedido) * 100, 100), 3) if total_pedido > 0 else 0.0,
        "valor_nf_produtos": valor_nf,
        "valor_pedido": round(total_pedido, 2),
        "nf_count": len(notas),
        "nf_ids": [nf.get("id") for nf in notas if nf.get("id")],
        "frete_tipo": str(frete.get("tipo") or "").upper(),
        "frete_cif_fob": str(frete.get("tipo") or "").upper() if str(frete.get("tipo") or "").upper() in {"CIF", "FOB"} else "",
        "frete_snapshot": frete,
        "aditivos_count": len(aditivos),
        "aditivos": aditivos,
        "cancelamentos_count": len(cancelamentos) + len(cancel_hist),
        "pedido_cancelado": order.get("status") == "cancelado",
        "status_pedido": order.get("status"),
    }


async def _build_delivery_balance(order: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    order = await _order_with_item_ids(order, tenant_id)
    produced = await _produced_by_order_item(tenant_id, order["id"])
    shipped = await _expedition_quantities_by_order_item(tenant_id, order["id"])
    rows = []
    for item in order.get("items") or []:
        item_id = _order_item_identity(item)
        qtd_pedido = _as_float(item.get("qtd") or item.get("quantidade"))
        qtd_produzida = produced.get(item_id, _as_float(item.get("qtd_produzida")))
        planned = (shipped.get(item_id) or {}).get("planejada", 0.0)
        confirmed = (shipped.get(item_id) or {}).get("expedida", 0.0)
        rows.append({
            "order_item_id": item_id,
            "sku_id": item.get("sku_id"),
            "codigo_kuryos": item.get("codigo_kuryos") or item.get("sku") or "",
            "item": item.get("item") or item.get("produto_nome") or "",
            "qtd_pedido": qtd_pedido,
            "qtd_produzida": round(qtd_produzida, 6),
            "qtd_expedicao_planejada": round(planned, 6),
            "qtd_expedida": round(confirmed, 6),
            "saldo_produzido_disponivel": round(max(qtd_produzida - planned, 0.0), 6),
            "saldo_pedido_a_expedir": round(max(qtd_pedido - confirmed, 0.0), 6),
            "percentual_produzido": round(min((qtd_produzida / qtd_pedido) * 100, 100), 3) if qtd_pedido > 0 else 0.0,
            "percentual_expedido": round(min((confirmed / qtd_pedido) * 100, 100), 3) if qtd_pedido > 0 else 0.0,
        })
    total_pedido = sum(row["qtd_pedido"] for row in rows)
    total_produzido = sum(row["qtd_produzida"] for row in rows)
    total_expedido = sum(row["qtd_expedida"] for row in rows)
    return {
        "order_id": order["id"],
        "order_numero": order.get("numero_pedido"),
        "items": rows,
        "summary": {
            "total_pedido": round(total_pedido, 6),
            "total_produzido": round(total_produzido, 6),
            "total_expedido": round(total_expedido, 6),
            "percentual_produzido": round(min((total_produzido / total_pedido) * 100, 100), 3) if total_pedido > 0 else 0.0,
            "percentual_expedido": round(min((total_expedido / total_pedido) * 100, 100), 3) if total_pedido > 0 else 0.0,
        },
        "operational_snapshot": await _order_fiscal_snapshot(tenant_id, order),
        "snapshot_at": _now(),
    }


async def _enrich_exp_with_delivery_snapshot(exp: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    if not exp.get("order_id") or not await _commercial_feature_enabled(tenant_id, COMMERCIAL_PARTIAL_FULFILLMENT_FLAG):
        return exp
    order = await db.orders.find_one({"id": exp["order_id"], "tenant_id": tenant_id}, {"_id": 0})
    if not order:
        return exp
    exp = dict(exp)
    exp["delivery_snapshot"] = await _build_delivery_balance(order, tenant_id)
    return exp


async def _apply_partial_delivery_controls(exp: Dict[str, Any], order: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    balance = await _build_delivery_balance(order, tenant_id)
    balance_by_item = {row["order_item_id"]: row for row in balance["items"]}
    order_items = (await _order_with_item_ids(order, tenant_id)).get("items") or []
    enriched_items = []
    requested_by_item: Dict[str, float] = {}
    for item in exp.get("items") or []:
        item_doc = dict(item)
        order_item_id = _match_order_item_id(item_doc, order_items)
        if not order_item_id:
            raise HTTPException(status_code=422, detail=f"Item de expedicao sem vinculo com item do pedido: {item_doc.get('produto_nome') or item_doc.get('sku')}")
        row = balance_by_item.get(order_item_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Item do pedido nao encontrado no saldo: {order_item_id}")
        requested = _as_float(item_doc.get("quantidade"))
        requested_by_item[order_item_id] = round(requested_by_item.get(order_item_id, 0.0) + requested, 6)
        available = min(row["saldo_produzido_disponivel"], row["saldo_pedido_a_expedir"])
        if requested_by_item[order_item_id] > available:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Entrega parcial excede saldo produzido disponivel do item.",
                    "order_item_id": order_item_id,
                    "requested": requested_by_item[order_item_id],
                    "available": available,
                    "qtd_produzida": row["qtd_produzida"],
                    "qtd_expedicao_planejada": row["qtd_expedicao_planejada"],
                    "saldo_pedido_a_expedir": row["saldo_pedido_a_expedir"],
                },
            )
        item_doc.update({
            "order_item_id": order_item_id,
            "partial_delivery_v2": True,
            "qtd_pedido_snapshot": row["qtd_pedido"],
            "qtd_produzida_snapshot": row["qtd_produzida"],
            "qtd_expedida_snapshot": row["qtd_expedida"],
            "saldo_produzido_disponivel_antes": row["saldo_produzido_disponivel"],
            "saldo_pedido_a_expedir_antes": row["saldo_pedido_a_expedir"],
        })
        enriched_items.append(item_doc)
    exp["items"] = enriched_items
    exp["delivery_snapshot"] = balance
    exp["operational_snapshot"] = balance["operational_snapshot"]
    exp["partial_delivery_v2"] = True
    return exp


# ===== MODELS =====
class ExpItem(BaseModel):
    order_item_id: Optional[str] = None
    produto_nome: str
    sku: str = ""
    quantidade: float
    unidade: str = "un"
    lote: str = ""
    numero_serie: str = ""
    estoque_item_id: Optional[str] = None
    saldo_lote_id: Optional[str] = None
    lote_id: Optional[str] = None
    palete_id: Optional[str] = None
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


class ExpOrderItemPartial(BaseModel):
    order_item_id: str
    quantidade: float
    lote: str = ""
    estoque_item_id: Optional[str] = None
    saldo_lote_id: Optional[str] = None
    lote_id: Optional[str] = None
    palete_id: Optional[str] = None
    volumes: int = 1
    peso_unitario: float = 0
    observacoes: str = ""


class ExpFromOrderItemsCreate(BaseModel):
    order_id: str
    endereco_entrega: str = ""
    transportadora: str = ""
    previsao_entrega: Optional[str] = None
    numero_nf_saida: str = ""
    items: List[ExpOrderItemPartial]
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
    idempotency_key: Optional[str] = None


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
    return await _enrich_exp_with_delivery_snapshot(exp, user["tenant_id"])


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


@expedicao_router.post("/ordens/from-order-items")
async def create_ordem_from_order_items(data: ExpFromOrderItemsCreate, request: Request):
    user = await get_current_user(request)
    tid = user["tenant_id"]
    await _require_commercial_feature(tid, COMMERCIAL_PARTIAL_FULFILLMENT_FLAG)

    if not data.items:
        raise HTTPException(status_code=400, detail="Informe ao menos um item do pedido para expedir")
    order = await db.orders.find_one({"id": data.order_id, "tenant_id": tid}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    if order.get("status") == "cancelado":
        raise HTTPException(status_code=422, detail="Pedido cancelado nao pode gerar expedicao parcial")

    order = await _order_with_item_ids(order, tid)
    order_items_by_id = {_order_item_identity(item): item for item in order.get("items") or []}
    exp_items = []
    for raw in data.items:
        qty = _as_float(raw.quantidade)
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Quantidade a expedir deve ser maior que zero")
        order_item = order_items_by_id.get(raw.order_item_id)
        if not order_item:
            raise HTTPException(status_code=404, detail=f"Item do pedido nao encontrado: {raw.order_item_id}")
        exp_items.append({
            "order_item_id": raw.order_item_id,
            "produto_nome": order_item.get("item") or order_item.get("produto_nome") or "",
            "sku": order_item.get("codigo_kuryos") or order_item.get("sku") or "",
            "quantidade": qty,
            "unidade": order_item.get("unidade") or "un",
            "lote": raw.lote,
            "numero_serie": "",
            "estoque_item_id": raw.estoque_item_id,
            "saldo_lote_id": raw.saldo_lote_id,
            "lote_id": raw.lote_id,
            "palete_id": raw.palete_id,
            "volumes": int(raw.volumes or 1),
            "peso_unitario": _as_float(raw.peso_unitario),
            "observacoes": raw.observacoes,
        })

    numero_exp = await _next_exp_numero(tid)
    now = _now()
    exp = {
        "id": _new_id(),
        "tenant_id": tid,
        "numero_exp": numero_exp,
        "order_id": order["id"],
        "order_numero": order.get("numero_pedido", ""),
        "project_name": order.get("project_name", ""),
        "cliente_nome": (order.get("cliente") or {}).get("razao_social") or (order.get("cliente") or {}).get("nome") or "",
        "cliente_id": order.get("cliente_id"),
        "endereco_entrega": data.endereco_entrega or (order.get("frete") or {}).get("endereco", ""),
        "transportadora": data.transportadora,
        "previsao_entrega": data.previsao_entrega,
        "data_expedicao": None,
        "data_entrega": None,
        "codigo_rastreio": None,
        "numero_nf_saida": data.numero_nf_saida,
        "status": "pendente",
        "conferencia": None,
        "items": exp_items,
        "observacoes": data.observacoes,
        "delivery_mode": "partial_order_items",
        "historico": [{"de": None, "para": "pendente", "por": user["name"], "em": now, "nota": "EXP parcial por item de pedido"}],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    exp = await _apply_partial_delivery_controls(exp, order, tid)
    await db.expedicao_ordens.insert_one(exp)
    exp.pop("_id", None)

    expedicao_ids = list(order.get("expedicao_ids") or [])
    if exp["id"] not in expedicao_ids:
        expedicao_ids.append(exp["id"])
    order_update = {
        "partial_fulfillment_v2": True,
        "last_exp_id": exp["id"],
        "last_exp_numero": numero_exp,
        "expedicao_ids": expedicao_ids,
        "updated_at": now,
    }
    if not order.get("exp_id"):
        order_update["exp_id"] = exp["id"]
        order_update["exp_numero"] = numero_exp
    await db.orders.update_one({"id": order["id"], "tenant_id": tid}, {"$set": order_update})
    return exp


async def _resolver_saldo_exato_expedicao(item: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if item.get("saldo_lote_id"):
        query["id"] = item["saldo_lote_id"]
    else:
        if item.get("estoque_item_id"):
            query["item_id"] = item["estoque_item_id"]
        elif item.get("sku"):
            query["codigo_item"] = item["sku"]
        else:
            raise HTTPException(
                status_code=422,
                detail="Item da expedicao sem saldo_lote_id, estoque_item_id ou SKU para identificar o lote.",
            )
        if item.get("lote"):
            query["lote"] = item["lote"]
        elif item.get("lote_id"):
            query["$or"] = [{"lote_id": item["lote_id"]}, {"cq_lote_id": item["lote_id"]}]

    candidates = await db.estoque_saldos_lote.find(query, {"_id": 0}).to_list(3)
    candidates = [row for row in candidates if _as_float(row.get("quantidade", row.get("quantidade_atual"))) > 0]
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail={"error": "lote_expedicao_nao_encontrado", "message": f"Lote nao encontrado para {item.get('produto_nome', 'item')}."},
        )
    if len(candidates) != 1:
        raise HTTPException(
            status_code=409,
            detail={"error": "lote_expedicao_ambiguo", "message": "Selecione explicitamente saldo_lote_id/lote antes de expedir."},
        )
    return candidates[0]


async def _baixar_lotes_da_expedicao(
    exp: Dict[str, Any], user: Dict[str, Any], idempotency_key: str
) -> List[Dict[str, Any]]:
    tenant_id = user["tenant_id"]
    baixados: List[Dict[str, Any]] = []
    try:
        for idx, item in enumerate(exp.get("items") or []):
            quantidade = _as_float(item.get("quantidade"))
            if quantidade <= 0:
                raise HTTPException(status_code=422, detail=f"Quantidade invalida no item {idx + 1} da expedicao.")
            saldo = await _resolver_saldo_exato_expedicao(item, tenant_id)
            estoque_item = await db.estoque_items.find_one(
                {"id": saldo.get("item_id"), "tenant_id": tenant_id}, {"_id": 0}
            )
            if not estoque_item:
                raise HTTPException(status_code=404, detail=f"Item agregado nao encontrado para o lote {saldo.get('lote')}.")
            item_cq = dict(item)
            item_cq["lote_id"] = saldo.get("cq_lote_id") or saldo.get("lote_id")
            await _assert_liberado_para_expedicao(estoque_item, item_cq, tenant_id)
            event = await baixar_saldo_lote_expedicao(
                db, new_id_fn=_new_id, now_iso_fn=_now, tenant_id=tenant_id,
                saldo_lote_id=saldo["id"], quantidade=quantidade, expedicao_id=exp["id"],
                item_index=idx, idempotency_key=idempotency_key, usuario=user,
            )
            baixados.append({
                "item_index": idx, "saldo_lote_id": saldo["id"], "estoque_item_id": saldo.get("item_id"),
                "lote_id": saldo.get("cq_lote_id") or saldo.get("lote_id"), "lote": saldo.get("lote", ""),
                "quantidade": quantidade, "movimento_id": event.get("id"),
            })
        return baixados
    except Exception:
        for entry in reversed(baixados):
            await estornar_saida_expedicao(
                db, new_id_fn=_new_id, now_iso_fn=_now, tenant_id=tenant_id,
                saldo_lote_id=entry["saldo_lote_id"], quantidade=entry["quantidade"],
                expedicao_id=exp["id"], item_index=entry["item_index"], idempotency_key=idempotency_key,
                usuario=user, motivo="Compensacao de falha no despacho da expedicao",
            )
        raise


async def _finalizar_reexpedicao_devolucao(exp: Dict[str, Any], user: Dict[str, Any]) -> None:
    devolucao_id = exp.get("devolucao_cliente_id")
    if not devolucao_id:
        return
    tid = user["tenant_id"]
    now = _now()
    devolucao = await db.devolucoes_cliente.find_one(
        {"id": devolucao_id, "tenant_id": tid}, {"_id": 0}
    )
    if not devolucao:
        return
    await db.devolucoes_cliente.update_one(
        {"id": devolucao_id, "tenant_id": tid},
        {"$set": {"status": "reexpedido", "reexpedido_em": now,
                  "reexpedicao_id": exp["id"], "updated_at": now}},
    )
    if devolucao.get("rt_id"):
        await db.retrabalho_ordens.update_one(
            {"id": devolucao["rt_id"], "tenant_id": tid},
            {"$set": {"status": "reexpedido", "reexpedicao_id": exp["id"], "updated_at": now}},
        )
    nf = await db.faturamento_notas.find_one(
        {"tenant_id": tid, "devolucao_cliente_id": devolucao_id}, {"_id": 0}
    )
    if nf:
        return
    count = await db.faturamento_notas.count_documents({"tenant_id": tid})
    nf = {
        "id": _new_id(), "tenant_id": tid, "numero_interno": f"NF-{count + 1:06d}",
        "numero_nfe": None, "chave_acesso": None, "order_id": exp.get("order_id"),
        "order_numero": exp.get("order_numero"), "exp_id": exp["id"], "exp_numero": exp.get("numero_exp"),
        "cliente_nome": exp.get("cliente_nome", ""), "cliente_id": exp.get("cliente_id"),
        "cliente_cnpj": "", "valor_produtos": 0.0, "valor_frete": 0.0, "valor_impostos": 0.0,
        "valor_total": 0.0, "forma_pagamento": "", "condicao_pagamento": "",
        "data_emissao": now[:10], "data_vencimento": None, "status": "rascunho",
        "status_pagamento": "aguardando", "valor_pago": 0.0, "data_pagamento": None,
        "duplicatas_geradas": False, "total_parcelas": 0, "devolucao_cliente_id": devolucao_id,
        "tipo_nota": "reexpedicao_retrabalho", "observacoes": f"NF de reexpedicao da devolucao {devolucao_id}",
        "historico": [{"de": None, "para": "rascunho", "por": user.get("name", ""), "em": now}],
        "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
    }
    await db.faturamento_notas.insert_one(nf)
    await db.devolucoes_cliente.update_one(
        {"id": devolucao_id, "tenant_id": tid},
        {"$set": {"nf_reexpedicao_id": nf["id"], "nf_reexpedicao_numero": nf["numero_interno"], "updated_at": now}},
    )


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

    if payload.get("status") == "expedido" and payload.get("idempotency_key"):
        replay_tx = await db.expedicao_transacoes.find_one(
            {"tenant_id": user["tenant_id"], "expedicao_id": exp_id,
             "idempotency_key": payload["idempotency_key"]}, {"_id": 0}
        )
        if replay_tx and replay_tx.get("status") == "concluida":
            await _finalizar_reexpedicao_devolucao(exp, user)
            exp["idempotent_replay"] = True
            return exp

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
            idempotency_key = (payload.get("idempotency_key") or "").strip()
            if len(idempotency_key) < 8:
                raise HTTPException(status_code=422, detail={
                    "error": "idempotency_key_obrigatoria",
                    "message": "Informe idempotency_key para confirmar a expedicao sem risco de baixa duplicada.",
                })
            tx_query = {"tenant_id": user["tenant_id"], "expedicao_id": exp_id, "idempotency_key": idempotency_key}
            tx = await db.expedicao_transacoes.find_one(tx_query, {"_id": 0})
            if tx and tx.get("status") == "concluida":
                replay = await db.expedicao_ordens.find_one({"id": exp_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
                replay["idempotent_replay"] = True
                return replay
            if tx and tx.get("status") == "falha_compensada":
                raise HTTPException(status_code=409, detail={
                    "error": "transacao_expedicao_compensada",
                    "message": "Esta tentativa foi compensada. Gere uma nova chave para tentar novamente.",
                })
            await db.expedicao_transacoes.update_one(
                tx_query,
                {"$setOnInsert": {"id": (tx or {}).get("id") or _new_id(), **tx_query,
                                   "status": "processando", "created_at": now},
                 "$set": {"updated_at": now}}, upsert=True,
            )
            claim = await db.expedicao_ordens.update_one(
                {"id": exp_id, "tenant_id": user["tenant_id"], "status": "conferido",
                 "$or": [{"despacho_lock": {"$exists": False}}, {"despacho_lock": idempotency_key}]},
                {"$set": {"despacho_lock": idempotency_key, "updated_at": now}},
            )
            if claim.matched_count != 1:
                raise HTTPException(status_code=409, detail={
                    "error": "expedicao_em_processamento",
                    "message": "Outra confirmacao de despacho ja esta processando esta expedicao.",
                })
            data_exp = payload.get("data_expedicao") or now[:10]
            updates["data_expedicao"] = data_exp
            try:
                baixas = await _baixar_lotes_da_expedicao(exp, user, idempotency_key)
                updates["baixas_lote"] = baixas
                updates["idempotency_key_despacho"] = idempotency_key
                await db.expedicao_transacoes.update_one(tx_query, {"$set": {
                    "status": "estoque_baixado", "baixas": baixas, "updated_at": _now(),
                }})
            except Exception as exc:
                await db.expedicao_ordens.update_one(
                    {"id": exp_id, "tenant_id": user["tenant_id"], "despacho_lock": idempotency_key},
                    {"$unset": {"despacho_lock": ""}, "$set": {"updated_at": _now()}},
                )
                await db.expedicao_transacoes.update_one(tx_query, {"$set": {
                    "status": "falha_compensada", "erro": str(exc), "updated_at": _now(),
                }})
                raise
        if novo_status == "entregue":
            updates["data_entrega"] = payload.get("data_entrega") or now[:10]

    for field in ("transportadora", "endereco_entrega", "previsao_entrega",
                  "codigo_rastreio", "numero_nf_saida", "observacoes", "data_expedicao", "data_entrega"):
        if field in payload and payload[field] is not None:
            updates[field] = payload[field]

    expedition_update: Dict[str, Any] = {"$set": updates}
    if payload.get("status") == "expedido":
        expedition_update["$unset"] = {"despacho_lock": ""}
    await db.expedicao_ordens.update_one(
        {"id": exp_id, "tenant_id": user["tenant_id"]}, expedition_update
    )
    if payload.get("status") == "expedido":
        updated_exp = await db.expedicao_ordens.find_one(
            {"id": exp_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
        )
        await _finalizar_reexpedicao_devolucao(updated_exp or exp, user)
        await db.expedicao_transacoes.update_one(
            {"tenant_id": user["tenant_id"], "expedicao_id": exp_id,
             "idempotency_key": payload.get("idempotency_key")},
            {"$set": {"status": "concluida", "concluida_em": _now(), "updated_at": _now()}},
        )
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
