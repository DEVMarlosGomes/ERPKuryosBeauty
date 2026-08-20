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
            aprovada = (
                bool(v.get("aprovacao_externa"))
                or status_raw == "aprovada"
                or resultado == "aprovada"
                or status_pd_raw in _STATUS_PD_APROVADO
            )
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
