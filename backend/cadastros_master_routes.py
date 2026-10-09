"""
Modulo Cadastros - fonte unica de cadastros operacionais.

Este modulo consolida clientes, fornecedores, produtos finais, materiais e
categorias sem duplicar as colecoes que ja alimentam CRM, Compras, P&D e PCP.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pymongo import ReturnDocument
from pydantic import BaseModel, Field

from rbac import (
    COMERCIAL_FULL,
    COMPRAS_FULL,
    INVENTORY_WRITE_ROLES,
    PCP_PLANNING_WRITE_ROLES,
    PD_FULL,
    PD_READ,
    QA_APPROVERS,
    require_roles,
)
from validation_utils import is_valid_cnpj, normalize_cnpj
from workflow_engine import (
    audit_log,
    build_sku_code_v2,
    next_sequence,
    next_sku_per_pair_v2,
    normalise_cli4,
    suggest_cli4_candidates,
    create_workflow_task,
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
CUTOVER_READ_ROLES = READ_ROLES | INVENTORY_WRITE_ROLES
CUTOVER_LOGISTICS_ROLES = {"admin", "logistica", "estoque"}

LEGACY_REVIEW_COLLECTIONS = (
    "legacy_master_data_reviews",
    "legacy_formula_bom_reviews",
    "legacy_order_reviews",
    "legacy_op_reviews",
    "legacy_inventory_cutover_reviews",
    "legacy_procurement_reviews",
    "legacy_receipt_reviews",
    "legacy_quality_reviews",
    "legacy_expedition_reviews",
    "legacy_hr_reviews",
    "legacy_supplemental_history_reviews",
    "legacy_source_archive_reviews",
)
LEGACY_REVIEW_SECTOR_ROLES = {
    "pcp": {"admin", "pcp", "producao", "lider_pd", "engenharia_produto", "gestor", "sales_ops"},
    "logistica": {"admin", "logistica", "estoque", "compras", "qa", "pcp"},
    "comercial": COMERCIAL_FULL | {"admin", "gestor"},
    "cadastros": READ_ROLES | {"admin", "gestor"},
    "expedicao": {"admin", "logistica", "faturamento"},
    "qualidade": QA_APPROVERS | {"lider_pd", "formulador", "engenharia_produto", "compras", "sales_ops"},
    "pd": PD_READ | {"admin"},
    "compras": COMPRAS_FULL | {"admin"},
    "administracao_ti": {"admin"},
    "rh": {"admin"},
}


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
    await db.cadastro_bom_solicitacoes.create_index(
        [("tenant_id", 1), ("kickoff_id", 1), ("bom_chave", 1)], unique=True
    )
    await db.cadastro_bom_solicitacoes.create_index([("tenant_id", 1), ("status", 1), ("created_at", -1)])
    await _ensure_compatible_index(
        db.legacy_formula_bom_reviews,
        [("tenant_id", 1), ("source_node", 1), ("source_key", 1)],
        unique=True,
        name="tenant_source_key_unique",
    )
    await _ensure_compatible_index(
        db.legacy_formula_bom_reviews,
        [("tenant_id", 1), ("review_status", 1), ("record_type", 1)],
        name="tenant_review_type",
    )
    await _ensure_compatible_index(
        db.legacy_formula_bom_reviews,
        [("tenant_id", 1), ("target_sku_id", 1), ("legacy_version", -1)],
        name="tenant_target_sku_version",
    )
    for collection in (db.legacy_order_reviews, db.legacy_op_reviews):
        await _ensure_compatible_index(
            collection,
            [("tenant_id", 1), ("source_node", 1), ("source_key", 1)],
            unique=True,
            name="tenant_source_key_unique",
        )
        await _ensure_compatible_index(
            collection,
            [("tenant_id", 1), ("review_status", 1), ("record_type", 1)],
            name="tenant_review_type",
        )
        await _ensure_compatible_index(
            collection,
            [("tenant_id", 1), ("reconciliation_classification", 1)],
            name="tenant_classification",
        )
    await _ensure_compatible_index(
        db.legacy_master_data_reviews,
        [("tenant_id", 1), ("source_node", 1), ("source_key", 1)],
        unique=True,
        name="tenant_source_key_unique",
    )
    await _ensure_compatible_index(
        db.legacy_master_data_reviews,
        [("tenant_id", 1), ("review_status", 1), ("record_type", 1)],
        name="tenant_review_type",
    )
    await _ensure_compatible_index(
        db.legacy_inventory_cutover_reviews,
        [("tenant_id", 1), ("source_node", 1), ("source_key", 1)],
        unique=True,
        name="tenant_source_key_unique",
    )
    await _ensure_compatible_index(
        db.legacy_inventory_cutover_reviews,
        [("tenant_id", 1), ("review_status", 1), ("record_type", 1)],
        name="tenant_review_type",
    )
    await _ensure_compatible_index(
        db.legacy_inventory_cutover_reviews,
        [("tenant_id", 1), ("physical_status", 1)],
        name="tenant_physical_status",
    )
    for collection_name in LEGACY_REVIEW_COLLECTIONS:
        await _ensure_compatible_index(
            db[collection_name],
            [("tenant_id", 1), ("assigned_sector", 1), ("sector_status", 1)],
            name="tenant_sector_status",
        )


async def _ensure_compatible_index(collection, keys, *, unique=False, name=None):
    """Reuse an equivalent index even when an older environment named it differently."""
    expected_keys = list(keys)
    indexes = await collection.index_information()
    for existing_name, spec in indexes.items():
        existing_keys = [tuple(item) for item in spec.get("key", [])]
        if existing_keys == expected_keys and bool(spec.get("unique", False)) == bool(unique):
            return existing_name
    return await collection.create_index(keys, unique=unique, name=name)


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
    endereco: Dict[str, Any] = Field(default_factory=dict)


class FornecedorCadastroUpdate(BaseModel):
    razao_social: Optional[str] = None
    cnpj: Optional[str] = None
    nome_fantasia: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    categoria: Optional[str] = None
    observacoes: Optional[str] = None
    status_cadastro: Optional[str] = None
    endereco: Optional[Dict[str, Any]] = None


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


class CadastroBomUpdate(BaseModel):
    descricao: Optional[str] = None
    unidade: Optional[str] = None
    observacoes: Optional[str] = None
    anexo_file_ids: Optional[List[str]] = None


class CadastroBomConcluir(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[str] = None
    unidade_estoque: Optional[str] = None
    unidade_compra: Optional[str] = None
    categoria_mp_id: str = ""
    fornecedor_id: str = ""
    observacoes: str = ""
    anexo_file_ids: List[str] = Field(default_factory=list)


class LegacyStructureDecision(BaseModel):
    decision: Literal["aprovar", "reprovar"]
    justificativa: str = Field(min_length=3, max_length=1000)


class LegacyStructurePromotion(BaseModel):
    formula_review_id: str
    bom_review_id: str
    produto_pai_nome: str = Field(min_length=2, max_length=200)


class LegacyMaterialDecision(BaseModel):
    decision: Literal["aprovar", "reprovar"]
    justificativa: str = Field(min_length=3, max_length=1000)
    target_domain: Optional[Literal["materiais:MP", "materiais:EP", "materiais:ES", "materiais:RT", "fragrancias"]] = None
    unidade_estoque: Optional[Literal["kg", "g", "l", "ml", "un", "m"]] = None
    unidade_compra: Optional[Literal["kg", "g", "l", "ml", "un", "m"]] = None
    nome_corrigido: Optional[str] = Field(default=None, max_length=200)


class LegacySupplierDecision(BaseModel):
    decision: Literal["aprovar", "reprovar"]
    justificativa: str = Field(min_length=3, max_length=1000)
    resolution_mode: Optional[Literal["criar", "consolidar"]] = None
    cnpj_corrigido: Optional[str] = Field(default=None, max_length=30)
    razao_social_corrigida: Optional[str] = Field(default=None, max_length=200)
    target_supplier_id: Optional[str] = None


class LegacySkuDecision(BaseModel):
    decision: Literal["aprovar", "reprovar"]
    justificativa: str = Field(min_length=3, max_length=1000)
    resolution_mode: Optional[Literal["criar", "consolidar"]] = None
    cliente_id: Optional[str] = None
    codigo_corrigido: Optional[str] = Field(default=None, max_length=80)
    nome_corrigido: Optional[str] = Field(default=None, max_length=200)
    target_sku_id: Optional[str] = None


class LegacyLotQualityDecision(BaseModel):
    decision: Literal["aprovar", "reprovar", "reter"]
    justificativa: str = Field(min_length=3, max_length=1000)


class LegacyPhysicalConfirmation(BaseModel):
    decision: Literal["confirmar", "divergencia"]
    observacoes: str = Field(min_length=3, max_length=1000)
    endereco_codigo: Optional[str] = Field(default=None, max_length=80)
    quantidade_contada: Optional[float] = Field(default=None, ge=0)
    unidade: Optional[str] = Field(default=None, max_length=20)


class LegacyOPProductionAction(BaseModel):
    cliente_id: str = Field(min_length=1, max_length=120)
    linha_id: Optional[str] = Field(default=None, max_length=120)
    qtd_planejada: float = Field(gt=0)
    qtd_produzida_importada: float = Field(ge=0)
    justificativa: str = Field(min_length=10, max_length=1000)


class LegacySectorReviewAction(BaseModel):
    action: Literal["iniciar", "divergencia", "encaminhar", "concluir"]
    observacao: str = Field(default="", max_length=2000)
    expected_updated_at: Optional[str] = None


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
        "endereco": doc.get("endereco") or {},
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
    seq = await next_sequence(tenant_id, f"mat_{tipo2}_seq", start=0)
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
        "itens_bom_aguardando_cadastro": await db.cadastro_bom_solicitacoes.count_documents({
            "tenant_id": tenant_id,
            "status": {"$in": ["pendente_cadastro", "em_cadastro"]},
        }),
        "estruturas_legadas_em_revisao": await db.legacy_formula_bom_reviews.count_documents({
            "tenant_id": tenant_id,
            "review_status": "pendente_revisao",
        }),
        "cadastros_legados_bloqueados": await db.legacy_master_data_reviews.count_documents({
            "tenant_id": tenant_id,
            "activation_status": "bloqueado",
        }),
        "corte_estoque_legado_bloqueado": await db.legacy_inventory_cutover_reviews.count_documents({
            "tenant_id": tenant_id,
            "activation_status": "bloqueado",
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


def _bom_material_type(tipo_bom: str) -> str:
    value = _clean(tipo_bom).lower()
    if value == "mp_formula":
        return "MP"
    if value == "rotulo":
        return "RT"
    if value == "emb_secundaria":
        return "ES"
    return "EP"


def _bom_purchase_category(tipo_bom: str) -> str:
    return "mp" if _clean(tipo_bom).lower() == "mp_formula" else "embalagem"


async def _bom_request_or_404(request_id: str, tenant_id: str) -> dict:
    doc = await db.cadastro_bom_solicitacoes.find_one(
        {"id": request_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitacao de cadastro do BOM nao encontrada.")
    return doc


async def _decorate_bom_request(doc: dict) -> dict:
    file_ids = list(dict.fromkeys(doc.get("anexo_file_ids") or []))
    files = []
    if file_ids:
        files = await db.files.find(
            {"tenant_id": doc["tenant_id"], "id": {"$in": file_ids}, "is_deleted": False},
            {"_id": 0, "storage_path": 0},
        ).to_list(100)
    return {**doc, "anexos": files, "anexos_count": len(files)}


@cadastros_master_router.get("/solicitacoes-bom")
async def list_cadastro_bom_requests(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = Query(None),
):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status and status != "todos":
        query["status"] = status
    if q:
        query["$or"] = [
            {"descricao": {"$regex": q, "$options": "i"}},
            {"codigo_sugerido": {"$regex": q, "$options": "i"}},
            {"numero_kickoff": {"$regex": q, "$options": "i"}},
            {"cliente_nome": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.cadastro_bom_solicitacoes.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return {
        "solicitacoes": [await _decorate_bom_request(doc) for doc in docs],
        "total": len(docs),
        "pendentes": sum(1 for doc in docs if doc.get("status") in {"pendente_cadastro", "em_cadastro"}),
    }


@cadastros_master_router.post("/solicitacoes-bom/sincronizar")
async def sync_existing_kickoff_bom_requests(request: Request):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    from kickoff_routes import _sync_bom_registration_requests

    kickoffs = await db.kickoffs.find(
        {
            "tenant_id": user["tenant_id"],
            "status": {"$nin": ["arquivado", "substituida"]},
            "bom.0": {"$exists": True},
        },
        {"_id": 0},
    ).to_list(1000)
    results = []
    for kickoff in kickoffs:
        results.append(await _sync_bom_registration_requests(kickoff, user))
    return {
        "kickoffs_processados": len(results),
        "solicitacoes_criadas": sum(int(row.get("solicitacoes_criadas") or 0) for row in results),
        "pendentes": sum(int(row.get("pendentes") or 0) for row in results),
    }


@cadastros_master_router.put("/solicitacoes-bom/{request_id}")
async def update_cadastro_bom_request(request_id: str, data: CadastroBomUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    existing = await _bom_request_or_404(request_id, user["tenant_id"])
    if existing.get("status") == "cadastrado":
        raise HTTPException(status_code=409, detail="Item ja cadastrado e liberado para Compras.")
    payload = data.model_dump(exclude_unset=True)
    if "anexo_file_ids" in payload:
        payload["anexo_file_ids"] = list(dict.fromkeys(payload.get("anexo_file_ids") or []))
    payload.update({"status": "em_cadastro", "updated_at": _now_iso()})
    await db.cadastro_bom_solicitacoes.update_one(
        {"id": request_id, "tenant_id": user["tenant_id"]}, {"$set": payload}
    )
    updated = await _bom_request_or_404(request_id, user["tenant_id"])
    await _audit(user, "cadastro_bom_atualizado", "cadastro_bom", request_id, before=existing, after=updated)
    return await _decorate_bom_request(updated)


async def _ensure_material_from_bom_request(doc: dict, data: CadastroBomConcluir, user: dict) -> dict:
    tenant_id = user["tenant_id"]
    if doc.get("material_id"):
        material = await db.materiais.find_one({"id": doc["material_id"], "tenant_id": tenant_id}, {"_id": 0})
        if material:
            return material
    name = _clean(data.nome or doc.get("descricao"))
    existing = await db.materiais.find_one(
        {"tenant_id": tenant_id, "nome": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}, {"_id": 0}
    )
    if existing:
        return existing
    tipo2 = _material_tipo_from_business(data.tipo) if data.tipo else _bom_material_type(doc.get("tipo_bom", ""))
    unit = data.unidade_compra or doc.get("unidade") or "un"
    now = _now_iso()
    material = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "codigo_interno": await _next_material_code(tenant_id, tipo2),
        "tipo2": tipo2,
        "subtipo": doc.get("tipo_bom", ""),
        "nome": name,
        "descricao": _clean(data.observacoes or doc.get("observacoes")),
        "categoria_mp_id": data.categoria_mp_id or "",
        "categoria_mp_codigo": "",
        "categoria_mp_nome": "",
        "unidade_estoque": data.unidade_estoque or unit,
        "unidade_compra": unit,
        "fator_conversao": 1.0,
        "fornecedores": [],
        "atributos": {},
        "especificacoes_tecnicas": doc.get("especificacoes") or {},
        "enderecamento": {},
        "status": "ativo",
        "origem": "kickoff_bom",
        "kickoff_id": doc.get("kickoff_id"),
        "cadastro_solicitacao_id": doc["id"],
        "anexo_file_ids": list(dict.fromkeys((doc.get("anexo_file_ids") or []) + (data.anexo_file_ids or []))),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.materiais.insert_one(material)
    material.pop("_id", None)
    return material


async def _ensure_purchase_item_from_material(doc: dict, material: dict, user: dict) -> dict:
    tenant_id = user["tenant_id"]
    existing = await db.compras_itens.find_one(
        {"tenant_id": tenant_id, "codigo_interno": material["codigo_interno"]}, {"_id": 0}
    )
    if existing:
        return existing
    now = _now_iso()
    item = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "codigo_interno": material["codigo_interno"],
        "descricao": material.get("nome") or doc.get("descricao", ""),
        "categoria": _bom_purchase_category(doc.get("tipo_bom", "")),
        "sub_categoria": doc.get("tipo_bom", ""),
        "unidade_compra": material.get("unidade_compra") or doc.get("unidade") or "un",
        "fator_conversao_producao": material.get("fator_conversao") or 1.0,
        "estoque_minimo": None,
        "estoque_seguranca": 0.0,
        "lead_time_dias": 0,
        "requer_homologacao_cq": True,
        "fornecedores_homologados": [],
        "ultimo_preco_pago": None,
        "material_id": material["id"],
        "origem": "kickoff_bom_cadastro",
        "kickoff_id": doc.get("kickoff_id"),
        "created_at": now,
        "updated_at": now,
    }
    await db.compras_itens.insert_one(item)
    item.pop("_id", None)
    return item


async def _ensure_purchase_demand_from_bom(doc: dict, item: dict, user: dict) -> dict:
    tenant_id = user["tenant_id"]
    existing = await db.compras_demandas.find_one(
        {"tenant_id": tenant_id, "cadastro_solicitacao_id": doc["id"], "origem": "kickoff_bom_cadastro"},
        {"_id": 0},
    )
    if existing:
        return existing
    year = datetime.now(timezone.utc).year
    sequence = await next_sequence(tenant_id, f"compras_demanda_{year}", start=1)
    now = _now_iso()
    demand = {
        "id": _new_id(),
        "tenant_id": tenant_id,
        "numero_solicitacao": f"SC-{year}-{sequence:03d}",
        "origem": "kickoff_bom_cadastro",
        "kickoff_id": doc.get("kickoff_id"),
        "cadastro_solicitacao_id": doc["id"],
        "projeto_id": doc.get("projeto_id"),
        "item_id": item["id"],
        "item_codigo": item.get("codigo_interno", ""),
        "item_descricao": item.get("descricao", ""),
        "unidade_compra": item.get("unidade_compra", ""),
        "quantidade": max(float(doc.get("quantidade_total_pedido") or 0), 1.0),
        "data_limite_pedido": None,
        "urgente": False,
        "motivo": f"Novo item cadastrado pelo BOM do Kickoff {doc.get('numero_kickoff', '')}",
        "fornecedor_selecionado_id": None,
        "fornecedor_selecionado_nome": "",
        "condicao_comercial_id": None,
        "po_id": None,
        "status": "pendente",
        "cotacao_status": "pendente_retorno_solicitacao",
        "observacoes": "Liberado automaticamente por Cadastros para iniciar cotacao.",
        "solicitante_id": user["id"],
        "solicitante_nome": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.compras_demandas.insert_one(demand)
    demand.pop("_id", None)
    return demand


@cadastros_master_router.post("/solicitacoes-bom/{request_id}/concluir")
async def conclude_cadastro_bom_request(request_id: str, data: CadastroBomConcluir, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CATEGORY_WRITE_ROLES)
    doc = await _bom_request_or_404(request_id, user["tenant_id"])
    if doc.get("status") == "cadastrado" and doc.get("demanda_compra_id"):
        return await _decorate_bom_request(doc)
    attachment_ids = list(dict.fromkeys((doc.get("anexo_file_ids") or []) + (data.anexo_file_ids or [])))
    if not attachment_ids:
        raise HTTPException(
            status_code=422,
            detail="Anexe ao menos uma ficha, desenho, especificacao ou documento antes de concluir o cadastro.",
        )
    material = await _ensure_material_from_bom_request(doc, data, user)
    purchase_item = await _ensure_purchase_item_from_material(doc, material, user)
    demand = await _ensure_purchase_demand_from_bom(doc, purchase_item, user)
    now = _now_iso()
    updates = {
        "status": "cadastrado",
        "material_id": material["id"],
        "material_codigo": material.get("codigo_interno"),
        "compras_item_id": purchase_item["id"],
        "demanda_compra_id": demand["id"],
        "anexo_file_ids": attachment_ids,
        "concluido_por": user["id"],
        "concluido_por_nome": user.get("name", ""),
        "concluido_em": now,
        "updated_at": now,
    }
    await db.cadastro_bom_solicitacoes.update_one(
        {"id": request_id, "tenant_id": user["tenant_id"]}, {"$set": updates}
    )

    kickoff = await db.kickoffs.find_one({"id": doc.get("kickoff_id"), "tenant_id": user["tenant_id"]}, {"_id": 0})
    if kickoff:
        bom = list(kickoff.get("bom") or [])
        for line in bom:
            if line.get("cadastro_chave") == doc.get("bom_chave"):
                line.update({
                    "cadastro_status": "cadastrado",
                    "cadastro_solicitacao_id": request_id,
                    "material_id": material["id"],
                    "codigo_interno": material.get("codigo_interno"),
                    "compras_item_id": purchase_item["id"],
                    "cadastro_concluido_em": now,
                })
        pending = sum(1 for line in bom if line.get("cadastro_status") != "cadastrado")
        summary = {
            "status": "liberado_compras" if pending == 0 else "aguardando_cadastros",
            "total_bom": len(bom),
            "cadastrados": len(bom) - pending,
            "pendentes": pending,
            "updated_at": now,
        }
        await db.kickoffs.update_one(
            {"id": kickoff["id"], "tenant_id": user["tenant_id"]},
            {"$set": {"bom": bom, "cadastro_bom": summary, "updated_at": now}},
        )

    await create_workflow_task(
        tenant_id=user["tenant_id"],
        entity_type="compras_demanda",
        entity_id=demand["id"],
        title=f"Cotar novo item cadastrado: {purchase_item.get('codigo_interno')} - {purchase_item.get('descricao')}",
        description=(
            f"Item originado do BOM do Kickoff {doc.get('numero_kickoff', '')}. "
            "Cadastro e anexo concluidos; iniciar cotacao e registrar retorno dos fornecedores."
        ),
        category="compras",
        blocking=False,
        due_in_days=2,
        created_by=user,
        metadata={
            "module_origin": "cadastros",
            "kickoff_id": doc.get("kickoff_id"),
            "cadastro_solicitacao_id": request_id,
            "item_id": purchase_item["id"],
        },
    )
    updated = await _bom_request_or_404(request_id, user["tenant_id"])
    await _audit(user, "cadastro_bom_concluido", "cadastro_bom", request_id, before=doc, after=updated)
    return await _decorate_bom_request(updated)


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
        "endereco": data.endereco or {},
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
    for field in ("razao_social", "cnpj", "nome_fantasia", "observacoes", "status_cadastro"):
        if field in payload:
            updates[field] = payload[field]
    if "cnpj" in payload:
        if not is_valid_cnpj(payload["cnpj"]):
            raise HTTPException(status_code=422, detail="CNPJ invalido.")
        updates["cnpj_normalizado"] = normalize_cnpj(payload["cnpj"])
    if "endereco" in payload:
        updates["endereco"] = payload.get("endereco") or {}
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


def _legacy_review_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total": len(rows),
        "por_tipo": {},
        "por_status": {},
        "por_classificacao": {},
    }
    for row in rows:
        for bucket, value in (
            ("por_tipo", row.get("record_type") or "desconhecido"),
            ("por_status", row.get("review_status") or "desconhecido"),
            ("por_classificacao", row.get("reconciliation_classification") or "desconhecido"),
        ):
            summary[bucket][value] = summary[bucket].get(value, 0) + 1
    return summary


_LEGACY_SENSITIVE_KEY = re.compile(
    r"(^|_)(password|senha|secret|token|credential|private_key|api_key|jwt)(_|$)",
    re.IGNORECASE,
)


def _sanitize_legacy_payload(value: Any, key: str = "") -> Any:
    """Keep the complete legacy payload visible without exposing credentials."""
    if _LEGACY_SENSITIVE_KEY.search(str(key)):
        return "*** protegido ***"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_legacy_payload(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_legacy_payload(item) for item in value]
    return value


def _legacy_payload_coverage(value: Any) -> Dict[str, int]:
    counts = {"campos": 0, "preenchidos": 0, "vazios": 0}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
            return
        if isinstance(item, list):
            if not item:
                counts["campos"] += 1
                counts["vazios"] += 1
            else:
                for child in item:
                    visit(child)
            return
        counts["campos"] += 1
        if item is None or (isinstance(item, str) and not item.strip()):
            counts["vazios"] += 1
        else:
            counts["preenchidos"] += 1

    visit(value)
    return counts


def _legacy_review_collection(name: str):
    if name not in LEGACY_REVIEW_COLLECTIONS:
        raise HTTPException(status_code=422, detail="Colecao de revisao invalida.")
    try:
        return db[name]
    except TypeError:  # SimpleNamespace used by isolated unit tests.
        return getattr(db, name)


def _require_legacy_sector_access(user: Dict[str, Any], sector: str) -> None:
    roles = LEGACY_REVIEW_SECTOR_ROLES.get(sector)
    if not roles:
        raise HTTPException(status_code=422, detail="Setor de revisao invalido.")
    require_roles(user, roles)


@cadastros_master_router.get("/revisoes-setoriais")
async def list_sector_legacy_reviews(
    request: Request,
    sector: str = Query(...),
    sector_status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Expose routed legacy documents in their sector without promoting or copying them."""
    user = await _get_current_user(request)
    if sector not in LEGACY_REVIEW_SECTOR_ROLES:
        raise HTTPException(status_code=422, detail="Setor de revisao invalido.")
    _require_legacy_sector_access(user, sector)
    tenant_id = user["tenant_id"]
    base_query: Dict[str, Any] = {"tenant_id": tenant_id, "assigned_sector": sector}
    if sector_status and sector_status != "todos":
        base_query["sector_status"] = sector_status
    if q and q.strip():
        pattern = re.escape(q.strip())
        base_query["$or"] = [
            {"source_key": {"$regex": pattern, "$options": "i"}},
            {"source_group_key": {"$regex": pattern, "$options": "i"}},
            {"source_node": {"$regex": pattern, "$options": "i"}},
            {"record_type": {"$regex": pattern, "$options": "i"}},
            {"legacy_code": {"$regex": pattern, "$options": "i"}},
            {"legacy_name": {"$regex": pattern, "$options": "i"}},
            {"legacy_status": {"$regex": pattern, "$options": "i"}},
            {"review_stage": {"$regex": pattern, "$options": "i"}},
        ]
    projection = {
        "_id": 0,
        "source_payload": 0,
        "reconciliation": 0,
        "resolved_items": 0,
        "item_states": 0,
        "sector_history": 0,
    }
    rows: List[Dict[str, Any]] = []
    collection_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    for collection_name in LEGACY_REVIEW_COLLECTIONS:
        collection = db[collection_name]
        count = await collection.count_documents(base_query)
        if count:
            collection_counts[collection_name] = count
            collection_rows = await collection.find(base_query, projection).sort([
                ("sector_status", 1), ("source_node", 1), ("source_key", 1)
            ]).to_list(count)
            for row in collection_rows:
                row["review_collection"] = collection_name
            rows.extend(collection_rows)
        for status in ("pendente", "concluido", "em_revisao", "divergencia"):
            status_count = await collection.count_documents({
                "tenant_id": tenant_id,
                "assigned_sector": sector,
                "sector_status": status,
            })
            status_counts[status] = status_counts.get(status, 0) + status_count
    rows.sort(key=lambda row: (
        str(row.get("sector_status") or ""),
        str(row.get("source_node") or ""),
        str(row.get("source_key") or row.get("id") or ""),
    ))
    return {
        "registros": rows[skip:skip + limit],
        "resumo": {
            "total": sum(collection_counts.values()),
            "por_colecao": collection_counts,
            "por_status": status_counts,
            "setor": sector,
        },
        "limit": limit,
        "skip": skip,
        "has_more": skip + limit < sum(collection_counts.values()),
        "read_only_review_queue": True,
        "operational_records_created": False,
    }


