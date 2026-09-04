"""
Modulo Cadastros - fonte unica de cadastros operacionais.

Este modulo consolida clientes, fornecedores, produtos finais, materiais e
categorias sem duplicar as colecoes que ja alimentam CRM, Compras, P&D e PCP.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from rbac import COMERCIAL_FULL, COMPRAS_FULL, PD_FULL, PD_READ, require_roles
from validation_utils import is_valid_cnpj, normalize_cnpj
from workflow_engine import (
    audit_log,
    build_sku_code_v2,
    next_sequence,
    next_sku_per_pair_v2,
    normalise_cli4,
    suggest_cli4_candidates,
)

logger = logging.getLogger(__name__)

cadastros_master_router = APIRouter(prefix="/api/cadastros", tags=["cadastros-master"])

db = None
_get_current_user = None
_new_id = None
_now_iso = None

READ_ROLES = PD_READ | COMERCIAL_FULL | COMPRAS_FULL
CLIENT_WRITE_ROLES = COMERCIAL_FULL | {"admin"}
SUPPLIER_WRITE_ROLES = COMPRAS_FULL | {"admin"}
PRODUCT_WRITE_ROLES = PD_FULL | COMERCIAL_FULL | {"admin"}
CATEGORY_WRITE_ROLES = PD_FULL | COMPRAS_FULL | {"admin"}
APPROVE_ROLES = {"admin", "lider_pd", "qa"}


def init_cadastros_master(database, get_current_user_fn, new_id_fn, now_iso_fn):
    global db, _get_current_user, _new_id, _now_iso
    db = database
    _get_current_user = get_current_user_fn
    _new_id = new_id_fn
    _now_iso = now_iso_fn
    logger.info("Cadastros master module initialized")


async def create_cadastros_master_indexes():
    await db.cad_categorias_mp.create_index([("tenant_id", 1), ("catmp3", 1)], unique=True)
    await db.cad_categorias_mp.create_index([("tenant_id", 1), ("status", 1)])
    await db.cad_categorias_mp.create_index([("tenant_id", 1), ("nome", 1)])
    await db.cadastros_auditoria.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.crm_clients.create_index([("tenant_id", 1), ("cli4", 1)])
    await db.materiais.create_index([("tenant_id", 1), ("categoria_mp_id", 1)])


class ClienteCadastroCreate(BaseModel):
    nome_empresa: str
    cnpj: str = ""
    cli4: str = ""
    responsavel: str = ""
    email: str = ""
    telefone: str = ""
    cidade: str = ""
    uf: str = ""
    segmento: str = ""
    observacoes: str = ""


class ClienteCadastroUpdate(BaseModel):
    nome_empresa: Optional[str] = None
    cnpj: Optional[str] = None
    cli4: Optional[str] = None
    responsavel: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    segmento: Optional[str] = None
    observacoes: Optional[str] = None
    status_cadastro: Optional[str] = None


class FornecedorCadastroCreate(BaseModel):
    razao_social: str
    cnpj: str
    nome_fantasia: str = ""
    email: str = ""
    telefone: str = ""
    categoria: str = ""
    observacoes: str = ""


class FornecedorCadastroUpdate(BaseModel):
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    categoria: Optional[str] = None
    observacoes: Optional[str] = None
    status_cadastro: Optional[str] = None


class CategoriaMPCreate(BaseModel):
    catmp3: str
    nome: str
    tipo: str = "mp"
    descricao: str = ""
    justificativa: str = ""


class CategoriaMPUpdate(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[str] = None
    descricao: Optional[str] = None
    status: Optional[str] = None


class ProdutoFinalCreate(BaseModel):
    nome_produto: str
    cliente_id: str
    cat3: str
    categoria: str = ""
    volume: Optional[float] = None
    unidade_volume: str = "ml"
    pd_request_id: str = ""
    observacoes: str = ""
    formula: List[Dict[str, Any]] = Field(default_factory=list)
    bom: List[Dict[str, Any]] = Field(default_factory=list)
    especificacoes_tecnicas: Dict[str, Any] = Field(default_factory=dict)
    enderecamento: Dict[str, Any] = Field(default_factory=dict)


class ProdutoFinalUpdate(BaseModel):
    nome_produto: Optional[str] = None
    categoria: Optional[str] = None
    volume: Optional[float] = None
    unidade_volume: Optional[str] = None
    pd_request_id: Optional[str] = None
    observacoes: Optional[str] = None
    status: Optional[str] = None
    formula: Optional[List[Dict[str, Any]]] = None
    bom: Optional[List[Dict[str, Any]]] = None
    especificacoes_tecnicas: Optional[Dict[str, Any]] = None
    enderecamento: Optional[Dict[str, Any]] = None


class MaterialCadastroCreate(BaseModel):
    tipo: str
    nome: str
    categoria_mp_id: str = ""
    subtipo: str = ""
    unidade_estoque: str = "kg"
    unidade_compra: str = "kg"
    fator_conversao: float = 1.0
    fornecedor_id: str = ""
    observacoes: str = ""
    especificacoes_tecnicas: Dict[str, Any] = Field(default_factory=dict)
    enderecamento: Dict[str, Any] = Field(default_factory=dict)


class MaterialCadastroUpdate(BaseModel):
    tipo: Optional[str] = None
    nome: Optional[str] = None
    categoria_mp_id: Optional[str] = None
    subtipo: Optional[str] = None
    unidade_estoque: Optional[str] = None
    unidade_compra: Optional[str] = None
    fator_conversao: Optional[float] = None
    fornecedor_id: Optional[str] = None
    observacoes: Optional[str] = None
    status: Optional[str] = None
    especificacoes_tecnicas: Optional[Dict[str, Any]] = None
    enderecamento: Optional[Dict[str, Any]] = None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _validate_cat3(value: str) -> str:
    cat3 = _clean(value).upper()
    if not re.match(r"^[A-Z]{3}$", cat3):
        raise HTTPException(status_code=422, detail="CAT3 deve ter exatamente 3 letras.")
    return cat3


def _validate_catmp3(value: str) -> str:
    catmp3 = _clean(value).upper()
    if not re.match(r"^[A-Z0-9]{3}$", catmp3):
        raise HTTPException(status_code=422, detail="CATMP3 deve ter 3 caracteres alfanumericos.")
    return catmp3


def _material_tipo_from_business(tipo: str) -> str:
    t = _clean(tipo).lower()
    if t in {"mp", "materia_prima", "materia-prima", "materia prima"}:
        return "MP"
    if t in {"insumo", "embalagem_primaria", "embalagem primaria", "ep"}:
        return "EP"
    if t in {"embalagem_secundaria", "embalagem secundaria", "es"}:
        return "ES"
    if t in {"rotulo", "rt", "etiqueta"}:
        return "RT"
    raise HTTPException(status_code=422, detail="Tipo invalido. Use mp, insumo, EP, ES ou RT.")


def _normalize_cliente(doc: dict) -> dict:
    return {
        "id": doc.get("id"),
        "nome_empresa": doc.get("nome_empresa") or doc.get("nome") or "",
        "cnpj": doc.get("cnpj") or "",
        "cnpj_normalized": doc.get("cnpj_normalized") or normalize_cnpj(doc.get("cnpj", "")),
        "cli4": doc.get("cli4") or "",
        "cli4_congelado": bool(doc.get("cli4_congelado")),
        "responsavel": doc.get("responsavel") or (doc.get("contato_principal") or {}).get("nome") or "",
        "email": doc.get("email") or (doc.get("contato_principal") or {}).get("email") or "",
        "telefone": doc.get("telefone") or (doc.get("contato_principal") or {}).get("telefone") or "",
        "cidade": doc.get("cidade") or "",
        "uf": doc.get("uf") or "",
        "segmento": doc.get("segmento") or "",
        "stage": doc.get("stage") or "",
        "status_cadastro": doc.get("status_cadastro") or ("inativo" if doc.get("stage") == "cliente_perdido" else "ativo"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _normalize_fornecedor(doc: dict) -> dict:
    homologacao = doc.get("homologacao") or {}
    contatos = doc.get("contatos") or []
    contato = contatos[0] if contatos else {}
    return {
        "id": doc.get("id"),
        "codigo_interno": doc.get("codigo_interno") or "",
        "razao_social": doc.get("razao_social") or "",
        "nome_fantasia": doc.get("nome_fantasia") or "",
        "cnpj": doc.get("cnpj") or "",
        "cnpj_normalizado": doc.get("cnpj_normalizado") or normalize_cnpj(doc.get("cnpj", "")),
        "email": contato.get("email") or doc.get("email") or "",
        "telefone": contato.get("telefone") or contato.get("whatsapp") or doc.get("telefone") or "",
        "categorias": doc.get("categorias") or [],
        "status_cadastro": doc.get("status_cadastro") or "ativo",
        "status_homologacao": homologacao.get("status") or doc.get("status") or "nao_iniciada",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def _audit(user: dict, action: str, entity_type: str, entity_id: str, before=None, after=None):
    try:
        await audit_log(
            tenant_id=user["tenant_id"],
            user_id=user["id"],
            user_name=user.get("name", ""),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Cadastros audit failed: %s", exc)


async def _next_supplier_code(tenant_id: str) -> str:
    seq = await next_sequence(tenant_id, "compras_fornecedores", start=0)
    return f"FOR-{str(seq).zfill(5)}"


async def _next_material_code(tenant_id: str, tipo2: str) -> str:
    seq = await next_sequence(tenant_id, f"mat_{tipo2}", start=0)
    return f"{tipo2}-{str(seq).zfill(5)}"


@cadastros_master_router.get("/dashboard")
async def cadastros_dashboard(request: Request):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    tenant_id = user["tenant_id"]
    total_clientes = await db.crm_clients.count_documents({"tenant_id": tenant_id})
    total_fornecedores = await db.compras_fornecedores.count_documents({"tenant_id": tenant_id})
    total_produtos = await db.skus.count_documents({"tenant_id": tenant_id})
    total_materiais = await db.materiais.count_documents({"tenant_id": tenant_id})
    total_cat_produtos = await db.categorias.count_documents({"tenant_id": tenant_id})
    total_cat_mps = await db.cad_categorias_mp.count_documents({"tenant_id": tenant_id})
    pendencias = {
        "categorias_produto": await db.categorias.count_documents({"tenant_id": tenant_id, "status": "pendente"}),
        "categorias_mp": await db.cad_categorias_mp.count_documents({"tenant_id": tenant_id, "status": "pendente"}),
        "fornecedores_homologacao": await db.compras_fornecedores.count_documents({
            "tenant_id": tenant_id,
            "homologacao.status": {"$in": ["nao_iniciada", "em_processo", "reprovado", "suspenso"]},
        }),
        "produtos_sem_pd": await db.skus.count_documents({
            "tenant_id": tenant_id,
            "status": "ativo",
            "$or": [{"pd_concluido": {"$ne": True}}, {"pd_request_id": {"$in": [None, ""]}}],
        }),
        "itens_pedidos_sem_cadastro": await db.orders.count_documents({
            "tenant_id": tenant_id,
            "cadastro_pendente": True,
        }),
    }
    return {
        "totais": {
            "clientes": total_clientes,
            "fornecedores": total_fornecedores,
            "produtos": total_produtos,
            "materiais": total_materiais,
            "categorias_produto": total_cat_produtos,
            "categorias_mp": total_cat_mps,
        },
        "pendencias": pendencias,
        "integracoes": [
            {"nome": "P&D", "status": "conectado", "detalhe": "Produtos concluidos e fichas tecnicas alimentam o cadastro."},
            {"nome": "Pedidos", "status": "conectado", "detalhe": "Pedidos diretos usam SKUs ativos do cadastro."},
            {"nome": "PCP", "status": "conectado", "detalhe": "PCP le produtos e matriz oficial."},
            {"nome": "Compras", "status": "conectado", "detalhe": "Fornecedores oficiais e homologacao compartilhados."},
            {"nome": "Estoque Lab", "status": "conectado", "detalhe": "Materiais podem ser vinculados ao banco de custos e estoque."},
        ],
    }


@cadastros_master_router.get("/clientes")
async def list_clientes(request: Request, q: Optional[str] = Query(None), status: Optional[str] = None):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status and status != "todos":
        query["status_cadastro"] = status
    if q:
        query["$or"] = [
            {"nome_empresa": {"$regex": q, "$options": "i"}},
            {"cnpj_normalized": {"$regex": normalize_cnpj(q), "$options": "i"}},
            {"cli4": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.crm_clients.find(query, {"_id": 0}).sort("nome_empresa", 1).to_list(1000)
    return {"clientes": [_normalize_cliente(d) for d in docs], "total": len(docs)}


@cadastros_master_router.post("/clientes", status_code=201)
async def create_cliente(data: ClienteCadastroCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CLIENT_WRITE_ROLES)
    nome = _clean(data.nome_empresa)
    if not nome:
        raise HTTPException(status_code=422, detail="Nome do cliente e obrigatorio.")
    cnpj_norm = normalize_cnpj(data.cnpj)
    if cnpj_norm and not is_valid_cnpj(cnpj_norm):
        raise HTTPException(status_code=422, detail="CNPJ invalido.")
    if cnpj_norm:
        existing = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "cnpj_normalized": cnpj_norm}, {"_id": 0})
        if existing:
            raise HTTPException(status_code=409, detail=f"CNPJ ja cadastrado para {existing.get('nome_empresa')}.")
    cli4 = normalise_cli4(data.cli4 or (suggest_cli4_candidates(nome)[0] if suggest_cli4_candidates(nome) else nome))
    conflict = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "cli4": cli4}, {"_id": 0, "nome_empresa": 1})
    if conflict:
        raise HTTPException(status_code=409, detail=f"CLI4 {cli4} ja esta em uso por {conflict.get('nome_empresa')}.")
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "nome_empresa": nome,
        "cnpj": data.cnpj,
        "cnpj_normalized": cnpj_norm,
        "cli4": cli4,
        "cli4_congelado": False,
        "responsavel": _clean(data.responsavel),
        "email": _clean(data.email),
        "telefone": _clean(data.telefone),
        "cidade": _clean(data.cidade),
        "uf": _clean(data.uf).upper(),
        "segmento": _clean(data.segmento),
        "observacoes": _clean(data.observacoes),
        "stage": "cliente_fechado",
        "status_cadastro": "ativo",
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.crm_clients.insert_one(doc)
    doc.pop("_id", None)
    await _audit(user, "cadastro_cliente_criado", "cliente", doc["id"], after=doc)
    return _normalize_cliente(doc)


@cadastros_master_router.put("/clientes/{cliente_id}")
async def update_cliente(cliente_id: str, data: ClienteCadastroUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CLIENT_WRITE_ROLES)
    existing = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "id": cliente_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
    payload = data.model_dump(exclude_unset=True)
    if "cnpj" in payload:
        cnpj_norm = normalize_cnpj(payload.get("cnpj"))
        if cnpj_norm and not is_valid_cnpj(cnpj_norm):
            raise HTTPException(status_code=422, detail="CNPJ invalido.")
        conflict = await db.crm_clients.find_one({
            "tenant_id": user["tenant_id"],
            "cnpj_normalized": cnpj_norm,
            "id": {"$ne": cliente_id},
        }, {"_id": 0})
        if cnpj_norm and conflict:
            raise HTTPException(status_code=409, detail="CNPJ ja cadastrado em outro cliente.")
        payload["cnpj_normalized"] = cnpj_norm
    if "cli4" in payload:
        if existing.get("cli4_congelado"):
            raise HTTPException(status_code=409, detail="CLI4 congelado: ja existe SKU para este cliente.")
        cli4 = normalise_cli4(payload.get("cli4") or existing.get("nome_empresa", ""))
        conflict = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "cli4": cli4, "id": {"$ne": cliente_id}}, {"_id": 0})
        if conflict:
            raise HTTPException(status_code=409, detail="CLI4 ja esta em uso.")
        payload["cli4"] = cli4
    payload["updated_at"] = _now_iso()
    await db.crm_clients.update_one({"tenant_id": user["tenant_id"], "id": cliente_id}, {"$set": payload})
    updated = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "id": cliente_id}, {"_id": 0})
    await _audit(user, "cadastro_cliente_atualizado", "cliente", cliente_id, before=existing, after=updated)
    return _normalize_cliente(updated)


@cadastros_master_router.delete("/clientes/{cliente_id}")
async def delete_cliente(cliente_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CLIENT_WRITE_ROLES)
    existing = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "id": cliente_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
    now = _now_iso()
    payload = {"status_cadastro": "inativo", "deleted_at": now, "updated_at": now}
    await db.crm_clients.update_one({"tenant_id": user["tenant_id"], "id": cliente_id}, {"$set": payload})
    updated = await db.crm_clients.find_one({"tenant_id": user["tenant_id"], "id": cliente_id}, {"_id": 0})
    await _audit(user, "cadastro_cliente_inativado", "cliente", cliente_id, before=existing, after=updated)
    return _normalize_cliente(updated)


@cadastros_master_router.get("/fornecedores")
async def list_fornecedores(request: Request, q: Optional[str] = Query(None), status: Optional[str] = None):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status and status != "todos":
        query["status_cadastro"] = status
    if q:
        query["$or"] = [
            {"razao_social": {"$regex": q, "$options": "i"}},
            {"nome_fantasia": {"$regex": q, "$options": "i"}},
            {"cnpj_normalizado": {"$regex": normalize_cnpj(q), "$options": "i"}},
            {"codigo_interno": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.compras_fornecedores.find(query, {"_id": 0}).sort("razao_social", 1).to_list(1000)
    return {"fornecedores": [_normalize_fornecedor(d) for d in docs], "total": len(docs)}


@cadastros_master_router.post("/fornecedores", status_code=201)
async def create_fornecedor(data: FornecedorCadastroCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, SUPPLIER_WRITE_ROLES)
    if not _clean(data.razao_social):
        raise HTTPException(status_code=422, detail="Razao social e obrigatoria.")
    if not is_valid_cnpj(data.cnpj):
        raise HTTPException(status_code=422, detail="CNPJ invalido.")
    cnpj_norm = normalize_cnpj(data.cnpj)
    existing = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "cnpj_normalizado": cnpj_norm}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail=f"CNPJ ja cadastrado para {existing.get('razao_social')}.")
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "codigo_interno": await _next_supplier_code(user["tenant_id"]),
        "razao_social": _clean(data.razao_social),
        "nome_fantasia": _clean(data.nome_fantasia),
        "cnpj": data.cnpj,
        "cnpj_normalizado": cnpj_norm,
        "contatos": [{
            "id": _new_id(),
            "nome": "Contato principal",
            "email": _clean(data.email),
            "telefone": _clean(data.telefone),
            "principal_compras": True,
        }],
        "categorias": [data.categoria] if _clean(data.categoria) else [],
        "observacoes": _clean(data.observacoes),
        "homologacao": {
            "status": "nao_iniciada",
            "data_homologacao": None,
            "proxima_reavaliacao": None,
            "documentos_file_ids": [],
            "historico_rncs_count": 0,
            "historico_rncs_criticas_12m": 0,
        },
        "status_cadastro": "ativo",
        "created_at": now,
        "updated_at": now,
        "log_auditoria": [{"acao": "fornecedor_criado_cadastros", "por_id": user["id"], "por_nome": user.get("name", ""), "em": now}],
    }
    await db.compras_fornecedores.insert_one(doc)
    doc.pop("_id", None)
    await _audit(user, "cadastro_fornecedor_criado", "fornecedor", doc["id"], after=doc)
    return _normalize_fornecedor(doc)


@cadastros_master_router.put("/fornecedores/{fornecedor_id}")
async def update_fornecedor(fornecedor_id: str, data: FornecedorCadastroUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, SUPPLIER_WRITE_ROLES)
    existing = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "id": fornecedor_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Fornecedor nao encontrado.")
    payload = data.model_dump(exclude_unset=True)
    updates: Dict[str, Any] = {"updated_at": _now_iso()}
    for field in ("razao_social", "nome_fantasia", "observacoes", "status_cadastro"):
        if field in payload:
            updates[field] = payload[field]
    if "categoria" in payload:
        updates["categorias"] = [payload["categoria"]] if _clean(payload["categoria"]) else []
    if "email" in payload or "telefone" in payload:
        contato = (existing.get("contatos") or [{}])[0]
        contato["email"] = payload.get("email", contato.get("email", ""))
        contato["telefone"] = payload.get("telefone", contato.get("telefone", ""))
        contato["id"] = contato.get("id") or _new_id()
        contato["principal_compras"] = True
        updates["contatos"] = [contato]
    await db.compras_fornecedores.update_one(
        {"tenant_id": user["tenant_id"], "id": fornecedor_id},
        {"$set": updates, "$push": {"log_auditoria": {"acao": "cadastro_atualizado_cadastros", "por_id": user["id"], "por_nome": user.get("name", ""), "em": _now_iso()}}},
    )
    updated = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "id": fornecedor_id}, {"_id": 0})
    await _audit(user, "cadastro_fornecedor_atualizado", "fornecedor", fornecedor_id, before=existing, after=updated)
    return _normalize_fornecedor(updated)


@cadastros_master_router.delete("/fornecedores/{fornecedor_id}")
async def delete_fornecedor(fornecedor_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, SUPPLIER_WRITE_ROLES)
    existing = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "id": fornecedor_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Fornecedor nao encontrado.")
    now = _now_iso()
    payload = {"status_cadastro": "inativo", "deleted_at": now, "updated_at": now}
    await db.compras_fornecedores.update_one(
        {"tenant_id": user["tenant_id"], "id": fornecedor_id},
        {"$set": payload, "$push": {"log_auditoria": {"acao": "fornecedor_inativado_cadastros", "por_id": user["id"], "por_nome": user.get("name", ""), "em": now}}},
    )
    updated = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "id": fornecedor_id}, {"_id": 0})
    await _audit(user, "cadastro_fornecedor_inativado", "fornecedor", fornecedor_id, before=existing, after=updated)
    return _normalize_fornecedor(updated)


@cadastros_master_router.get("/categorias-mp")
async def list_categorias_mp(request: Request, status: Optional[str] = None):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status and status != "todos":
        query["status"] = status
    docs = await db.cad_categorias_mp.find(query, {"_id": 0}).sort("catmp3", 1).to_list(1000)
    return {"categorias": docs, "total": len(docs)}


@cadastros_master_router.post("/categorias-mp", status_code=201)
async def create_categoria_mp(data: CategoriaMPCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    catmp3 = _validate_catmp3(data.catmp3)
    if not _clean(data.nome):
        raise HTTPException(status_code=422, detail="Nome da categoria e obrigatorio.")
    existing = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "catmp3": catmp3}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail=f"CATMP3 {catmp3} ja esta em uso.")
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "catmp3": catmp3,
        "nome": _clean(data.nome),
        "tipo": _clean(data.tipo) or "mp",
        "descricao": _clean(data.descricao),
        "justificativa": _clean(data.justificativa),
        "status": "pendente",
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
        "approved_at": None,
        "approved_by": None,
    }
    await db.cad_categorias_mp.insert_one(doc)
    doc.pop("_id", None)
    await _audit(user, "categoria_mp_solicitada", "categoria_mp", doc["id"], after=doc)
    return doc


@cadastros_master_router.post("/categorias-mp/{categoria_id}/aprovar")
async def approve_categoria_mp(categoria_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    existing = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria de MP nao encontrada.")
    if existing.get("status") == "ativa":
        return existing
    now = _now_iso()
    await db.cad_categorias_mp.update_one(
        {"tenant_id": user["tenant_id"], "id": categoria_id},
        {"$set": {"status": "ativa", "approved_at": now, "approved_by": user.get("name", ""), "updated_at": now}},
    )
    updated = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"_id": 0})
    await _audit(user, "categoria_mp_aprovada", "categoria_mp", categoria_id, before=existing, after=updated)
    return updated


@cadastros_master_router.put("/categorias-mp/{categoria_id}")
async def update_categoria_mp(categoria_id: str, data: CategoriaMPUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    existing = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria de MP nao encontrada.")
    payload = data.model_dump(exclude_unset=True)
    for field in ("nome", "tipo", "descricao", "status"):
        if field in payload:
            payload[field] = _clean(payload[field])
    payload["updated_at"] = _now_iso()
    await db.cad_categorias_mp.update_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"$set": payload})
    updated = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"_id": 0})
    await _audit(user, "categoria_mp_atualizada", "categoria_mp", categoria_id, before=existing, after=updated)
    return updated


@cadastros_master_router.delete("/categorias-mp/{categoria_id}")
async def delete_categoria_mp(categoria_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    existing = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria de MP nao encontrada.")
    now = _now_iso()
    payload = {"status": "inativa", "deleted_at": now, "updated_at": now}
    await db.cad_categorias_mp.update_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"$set": payload})
    updated = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": categoria_id}, {"_id": 0})
    await _audit(user, "categoria_mp_inativada", "categoria_mp", categoria_id, before=existing, after=updated)
    return updated


@cadastros_master_router.get("/produtos")
async def list_produtos(request: Request, q: Optional[str] = Query(None), status: Optional[str] = None):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status and status != "todos":
        query["status"] = status
    if q:
        query["$or"] = [
            {"codigo_interno": {"$regex": q, "$options": "i"}},
            {"nome_produto": {"$regex": q, "$options": "i"}},
            {"cliente_nome": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.skus.find(query, {"_id": 0}).sort("codigo_interno", 1).to_list(1000)
    return {"produtos": docs, "total": len(docs)}


@cadastros_master_router.post("/produtos", status_code=201)
async def create_produto_final(data: ProdutoFinalCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, PRODUCT_WRITE_ROLES)
    tenant_id = user["tenant_id"]
    nome = _clean(data.nome_produto)
    if not nome:
        raise HTTPException(status_code=422, detail="Nome do produto e obrigatorio.")
    cat3 = _validate_cat3(data.cat3)
    categoria = await db.categorias.find_one({"tenant_id": tenant_id, "cat3": cat3, "status": "ativa"}, {"_id": 0})
    if not categoria:
        raise HTTPException(status_code=409, detail=f"Categoria {cat3} nao esta ativa.")
    cliente = await db.crm_clients.find_one({"tenant_id": tenant_id, "id": data.cliente_id}, {"_id": 0})
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
    cli4 = normalise_cli4(cliente.get("cli4") or cliente.get("nome_empresa", ""))
    if not cli4:
        raise HTTPException(status_code=409, detail="Cliente sem CLI4.")
    seq = await next_sku_per_pair_v2(tenant_id, cat3, cli4)
    codigo = build_sku_code_v2(cat3, cli4, seq)
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "codigo_interno": codigo,
        "cat3": cat3,
        "cli4": cli4,
        "nome_produto": nome,
        "categoria": data.categoria or categoria.get("nome", ""),
        "cliente_id": data.cliente_id,
        "cliente_nome": cliente.get("nome_empresa", ""),
        "volume": data.volume,
        "unidade_volume": data.unidade_volume,
        "pd_request_id": _clean(data.pd_request_id),
        "pd_concluido": bool(_clean(data.pd_request_id)),
        "status": "ativo",
        "origem": "cadastros",
        "observacoes": _clean(data.observacoes),
        "formula": data.formula or [],
        "bom": data.bom or [],
        "especificacoes_tecnicas": data.especificacoes_tecnicas or {},
        "enderecamento": data.enderecamento or {},
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.skus.insert_one(doc)
    await db.crm_clients.update_one({"tenant_id": tenant_id, "id": data.cliente_id}, {"$set": {"cli4": cli4, "cli4_congelado": True, "updated_at": now}})
    doc.pop("_id", None)
    await _audit(user, "produto_final_criado", "sku", doc["id"], after=doc)
    return doc


@cadastros_master_router.put("/produtos/{produto_id}")
async def update_produto_final(produto_id: str, data: ProdutoFinalUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, PRODUCT_WRITE_ROLES)
    existing = await db.skus.find_one({"tenant_id": user["tenant_id"], "id": produto_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Produto nao encontrado.")
    payload = data.model_dump(exclude_unset=True)
    updates: Dict[str, Any] = {"updated_at": _now_iso()}
    for field in ("nome_produto", "categoria", "volume", "unidade_volume", "pd_request_id", "observacoes", "status"):
        if field in payload:
            updates[field] = payload[field]
    if "pd_request_id" in payload:
        updates["pd_concluido"] = bool(_clean(payload.get("pd_request_id")))
    for field in ("formula", "bom", "especificacoes_tecnicas", "enderecamento"):
        if field in payload:
            updates[field] = payload[field] if payload[field] is not None else ([] if field in ("formula", "bom") else {})
    await db.skus.update_one({"tenant_id": user["tenant_id"], "id": produto_id}, {"$set": updates})
    updated = await db.skus.find_one({"tenant_id": user["tenant_id"], "id": produto_id}, {"_id": 0})
    await _audit(user, "produto_final_atualizado", "sku", produto_id, before=existing, after=updated)
    return updated


@cadastros_master_router.delete("/produtos/{produto_id}")
async def delete_produto_final(produto_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, PRODUCT_WRITE_ROLES)
    existing = await db.skus.find_one({"tenant_id": user["tenant_id"], "id": produto_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Produto nao encontrado.")
    now = _now_iso()
    payload = {"status": "inativo", "deleted_at": now, "updated_at": now}
    await db.skus.update_one({"tenant_id": user["tenant_id"], "id": produto_id}, {"$set": payload})
    updated = await db.skus.find_one({"tenant_id": user["tenant_id"], "id": produto_id}, {"_id": 0})
    await _audit(user, "produto_final_inativado", "sku", produto_id, before=existing, after=updated)
    return updated


@cadastros_master_router.get("/materiais-cadastro")
async def list_materiais_cadastro(request: Request, tipo: Optional[str] = None, q: Optional[str] = Query(None)):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if tipo and tipo != "todos":
        query["tipo2"] = _material_tipo_from_business(tipo)
    if q:
        query["$or"] = [
            {"codigo_interno": {"$regex": q, "$options": "i"}},
            {"nome": {"$regex": q, "$options": "i"}},
            {"subtipo": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.materiais.find(query, {"_id": 0}).sort("codigo_interno", 1).to_list(1000)
    return {"materiais": docs, "total": len(docs)}


@cadastros_master_router.post("/materiais-cadastro", status_code=201)
async def create_material_cadastro(data: MaterialCadastroCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    tipo2 = _material_tipo_from_business(data.tipo)
    nome = _clean(data.nome)
    if not nome:
        raise HTTPException(status_code=422, detail="Nome do material e obrigatorio.")
    categoria = None
    if data.categoria_mp_id:
        categoria = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": data.categoria_mp_id, "status": "ativa"}, {"_id": 0})
        if not categoria:
            raise HTTPException(status_code=409, detail="Categoria de MP/Insumo nao esta ativa.")
    fornecedor = None
    if data.fornecedor_id:
        fornecedor = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "id": data.fornecedor_id}, {"_id": 0})
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor nao encontrado.")
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": user["tenant_id"],
        "codigo_interno": await _next_material_code(user["tenant_id"], tipo2),
        "tipo2": tipo2,
        "subtipo": _clean(data.subtipo) or (categoria or {}).get("nome", ""),
        "nome": nome,
        "descricao": _clean(data.observacoes),
        "categoria_mp_id": data.categoria_mp_id or "",
        "categoria_mp_codigo": (categoria or {}).get("catmp3", ""),
        "categoria_mp_nome": (categoria or {}).get("nome", ""),
        "unidade_estoque": data.unidade_estoque,
        "unidade_compra": data.unidade_compra,
        "fator_conversao": data.fator_conversao,
        "fornecedores": [{
            "fornecedor_id": fornecedor.get("id"),
            "fornecedor_nome": fornecedor.get("razao_social"),
            "codigo_fornecedor": "",
            "status_homologacao": (fornecedor.get("homologacao") or {}).get("status", "nao_iniciada"),
            "adicionado_em": now,
        }] if fornecedor else [],
        "atributos": {},
        "especificacoes_tecnicas": data.especificacoes_tecnicas or {},
        "enderecamento": data.enderecamento or {},
        "status": "ativo",
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.materiais.insert_one(doc)
    doc.pop("_id", None)
    await _audit(user, "material_cadastro_criado", "material", doc["id"], after=doc)
    return doc


@cadastros_master_router.put("/materiais-cadastro/{material_id}")
async def update_material_cadastro(material_id: str, data: MaterialCadastroUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    existing = await db.materiais.find_one({"tenant_id": user["tenant_id"], "id": material_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Material nao encontrado.")
    payload = data.model_dump(exclude_unset=True)
    updates: Dict[str, Any] = {"updated_at": _now_iso()}
    if "tipo" in payload:
        updates["tipo2"] = _material_tipo_from_business(payload["tipo"])
    if "nome" in payload:
        nome = _clean(payload.get("nome"))
        if not nome:
            raise HTTPException(status_code=422, detail="Nome do material e obrigatorio.")
        updates["nome"] = nome
    if "categoria_mp_id" in payload:
        categoria = None
        if payload.get("categoria_mp_id"):
            categoria = await db.cad_categorias_mp.find_one({"tenant_id": user["tenant_id"], "id": payload["categoria_mp_id"], "status": "ativa"}, {"_id": 0})
            if not categoria:
                raise HTTPException(status_code=409, detail="Categoria de MP/Insumo nao esta ativa.")
        updates["categoria_mp_id"] = payload.get("categoria_mp_id") or ""
        updates["categoria_mp_codigo"] = (categoria or {}).get("catmp3", "")
        updates["categoria_mp_nome"] = (categoria or {}).get("nome", "")
    if "fornecedor_id" in payload:
        fornecedor = None
        if payload.get("fornecedor_id"):
            fornecedor = await db.compras_fornecedores.find_one({"tenant_id": user["tenant_id"], "id": payload["fornecedor_id"]}, {"_id": 0})
            if not fornecedor:
                raise HTTPException(status_code=404, detail="Fornecedor nao encontrado.")
        updates["fornecedores"] = [{
            "fornecedor_id": fornecedor.get("id"),
            "fornecedor_nome": fornecedor.get("razao_social"),
            "codigo_fornecedor": "",
            "status_homologacao": (fornecedor.get("homologacao") or {}).get("status", "nao_iniciada"),
            "adicionado_em": _now_iso(),
        }] if fornecedor else []
    for field in ("subtipo", "unidade_estoque", "unidade_compra", "fator_conversao", "status"):
        if field in payload:
            updates[field] = payload[field]
    if "observacoes" in payload:
        updates["descricao"] = _clean(payload.get("observacoes"))
    for field in ("especificacoes_tecnicas", "enderecamento"):
        if field in payload:
            updates[field] = payload[field] if payload[field] is not None else {}
    await db.materiais.update_one({"tenant_id": user["tenant_id"], "id": material_id}, {"$set": updates})
    updated = await db.materiais.find_one({"tenant_id": user["tenant_id"], "id": material_id}, {"_id": 0})
    await _audit(user, "material_cadastro_atualizado", "material", material_id, before=existing, after=updated)
    return updated


@cadastros_master_router.delete("/materiais-cadastro/{material_id}")
async def delete_material_cadastro(material_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    existing = await db.materiais.find_one({"tenant_id": user["tenant_id"], "id": material_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Material nao encontrado.")
    now = _now_iso()
    payload = {"status": "inativo", "deleted_at": now, "updated_at": now}
    await db.materiais.update_one({"tenant_id": user["tenant_id"], "id": material_id}, {"$set": payload})
    updated = await db.materiais.find_one({"tenant_id": user["tenant_id"], "id": material_id}, {"_id": 0})
    await _audit(user, "material_cadastro_inativado", "material", material_id, before=existing, after=updated)
    return updated
