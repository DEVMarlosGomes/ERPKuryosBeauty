"""
propostas_routes.py — R14: Proposta Comercial & Pedido de Fabricação

Coleção: db.propostas_comerciais  (uma por projeto, upsert)
Endpoints:
  GET    /crm/projects/{id}/proposta
  POST   /crm/projects/{id}/proposta          (criar / atualizar inteiro)
  PATCH  /crm/projects/{id}/proposta          (atualizar parcialmente)
  GET    /crm/projects/{id}/amostras-status   (R18: validação antes de confirmar pedido)
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import math
import os

from rbac import require_roles
from workflow_engine import audit_log

propostas_router = APIRouter(prefix="/api/crm/projects", tags=["propostas"])

db = None
_get_current_user = None
_new_id = None
_now_iso = None


def init_propostas(database, get_current_user_fn, new_id_fn, now_iso_fn):
    global db, _get_current_user, _new_id, _now_iso
    db = database
    _get_current_user = get_current_user_fn
    _new_id = new_id_fn
    _now_iso = now_iso_fn


# ── Schemas ──────────────────────────────────────────────────────────────────

class InsumoItem(BaseModel):
    descricao: str = ""
    qtd: Optional[float] = None
    unidade: str = ""

class PedidoItem(BaseModel):
    id: str = ""
    sample_id: str = ""
    variacao_id: str = ""
    sku_id: str = ""
    codigo_kuryos: str = ""
    codigo_cliente: str = ""
    item: str = ""
    prazo_entrega: str = ""
    qtd: Optional[float] = None
    custo_base: Optional[float] = None
    margem_percentual: Optional[float] = None
    preco_sugerido: Optional[float] = None
    preco_negociado: Optional[float] = None
    valor_unitario: Optional[float] = None
    valor_total: Optional[float] = None  # calculado no frontend, salvo aqui

class DesenvolvimentoEmbalagemItem(BaseModel):
    id: str = ""
    pedido_item_id: str = ""
    sample_id: str = ""
    variacao_id: str = ""
    sku_id: str = ""
    tipo: str = ""
    descricao: str = ""
    especificacao: str = ""
    fornecedor_id: str = ""
    fornecedor_nome: str = ""
    custo_unitario: Optional[float] = None
    prazo_dias: Optional[int] = None
    status: str = "em_desenvolvimento"
    observacoes: str = ""

class PropostaPayload(BaseModel):
    # Bloco A — Proposta Comercial
    tipo_produto: str = ""
    variacao_produto: str = ""
    preco_unitario: Optional[float] = None
    insumos_inclusos: List[str] = []
    observacoes_proposta: str = ""
    # Bloco B — Pedido de Fabricação
    items_pedido: List[PedidoItem] = []
    desenvolvimentos_embalagem: List[DesenvolvimentoEmbalagemItem] = []
    condicoes_pagamento: str = ""
    insumos_fabricacao: List[InsumoItem] = []
    rodape_observacoes: str = ""
    # Controle
    status: str = "rascunho"  # rascunho | enviado | confirmado | cancelado
    negociacao_status: str = "rascunho"  # rascunho | em_negociacao | aprovado | reprovado
    negociacao_motivo: str = ""
    negociacao_evidencia_file_id: str = ""
    negociacao_observacoes: str = ""

class PropostaPatch(BaseModel):
    tipo_produto: Optional[str] = None
    variacao_produto: Optional[str] = None
    preco_unitario: Optional[float] = None
    insumos_inclusos: Optional[List[str]] = None
    observacoes_proposta: Optional[str] = None
    items_pedido: Optional[List[PedidoItem]] = None
    desenvolvimentos_embalagem: Optional[List[DesenvolvimentoEmbalagemItem]] = None
    condicoes_pagamento: Optional[str] = None
    insumos_fabricacao: Optional[List[InsumoItem]] = None
    rodape_observacoes: Optional[str] = None
    status: Optional[str] = None
    negociacao_status: Optional[str] = None
    negociacao_motivo: Optional[str] = None
    negociacao_evidencia_file_id: Optional[str] = None
    negociacao_observacoes: Optional[str] = None


class NegociacaoPayload(BaseModel):
    decisao: str
    motivo: str = ""
    evidencia_file_id: str = ""
    observacoes: str = ""


WRITE_ROLES = {"admin", "sales_ops", "vendedor"}
NEGOTIATION_DECISIONS = {"aprovado", "reprovado"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_project(projeto_id: str, tenant_id: str) -> dict:
    proj = await db.crm_projects.find_one(
        {"id": projeto_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return proj


# ── Endpoints ─────────────────────────────────────────────────────────────────

@propostas_router.get("/{projeto_id}/proposta")
async def get_proposta(projeto_id: str, request: Request):
    user = await _get_current_user(request)
    await _get_project(projeto_id, user["tenant_id"])
    doc = await db.propostas_comerciais.find_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not doc:
        return {}
    return doc


@propostas_router.post("/{projeto_id}/proposta")
async def upsert_proposta(projeto_id: str, payload: PropostaPayload, request: Request):
    """Cria ou substitui completamente a proposta do projeto."""
    user = await _get_current_user(request)
    require_roles(user, WRITE_ROLES)
    project = await _get_project(projeto_id, user["tenant_id"])

    now = _now_iso()
    existing = await db.propostas_comerciais.find_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]}
    )

    items_dict = [item.dict() for item in payload.items_pedido]
    insumos_dict = [i.dict() for i in payload.insumos_fabricacao]

    if existing:
        doc_id = existing.get("id", _new_id())
        await db.propostas_comerciais.update_one(
            {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]},
            {"$set": {
                **payload.dict(exclude={"items_pedido", "insumos_fabricacao"}),
                "items_pedido": items_dict,
                "insumos_fabricacao": insumos_dict,
                "updated_at": now,
                "updated_by": user["id"],
                "updated_by_name": user.get("name", ""),
            }},
        )
    else:
        doc_id = _new_id()
        doc = {
            "id": doc_id,
            "tenant_id": user["tenant_id"],
            "projeto_id": projeto_id,
            "projeto_nome": project.get("nome_projeto", ""),
            "cliente_id": project.get("cliente_id"),
            "cliente_nome": project.get("cliente_nome", ""),
            **payload.dict(exclude={"items_pedido", "insumos_fabricacao"}),
            "items_pedido": items_dict,
            "insumos_fabricacao": insumos_dict,
            "arquivos": [],
            "created_at": now,
            "created_by": user["id"],
            "created_by_name": user.get("name", ""),
            "updated_at": now,
            "updated_by": user["id"],
            "updated_by_name": user.get("name", ""),
        }
        await db.propostas_comerciais.insert_one(doc)

    updated = await db.propostas_comerciais.find_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )

    # R20: disparar explosão de BOM quando pedido confirmado
    if payload.status == "confirmado":
        try:
            await explode_bom_for_proposta(updated, user["tenant_id"], user)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"R20 BOM explosion failed: {exc}")

    return updated


@propostas_router.patch("/{projeto_id}/proposta")
async def patch_proposta(projeto_id: str, payload: PropostaPatch, request: Request):
    user = await _get_current_user(request)
    require_roles(user, WRITE_ROLES)
    await _get_project(projeto_id, user["tenant_id"])

    patch = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}

    if "items_pedido" in patch:
        patch["items_pedido"] = [
            i.dict() if isinstance(i, PedidoItem) else i for i in patch["items_pedido"]
        ]
    if "insumos_fabricacao" in patch:
        patch["insumos_fabricacao"] = [
            i.dict() if isinstance(i, InsumoItem) else i for i in patch["insumos_fabricacao"]
        ]

    if not patch:
        return {"ok": True}

    patch["updated_at"] = _now_iso()
    patch["updated_by"] = user["id"]
    patch["updated_by_name"] = user.get("name", "")

    result = await db.propostas_comerciais.update_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]},
        {"$set": patch},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Proposta não encontrada — crie com POST primeiro")

    updated = await db.propostas_comerciais.find_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    return updated


async def _create_or_reuse_order_from_proposta(
    project: dict,
    proposta: dict,
    kickoff: dict,
    user: dict,
) -> dict:
    """Cria o rascunho editável do pedido somente após aprovação do orçamento."""
    existing = await db.orders.find_one(
        {
            "tenant_id": user["tenant_id"],
            "projeto_id": project["id"],
            "origem": "orcamento_aprovado",
        },
        {"_id": 0},
    )
    if existing:
        return existing

    from orders_routes import (
        ClienteData,
        CondicoesData,
        OrderCreate,
        OrderItem,
        _create_order_document,
        _enrich_from_crm_client,
    )

    items = []
    for raw in proposta.get("items_pedido") or []:
        items.append(OrderItem(
            sku_id=raw.get("sku_id") or None,
            codigo_kuryos=raw.get("codigo_kuryos", ""),
            codigo_cliente=raw.get("codigo_cliente", ""),
            item=raw.get("item", ""),
            prazo_entrega=raw.get("prazo_entrega", ""),
            qtd=float(raw.get("qtd") or 0),
            valor_unitario=float(raw.get("valor_unitario") or raw.get("preco_negociado") or 0),
            valor_total=float(raw.get("valor_total") or 0),
        ))

    if not items:
        samples = await db.crm_samples.find(
            {"tenant_id": user["tenant_id"], "projeto_id": project["id"]},
            {"_id": 0},
        ).to_list(500)
        for sample in samples:
            for variation in sample.get("variacoes") or []:
                if variation.get("resultado") != "aprovada":
                    continue
                label = " - ".join(filter(None, [
                    sample.get("nome_produto") or sample.get("nome_amostra"),
                    variation.get("descricao_aplicacao") or variation.get("codigo"),
                ]))
                items.append(OrderItem(
                    item=label,
                    qtd=0,
                    valor_unitario=0,
                    valor_total=0,
                ))

    cliente = await _enrich_from_crm_client(project.get("cliente_id", ""), user["tenant_id"])
    order_data = OrderCreate(
        kickoff_id=kickoff["id"],
        cliente_id=project.get("cliente_id"),
        cliente=ClienteData(**cliente),
        items=items,
        condicoes=CondicoesData(
            prazo=proposta.get("condicoes_pagamento", ""),
            forma_pgto=proposta.get("condicoes_pagamento", ""),
        ),
        observacoes=proposta.get("rodape_observacoes", ""),
        allow_duplicate=True,
    )
    order = await _create_order_document(order_data, user, origem="pipeline")
    await db.orders.update_one(
        {"id": order["id"], "tenant_id": user["tenant_id"]},
        {"$set": {
            "projeto_id": project["id"],
            "proposta_id": proposta.get("id"),
            "origem": "orcamento_aprovado",
            "aprovacao_cliente": "aprovado",
            "aprovacao_cliente_em": _now_iso(),
            "updated_at": _now_iso(),
        }},
    )
    return await db.orders.find_one(
        {"id": order["id"], "tenant_id": user["tenant_id"]}, {"_id": 0}
    )


@propostas_router.post("/{projeto_id}/proposta/decisao")
async def decidir_orcamento(projeto_id: str, payload: NegociacaoPayload, request: Request):
    """Registra Aprovação/Reprovação e executa o marco comercial correspondente."""
    user = await _get_current_user(request)
    require_roles(user, WRITE_ROLES)
    if payload.decisao not in NEGOTIATION_DECISIONS:
        raise HTTPException(status_code=422, detail="decisao deve ser 'aprovado' ou 'reprovado'.")
    if payload.decisao == "reprovado" and not payload.motivo.strip():
        raise HTTPException(status_code=422, detail="Motivo obrigatório para reprovar o orçamento.")

    project = await _get_project(projeto_id, user["tenant_id"])
    proposta = await db.propostas_comerciais.find_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not proposta:
        raise HTTPException(status_code=409, detail="Salve o orçamento antes de registrar a decisão do cliente.")

    now = _now_iso()
    decision_patch = {
        "negociacao_status": payload.decisao,
        "negociacao_motivo": payload.motivo.strip(),
        "negociacao_evidencia_file_id": payload.evidencia_file_id,
        "negociacao_observacoes": payload.observacoes,
        "negociacao_decidida_em": now,
        "negociacao_decidida_por": user["id"],
        "updated_at": now,
    }
    await db.propostas_comerciais.update_one(
        {"id": proposta["id"], "tenant_id": user["tenant_id"]},
        {"$set": decision_patch},
    )

    from crm_routes import _advance_project_stage_if_needed

    if payload.decisao == "reprovado":
        project = await _advance_project_stage_if_needed(
            projeto_id,
            "projeto_arquivado",
            user,
            movement_source="orcamento_reprovado",
            extra_set={"motivo_arquivamento": payload.motivo.strip()},
        )
        order = None
        kickoff = None
    else:
        status = await get_amostras_status(projeto_id, request)
        if not status.get("pode_confirmar"):
            raise HTTPException(status_code=409, detail="É necessária ao menos uma amostra aprovada pelo P&D e pelo Comercial.")
        project = await _advance_project_stage_if_needed(
            projeto_id,
            "pedido_aprovado",
            user,
            movement_source="orcamento_aprovado",
        )
        from kickoff_routes import create_kickoff_for_project

        kickoff = await create_kickoff_for_project(projeto_id, user)
        order = await _create_or_reuse_order_from_proposta(project, proposta, kickoff, user)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="orcamento_decidido",
        entity_type="projeto",
        entity_id=projeto_id,
        before={"stage": project.get("stage") if project else None},
        after={"decisao": payload.decisao, "motivo": payload.motivo},
    )
    return {
        "decisao": payload.decisao,
        "project": project,
        "kickoff": kickoff,
        "order": order,
    }


# ── R18: Status das amostras do projeto ──────────────────────────────────────

@propostas_router.get("/{projeto_id}/amostras-status")
async def get_amostras_status(projeto_id: str, request: Request):
    """
    R18 — Retorna situação de cada variação de amostra do projeto.
    Usado pelo frontend para bloquear confirmação de pedido quando nenhuma
    amostra está aprovada pelo cliente.
    """
    user = await _get_current_user(request)
    await _get_project(projeto_id, user["tenant_id"])

    samples = await db.crm_samples.find(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]},
        {"_id": 0, "id": 1, "numero_amostra": 1, "nome_produto": 1, "variacoes": 1},
    ).to_list(500)

    resumo = []
    total_aprovadas = 0
    sku_ids_needed = []

    _STATUS_PD_APROVADO = {"aprovado", "concluido", "APPROVED", "COMPLETED"}
    _STATUS_PD_REPROVADO = {"reprovado", "REJECTED"}

    for s in samples:
        for v in s.get("variacoes", []):
            status_raw = v.get("status", "solicitada")
            resultado = v.get("resultado", "")
            status_pd_raw = v.get("status_pd_raw", "")
            aprovacao_pd = bool(v.get("aprovacao_pd")) or status_pd_raw in _STATUS_PD_APROVADO
            aprovacao_comercial = bool(v.get("aprovacao_externa")) and resultado == "aprovada"
            aprovada = aprovacao_pd and aprovacao_comercial
            if aprovada:
                label = "aprovada"
                total_aprovadas += 1
            elif status_raw in ("reprovada", "cancelada") or resultado == "reprovada" or status_pd_raw in _STATUS_PD_REPROVADO:
                label = "reprovada"
            elif status_raw in ("plano_futuro",):
                label = "plano_futuro"
            else:
                label = "em_andamento"

            sku_id = v.get("sku_id")
            if sku_id:
                sku_ids_needed.append(sku_id)

            resumo.append({
                "amostra_id": s["id"],
                "numero_amostra": s.get("numero_amostra", ""),
                "nome_produto": s.get("nome_produto", "") or v.get("nome_produto", ""),
                "variacao_id": v["id"],
                "codigo": v.get("codigo", ""),
                "descricao": v.get("descricao_aplicacao", ""),
                "status": label,
                "aprovada": aprovada,
                "aprovacao_pd": aprovacao_pd,
                "aprovacao_comercial": aprovacao_comercial,
                "sku_id": sku_id,
                "sku_codigo": "",
            })

    # Fetch SKU codes in one query
    if sku_ids_needed:
        skus = await db.skus.find(
            {"id": {"$in": sku_ids_needed}},
            {"_id": 0, "id": 1, "codigo_interno": 1},
        ).to_list(200)
        sku_map = {s["id"]: s.get("codigo_interno", "") for s in skus}
        for item in resumo:
            if item["sku_id"]:
                item["sku_codigo"] = sku_map.get(item["sku_id"], "")

    return {
        "total": len(resumo),
        "total_aprovadas": total_aprovadas,
        "pode_confirmar": total_aprovadas > 0,
        "variacoes": resumo,
    }


# ── R20: Explosão de BOM → Necessidade de Material ───────────────────────────

async def explode_bom_for_proposta(proposta: dict, tenant_id: str, user: dict) -> dict:
    """
    R20 — Calcula necessidade de materiais por quantidade negociada.

    Composição 1 (bulk): (percentual/100) × qtd_envase_g × qtd_pedido → converte para kg
    Composição 2 (embalagem): quantidade_por_unidade × qtd_pedido → ceil(/ fator_conversao)

    Consolida por codigo_material, salva em db.order_material_requirements.
    """
    necessidades: dict = {}  # key: codigo_material

    for pedido_item in proposta.get("items_pedido", []):
        codigo_kuryos = (pedido_item.get("codigo_kuryos") or "").strip()
        qtd_pedido = float(pedido_item.get("qtd") or 0)
        if not codigo_kuryos or qtd_pedido <= 0:
            continue

        sku = await db.skus.find_one(
            {"codigo": codigo_kuryos, "tenant_id": tenant_id}, {"_id": 0}
        )
        if not sku:
            continue

        sku_id = sku["id"]
        produto_pai_id = sku.get("produto_pai_id")
        apresentacao = sku.get("apresentacao") or {}
        qtd_envase_g = apresentacao.get("qtd_envase")  # granel por unidade (g)

        # ── Composição 2 — Embalagem (por unidade acabada, per SKU) ──────────
        bom_embal = await db.bom_items.find(
            {"sku_id": sku_id, "camada": "embalagem", "vigente": True, "tenant_id": tenant_id},
            {"_id": 0},
        ).to_list(200)

        for item in bom_embal:
            cod = item["codigo_material"]
            qtd_raw = item["quantidade_por_unidade"] * qtd_pedido
            fator = float(item.get("fator_conversao") or 1.0)
            # Arredonda para CIMA na unidade de compra (não compra fração de caixa/bobina)
            qtd_compra = math.ceil(qtd_raw / fator)

            if cod not in necessidades:
                necessidades[cod] = {
                    "insumo_id": cod,
                    "tipo": item.get("tipo", "EP"),
                    "descricao": item.get("nome_material", cod),
                    "qtd_necessaria": 0.0,
                    "qtd_necessaria_compra": 0.0,
                    "unidade_consumo": item.get("unidade_consumo", "un"),
                    "unidade_compra": item.get("unidade_compra", "un"),
                    "fator_conversao": fator,
                    "responsavel": "compras",
                    "sku_ids": [],
                    "pendente_info": False,
                }
            necessidades[cod]["qtd_necessaria"] = round(
                necessidades[cod]["qtd_necessaria"] + qtd_raw, 4
            )
            necessidades[cod]["qtd_necessaria_compra"] = round(
                necessidades[cod]["qtd_necessaria_compra"] + qtd_compra, 4
            )
            if sku_id not in necessidades[cod]["sku_ids"]:
                necessidades[cod]["sku_ids"].append(sku_id)

        # ── Composição 1 — Bulk (percentual × granel por unidade × qtd) ──────
        if produto_pai_id:
            bom_bulk = await db.bom_items.find(
                {
                    "produto_pai_id": produto_pai_id,
                    "camada": "bulk",
                    "vigente": True,
                    "tenant_id": tenant_id,
                },
                {"_id": 0},
            ).to_list(200)

            for item in bom_bulk:
                cod = item["codigo_material"]

                if not qtd_envase_g or qtd_envase_g <= 0:
                    # Sem peso por unidade — item fica como pendente_info
                    if cod not in necessidades:
                        necessidades[cod] = {
                            "insumo_id": cod,
                            "tipo": item.get("tipo", "MP"),
                            "descricao": item.get("nome_material", cod),
                            "qtd_necessaria": None,
                            "qtd_necessaria_compra": None,
                            "unidade_consumo": "g",
                            "unidade_compra": "kg",
                            "fator_conversao": 1000.0,
                            "responsavel": "compras",
                            "sku_ids": [],
                            "pendente_info": True,
                        }
                    else:
                        necessidades[cod]["pendente_info"] = True
                    if sku_id not in necessidades[cod]["sku_ids"]:
                        necessidades[cod]["sku_ids"].append(sku_id)
                    continue

                qtd_g = (item["percentual"] / 100.0) * float(qtd_envase_g) * qtd_pedido
                qtd_kg = qtd_g / 1000.0

                if cod not in necessidades:
                    necessidades[cod] = {
                        "insumo_id": cod,
                        "tipo": item.get("tipo", "MP"),
                        "descricao": item.get("nome_material", cod),
                        "qtd_necessaria": 0.0,
                        "qtd_necessaria_compra": 0.0,
                        "unidade_consumo": "g",
                        "unidade_compra": "kg",
                        "fator_conversao": 1000.0,
                        "responsavel": "compras",
                        "sku_ids": [],
                        "pendente_info": False,
                    }

                necessidades[cod]["qtd_necessaria"] = round(
                    (necessidades[cod]["qtd_necessaria"] or 0) + qtd_g, 3
                )
                # Arredonda para 0.1 kg acima (ninguém pesa fração de grama num pedido)
                qtd_kg_compra = math.ceil(qtd_kg * 10) / 10
                necessidades[cod]["qtd_necessaria_compra"] = round(
                    (necessidades[cod]["qtd_necessaria_compra"] or 0) + qtd_kg_compra, 3
                )
                if sku_id not in necessidades[cod]["sku_ids"]:
                    necessidades[cod]["sku_ids"].append(sku_id)

    materiais_list = [{"id": _new_id(), **v} for v in necessidades.values()]

    now = _now_iso()
    tem_pendente = any(m.get("pendente_info") for m in materiais_list)
    doc = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "proposta_id": proposta.get("id"),
        "projeto_id": proposta.get("projeto_id"),
        "cliente_id": proposta.get("cliente_id"),
        "cliente_nome": proposta.get("cliente_nome", ""),
        "gerado_em": now,
        "gerado_por": user["id"],
        "gerado_por_name": user.get("name", ""),
        "status": "pendente_info" if tem_pendente else "gerado",
        "materiais": materiais_list,
    }

    await db.order_material_requirements.update_one(
        {"proposta_id": proposta.get("id"), "tenant_id": tenant_id},
        {"$set": doc},
        upsert=True,
    )
    doc.pop("_id", None)
    return doc


@propostas_router.get("/{projeto_id}/material-requirements")
async def get_material_requirements(projeto_id: str, request: Request):
    """R20 — Retorna necessidades de material geradas para a proposta confirmada."""
    user = await _get_current_user(request)
    await _get_project(projeto_id, user["tenant_id"])

    proposta = await db.propostas_comerciais.find_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not proposta:
        return {}

    req = await db.order_material_requirements.find_one(
        {"proposta_id": proposta["id"], "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    return req or {}


# ── Upload de arquivo ────────────────────────────────────────────────────────

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "propostas")


@propostas_router.post("/{projeto_id}/proposta/attachments")
async def upload_attachment(
    projeto_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    """Anexa um arquivo à proposta. Salva em disco e registra referência."""
    user = await _get_current_user(request)
    await _get_project(projeto_id, user["tenant_id"])

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = _new_id()
    ext = os.path.splitext(file.filename or "")[1] or ""
    filename_stored = f"{file_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename_stored)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    ref = {
        "id": file_id,
        "nome_original": file.filename,
        "tipo": file.content_type or "application/octet-stream",
        "tamanho_bytes": len(contents),
        "path": filename_stored,
        "url": f"/api/propostas/files/{filename_stored}",
        "uploaded_at": _now_iso(),
        "uploaded_by": user["id"],
        "uploaded_by_name": user.get("name", ""),
    }

    await db.propostas_comerciais.update_one(
        {"projeto_id": projeto_id, "tenant_id": user["tenant_id"]},
        {"$push": {"arquivos": ref}},
    )

    return ref