@cadastros_master_router.get("/revisoes-setoriais/{collection_name}/{review_id}")
async def get_sector_legacy_review(collection_name: str, review_id: str, request: Request):
    """Return every available source field for an assigned sector review."""
    user = await _get_current_user(request)
    collection = _legacy_review_collection(collection_name)
    review = await collection.find_one(
        {"tenant_id": user["tenant_id"], "id": review_id},
        {"_id": 0},
    )
    if not review:
        raise HTTPException(status_code=404, detail="Revisao legada nao encontrada.")
    _require_legacy_sector_access(user, _clean(review.get("assigned_sector")))
    sanitized = _sanitize_legacy_payload(review)
    source_payload = sanitized.get("source_payload") or {}
    return {
        "registro": sanitized,
        "cobertura_origem": _legacy_payload_coverage(source_payload),
        "operational_activation_allowed": False,
        "next_sector": review.get("next_sector"),
    }


@cadastros_master_router.post("/revisoes-setoriais/{collection_name}/{review_id}/acao")
async def action_sector_legacy_review(
    collection_name: str,
    review_id: str,
    data: LegacySectorReviewAction,
    request: Request,
):
    """Move a single legacy review through its sector workflow without replaying operations."""
    user = await _get_current_user(request)
    collection = _legacy_review_collection(collection_name)
    query = {"tenant_id": user["tenant_id"], "id": review_id}
    review = await collection.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Revisao legada nao encontrada.")
    current_sector = _clean(review.get("assigned_sector"))
    _require_legacy_sector_access(user, current_sector)
    current_status = _clean(review.get("sector_status")) or "pendente"
    if current_status == "concluido":
        raise HTTPException(status_code=409, detail="Esta revisao setorial ja foi concluida.")
    if data.expected_updated_at and data.expected_updated_at != review.get("updated_at"):
        raise HTTPException(status_code=409, detail="A revisao foi alterada; atualize antes de continuar.")

    note = _clean(data.observacao)
    if data.action in {"divergencia", "encaminhar", "concluir"} and len(note) < 10:
        raise HTTPException(status_code=422, detail="Informe uma observacao com pelo menos 10 caracteres.")

    now = _now_iso()
    next_sector = _clean(review.get("next_sector"))
    updates: Dict[str, Any] = {
        "updated_at": now,
        "sector_last_action": data.action,
        "sector_last_note": note,
        "sector_last_user_id": user.get("id"),
        "sector_last_user_name": user.get("name") or user.get("email") or "",
    }
    target_sector = current_sector
    if data.action == "iniciar":
        updates.update({"sector_status": "em_revisao", "sector_started_at": now})
    elif data.action == "divergencia":
        updates.update({"sector_status": "divergencia", "sector_divergence_at": now})
    elif data.action == "encaminhar":
        if not next_sector:
            raise HTTPException(status_code=409, detail="Esta revisao nao possui proximo setor configurado.")
        target_sector = next_sector
        updates.update({
            "assigned_sector": next_sector,
            "previous_sector": current_sector,
            "next_sector": None,
            "sector_status": "pendente",
            "sector_forwarded_at": now,
        })
    else:
        if next_sector:
            raise HTTPException(status_code=409, detail="Encaminhe ao proximo setor antes de concluir.")
        updates.update({"sector_status": "concluido", "sector_completed_at": now})

    guarded_query = {**query, "assigned_sector": current_sector, "sector_status": review.get("sector_status")}
    if data.expected_updated_at:
        guarded_query["updated_at"] = data.expected_updated_at
    history = {
        "action": data.action,
        "from": current_sector,
        "to": target_sector,
        "status_before": current_status,
        "at": now,
        "user_id": user.get("id"),
        "user_name": user.get("name") or user.get("email") or "",
        "note": note,
    }
    result = await collection.update_one(guarded_query, {"$set": updates, "$push": {"sector_history": history}})
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="A revisao mudou durante a operacao; recarregue a fila.")
    updated = await collection.find_one(query, {"_id": 0, "source_payload": 0})
    await _audit(
        user,
        f"revisao_legada_setorial_{data.action}",
        collection_name,
        review_id,
        before={key: review.get(key) for key in ("assigned_sector", "next_sector", "sector_status")},
        after={key: updated.get(key) for key in ("assigned_sector", "next_sector", "sector_status")},
    )
    return {
        "registro": updated,
        "operational_records_created": False,
        "message": "Revisao encaminhada ao proximo setor." if data.action == "encaminhar" else "Revisao setorial atualizada.",
    }


async def _validate_legacy_review_materials(
    review: Dict[str, Any], expected_type: str, session=None
) -> List[Dict[str, Any]]:
    if review.get("record_type") != expected_type:
        raise HTTPException(status_code=409, detail=f"Registro nao e do tipo {expected_type}.")
    if not review.get("target_sku_id"):
        raise HTTPException(status_code=409, detail="Registro sem SKU de destino resolvido.")
    if review.get("reconciliation_classification") != "safe_full":
        raise HTTPException(
            status_code=409,
            detail="Registro possui material, quantidade ou linha pendente e nao pode ser aprovado.",
        )
    items = review.get("resolved_items") or []
    if not items:
        raise HTTPException(status_code=409, detail="Registro sem itens resolvidos.")
    allowed_types = {"MP", "FR"} if expected_type == "formula" else {"EP", "ES", "RT"}
    if any(item.get("target_type") not in allowed_types for item in items):
        raise HTTPException(
            status_code=409,
            detail=f"Tipos de material invalidos para {expected_type}; permitidos: {', '.join(sorted(allowed_types))}.",
        )
    if any(float(item.get("quantity") or 0) <= 0 for item in items):
        raise HTTPException(status_code=409, detail="Todos os itens devem possuir quantidade positiva.")
    if expected_type == "formula":
        total = sum(float(item.get("quantity") or 0) for item in items)
        if abs(total - 100.0) > 0.01:
            raise HTTPException(status_code=409, detail=f"Formula soma {total:.4f}%; esperado 100%.")

    material_snapshots: List[Dict[str, Any]] = []
    for item in items:
        collection = db.fragrancias if item.get("target_domain") == "fragrancias" else db.materiais
        material = await collection.find_one(
            {"tenant_id": review["tenant_id"], "id": item.get("target_material_id")},
            {"_id": 0},
            session=session,
        )
        if not material:
            raise HTTPException(
                status_code=409,
                detail=f"Material resolvido nao existe mais: {item.get('target_material_code')}.",
            )
        material_snapshots.append(material)
    return material_snapshots


@cadastros_master_router.get("/estruturas-legadas")
async def list_legacy_structures(
    request: Request,
    record_type: Optional[str] = None,
    review_status: Optional[str] = None,
    q: Optional[str] = Query(None),
):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if record_type and record_type != "todos":
        query["record_type"] = record_type
    if review_status and review_status != "todos":
        query["review_status"] = review_status
    if q:
        query["$or"] = [
            {"legacy_sku": {"$regex": q, "$options": "i"}},
            {"target_sku_code": {"$regex": q, "$options": "i"}},
            {"source_key": {"$regex": q, "$options": "i"}},
        ]
    projection = {"_id": 0, "source_payload": 0, "resolved_items": 0}
    rows = await db.legacy_formula_bom_reviews.find(query, projection).sort([
        ("target_sku_code", 1), ("record_type", 1), ("legacy_version", -1)
    ]).to_list(1000)
    return {"registros": rows, "resumo": _legacy_review_summary(rows)}


@cadastros_master_router.get("/revisoes-pedidos-ops")
async def list_legacy_order_op_reviews(
    request: Request,
    record_type: Optional[str] = None,
    classification: Optional[str] = None,
    q: Optional[str] = Query(None),
    limit: int = Query(250, ge=1, le=500),
):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    tenant_id = user["tenant_id"]
    collection = db.legacy_op_reviews if record_type == "production_order" else db.legacy_order_reviews
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if record_type and record_type != "todos":
        query["record_type"] = record_type
    if classification and classification != "todos":
        query["reconciliation_classification"] = classification
    if q:
        pattern = re.escape(q.strip())
        query["$or"] = [
            {"source_key": {"$regex": pattern, "$options": "i"}},
            {"legacy_status": {"$regex": pattern, "$options": "i"}},
            {"target_sku_code": {"$regex": pattern, "$options": "i"}},
            {"reconciliation.legacy_client": {"$regex": pattern, "$options": "i"}},
            {"reconciliation.legacy_lot": {"$regex": pattern, "$options": "i"}},
        ]
    projection = {"_id": 0, "source_payload": 0, "reconciliation": 0}
    rows = await collection.find(query, projection).sort([("source_key", 1)]).to_list(limit)
    summary = {
        "commercial_order": await db.legacy_order_reviews.count_documents({"tenant_id": tenant_id, "record_type": "commercial_order"}),
        "order_line": await db.legacy_order_reviews.count_documents({"tenant_id": tenant_id, "record_type": "order_line"}),
        "production_order": await db.legacy_op_reviews.count_documents({"tenant_id": tenant_id, "record_type": "production_order"}),
        "manual_review": (
            await db.legacy_order_reviews.count_documents({"tenant_id": tenant_id, "reconciliation_classification": "manual_review"})
            + await db.legacy_op_reviews.count_documents({"tenant_id": tenant_id, "reconciliation_classification": "manual_review"})
        ),
        "open_requires_decision": await db.legacy_op_reviews.count_documents({
            "tenant_id": tenant_id, "reconciliation_classification": "open_requires_decision"
        }),
    }
    return {"registros": rows, "resumo": summary, "limit": limit}


@cadastros_master_router.get("/revisoes-cadastros-bloqueados")
async def list_blocked_master_data_reviews(
    request: Request,
    record_type: Optional[str] = None,
    q: Optional[str] = Query(None),
):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    tenant_id = user["tenant_id"]
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if record_type and record_type != "todos":
        query["record_type"] = record_type
    if q:
        pattern = re.escape(q.strip())
        query["$or"] = [
            {"source_key": {"$regex": pattern, "$options": "i"}},
            {"legacy_code": {"$regex": pattern, "$options": "i"}},
            {"legacy_name": {"$regex": pattern, "$options": "i"}},
            {"reason": {"$regex": pattern, "$options": "i"}},
        ]
    projection = {"_id": 0, "source_payload": 0}
    rows = await db.legacy_master_data_reviews.find(query, projection).sort([
        ("record_type", 1), ("legacy_code", 1)
    ]).to_list(500)
    summary = {
        kind: await db.legacy_master_data_reviews.count_documents({"tenant_id": tenant_id, "record_type": kind})
        for kind in ("supplier", "material", "sku")
    }
    summary["total"] = sum(summary.values())
    return {"registros": rows, "resumo": summary}


@cadastros_master_router.get("/revisoes-corte-estoque")
async def list_inventory_cutover_reviews(
    request: Request,
    record_type: Optional[str] = None,
    physical_status: Optional[str] = None,
    assigned_sector: Optional[str] = None,
    q: Optional[str] = Query(None),
    limit: int = Query(300, ge=1, le=500),
):
    user = await _get_current_user(request)
    require_roles(user, CUTOVER_READ_ROLES)
    tenant_id = user["tenant_id"]
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if record_type and record_type != "todos":
        query["record_type"] = record_type
    if physical_status and physical_status != "todos":
        query["physical_status"] = physical_status
    if assigned_sector and assigned_sector != "todos":
        if assigned_sector not in {"qualidade", "logistica"}:
            raise HTTPException(status_code=422, detail="Setor de revisao invalido.")
        query["assigned_sector"] = assigned_sector
    if q:
        pattern = re.escape(q.strip())
        query["$or"] = [
            {"legacy_code": {"$regex": pattern, "$options": "i"}},
            {"legacy_name": {"$regex": pattern, "$options": "i"}},
            {"legacy_material_code": {"$regex": pattern, "$options": "i"}},
            {"legacy_address_code": {"$regex": pattern, "$options": "i"}},
        ]
    projection = {"_id": 0, "source_payload": 0}
    rows = await db.legacy_inventory_cutover_reviews.find(query, projection).sort([
        ("record_type", 1), ("legacy_code", 1)
    ]).to_list(limit)
    summary_base = {"tenant_id": tenant_id}
    if assigned_sector and assigned_sector != "todos":
        summary_base["assigned_sector"] = assigned_sector
    summary = {
        kind: await db.legacy_inventory_cutover_reviews.count_documents({**summary_base, "record_type": kind})
        for kind in ("address", "lot")
    }
    summary["total"] = sum(summary.values())
    summary["blocked"] = await db.legacy_inventory_cutover_reviews.count_documents({
        **summary_base, "activation_status": "bloqueado", "operational_eligible": False,
    })
    return {"registros": rows, "resumo": summary, "limit": limit}


@cadastros_master_router.get("/revisoes-corte-estoque/{review_id}")
async def get_inventory_cutover_review(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CUTOVER_READ_ROLES)
    review = await db.legacy_inventory_cutover_reviews.find_one(
        {"tenant_id": user["tenant_id"], "id": review_id}, {"_id": 0}
    )
    if not review:
        raise HTTPException(status_code=404, detail="Registro de corte fisico legado nao encontrado.")
    return review


@cadastros_master_router.post("/revisoes-corte-estoque/{review_id}/decisao-cq")
async def decide_inventory_cutover_quality(review_id: str, data: LegacyLotQualityDecision, request: Request):
    user = await _get_current_user(request)
    require_roles(user, QA_APPROVERS)
    tenant_id = user["tenant_id"]
    query = {
        "tenant_id": tenant_id, "id": review_id, "record_type": "lot",
        "assigned_sector": "qualidade", "sector_status": "pendente",
        "activation_status": "bloqueado", "operational_eligible": False,
    }
    review = await db.legacy_inventory_cutover_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=409, detail="Lote nao esta pendente na fila de Qualidade.")
    now = _now_iso()
    history = list(review.get("sector_history") or [])
    history.append({
        "sector": "qualidade", "stage": "validacao_cq_lote_legado", "status": data.decision,
        "at": now, "by": user["id"], "by_name": user.get("name", ""),
        "reason": _clean(data.justificativa),
    })
    updates: Dict[str, Any] = {
        "quality_decision": data.decision, "quality_justification": _clean(data.justificativa),
        "quality_reviewed_at": now, "quality_reviewed_by": user["id"],
        "quality_reviewed_by_name": user.get("name", ""), "sector_history": history, "updated_at": now,
    }
    if data.decision == "aprovar":
        updates.update({
            "assigned_sector": "logistica", "next_sector": None,
            "review_stage": "conferencia_fisica_lote", "sector_status": "pendente",
            "review_status": "cq_aprovado_aguardando_logistica",
        })
    else:
        updates.update({
            "sector_status": "reprovado" if data.decision == "reprovar" else "retido",
            "review_status": "reprovado_cq" if data.decision == "reprovar" else "retido_cq",
        })
    result = await db.legacy_inventory_cutover_reviews.update_one(query, {"$set": updates})
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="O lote foi alterado por outro usuario; recarregue a fila.")
    updated = await db.legacy_inventory_cutover_reviews.find_one(
        {"tenant_id": tenant_id, "id": review_id}, {"_id": 0, "source_payload": 0}
    )
    await _audit(user, f"corte_legado_cq_{data.decision}", "legacy_inventory_cutover_review", review_id, before=review, after=updated)
    return updated


@cadastros_master_router.post("/revisoes-corte-estoque/{review_id}/conferencia-logistica")
async def confirm_inventory_cutover_logistics(review_id: str, data: LegacyPhysicalConfirmation, request: Request):
    user = await _get_current_user(request)
    require_roles(user, CUTOVER_LOGISTICS_ROLES)
    tenant_id = user["tenant_id"]
    query = {
        "tenant_id": tenant_id, "id": review_id, "assigned_sector": "logistica",
        "sector_status": "pendente", "activation_status": "bloqueado", "operational_eligible": False,
    }
    review = await db.legacy_inventory_cutover_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=409, detail="Registro nao esta pendente na fila de Logistica.")
    if review.get("record_type") == "lot" and review.get("quality_decision") != "aprovar":
        raise HTTPException(status_code=409, detail="O lote precisa ser aprovado pelo CQ antes da conferencia logistica.")
    if data.decision == "confirmar" and review.get("record_type") == "lot":
        if data.quantidade_contada is None or not _clean(data.unidade) or not _clean(data.endereco_codigo):
            raise HTTPException(status_code=422, detail="Quantidade contada, unidade e endereco sao obrigatorios para o lote.")
    if data.decision == "confirmar" and review.get("record_type") == "address" and not _clean(data.endereco_codigo):
        raise HTTPException(status_code=422, detail="Confirme o codigo fisico do endereco.")
    now = _now_iso()
    history = list(review.get("sector_history") or [])
    status = "concluido" if data.decision == "confirmar" else "divergencia"
    history.append({
        "sector": "logistica", "stage": review.get("review_stage"), "status": status,
        "at": now, "by": user["id"], "by_name": user.get("name", ""),
        "reason": _clean(data.observacoes),
    })
    confirmation = {
        "decision": data.decision, "endereco_codigo": _clean(data.endereco_codigo),
        "quantidade_contada": data.quantidade_contada, "unidade": _clean(data.unidade),
        "observacoes": _clean(data.observacoes), "confirmed_at": now,
        "confirmed_by": user["id"], "confirmed_by_name": user.get("name", ""),
    }
    updates = {
        "sector_status": status, "physical_status": "conferido" if data.decision == "confirmar" else "divergente",
        "physical_count_confirmed": data.decision == "confirmar", "physical_confirmation": confirmation,
        "review_status": "pronto_para_corte" if data.decision == "confirmar" else "pendente_revisao",
        "sector_history": history, "updated_at": now,
    }
    result = await db.legacy_inventory_cutover_reviews.update_one(query, {"$set": updates})
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="O registro foi alterado por outro usuario; recarregue a fila.")
    updated = await db.legacy_inventory_cutover_reviews.find_one(
        {"tenant_id": tenant_id, "id": review_id}, {"_id": 0, "source_payload": 0}
    )
    await _audit(user, f"corte_legado_logistica_{data.decision}", "legacy_inventory_cutover_review", review_id, before=review, after=updated)
    return updated


@cadastros_master_router.get("/revisoes-cadastros-bloqueados/{review_id}")
async def get_blocked_master_data_review(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    review = await db.legacy_master_data_reviews.find_one(
        {"tenant_id": user["tenant_id"], "id": review_id}, {"_id": 0}
    )
    if not review:
        raise HTTPException(status_code=404, detail="Pendencia de cadastro legado nao encontrada.")
    return review


@cadastros_master_router.post("/revisoes-cadastros-bloqueados/{review_id}/decisao-material")
async def decide_blocked_legacy_material(review_id: str, data: LegacyMaterialDecision, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    query = {"tenant_id": user["tenant_id"], "id": review_id, "record_type": "material"}
    review = await db.legacy_master_data_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Material legado bloqueado nao encontrado.")
    if review.get("activation_status") == "promovido":
        raise HTTPException(status_code=409, detail="Material ja promovido; a revisao tornou-se imutavel.")

    resolution = None
    if data.decision == "aprovar":
        if not data.target_domain or not data.unidade_estoque or not data.unidade_compra:
            raise HTTPException(status_code=422, detail="Dominio, unidade de estoque e unidade de compra sao obrigatorios.")
        if data.target_domain in {"materiais:EP", "materiais:ES", "materiais:RT"} and data.unidade_estoque != "un":
            raise HTTPException(status_code=422, detail="EP, ES e RT devem usar unidade de estoque 'un'.")
        if data.target_domain == "fragrancias" and data.unidade_estoque not in {"kg", "g", "l", "ml"}:
            raise HTTPException(status_code=422, detail="Fragrancia deve usar unidade de massa ou volume.")
        name = _clean(data.nome_corrigido) or _clean(review.get("legacy_name"))
        if len(name) < 2:
            raise HTTPException(status_code=422, detail="Informe um nome valido para o material.")
        resolution = {
            "target_domain": data.target_domain,
            "unidade_estoque": data.unidade_estoque,
            "unidade_compra": data.unidade_compra,
            "nome": name,
        }
    now = _now_iso()
    updates: Dict[str, Any] = {
        "review_status": "aprovado" if data.decision == "aprovar" else "reprovado",
        "review_decision": data.decision,
        "review_justification": _clean(data.justificativa),
        "resolution": resolution,
        "reviewed_by": user["id"],
        "reviewed_by_name": user.get("name", ""),
        "reviewed_at": now,
        "updated_at": now,
    }
    await db.legacy_master_data_reviews.update_one(query, {"$set": updates})
    updated = await db.legacy_master_data_reviews.find_one(query, {"_id": 0, "source_payload": 0})
    await _audit(user, f"material_legado_{updates['review_status']}", "legacy_master_data_review", review_id, before=review, after=updated)
    return updated


@cadastros_master_router.post("/revisoes-cadastros-bloqueados/{review_id}/promover-material")
async def promote_blocked_legacy_material(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    tenant_id = user["tenant_id"]
    query = {"tenant_id": tenant_id, "id": review_id, "record_type": "material"}
    review = await db.legacy_master_data_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Material legado bloqueado nao encontrado.")
    if review.get("activation_status") == "promovido":
        promotion = review.get("promotion") or {}
        target_collection = promotion.get("collection")
        existing = await db[target_collection].find_one(
            {"tenant_id": tenant_id, "id": promotion.get("target_id")}, {"_id": 0}
        ) if target_collection in {"materiais", "fragrancias"} else None
        if existing:
            return {"status": "ja_promovido", "registro": existing}
    if review.get("review_status") != "aprovado" or not review.get("resolution"):
        raise HTTPException(status_code=409, detail="A classificacao precisa ser aprovada antes da promocao.")
    mongo_client = getattr(db, "client", None)
    if not mongo_client or not hasattr(mongo_client, "start_session"):
        raise HTTPException(status_code=503, detail="Promocao exige MongoDB com transacoes.")

    target_id = _new_id()
    now = _now_iso()
    promoted_doc = None
    target_collection = None
    try:
        async with await mongo_client.start_session() as session:
            async with session.start_transaction():
                current = await db.legacy_master_data_reviews.find_one(query, {"_id": 0}, session=session)
                if not current or current.get("review_status") != "aprovado" or current.get("activation_status") != "bloqueado":
                    raise HTTPException(status_code=409, detail="Estado da revisao mudou; recarregue a tela.")
                resolution = current.get("resolution") or {}
                domain = resolution.get("target_domain")
                if domain not in {"materiais:MP", "materiais:EP", "materiais:ES", "materiais:RT", "fragrancias"}:
                    raise HTTPException(status_code=409, detail="Dominio aprovado e invalido.")
                target_collection = "fragrancias" if domain == "fragrancias" else "materiais"
                duplicate = await db[target_collection].find_one({
                    "tenant_id": tenant_id, "legacy_material_code": current["source_key"]
                }, {"_id": 0}, session=session)
                if duplicate:
                    raise HTTPException(status_code=409, detail="O material legado ja existe no cadastro operacional.")

                tipo2 = "FR" if domain == "fragrancias" else domain.split(":", 1)[1]
                counter_name = "fr_seq" if tipo2 == "FR" else f"mat_{tipo2}_seq"
                counter = await db.counters.find_one_and_update(
                    {"_id": f"{counter_name}:{tenant_id}"},
                    {"$inc": {"seq": 1}, "$setOnInsert": {"start": 0}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                    session=session,
                )
                code = f"{tipo2}-{int(counter['seq']):05d}"
                raw = current.get("source_payload") or {}
                common = {
                    "id": target_id, "tenant_id": tenant_id, "codigo_interno": code,
                    "descricao": _clean(raw.get("especificacoesTecnicas")),
                    "fornecedores": [], "legacy_material_code": current["source_key"],
                    "legacy_type": _clean(raw.get("tipo")), "_legacy_supplier_refs": raw.get("fornecedores") or {},
                    "created_by": user["id"], "created_by_name": user.get("name", ""),
                    "created_at": now, "updated_at": now,
                    "_migration": {"source": "firebase-current", "approved_rule": "human_review_material_promotion_v1", "review_id": review_id},
                }
                if target_collection == "fragrancias":
                    promoted_doc = {
                        **common, "inspiracao": resolution["nome"],
                        "status": "ativa" if raw.get("ativo", True) is not False else "inativa",
                        "unidade_estoque_legacy": resolution["unidade_estoque"],
                    }
                else:
                    try:
                        factor = float(raw.get("fatorConversao") or 1)
                    except (TypeError, ValueError):
                        factor = 1.0
                    promoted_doc = {
                        **common, "tipo2": tipo2, "subtipo": "Legado revisado", "nome": resolution["nome"],
                        "unidade_estoque": resolution["unidade_estoque"], "unidade_compra": resolution["unidade_compra"],
                        "fator_conversao": factor, "atributos": {},
                        "status": "ativo" if raw.get("ativo", True) is not False else "inativo",
                    }
                await db[target_collection].insert_one(promoted_doc, session=session)
                promotion = {
                    "collection": target_collection, "target_id": target_id, "target_code": code,
                    "promoted_at": now, "promoted_by": user["id"], "promoted_by_name": user.get("name", ""),
                }
                result = await db.legacy_master_data_reviews.update_one(
                    {**query, "review_status": "aprovado", "activation_status": "bloqueado"},
                    {"$set": {"activation_status": "promovido", "operational_eligible": True, "promotion": promotion, "updated_at": now}},
                    session=session,
                )
                if result.modified_count != 1:
                    raise HTTPException(status_code=409, detail="A revisao foi alterada durante a promocao.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha na promocao atomica de material legado")
        raise HTTPException(status_code=500, detail="Falha atomica ao promover material; nenhuma alteracao foi confirmada.") from exc
    promoted_doc.pop("_id", None)
    await _audit(user, "material_legado_promovido", target_collection, target_id, after=promoted_doc)
    return {"status": "promovido", "registro": promoted_doc}


@cadastros_master_router.post("/revisoes-cadastros-bloqueados/{review_id}/decisao-fornecedor")
async def decide_blocked_legacy_supplier(review_id: str, data: LegacySupplierDecision, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    query = {"tenant_id": user["tenant_id"], "id": review_id, "record_type": "supplier"}
    review = await db.legacy_master_data_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Fornecedor legado bloqueado nao encontrado.")
    if review.get("activation_status") in {"promovido", "consolidado"}:
        raise HTTPException(status_code=409, detail="Fornecedor ja resolvido; a revisao tornou-se imutavel.")

    resolution = None
    if data.decision == "aprovar":
        if data.resolution_mode == "criar":
            cnpj = normalize_cnpj(data.cnpj_corrigido)
            if not cnpj or not is_valid_cnpj(cnpj):
                raise HTTPException(status_code=422, detail="Informe um CNPJ valido para criar o fornecedor.")
            name = _clean(data.razao_social_corrigida) or _clean(review.get("legacy_name"))
            if len(name) < 2:
                raise HTTPException(status_code=422, detail="Informe uma razao social valida.")
            existing = await db.compras_fornecedores.find_one(
                {"tenant_id": user["tenant_id"], "cnpj_normalizado": cnpj}, {"_id": 0, "id": 1, "razao_social": 1}
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"CNPJ ja pertence a {existing.get('razao_social')}; use consolidacao.",
                )
            resolution = {"mode": "criar", "cnpj": cnpj, "razao_social": name}
        elif data.resolution_mode == "consolidar":
            target = await db.compras_fornecedores.find_one(
                {"tenant_id": user["tenant_id"], "id": data.target_supplier_id},
                {"_id": 0, "id": 1, "codigo_interno": 1, "razao_social": 1, "cnpj_normalizado": 1},
            )
            if not target:
                raise HTTPException(status_code=404, detail="Fornecedor de destino nao encontrado.")
            resolution = {
                "mode": "consolidar", "target_supplier_id": target["id"],
                "target_supplier_code": target.get("codigo_interno"), "target_supplier_name": target.get("razao_social"),
                "target_supplier_cnpj": target.get("cnpj_normalizado"),
            }
        else:
            raise HTTPException(status_code=422, detail="Escolha criar ou consolidar o fornecedor.")

    now = _now_iso()
    updates = {
        "review_status": "aprovado" if data.decision == "aprovar" else "reprovado",
        "review_decision": data.decision, "review_justification": _clean(data.justificativa),
        "resolution": resolution, "reviewed_by": user["id"], "reviewed_by_name": user.get("name", ""),
        "reviewed_at": now, "updated_at": now,
    }
    await db.legacy_master_data_reviews.update_one(query, {"$set": updates})
    updated = await db.legacy_master_data_reviews.find_one(query, {"_id": 0, "source_payload": 0})
    await _audit(user, f"fornecedor_legado_{updates['review_status']}", "legacy_master_data_review", review_id, before=review, after=updated)
    return updated


@cadastros_master_router.post("/revisoes-cadastros-bloqueados/{review_id}/promover-fornecedor")
async def promote_blocked_legacy_supplier(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    tenant_id = user["tenant_id"]
    query = {"tenant_id": tenant_id, "id": review_id, "record_type": "supplier"}
    review = await db.legacy_master_data_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Fornecedor legado bloqueado nao encontrado.")
    if review.get("activation_status") in {"promovido", "consolidado"}:
        return {"status": review["activation_status"], "resolucao": review.get("promotion") or {}}
    if review.get("review_status") != "aprovado" or not review.get("resolution"):
        raise HTTPException(status_code=409, detail="A resolucao precisa ser aprovada antes da promocao.")
    mongo_client = getattr(db, "client", None)
    if not mongo_client or not hasattr(mongo_client, "start_session"):
        raise HTTPException(status_code=503, detail="Promocao exige MongoDB com transacoes.")

    now = _now_iso()
    target_doc = None
    final_status = "promovido"
    try:
        async with await mongo_client.start_session() as session:
            async with session.start_transaction():
                current = await db.legacy_master_data_reviews.find_one(query, {"_id": 0}, session=session)
                if not current or current.get("review_status") != "aprovado" or current.get("activation_status") != "bloqueado":
                    raise HTTPException(status_code=409, detail="Estado da revisao mudou; recarregue a tela.")
                resolution = current.get("resolution") or {}
                if resolution.get("mode") == "consolidar":
                    target_doc = await db.compras_fornecedores.find_one(
                        {"tenant_id": tenant_id, "id": resolution.get("target_supplier_id")}, {"_id": 0}, session=session
                    )
                    if not target_doc:
                        raise HTTPException(status_code=409, detail="Fornecedor de consolidacao nao existe mais.")
                    final_status = "consolidado"
                elif resolution.get("mode") == "criar":
                    cnpj = resolution.get("cnpj")
                    if await db.compras_fornecedores.find_one({"tenant_id": tenant_id, "cnpj_normalizado": cnpj}, session=session):
                        raise HTTPException(status_code=409, detail="CNPJ passou a existir; revise e consolide o fornecedor.")
                    counter = await db.counters.find_one_and_update(
                        {"_id": f"compras_fornecedores:{tenant_id}"},
                        {"$inc": {"seq": 1}, "$setOnInsert": {"start": 0}}, upsert=True,
                        return_document=ReturnDocument.AFTER, session=session,
                    )
                    raw = current.get("source_payload") or {}
                    contact_name, contact_phone, contact_email = _clean(raw.get("contatoNome")), _clean(raw.get("contatoTelefone")), _clean(raw.get("contatoEmail")).lower()
                    contacts = [{
                        "id": _new_id(), "nome": contact_name, "cargo": "", "telefone": contact_phone,
                        "email": contact_email, "whatsapp": contact_phone, "principal_compras": True,
                    }] if contact_name or contact_phone or contact_email else []
                    target_doc = {
                        "id": _new_id(), "tenant_id": tenant_id,
                        "codigo_interno": f"FOR-{int(counter['seq']):05d}",
                        "razao_social": resolution["razao_social"], "nome_fantasia": _clean(raw.get("nomeFantasia")),
                        "cnpj": cnpj, "cnpj_normalizado": cnpj, "ie": "", "im": "",
                        "endereco": {key: (_clean(raw.get(key)).upper() if key == "uf" else _clean(raw.get(key))) for key in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf")},
                        "contatos": contacts, "categorias": [_clean(raw.get("tipo"))] if _clean(raw.get("tipo")) else [],
                        "site": _clean(raw.get("site")), "condicao_pagamento": _clean(raw.get("condicaoPagamento")),
                        "certificacoes": _clean(raw.get("certificacoes")), "legacy_webmais_id": _clean(raw.get("importadoWebmaisId")),
                        "homologacao": {"status": "nao_iniciada", "data_homologacao": None, "proxima_reavaliacao": None, "documentos_file_ids": [], "historico_rncs_count": 0, "historico_rncs_criticas_12m": 0},
                        "status_cadastro": "ativo" if raw.get("ativo", True) is not False else "inativo",
                        "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": now, "updated_at": now,
                        "_migration": {"source": "firebase-current", "approved_rule": "human_review_supplier_promotion_v1", "review_id": review_id},
                    }
                    await db.compras_fornecedores.insert_one(target_doc, session=session)
                else:
                    raise HTTPException(status_code=409, detail="Modo de resolucao invalido.")

                promotion = {
                    "target_id": target_doc["id"], "target_code": target_doc.get("codigo_interno"),
                    "resolution_mode": resolution["mode"], "promoted_at": now,
                    "promoted_by": user["id"], "promoted_by_name": user.get("name", ""),
                }
                result = await db.legacy_master_data_reviews.update_one(
                    {**query, "review_status": "aprovado", "activation_status": "bloqueado"},
                    {"$set": {"activation_status": final_status, "operational_eligible": True, "promotion": promotion, "updated_at": now}},
                    session=session,
                )
                if result.modified_count != 1:
                    raise HTTPException(status_code=409, detail="A revisao foi alterada durante a promocao.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha na promocao atomica de fornecedor legado")
        raise HTTPException(status_code=500, detail="Falha atomica ao resolver fornecedor; nenhuma alteracao foi confirmada.") from exc
    target_doc.pop("_id", None)
    await _audit(user, f"fornecedor_legado_{final_status}", "fornecedor", target_doc["id"], after=target_doc)
    return {"status": final_status, "registro": target_doc}


@cadastros_master_router.post("/revisoes-cadastros-bloqueados/{review_id}/decisao-sku")
async def decide_blocked_legacy_sku(review_id: str, data: LegacySkuDecision, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    tenant_id = user["tenant_id"]
    query = {"tenant_id": tenant_id, "id": review_id, "record_type": "sku"}
    review = await db.legacy_master_data_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="SKU legado bloqueado nao encontrado.")
    if review.get("activation_status") in {"promovido", "consolidado"}:
        raise HTTPException(status_code=409, detail="SKU ja resolvido; a revisao tornou-se imutavel.")

    resolution = None
    if data.decision == "aprovar":
        if data.resolution_mode == "criar":
            cliente = await db.crm_clients.find_one(
                {"tenant_id": tenant_id, "id": data.cliente_id},
                {"_id": 0, "id": 1, "nome_empresa": 1, "cli3": 1, "cli4": 1},
            )
            if not cliente:
                raise HTTPException(status_code=404, detail="Cliente de destino nao encontrado.")
            codigo = _clean(data.codigo_corrigido).upper()
            nome = _clean(data.nome_corrigido) or _clean(review.get("legacy_name"))
            if len(codigo) < 2 or len(nome) < 2:
                raise HTTPException(status_code=422, detail="Informe codigo e nome validos para o SKU legado.")
            duplicate = await db.skus.find_one(
                {"tenant_id": tenant_id, "codigo_interno": {"$regex": f"^{re.escape(codigo)}$", "$options": "i"}},
                {"_id": 0, "id": 1, "codigo_interno": 1, "nome_produto": 1},
            )
            if duplicate:
                raise HTTPException(status_code=409, detail="Codigo ja existe; use a consolidacao no SKU encontrado.")
            resolution = {
                "mode": "criar", "cliente_id": cliente["id"],
                "cliente_nome": cliente.get("nome_empresa", ""), "cli3": cliente.get("cli3", ""),
                "cli4": cliente.get("cli4", ""), "codigo": codigo, "nome": nome,
            }
        elif data.resolution_mode == "consolidar":
            target = await db.skus.find_one(
                {"tenant_id": tenant_id, "id": data.target_sku_id},
                {"_id": 0, "id": 1, "codigo_interno": 1, "nome_produto": 1, "cliente_id": 1, "cliente_nome": 1},
            )
            if not target:
                raise HTTPException(status_code=404, detail="SKU de destino nao encontrado.")
            resolution = {
                "mode": "consolidar", "target_sku_id": target["id"],
                "target_sku_code": target.get("codigo_interno"), "target_sku_name": target.get("nome_produto"),
                "cliente_id": target.get("cliente_id"), "cliente_nome": target.get("cliente_nome"),
            }
        else:
            raise HTTPException(status_code=422, detail="Escolha criar ou consolidar o SKU.")

    now = _now_iso()
    updates = {
        "review_status": "aprovado" if data.decision == "aprovar" else "reprovado",
        "review_decision": data.decision, "review_justification": _clean(data.justificativa),
        "resolution": resolution, "reviewed_by": user["id"], "reviewed_by_name": user.get("name", ""),
        "reviewed_at": now, "updated_at": now,
    }
    await db.legacy_master_data_reviews.update_one(query, {"$set": updates})
    updated = await db.legacy_master_data_reviews.find_one(query, {"_id": 0, "source_payload": 0})
    await _audit(user, f"sku_legado_{updates['review_status']}", "legacy_master_data_review", review_id, before=review, after=updated)
    return updated


@cadastros_master_router.post("/revisoes-cadastros-bloqueados/{review_id}/promover-sku")
async def promote_blocked_legacy_sku(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    tenant_id = user["tenant_id"]
    query = {"tenant_id": tenant_id, "id": review_id, "record_type": "sku"}
    review = await db.legacy_master_data_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="SKU legado bloqueado nao encontrado.")
    if review.get("activation_status") in {"promovido", "consolidado"}:
        return {"status": review["activation_status"], "resolucao": review.get("promotion") or {}}
    if review.get("review_status") != "aprovado" or not review.get("resolution"):
        raise HTTPException(status_code=409, detail="A resolucao precisa ser aprovada antes da promocao.")
    mongo_client = getattr(db, "client", None)
    if not mongo_client or not hasattr(mongo_client, "start_session"):
        raise HTTPException(status_code=503, detail="Promocao exige MongoDB com transacoes.")

    now = _now_iso()
    target_doc = None
    final_status = "promovido"
    try:
        async with await mongo_client.start_session() as session:
            async with session.start_transaction():
                current = await db.legacy_master_data_reviews.find_one(query, {"_id": 0}, session=session)
                if not current or current.get("review_status") != "aprovado" or current.get("activation_status") != "bloqueado":
                    raise HTTPException(status_code=409, detail="Estado da revisao mudou; recarregue a tela.")
                resolution = current.get("resolution") or {}
                if resolution.get("mode") == "consolidar":
                    target_doc = await db.skus.find_one(
                        {"tenant_id": tenant_id, "id": resolution.get("target_sku_id")}, {"_id": 0}, session=session
                    )
                    if not target_doc:
                        raise HTTPException(status_code=409, detail="SKU de consolidacao nao existe mais.")
                    final_status = "consolidado"
                elif resolution.get("mode") == "criar":
                    codigo = resolution.get("codigo")
                    duplicate = await db.skus.find_one(
                        {"tenant_id": tenant_id, "codigo_interno": {"$regex": f"^{re.escape(codigo)}$", "$options": "i"}},
                        {"_id": 0}, session=session,
                    )
                    if duplicate:
                        raise HTTPException(status_code=409, detail="Codigo passou a existir; revise e consolide o SKU.")
                    cliente = await db.crm_clients.find_one(
                        {"tenant_id": tenant_id, "id": resolution.get("cliente_id")}, {"_id": 0}, session=session
                    )
                    if not cliente:
                        raise HTTPException(status_code=409, detail="Cliente aprovado nao existe mais.")
                    raw = current.get("source_payload") or {}
                    active = _clean(raw.get("ativo")).lower() != "inativo"
                    target_doc = {
                        "id": _new_id(), "tenant_id": tenant_id,
                        "codigo_interno": codigo, "codigo_legado": _clean(current.get("legacy_code")) or codigo,
                        "cat3": "", "cli4": _clean(cliente.get("cli4")).upper(),
                        "cat2": "", "cli3": _clean(cliente.get("cli3")).upper(),
                        "nome_produto": resolution["nome"], "categoria": _clean(raw.get("categoria")),
                        "subcategoria": _clean(raw.get("subcategoria")), "formula_vinculada": "",
                        "cliente_id": cliente["id"], "cliente_nome": _clean(cliente.get("nome_empresa")),
                        "projeto_id": None, "projeto_nome": "", "amostra_id": None, "produto_pai_id": None,
                        "preco_unitario": 0.0, "moq": 0,
                        "anvisa": {"numero": _clean(raw.get("msAnvisa")), "validade": None},
                        "status": "ativo" if active else "inativo", "pd_concluido": True,
                        "pd_concluido_em": now, "pd_concluido_origem": "migracao_legado_autorizado_revisado",
                        "origem_contratual_status": "legado_autorizado", "cgi_contrato_id": None,
                        "cgi_numero": None, "cgi_assinado_em": None, "legado_sem_cgi": True,
                        "bloqueado_por_cgi": False, "legacy_authorized": True,
                        "legacy_aliases": [], "legacy_skus_anteriores": raw.get("skusAnteriores") or [],
                        "legacy_product_data": raw, "descontinuado_motivo": None, "descontinuado_em": None,
                        "descontinuado_por": None, "historico_pedidos": [], "data_ultimo_pedido": None,
                        "frequencia_media_recompra_dias": 0,
                        "medias_producao": {"media_geral_unh": None, "media_12m_unh": None, "media_3m_unh": None,
                            "media_1m_unh": None, "meta_unh": None, "ajuste_percentual": 0,
                            "meta_set_by": None, "meta_set_at": None, "historico_producao": []},
                        "created_at": now, "updated_at": now,
                        "_migration": {"source": "firebase-current", "source_node": "produtos",
                            "source_id": current["source_key"], "approved_rule": "human_review_legacy_sku_promotion_v1",
                            "review_id": review_id, "applied_at": now},
                    }
                    await db.skus.insert_one(target_doc, session=session)
                else:
                    raise HTTPException(status_code=409, detail="Modo de resolucao invalido.")

                promotion = {
                    "target_id": target_doc["id"], "target_code": target_doc.get("codigo_interno"),
                    "resolution_mode": resolution["mode"], "promoted_at": now,
                    "promoted_by": user["id"], "promoted_by_name": user.get("name", ""),
                }
                result = await db.legacy_master_data_reviews.update_one(
                    {**query, "review_status": "aprovado", "activation_status": "bloqueado"},
                    {"$set": {"activation_status": final_status, "operational_eligible": True,
                        "promotion": promotion, "updated_at": now}}, session=session,
                )
                if result.modified_count != 1:
                    raise HTTPException(status_code=409, detail="A revisao foi alterada durante a promocao.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha na promocao atomica de SKU legado")
        raise HTTPException(status_code=500, detail="Falha atomica ao resolver SKU; nenhuma alteracao foi confirmada.") from exc
    target_doc.pop("_id", None)
    await _audit(user, f"sku_legado_{final_status}", "sku", target_doc["id"], after=target_doc)
    return {"status": final_status, "registro": target_doc}


@cadastros_master_router.get("/revisoes-pedidos-ops/{review_id}")
async def get_legacy_order_op_review(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    query = {"tenant_id": user["tenant_id"], "id": review_id}
    review = await db.legacy_order_reviews.find_one(query, {"_id": 0})
    if not review:
        review = await db.legacy_op_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Revisao legada nao encontrada.")
    return review


@cadastros_master_router.post("/revisoes-pedidos-ops/{review_id}/preparar-producao")
async def prepare_legacy_op_for_production(
    review_id: str,
    data: LegacyOPProductionAction,
    request: Request,
):
    """Resolve an open legacy OP and promote it only when its operational BOM is ready."""
    user = await _get_current_user(request)
    require_roles(user, PCP_PLANNING_WRITE_ROLES)
    tenant_id = user["tenant_id"]
    query = {"tenant_id": tenant_id, "id": review_id, "record_type": "production_order"}
    review = await db.legacy_op_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Revisao de OP legada nao encontrada.")

    existing_op = await db.ops.find_one(
        {"tenant_id": tenant_id, "legacy_review_id": review_id}, {"_id": 0}
    )
    if existing_op:
        existing_order = await db.orders.find_one(
            {"tenant_id": tenant_id, "id": existing_op.get("pedido_id")}, {"_id": 0}
        )
        return {"status": "ja_promovido", "op": existing_op, "pedido": existing_order}
    if review.get("activation_status") == "promovido":
        raise HTTPException(status_code=409, detail="Revisao marcada como promovida, mas a OP vinculada nao foi encontrada.")

    raw = review.get("source_payload") or {}
    legacy_status = _clean(raw.get("status") or review.get("legacy_status")).lower()
    if legacy_status.startswith("conclu") or legacy_status.startswith("cancel"):
        raise HTTPException(status_code=409, detail="Somente OPs legadas abertas podem entrar no fluxo operacional.")
    if data.qtd_produzida_importada > data.qtd_planejada:
        raise HTTPException(status_code=422, detail="Produzido importado nao pode ser maior que a quantidade planejada revisada.")

    cliente = await db.crm_clients.find_one(
        {"tenant_id": tenant_id, "id": data.cliente_id, "stage": {"$ne": "cliente_perdido"}},
        {"_id": 0},
    )
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente ativo selecionado nao foi encontrado.")
    sku = await db.skus.find_one(
        {"tenant_id": tenant_id, "id": review.get("target_sku_id")}, {"_id": 0}
    )
    if not sku:
        raise HTTPException(status_code=409, detail="SKU reconciliado nao existe mais no cadastro operacional.")
    linha = None
    if data.linha_id:
        linha = await db.pcp_linhas.find_one(
            {"tenant_id": tenant_id, "id": data.linha_id, "status": {"$ne": "inativa"}}, {"_id": 0}
        )
        if not linha:
            raise HTTPException(status_code=404, detail="Linha ativa selecionada nao foi encontrada.")

    is_running = legacy_status.startswith("em produ") or legacy_status.startswith("produ")
    is_partial = "parcial" in legacy_status
    is_waiting_confirmation = legacy_status.startswith("aguardando")
    if (is_running or is_partial) and not linha:
        raise HTTPException(status_code=422, detail="Selecione a linha para uma OP que ja possui producao importada.")

    bulk_count = 0
    if sku.get("produto_pai_id"):
        bulk_count = await db.bom_items.count_documents({
            "tenant_id": tenant_id,
            "produto_pai_id": sku["produto_pai_id"],
            "camada": "bulk",
            "vigente": True,
        })
    packaging_count = await db.bom_items.count_documents({
        "tenant_id": tenant_id,
        "sku_id": sku["id"],
        "camada": "embalagem",
        "vigente": True,
    })
    missing_bom = []
    if bulk_count == 0:
        missing_bom.append("formula_bulk")
    if packaging_count == 0:
        missing_bom.append("bom_embalagem")

    now = _now_iso()
    resolution = {
        "cliente_id": cliente["id"],
        "cliente_nome": cliente.get("nome_empresa") or cliente.get("nome") or "",
        "linha_id": linha.get("id") if linha else None,
        "linha_nome": linha.get("nome") if linha else _clean(raw.get("linha")),
        "qtd_planejada": float(data.qtd_planejada),
        "qtd_produzida_importada": float(data.qtd_produzida_importada),
        "justificativa": data.justificativa.strip(),
        "resolved_by": user["id"],
        "resolved_by_name": user.get("name", ""),
        "resolved_at": now,
    }
    if missing_bom:
        task = await db.workflow_tasks.find_one(
            {
                "tenant_id": tenant_id,
                "metadata.legacy_review_id": review_id,
                "status": {"$in": ["pendente", "em_andamento", "bloqueada"]},
            },
            {"_id": 0},
        )
        if not task:
            task = await create_workflow_task(
                tenant_id=tenant_id,
                entity_type="sku",
                entity_id=sku["id"],
                title=f"Completar BOM para liberar OP legada {review.get('source_key')}",
                description=(
                    f"SKU {sku.get('codigo_interno') or sku['id']} precisa de "
                    f"{', '.join(missing_bom)} antes da promocao para producao real."
                ),
                category="cadastros",
                blocking=True,
                due_in_days=2,
                created_by=user,
                metadata={
                    "module_origin": "firebase_legacy_cutover",
                    "legacy_review_id": review_id,
                    "legacy_op": review.get("source_key"),
                    "sku_id": sku["id"],
                    "missing_bom": missing_bom,
                },
            )
        await db.legacy_op_reviews.update_one(
            {**query, "activation_status": "bloqueado"},
            {
                "$set": {
                    "review_status": "em_revisao",
                    "sector_status": "em_revisao",
                    "assigned_sector": "cadastros",
                    "next_sector": "pcp",
                    "review_stage": "completar_bom_para_producao",
                    "production_resolution": resolution,
                    "production_blockers": missing_bom,
                    "workflow_task_id": task["id"],
                    "updated_at": now,
                },
                "$push": {
                    "sector_history": {
                        "from": review.get("assigned_sector") or "pcp",
                        "to": "cadastros",
                        "stage": "completar_bom_para_producao",
                        "at": now,
                        "by": user["id"],
                    }
                },
            },
        )
        await _audit(user, "op_legada_encaminhada_bom", "legacy_op_review", review_id, before=review, after=resolution)
        return {
            "status": "encaminhado_cadastros",
            "promovido": False,
            "blockers": missing_bom,
            "task": {key: task.get(key) for key in ("id", "display_code", "title", "status")},
        }

    status = "aberta"
    if is_running or is_partial:
        status = "em_processo"
    elif is_waiting_confirmation:
        status = "aguardando_confirmacao_pcp"
    order_id = _new_id()
    op_id = _new_id()
    source_key = _clean(review.get("source_key"))
    order_number = f"MIG-{source_key}"
    op_number = f"LEG-{source_key}"
    item_id = _new_id()
    item_name = _clean(raw.get("produto") or sku.get("nome_produto") or sku.get("codigo_interno"))
    sku_code = _clean(sku.get("codigo_interno") or review.get("target_sku_code") or raw.get("sku"))
    order_item = {
        "id": item_id,
        "item": item_name,
        "sku_id": sku["id"],
        "codigo_kuryos": sku_code,
        "qtd": float(data.qtd_planejada),
        "qtd_planejada": float(data.qtd_planejada),
        "qtd_produzida_importada": float(data.qtd_produzida_importada),
        "lote": _clean(raw.get("lote")),
        "valor_unitario": 0,
        "valor_total": 0,
    }
    order = {
        "id": order_id,
        "tenant_id": tenant_id,
        "numero_pedido": order_number,
        "cliente_id": cliente["id"],
        "cliente": {"id": cliente["id"], "nome": resolution["cliente_nome"]},
        "project_name": item_name,
        "status": "em_producao",
        "origem": "firebase_legacy_cutover",
        "cgi_status": "legado_autorizado",
        "aprovacao_cliente": True,
        "aprovacao_comercial": True,
        "items": [order_item],
        "total_bruto": 0,
        "total_desconto": 0,
        "total_pedido": 0,
        "observacoes": data.justificativa.strip(),
        "op_id": op_id,
        "legacy_review_id": review_id,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    op_item = {
        "id": item_id,
        "order_item_id": item_id,
        "item": item_name,
        "sku_id": sku["id"],
        "codigo_kuryos": sku_code,
        "qtd_planejada": float(data.qtd_planejada),
        "qtd_produzida": float(data.qtd_produzida_importada),
        "legacy_qtd_produzida_importada": float(data.qtd_produzida_importada),
        "lote": _clean(raw.get("lote")),
        "prazo_sla": "",
    }
    op = {
        "id": op_id,
        "tenant_id": tenant_id,
        "numero_op": op_number,
        "pedido_id": order_id,
        "numero_pedido": order_number,
        "cliente_id": cliente["id"],
        "cliente_nome": resolution["cliente_nome"],
        "project_name": item_name,
        "status": status,
        "pcp_origem": "firebase_legacy_cutover",
        "pcp_status": "aguardando_separacao" if status != "aguardando_confirmacao_pcp" else "aguardando_confirmacao_pcp",
        "linha_id": linha.get("id") if linha else None,
        "linha_nome": resolution["linha_nome"],
        "linha_tipo": linha.get("tipo", "geral") if linha else "geral",
        "items": [op_item],
        "tecnico": {"revisao_obrigatoria": False, "apto_operacao": True, "bloqueios": [], "alertas": []},
        "observacoes": data.justificativa.strip(),
        "legacy_review_id": review_id,
        "legacy_source_key": source_key,
        "legacy_baseline_imported": True,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }
    mongo_client = getattr(db, "client", None)
    if not mongo_client or not hasattr(mongo_client, "start_session"):
        raise HTTPException(status_code=503, detail="Promocao de OP exige MongoDB com transacoes.")
    try:
        async with await mongo_client.start_session() as session:
            async with session.start_transaction():
                duplicate = await db.ops.find_one(
                    {"tenant_id": tenant_id, "$or": [{"legacy_review_id": review_id}, {"numero_op": op_number}]},
                    {"_id": 0, "id": 1},
                    session=session,
                )
                if duplicate:
                    raise HTTPException(status_code=409, detail="Ja existe OP operacional para esta origem legada.")
                await db.orders.insert_one(order, session=session)
                await db.ops.insert_one(op, session=session)
                result = await db.legacy_op_reviews.update_one(
                    {**query, "activation_status": "bloqueado"},
                    {"$set": {
                        "review_status": "aprovado",
                        "activation_status": "promovido",
                        "operational_eligible": True,
                        "sector_status": "concluido",
                        "assigned_sector": "pcp",
                        "next_sector": None,
                        "review_stage": "promovido_producao",
                        "production_resolution": resolution,
                        "production_blockers": [],
                        "promotion": {"order_id": order_id, "op_id": op_id, "promoted_at": now, "promoted_by": user["id"]},
                        "updated_at": now,
                    }},
                    session=session,
                )
                if result.modified_count != 1:
                    raise HTTPException(status_code=409, detail="A revisao mudou durante a promocao; recarregue a tela.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao promover OP legada para producao")
        raise HTTPException(status_code=500, detail="Falha transacional; pedido e OP nao foram criados.") from exc
    order.pop("_id", None)
    op.pop("_id", None)
    await _audit(user, "op_legada_promovida_producao", "op", op_id, before=review, after=op)
    return {"status": "promovido", "promovido": True, "pedido": order, "op": op}


@cadastros_master_router.get("/estruturas-legadas/{review_id}")
async def get_legacy_structure(review_id: str, request: Request):
    user = await _get_current_user(request)
    require_roles(user, READ_ROLES)
    review = await db.legacy_formula_bom_reviews.find_one(
        {"tenant_id": user["tenant_id"], "id": review_id}, {"_id": 0}
    )
    if not review:
        raise HTTPException(status_code=404, detail="Estrutura legada nao encontrada.")
    return review


@cadastros_master_router.post("/estruturas-legadas/{review_id}/decisao")
async def decide_legacy_structure(review_id: str, data: LegacyStructureDecision, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    query = {"tenant_id": user["tenant_id"], "id": review_id}
    review = await db.legacy_formula_bom_reviews.find_one(query, {"_id": 0})
    if not review:
        raise HTTPException(status_code=404, detail="Estrutura legada nao encontrada.")
    if review.get("activation_status") == "promovido":
        raise HTTPException(status_code=409, detail="Estrutura ja promovida e imutavel neste fluxo.")
    if data.decision == "aprovar":
        await _validate_legacy_review_materials(review, review.get("record_type"))
        status = "aprovado"
    else:
        status = "reprovado"
    now = _now_iso()
    updates = {
        "review_status": status,
        "review_decision": data.decision,
        "review_justification": _clean(data.justificativa),
        "reviewed_by": user["id"],
        "reviewed_by_name": user.get("name", ""),
        "reviewed_at": now,
        "updated_at": now,
    }
    await db.legacy_formula_bom_reviews.update_one(query, {"$set": updates})
    updated = await db.legacy_formula_bom_reviews.find_one(query, {"_id": 0, "source_payload": 0})
    await _audit(user, f"estrutura_legada_{status}", "legacy_formula_bom_review", review_id, before=review, after=updated)
    return updated


@cadastros_master_router.post("/estruturas-legadas/promover")
async def promote_legacy_structure(data: LegacyStructurePromotion, request: Request):
    user = await _get_current_user(request)
    require_roles(user, APPROVE_ROLES)
    tenant_id = user["tenant_id"]
    review_ids = [data.formula_review_id, data.bom_review_id]
    if len(set(review_ids)) != 2:
        raise HTTPException(status_code=422, detail="Selecione uma formula e um BOM diferentes.")
    reviews = await db.legacy_formula_bom_reviews.find(
        {"tenant_id": tenant_id, "id": {"$in": review_ids}}, {"_id": 0}
    ).to_list(2)
    by_type = {review.get("record_type"): review for review in reviews}
    formula_review = by_type.get("formula")
    bom_review = by_type.get("bom")
    if not formula_review or not bom_review:
        raise HTTPException(status_code=404, detail="Formula ou BOM de revisao nao encontrado.")
    if formula_review.get("id") != data.formula_review_id or bom_review.get("id") != data.bom_review_id:
        raise HTTPException(status_code=422, detail="Os IDs selecionados nao correspondem aos tipos informados.")
    if formula_review.get("target_sku_id") != bom_review.get("target_sku_id"):
        raise HTTPException(status_code=409, detail="Formula e BOM devem pertencer ao mesmo SKU.")
    if any(review.get("review_status") != "aprovado" for review in reviews):
        raise HTTPException(status_code=409, detail="Formula e BOM precisam ser aprovados antes da promocao.")
    promoted = next((review for review in reviews if review.get("activation_status") == "promovido"), None)
    if promoted:
        produto_pai_id = promoted.get("promotion", {}).get("produto_pai_id")
        existing_parent = await db.produtos_pai.find_one(
            {"tenant_id": tenant_id, "id": produto_pai_id}, {"_id": 0}
        )
        if existing_parent:
            return {"status": "ja_promovido", "produto_pai": existing_parent, "sku_id": formula_review["target_sku_id"]}

    parent_name = _clean(data.produto_pai_nome)
    if len(parent_name) < 2:
        raise HTTPException(status_code=422, detail="Informe o nome do produto-pai.")
    mongo_client = getattr(db, "client", None)
    if not mongo_client or not hasattr(mongo_client, "start_session"):
        raise HTTPException(status_code=503, detail="Promocao exige MongoDB com transacoes.")

    produto_pai_id = _new_id()
    now = _now_iso()
    try:
        async with await mongo_client.start_session() as session:
            async with session.start_transaction():
                current_reviews = await db.legacy_formula_bom_reviews.find(
                    {"tenant_id": tenant_id, "id": {"$in": review_ids}}, {"_id": 0}, session=session
                ).to_list(2)
                current_by_type = {review.get("record_type"): review for review in current_reviews}
                formula_review = current_by_type.get("formula")
                bom_review = current_by_type.get("bom")
                if not formula_review or not bom_review or any(
                    review.get("review_status") != "aprovado" or review.get("activation_status") != "bloqueado"
                    for review in current_reviews
                ):
                    raise HTTPException(status_code=409, detail="Estado da revisao mudou; recarregue a tela.")
                sku = await db.skus.find_one(
                    {"tenant_id": tenant_id, "id": formula_review["target_sku_id"]}, {"_id": 0}, session=session
                )
                if not sku:
                    raise HTTPException(status_code=404, detail="SKU de destino nao encontrado.")
                if sku.get("produto_pai_id"):
                    raise HTTPException(status_code=409, detail="SKU ja esta vinculado a um produto-pai.")
                if sku.get("formula") or sku.get("bom"):
                    raise HTTPException(status_code=409, detail="SKU ja possui formula/BOM tecnico; revise manualmente para evitar sobrescrita.")

                formula_materials = await _validate_legacy_review_materials(formula_review, "formula", session=session)
                bom_materials = await _validate_legacy_review_materials(bom_review, "bom", session=session)
                formula_by_id = {material["id"]: material for material in formula_materials}
                bom_by_id = {material["id"]: material for material in bom_materials}
                parent = {
                    "id": produto_pai_id,
                    "tenant_id": tenant_id,
                    "nome": parent_name,
                    "descricao": "Produto-pai promovido de formula/BOM legado revisado.",
                    "cliente_id": sku.get("cliente_id"),
                    "cliente_nome": sku.get("cliente_nome", ""),
                    "created_by": user["id"],
                    "created_by_name": user.get("name", ""),
                    "created_at": now,
                    "updated_at": now,
                    "origem": "firebase_legacy_review",
                    "legacy_review_ids": review_ids,
                }
                bulk_items = []
                sku_formula = []
                for item in formula_review["resolved_items"]:
                    material = formula_by_id[item["target_material_id"]]
                    bom_item = {
                        "id": _new_id(), "tenant_id": tenant_id, "produto_pai_id": produto_pai_id,
                        "sku_id": None, "camada": "bulk", "versao": 1, "vigente": True,
                        "vigente_desde": now, "codigo_material": item["target_material_code"],
                        "material_id": item["target_material_id"], "tipo": item["target_type"],
                        "nome_material": material.get("nome") or item["target_material_code"],
                        "percentual": float(item["quantity"]), "unidade": "%",
                        "observacoes": f"Legado revisado: {formula_review['source_key']}", "created_at": now,
                    }
                    bulk_items.append(bom_item)
                    sku_formula.append({
                        "material_id": item["target_material_id"], "material_codigo": item["target_material_code"],
                        "material_nome": bom_item["nome_material"], "percentual": bom_item["percentual"],
                        "fase": "", "funcao": "", "origem_revisao_id": formula_review["id"],
                    })
                packaging_items = []
                sku_bom = []
                for item in bom_review["resolved_items"]:
                    material = bom_by_id[item["target_material_id"]]
                    unit_stock = material.get("unidade_estoque") or "un"
                    unit_purchase = material.get("unidade_compra") or unit_stock
                    bom_item = {
                        "id": _new_id(), "tenant_id": tenant_id, "produto_pai_id": produto_pai_id,
                        "sku_id": sku["id"], "camada": "embalagem", "versao": 1, "vigente": True,
                        "vigente_desde": now, "codigo_material": item["target_material_code"],
                        "material_id": item["target_material_id"], "tipo": item["target_type"],
                        "nome_material": material.get("nome") or item["target_material_code"],
                        "quantidade_por_unidade": float(item["quantity"]), "unidade_consumo": unit_stock,
                        "unidade_compra": unit_purchase, "fator_conversao": float(material.get("fator_conversao") or 1),
                        "observacoes": f"Legado revisado: {bom_review['source_key']}", "created_at": now,
                    }
                    packaging_items.append(bom_item)
                    sku_bom.append({
                        "material_id": item["target_material_id"], "material_codigo": item["target_material_code"],
                        "material_nome": bom_item["nome_material"], "quantidade": bom_item["quantidade_por_unidade"],
                        "unidade": unit_stock, "etapa": "embalagem", "origem_revisao_id": bom_review["id"],
                    })

                await db.produtos_pai.insert_one(parent, session=session)
                await db.bom_items.insert_many(bulk_items + packaging_items, ordered=True, session=session)
                sku_update = {
                    "produto_pai_id": produto_pai_id,
                    "formula": sku_formula,
                    "bom": sku_bom,
                    "formula_legado_revisada": True,
                    "bom_legado_revisado": True,
                    "updated_at": now,
                }
                sku_result = await db.skus.update_one(
                    {"tenant_id": tenant_id, "id": sku["id"], "produto_pai_id": {"$in": [None, ""]}},
                    {"$set": sku_update}, session=session,
                )
                if sku_result.modified_count != 1:
                    raise HTTPException(status_code=409, detail="SKU foi alterado durante a promocao; recarregue a tela.")
                promotion = {
                    "produto_pai_id": produto_pai_id, "sku_id": sku["id"], "promoted_at": now,
                    "promoted_by": user["id"], "promoted_by_name": user.get("name", ""),
                }
                result = await db.legacy_formula_bom_reviews.update_many(
                    {"tenant_id": tenant_id, "id": {"$in": review_ids}, "review_status": "aprovado", "activation_status": "bloqueado"},
                    {"$set": {"activation_status": "promovido", "operational_eligible": True, "promotion": promotion, "updated_at": now}},
                    session=session,
                )
                if result.modified_count != 2:
                    raise HTTPException(status_code=409, detail="Nao foi possivel bloquear atomicamente as duas revisoes.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha na promocao atomica de formula/BOM legado")
        raise HTTPException(status_code=500, detail="Falha atomica ao promover formula/BOM; nenhuma alteracao foi confirmada.") from exc

    response = {
        "status": "promovido", "produto_pai_id": produto_pai_id,
        "sku_id": formula_review["target_sku_id"], "formula_review_id": data.formula_review_id,
        "bom_review_id": data.bom_review_id,
    }
    await _audit(user, "estrutura_legada_promovida", "produto_pai", produto_pai_id, after=response)
    return response


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
