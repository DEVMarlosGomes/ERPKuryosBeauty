"""
CRM Routes - Kuryos Beauty CRM
3-level pipeline: Clients (CRM1) → Projects (CRM2) → Samples (CRM3) → SKU
"""

from fastapi import APIRouter, HTTPException, Request, Query, File, UploadFile
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import logging
import re
import asyncio
import os
import base64
from pathlib import Path
from validation_utils import (
    clean_text,
    normalize_cnpj,
    normalize_email,
    normalize_phone,
    is_valid_cnpj,
    is_valid_email,
    is_valid_phone,
)

from workflow_engine import (
    audit_log,
    create_workflow_task,
    next_sample_number,
    next_sample_code,
    int_to_letters,
    next_sku_per_pair_v2,
    build_sku_code_v2,
    cat2_from_categoria,
    normalise_cli3,
    normalise_cli4,
    suggest_cli4_candidates,
    recalc_sku_averages,
    assert_client_exists,
    assert_project_exists,
    assert_sample_exists,
    assert_no_blocking_tasks,
    trigger_tasks_for_transition,
    inherit,
    INHERITED_FROM_CLIENT,
    INHERITED_FROM_PROJECT,
    INHERITED_FROM_SAMPLE,
)
from rbac import (
    require_roles,
    has_role,
    COMERCIAL_FULL,
    COMERCIAL_LEAD,
    PD_READ,
    PD_WRITE,
    PD_FULL,
    QA_APPROVERS,
    DOC_REVIEWERS,
    ADMIN_ONLY,
)
from produtos_routes import find_or_create_produto_pai, _vincular_sku_ao_produto_pai_internal

logger = logging.getLogger(__name__)

crm_router = APIRouter(prefix="/api/crm")

# ============ MODULE STATE (set via init) ============
db = None
_get_current_user = None
_new_id = None
_now_iso = None
_broadcast_event = None

def init_crm(database, get_user_fn, new_id_fn, now_iso_fn, broadcast_event_fn=None):
    global db, _get_current_user, _new_id, _now_iso, _broadcast_event
    db = database
    _get_current_user = get_user_fn
    _new_id = new_id_fn
    _now_iso = now_iso_fn
    _broadcast_event = broadcast_event_fn
    logger.info("CRM module initialized")

# ============ CONSTANTS ============

CLIENT_STAGES = ["prospeccao", "qualificado", "projeto_em_discussao", "negociacao", "cliente_fechado", "cliente_perdido"]

CLIENT_TRANSITIONS = {
    "prospeccao": ["qualificado", "cliente_perdido"],
    "qualificado": ["projeto_em_discussao", "prospeccao", "cliente_perdido"],
    "projeto_em_discussao": ["negociacao", "qualificado", "prospeccao", "cliente_perdido"],
    "negociacao": ["cliente_fechado", "projeto_em_discussao", "qualificado", "prospeccao", "cliente_perdido"],
    "cliente_fechado": ["negociacao", "projeto_em_discussao", "qualificado", "prospeccao"],
    "cliente_perdido": ["prospeccao"],
}

# Stages where moving backward is considered a regression (requires justification)
_CLIENT_STAGE_ORDER = ["prospeccao", "qualificado", "projeto_em_discussao", "negociacao", "cliente_fechado", "cliente_perdido"]

PROJECT_STAGES = [
    "projeto_em_discussao",
    "amostra_solicitada",
    "amostra_em_desenvolvimento",
    "amostra_enviada",
    "em_negociacao",
    "pedido_aprovado",
    "projeto_arquivado",
]

PROJECT_TRANSITIONS = {
    "projeto_em_discussao": ["amostra_solicitada", "projeto_arquivado"],
    "amostra_solicitada": ["amostra_em_desenvolvimento", "projeto_arquivado"],
    "amostra_em_desenvolvimento": ["amostra_enviada", "projeto_arquivado"],
    "amostra_enviada": ["em_negociacao", "amostra_em_desenvolvimento", "projeto_arquivado"],
    "em_negociacao": ["pedido_aprovado", "amostra_em_desenvolvimento", "projeto_arquivado"],
    "pedido_aprovado": [],
    "projeto_arquivado": [],
    # legado
    "amostras": ["amostra_em_desenvolvimento", "projeto_arquivado"],
}

SAMPLE_STAGES = ["solicitada", "em_elaboracao", "retrabalho", "enviada", "aprovada", "reprovada"]
SAMPLE_TEST_STATUSES = ["aguardando", "em_teste", "liberada", "reprovada"]
CLIENT_DECISION_STATUSES = ["aprovada", "retrabalho", "arquivado"]

SAMPLE_TRANSITIONS = {
    "solicitada": ["em_elaboracao"],
    "em_elaboracao": ["enviada", "retrabalho"],
    "retrabalho": ["em_elaboracao"],
    "enviada": ["aprovada", "reprovada", "retrabalho"],
    "aprovada": [],
    "reprovada": [],
}

CANAL_ORIGEM_OPTIONS = [
    # Prospecção Ativa — Digital
    "linkedin_dm_outbound",
    "linkedin_engajamento_organico",
    "instagram_abordagem_direta",
    "whatsapp_abordagem_fria",
    "email_outbound_automatizado",
    "email_outbound_manual",
    # Prospecção Ativa — Presencial
    "evento",
    "feira_setor",
    "visita_presencial_espontanea",
    "abordagem_pdv",
    # Indicação
    "indicacao_cliente_ativo",
    "indicacao_fornecedor_parceiro",
    "indicacao_ex_cliente",
    "indicacao_pessoal",
    "indicacao_influenciador_parceiro_midia",
    # Inbound — Digital
    "formulario_site",
    "whatsapp_receptivo",
    "instagram_dm_receptivo",
    "linkedin_inbound",
    "google_organico",
    "google_ads",
    "meta_ads",
    # Inbound — Conteúdo
    "blog",
    "seo",
    "newsletter",
    "youtube",
    "webinar_live",
    # Relacionamento Existente
    "reativacao_lead_frio",
    "reativacao_ex_cliente",
    "cross_sell_cliente_ativo",
    "upsell_cliente_ativo",
    # Outros
    "parceria_cobrand",
    "consultor_agencia",
    "licitacao_edital",
    "outro",
]

# Categorias de Interesse 2 níveis conforme PRD
CATEGORIA_INTERESSE_OPTIONS = {
    "capilares": ["shampoo", "condicionador", "mascara_capilar", "leave_in_finalizador", "oleo_capilar", "ampola_tratamento", "tonico_capilar", "coloracao_tonalizante", "relaxante_alisante", "neutralizante", "botox_capilar", "progressiva_escova"],
    "skin_care_dermocosmeticos": ["hidratante_corporal", "hidratante_facial", "serum_facial", "protetor_solar_facial", "protetor_solar_corporal", "esfoliante", "tonico_facial", "sabonete_liquido_facial", "mascara_facial", "contorno_olhos", "vitamina_c_antioxidante", "clareador", "antiacneico"],
    "higiene_pessoal": ["sabonete_liquido_corporal", "sabonete_em_barra", "gel_banho", "desodorante_spray", "desodorante_rollon", "desodorante_creme", "talco", "antisseptico_maos"],
    "perfumaria": ["perfume_edp", "eau_de_toilette", "body_splash_colonia", "splash_capilar", "home_spray_aromatizador", "sache_perfumado", "sabonete_perfumado"],
    "maquiagem": ["base_liquida", "bb_cream_cc_cream", "primer", "blush_bronzer", "iluminador", "batom_gloss", "delineador", "mascara_cilios", "fixador"],
    "corporal_spa": ["oleo_corporal", "manteiga_corporal", "esfoliante_corporal", "creme_maos_pes", "creme_estrias", "gel_redutor", "creme_pos_depilacao", "creme_massagem"],
    "infantil": ["shampoo_infantil", "condicionador_infantil", "sabonete_infantil", "locao_infantil", "protetor_solar_infantil", "oleo_massagem_infantil"],
    "masculino": ["shampoo_masculino", "balsamo_pos_barba", "gel_creme_barbear", "locao_pos_barba", "desodorante_masculino", "perfume_masculino", "hidratante_facial_masculino"],
    "profissional_salao": ["tratamento_intensivo", "progressiva_escova", "coloracao_profissional", "tonalizante", "alisamento", "neutralizante_profissional"],
    "regulatorio_grau2": ["protetor_solar_fps6", "repelente_insetos", "clareador_pele", "antiacneico", "ativo_farmacologico"],
}

# Campos que indicam produto Grau 2 ANVISA
CATEGORIAS_GRAU2 = ["protetor_solar_facial", "protetor_solar_corporal", "protetor_solar_fps6", "protetor_solar_infantil", "repelente_insetos", "clareador", "clareador_pele", "antiacneico", "ativo_farmacologico"]

ORIGEM_LEAD_OPTIONS = [
    "indicacao_cliente_habibi",
    "indicacao_fornecedor",
    "indicacao_parceiro",
    "feira_setor",
    "evento",
    "linkedin",
    "instagram",
    "google",
    "site",
    "outro",
]

VOLUME_ESTIMADO_OPTIONS = ["menos_1k", "1k_5k", "5k_20k", "20k_50k", "50k_100k", "mais_100k"]

TEM_ANVISA_OPTIONS = ["sim", "nao", "depende"]

MOTIVO_PERDA_OPTIONS = ["preco", "prazo", "qualidade", "concorrencia", "projeto_cancelado", "sem_retorno", "outro"]

# Segmentos de cliente
SEGMENTO_CLIENTE_OPTIONS = ["marca_propria", "distribuidor", "varejo", "salao", "industria", "outro"]

# Porte do cliente
PORTE_CLIENTE_OPTIONS = ["pequeno", "medio", "grande"]

# Temperatura do lead
TEMPERATURA_LEAD_OPTIONS = ["quente", "morno", "frio"]

# Cargos de decisores
CARGO_DECISOR_OPTIONS = ["ceo", "comprador", "desenvolvimento", "diretor_comercial", "gerente_produto", "outro"]

UF_OPTIONS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]

CANAL_ORIGEM_GROUPS = {
    "prospeccao_ativa_digital": [
        "linkedin_dm_outbound",
        "linkedin_engajamento_organico",
        "instagram_abordagem_direta",
        "whatsapp_abordagem_fria",
        "email_outbound_automatizado",
        "email_outbound_manual",
    ],
    "prospeccao_ativa_presencial": [
        "evento",
        "feira_setor",
        "visita_presencial_espontanea",
        "abordagem_pdv",
    ],
    "indicacao": [
        "indicacao_cliente_ativo",
        "indicacao_fornecedor_parceiro",
        "indicacao_ex_cliente",
        "indicacao_pessoal",
        "indicacao_influenciador_parceiro_midia",
    ],
    "inbound_digital": [
        "formulario_site",
        "whatsapp_receptivo",
        "instagram_dm_receptivo",
        "linkedin_inbound",
        "google_organico",
        "google_ads",
        "meta_ads",
    ],
    "inbound_conteudo": [
        "blog",
        "seo",
        "newsletter",
        "youtube",
        "webinar_live",
    ],
    "relacionamento_existente": [
        "reativacao_lead_frio",
        "reativacao_ex_cliente",
        "cross_sell_cliente_ativo",
        "upsell_cliente_ativo",
    ],
    "outros": [
        "parceria_cobrand",
        "consultor_agencia",
        "licitacao_edital",
        "outro",
    ],
}

# Prazo de follow-up por etapa (em dias)
FOLLOW_UP_PRAZOS = {
    "prospeccao": 3,
    "qualificado": 5,
    "projeto_em_discussao": 7,
    "negociacao": 5,
    "cliente_fechado": 30,
    "cliente_perdido": 90,
}

PROJECT_POSICIONAMENTO_OPTIONS = [
    "custo_beneficio",
    "premium",
    "luxo",
    "acessivel",
    "nicho",
    "profissional",
]

PROJECT_TIPO_SERVICO_OPTIONS = [
    "full_service_kuryos",
    "co_desenvolvimento",
    "formula_do_cliente",
]

PROJECT_RESTRICAO_TECNICA_OPTIONS = [
    "vegano",
    "sem_parabenos",
    "sem_sulfato",
    "sem_silicone",
    "hipoalergenico",
    "natural",
    "organico",
    "anvisa_g2",
    "outro",
]

TIPO_AMOSTRA_OPTIONS = [
    "desenvolvimento_novo",
    "portfolio_existente",
    "adaptacao_de_formula",
]

UNIDADE_QUANTIDADE_AMOSTRA_OPTIONS = ["g", "kg", "ml", "l", "un"]

SAMPLE_VARIATION_PARAM_OPTIONS = [
    "fragrancia",
    "cor",
    "ativo",
    "outro",
]

SAMPLE_RESULTADO_OPTIONS = [
    "aprovada",
    "reprovada",
    "retrabalho",
]

STAGE_LABELS = {
    "prospeccao": "Prospecção",
    "qualificado": "Qualificado",
    "projeto_em_discussao": "Projeto em Discussão",
    "negociacao": "Negociação",
    "cliente_fechado": "Cliente Fechado",
    "cliente_perdido": "Cliente Perdido",
    "amostras": "Amostra Solicitada",
    "amostra_solicitada": "Amostra Solicitada",
    "amostra_em_desenvolvimento": "Amostra em Desenvolvimento",
    "amostra_enviada": "Amostra Enviada ao Cliente",
    "em_negociacao": "Em Negociação",
    "pedido_aprovado": "Pedido Aprovado",
    "projeto_arquivado": "Projeto Arquivado",
    "solicitada": "Solicitada",
    "em_elaboracao": "Em Elaboração",
    "retrabalho": "Retrabalho",
    "enviada": "Enviada",
    "aprovada": "Aprovada",
    "reprovada": "Reprovada",
}

# ============ PYDANTIC MODELS ============

class ContatoPrincipal(BaseModel):
    nome: str = ""
    cargo: str = ""
    cargo_custom: Optional[str] = None
    whatsapp: str = ""
    email: str = ""

class ContatoAdicional(BaseModel):
    nome: str = ""
    cargo: str = ""
    cargo_custom: Optional[str] = None
    whatsapp: str = ""
    email: str = ""

class Decisor(BaseModel):
    nome: str = ""
    cargo: str = ""
    contato: str = ""

class FornecedorAtual(BaseModel):
    tem: bool = False
    motivo_troca: str = ""

class AnvisaInfo(BaseModel):
    necessario: bool = False
    status: str = ""

class ClientCreate(BaseModel):
    nome_empresa: str
    cnpj: str = ""
    contato_principal: Optional[ContatoPrincipal] = None
    contatos_adicionais: List[ContatoAdicional] = []
    canal_origem: str = ""
    categoria_interesse: List[str] = []
    origem_lead: str = ""
    # Novos campos PRD
    temperatura_lead: str = "morno"
    responsavel_comercial: str = ""
    segmento: str = ""
    porte: str = ""
    regiao: str = ""
    site: str = ""
    instagram: str = ""
    observacoes: str = ""
    # SKU identifiers
    cli3: str = ""
    cli4: str = ""  # R23: 4-letter code — auto-suggested from nome_empresa if empty
    # Qualificação — opcionais na criação, permitem auto-completar blocking task
    decisores: List[Decisor] = []
    tem_anvisa: str = ""
    volume_estimado_mensal: str = ""
    fornecedor_atual: Optional[FornecedorAtual] = None


class ClientUpdate(BaseModel):
    nome_empresa: Optional[str] = None
    cnpj: Optional[str] = None
    contato_principal: Optional[ContatoPrincipal] = None
    contatos_adicionais: Optional[List[ContatoAdicional]] = None
    canal_origem: Optional[str] = None
    categoria_interesse: Optional[List[str]] = None
    origem_lead: Optional[str] = None
    decisores: Optional[List[Decisor]] = None
    tem_marca_propria: Optional[bool] = None
    tem_anvisa: Optional[str] = None
    volume_estimado_mensal: Optional[str] = None
    fornecedor_atual: Optional[FornecedorAtual] = None
    prazo_urgencia: Optional[str] = None
    amostras_aprovadas: Optional[List[str]] = None
    valor_estimado_projeto: Optional[float] = None
    valor_estimado_projeto_currency: Optional[str] = None
    moq_negociado: Optional[str] = None
    condicao_pagamento: Optional[str] = None
    anvisa_necessario: Optional[AnvisaInfo] = None
    concorrentes_envolvidos: Optional[List[str]] = None
    data_pedido: Optional[str] = None
    skus_confirmados: Optional[List[str]] = None
    valor_primeiro_pedido: Optional[float] = None
    valor_primeiro_pedido_currency: Optional[str] = None
    previsao_segundo_pedido: Optional[str] = None
    motivo_perda: Optional[str] = None
    # Novos campos PRD
    temperatura_lead: Optional[str] = None
    responsavel_comercial: Optional[str] = None
    segmento: Optional[str] = None
    porte: Optional[str] = None
    regiao: Optional[str] = None
    site: Optional[str] = None
    instagram: Optional[str] = None
    observacoes: Optional[str] = None
    ultima_atualizacao_temperatura: Optional[str] = None
    cli3: Optional[str] = None
    cli4: Optional[str] = None  # R23: frozen after first SKU

class ClientMove(BaseModel):
    stage: str
    motivo_perda: Optional[str] = None
    justificativa: Optional[str] = None

class ProjectBatchItem(BaseModel):
    nome_projeto: str
    categoria: str = ""
    briefing_resumido: str = ""
    responsavel_comercial: str = ""
    ideia_conceito: str = ""
    referencia_mercado: str = ""
    publico_alvo: str = ""
    posicionamento: str = ""
    faixa_preco_venda: Optional[float] = None
    volume_estimado_pedido: Optional[int] = None
    tipo_servico: str = ""
    sensorial_desejado: str = ""
    restricoes_tecnicas: List[str] = []
    claims_desejados: str = ""
    prazo_desejado_amostra: str = ""
    observacoes_livres: str = ""

class ProjectBatchCreate(BaseModel):
    cliente_id: str
    projects: List[ProjectBatchItem]

class ProjectUpdate(BaseModel):
    nome_projeto: Optional[str] = None
    categoria: Optional[str] = None
    briefing_tecnico: Optional[str] = None
    responsavel_comercial: Optional[str] = None
    ideia_conceito: Optional[str] = None
    referencia_mercado: Optional[str] = None
    publico_alvo: Optional[str] = None
    posicionamento: Optional[str] = None
    faixa_preco_venda: Optional[float] = None
    volume_estimado_pedido: Optional[int] = None
    tipo_servico: Optional[str] = None
    sensorial_desejado: Optional[str] = None
    restricoes_tecnicas: Optional[List[str]] = None
    claims_desejados: Optional[str] = None
    prazo_desejado_amostra: Optional[str] = None
    observacoes_livres: Optional[str] = None
    responsavel_interno: Optional[str] = None
    data_inicio_desenvolvimento: Optional[str] = None
    prazo_prometido_cliente: Optional[str] = None
    numero_amostras_solicitadas: Optional[int] = None
    motivo_arquivamento: Optional[str] = None

class ProjectMove(BaseModel):
    stage: str
    motivo_arquivamento: Optional[str] = None

class SampleBatchItem(BaseModel):
    nome_amostra: str
    codigo_referencia: str = ""
    observacao_tecnica: str = ""
    tipo_amostra: str = "nova_formula"
    referencia_formula: str = ""
    produto: str = ""
    objetivo_projeto: str = ""
    aplicacoes_desenvolver: str = ""
    ativos_claims: str = ""
    referencias: str = ""
    referencias_fotos: List[str] = []
    orcamento_projeto: str = ""
    textura_esperada: str = ""
    aplicacao: str = ""
    sensorial: str = ""
    ph: str = ""

class SampleBatchCreate(BaseModel):
    projeto_id: str
    samples: List[SampleBatchItem]

class SampleUpdate(BaseModel):
    nome_amostra: Optional[str] = None
    codigo_referencia: Optional[str] = None
    observacao_tecnica: Optional[str] = None
    responsavel_pd: Optional[str] = None
    data_envio: Optional[str] = None
    feedback_cliente: Optional[str] = None
    direcoes_retrabalho: Optional[str] = None
    prazo_entrega_cliente: Optional[str] = None
    tipo_amostra: Optional[str] = None
    referencia_formula: Optional[str] = None
    quantidade_por_variacao: Optional[float] = None
    unidade_quantidade: Optional[str] = None
    briefing_especifico: Optional[str] = None
    resultado: Optional[str] = None
    produto: Optional[str] = None
    objetivo_projeto: Optional[str] = None
    aplicacoes_desenvolver: Optional[str] = None
    ativos_claims: Optional[str] = None
    referencias: Optional[str] = None
    referencias_fotos: Optional[List[str]] = None
    orcamento_projeto: Optional[str] = None
    textura_esperada: Optional[str] = None
    aplicacao: Optional[str] = None
    sensorial: Optional[str] = None
    ph: Optional[str] = None

class SampleMove(BaseModel):
    stage: str
    motivo_retrabalho: Optional[str] = None
    origem_retrabalho: Optional[str] = None
    feedback_cliente: Optional[str] = None
    direcoes_retrabalho: Optional[str] = None

class VariacaoItem(BaseModel):
    descricao_aplicacao: str
    percentual_fragrancia: Optional[float] = None
    referencia_fragrancia: str = ""   # R07: deve seguir padrão "FR-NNNNN - Nome"
    fr_codigo: str = ""               # R08: código interno do cadastro db.fragrancias
    custo_fragrancia: Optional[float] = None
    custo_fragrancia_currency: str = "BRL"
    observacoes_especificas: str = ""
    feedback_cliente: str = ""
    direcoes_retrabalho: str = ""

class SampleBatchItemV2(BaseModel):
    """Nova versão com suporte a variações"""
    nome_produto: str
    categoria: str = ""
    briefing_base: str = ""
    responsavel_pd: str = ""
    parametro_variacao: str = ""
    tipo_amostra: str = ""
    referencia_formula: str = ""
    quantidade_por_variacao: Optional[float] = None
    unidade_quantidade: str = "g"
    prazo_entrega_cliente: str = ""
    briefing_especifico: str = ""
    feedback_cliente: str = ""
    direcoes_retrabalho: str = ""
    resultado: str = ""
    # Campos de briefing herdados
    produto: str = ""
    objetivo_projeto: str = ""
    aplicacoes_desenvolver: str = ""
    ativos_claims: str = ""
    referencias: str = ""
    referencias_fotos: List[str] = []
    orcamento_projeto: str = ""
    textura_esperada: str = ""
    aplicacao: str = ""
    sensorial: str = ""
    ph: str = ""
    observacao_tecnica: str = ""
    # Variações
    variacoes: List[VariacaoItem] = []

class SampleBatchCreateV2(BaseModel):
    projeto_id: str
    samples: List[SampleBatchItemV2]
    # R02: campos do card a atualizar no projeto antes de criar amostras
    projeto_updates: Optional[dict] = None

class VariacaoUpdate(BaseModel):
    descricao_aplicacao: Optional[str] = None
    percentual_fragrancia: Optional[float] = None
    referencia_fragrancia: Optional[str] = None
    custo_fragrancia: Optional[float] = None
    custo_fragrancia_currency: Optional[str] = None
    observacoes_especificas: Optional[str] = None
    feedback_cliente: Optional[str] = None

class VariacaoMove(BaseModel):
    status: str
    motivo_retrabalho: Optional[str] = None
    origem_retrabalho: Optional[str] = None
    feedback_cliente: Optional[str] = None
    direcoes_retrabalho: Optional[str] = None

class SKUUpdate(BaseModel):
    preco_unitario: Optional[float] = None
    preco_unitario_currency: Optional[str] = None
    moq: Optional[int] = None
    anvisa_numero: Optional[str] = None
    anvisa_validade: Optional[str] = None
    status: Optional[str] = None
    nome_produto: Optional[str] = None

class SKUMetaUpdate(BaseModel):
    meta_unh: Optional[float] = None
    ajuste_percentual: Optional[float] = None  # -100 to +100

class SKUDescontinuar(BaseModel):
    motivo: str

class OrderAdd(BaseModel):
    data_pedido: str
    quantidade: int
    valor_total: float
    observacao: str = ""

class AlertResolve(BaseModel):
    comment: str = ""

class FollowUpSchedule(BaseModel):
    """Agendamento de follow-up manual (RN-FU-03)"""
    client_id: str
    data_follow_up: str  # ISO datetime
    observacao: str = ""

# ============ HELPER ============

def _serialize(doc: dict) -> dict:
    """Remove MongoDB _id from doc"""
    if doc:
        doc.pop("_id", None)
    return doc


def _normalize_currency_code(value: Optional[str], default: str = "BRL") -> str:
    code = (value or default or "BRL").strip().upper()
    return code if code in {"BRL", "USD"} else default

async def _get_next_sample_code(projeto_id: str, tenant_id: str) -> str:
    """Retorna o próximo código de amostra GLOBAL no formato {ANO}-{NNNN} (ERP v3.0)."""
    return await next_sample_code(tenant_id)


async def _resolve_cli4(tenant_id: str, requested: str, nome_empresa: str) -> str:
    """
    Return the CLI4 to use for a new client.
    - If `requested` is provided and unique: use it.
    - If `requested` is empty: auto-suggest from `nome_empresa`.
    - Raises HTTPException 409 if the requested code conflicts.
    """
    if requested:
        code = normalise_cli4(requested)
        conflict = await db.crm_clients.find_one(
            {"tenant_id": tenant_id, "cli4": code}, {"_id": 0, "nome_empresa": 1}
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"CLI4 '{code}' já está em uso pelo cliente '{conflict['nome_empresa']}'"
            )
        return code

    # Auto-suggest from name
    candidates = suggest_cli4_candidates(nome_empresa)
    for code in candidates:
        conflict = await db.crm_clients.find_one(
            {"tenant_id": tenant_id, "cli4": code}, {"_id": 0}
        )
        if not conflict:
            return code
    # Fallback: first candidate even if occupied (caller can update later)
    return candidates[0] if candidates else normalise_cli4(nome_empresa)

LEGACY_PROJECT_STAGE_ALIASES = {
    "amostras": "amostra_solicitada",
}

def _normalize_project_stage(stage: Optional[str]) -> Optional[str]:
    if not stage:
        return stage
    return LEGACY_PROJECT_STAGE_ALIASES.get(stage, stage)

def _project_stage_rank(stage: Optional[str]) -> int:
    normalized = _normalize_project_stage(stage)
    order = [
        "projeto_em_discussao",
        "amostra_solicitada",
        "amostra_em_desenvolvimento",
        "amostra_enviada",
        "em_negociacao",
        "pedido_aprovado",
        "projeto_arquivado",
    ]
    try:
        return order.index(normalized)
    except ValueError:
        return -1

def _business_days_before(date_str: str, days: int) -> Optional[datetime]:
    if not date_str:
        return None
    raw = clean_text(date_str)
    if not raw:
        return None
    try:
        target = datetime.fromisoformat(raw)
    except ValueError:
        try:
            target = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    current = target
    remaining = max(days, 0)
    while remaining > 0:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current

def _days_until(target: Optional[datetime]) -> Optional[int]:
    if not target:
        return None
    now = datetime.now()
    delta = target - now
    return max(delta.days, 0)

def _now_plus_hours_iso(now: str, hours: int) -> str:
    try:
        base = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + timedelta(hours=hours)).isoformat()

def _initial_sample_test_state(now: str) -> dict:
    return {
        "status_teste": "aguardando",
        "prazo_teste_ate": _now_plus_hours_iso(now, 48),
        "inicio_teste_em": None,
        "fim_teste_em": None,
        "teste_historico": [{
            "de": "",
            "para": "aguardando",
            "data": now,
            "sla_horas": 48,
            "origem": "crm_sample_created",
        }],
    }

def _sample_test_patch_for_pd_status(pd_status: str, now: str) -> tuple[dict, Optional[dict]]:
    status_map = {
        "em_testes": "em_teste",
        "aguardando_aprovacao": "liberada",
        "aprovado": "liberada",
        "concluido": "liberada",
        "retrabalho_interno": "reprovada",
    }
    status_teste = status_map.get(pd_status)
    if not status_teste:
        return {}, None

    patch = {
        "status_teste": status_teste,
        "prazo_teste_ate": _now_plus_hours_iso(now, 48),
        "updated_at": now,
    }
    if status_teste == "em_teste":
        patch["inicio_teste_em"] = now
        patch["fim_teste_em"] = None
    elif status_teste in {"liberada", "reprovada"}:
        patch["fim_teste_em"] = now

    history = {
        "para": status_teste,
        "data": now,
        "status_pd": pd_status,
        "sla_horas": 48,
        "origem": "pd_status_sync",
    }
    return patch, history

def _build_briefing_record(
    *,
    tenant_id: str,
    project: dict,
    sample_id: str,
    sample_payload: dict,
    user: dict,
    now: str,
    origem: str = "crm_sample",
) -> dict:
    campos = {
        "nome_produto": sample_payload.get("nome_produto") or sample_payload.get("nome_amostra", ""),
        "categoria": sample_payload.get("categoria", ""),
        "briefing_base": sample_payload.get("briefing_base", ""),
        "briefing_especifico": sample_payload.get("briefing_especifico", ""),
        "produto": sample_payload.get("produto", ""),
        "objetivo_projeto": sample_payload.get("objetivo_projeto", ""),
        "aplicacoes_desenvolver": sample_payload.get("aplicacoes_desenvolver", ""),
        "ativos_claims": sample_payload.get("ativos_claims", ""),
        "referencias": sample_payload.get("referencias", ""),
        "textura_esperada": sample_payload.get("textura_esperada", ""),
        "aplicacao": sample_payload.get("aplicacao", ""),
        "sensorial": sample_payload.get("sensorial", ""),
        "ph": sample_payload.get("ph", ""),
        "observacao_tecnica": sample_payload.get("observacao_tecnica", ""),
        "publico_alvo": project.get("publico_alvo", ""),
        "posicionamento": project.get("posicionamento", ""),
        "tipo_servico": project.get("tipo_servico", ""),
        "volume_estimado_pedido": project.get("volume_estimado_pedido"),
        "prazo_desejado_amostra": project.get("prazo_desejado_amostra", ""),
    }
    return {
        "id": f"briefing-{sample_id}",
        "tenant_id": tenant_id,
        "cliente_id": project.get("cliente_id"),
        "cliente_nome": project.get("cliente_nome", ""),
        "projeto_id": project.get("id"),
        "projeto_nome": project.get("nome_projeto", ""),
        "amostra_id": sample_id,
        "versao": 1,
        "status": "ativo",
        "origem": origem,
        "campos": campos,
        "created_by": user.get("id"),
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }

async def _persist_briefing_record(record: dict):
    collection = getattr(db, "crm_briefings", None)
    if collection and hasattr(collection, "insert_one"):
        await collection.insert_one(dict(record))
    return record

def _build_client_decision(
    *,
    resultado: str,
    feedback_cliente: str,
    direcoes_retrabalho: str,
    user: dict,
    now: str,
    rework_sample_id: Optional[str] = None,
):
    canonical = "arquivado" if resultado == "reprovada" else resultado
    return {
        "resultado": canonical,
        "feedback_cliente": feedback_cliente or "",
        "direcoes_retrabalho": direcoes_retrabalho or "",
        "registrado_por": user.get("id"),
        "registrado_por_nome": user.get("name", ""),
        "registrado_em": now,
        "rework_sample_id": rework_sample_id,
    }

async def _create_project_deadline_alert_task(project: dict, user: dict):
    prazo = clean_text(project.get("prazo_desejado_amostra", ""))
    if not prazo:
        return None
    alert_date = _business_days_before(prazo, 3)
    if not alert_date:
        return None
    due_in_days = _days_until(alert_date)
    existing = await db.workflow_tasks.find_one(
        {
            "tenant_id": user["tenant_id"],
            "entity_type": "project",
            "entity_id": project["id"],
            "title": "Prazo-alvo da amostra em 3 dias uteis",
            "status": {"$in": ["pendente", "em_andamento"]},
        },
        {"_id": 0},
    )
    if existing:
        return existing
    return await create_workflow_task(
        tenant_id=user["tenant_id"],
        entity_type="project",
        entity_id=project["id"],
        title="Prazo-alvo da amostra em 3 dias uteis",
        description=f"Alerta automatico para o prazo desejado de amostra ({prazo}).",
        category="projeto",
        blocking=False,
        due_in_days=due_in_days if due_in_days is not None else 0,
        responsible_id=project.get("responsavel_comercial") or project.get("created_by"),
        created_by=user,
        metadata={
            "trigger": "prazo_desejado_amostra",
            "prazo_desejado_amostra": prazo,
            "alerta_para": alert_date.date().isoformat(),
        },
    )


async def _rollback_batch_created_projects(
    tenant_id: str,
    *,
    project_ids: List[str],
    workflow_task_ids: List[str],
    audit_log_ids: List[str],
):
    if workflow_task_ids:
        await db.workflow_tasks.delete_many(
            {"tenant_id": tenant_id, "id": {"$in": workflow_task_ids}}
        )
    if audit_log_ids:
        await db.audit_logs.delete_many(
            {"tenant_id": tenant_id, "id": {"$in": audit_log_ids}}
        )
    if project_ids:
        await db.crm_projects.delete_many(
            {"tenant_id": tenant_id, "id": {"$in": project_ids}}
        )


CRM_TO_PD_STATUS_MAP = {
    "solicitada": "solicitado",
    "em_elaboracao": "em_desenvolvimento",
    "enviada": "aguardando_aprovacao",
    "reprovada": "retrabalho_interno",
    "retrabalho": "retrabalho_interno",
}


async def _broadcast_pd_card_update(tenant_id: str, card: dict, old_status: str, new_status: str):
    if not _broadcast_event or not card:
        return
    await _broadcast_event(
        tenant_id,
        "pd_card_moved",
        {
            "card": card,
            "from_status": old_status,
            "to_status": new_status,
        },
    )


async def _sync_pd_cards_from_crm_stage(
    *,
    tenant_id: str,
    sample_id: str,
    user: dict,
    now: str,
    crm_stage: str,
    variacao_id: Optional[str] = None,
    feedback_cliente: str = "",
    direcoes_retrabalho: str = "",
    resultado_cliente: str = "",
):
    pd_status = CRM_TO_PD_STATUS_MAP.get(crm_stage)
    if not pd_status:
        return []

    query = {"tenant_id": tenant_id}
    if variacao_id:
        query["amostra_variacao_id"] = variacao_id
    else:
        query["amostra_id"] = sample_id

    cards = await db.pd_cards.find(query, {"_id": 0}).to_list(200)
    updated_cards = []
    for card in cards:
        old_status = card.get("status_pd", "")
        updates = {
            "status_pd": pd_status,
            "updated_at": now,
        }
        if feedback_cliente:
            updates["feedback_cliente"] = feedback_cliente
        if direcoes_retrabalho:
            updates["direcoes_retrabalho"] = direcoes_retrabalho
        if resultado_cliente:
            updates["resultado_cliente"] = resultado_cliente

        history_entry = {
            "de": old_status,
            "para": pd_status,
            "data": now,
            "usuario": user["name"],
            "usuario_id": user["id"],
            "observacao": f"Sincronizado automaticamente pelo CRM: {STAGE_LABELS.get(crm_stage, crm_stage)}",
            "sincronizado_crm": True,
        }
        if resultado_cliente:
            history_entry["resultado_cliente"] = resultado_cliente

        await db.pd_cards.update_one(
            {"id": card["id"], "tenant_id": tenant_id},
            {
                "$set": updates,
                "$push": {"historico_movimentacoes": history_entry},
            },
        )

        updated_card = {**card, **updates}
        updated_cards.append(updated_card)
        await _broadcast_pd_card_update(tenant_id, updated_card, old_status, pd_status)

    return updated_cards

async def _advance_project_stage_if_needed(
    project_id: str,
    target_stage: str,
    user: dict,
    *,
    movement_source: str,
    extra_set: Optional[dict] = None,
):
    project = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not project:
        return None

    old_stage = _normalize_project_stage(project.get("stage"))
    new_stage = _normalize_project_stage(target_stage)
    if not old_stage or not new_stage or old_stage == new_stage:
        return project

    allowed = [_normalize_project_stage(stage) for stage in PROJECT_TRANSITIONS.get(old_stage, [])]
    if new_stage not in allowed:
        old_rank = _project_stage_rank(old_stage)
        new_rank = _project_stage_rank(new_stage)
        can_auto_advance = (
            old_rank >= 0
            and new_rank > old_rank
            and new_stage != "projeto_arquivado"
            and old_stage != "projeto_arquivado"
        )
        if not can_auto_advance:
            return project

    now = _now_iso()
    movement = {
        "de": old_stage,
        "para": new_stage,
        "data": now,
        "usuario": user["name"],
        "usuario_id": user["id"],
        "origem": movement_source,
    }

    update_fields = {"stage": new_stage, "updated_at": now}
    if extra_set:
        update_fields.update(extra_set)

    await db.crm_projects.update_one(
        {"id": project_id, "tenant_id": user["tenant_id"]},
        {
            "$set": update_fields,
            "$push": {"historico_movimentacoes": movement},
        },
    )
    updated = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )

    new_tasks = await trigger_tasks_for_transition(
        entity_type="project",
        entity_id=project_id,
        tenant_id=user["tenant_id"],
        old_stage=old_stage,
        new_stage=new_stage,
        user=user,
    )
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="project_auto_moved",
        entity_type="project",
        entity_id=project_id,
        before={"stage": old_stage},
        after={"stage": new_stage},
        metadata={
            "source": movement_source,
            "tasks_generated": [task["id"] for task in new_tasks],
        },
    )
    if new_stage == "em_negociacao" and updated:
        await _mirror_client_stage_to_negociacao(updated, user)

    return updated


def _pd_status_to_project_stage_sync(pd_status: str, now: str) -> Optional[tuple[str, str, dict]]:
    if pd_status == "solicitado":
        return (
            "amostra_solicitada",
            "pd_card_requested",
            {},
        )
    if pd_status == "em_desenvolvimento":
        return (
            "amostra_em_desenvolvimento",
            "pd_card_in_development",
            {"data_inicio_desenvolvimento": now},
        )
    if pd_status == "aguardando_aprovacao":
        return (
            "amostra_enviada",
            "pd_card_waiting_approval",
            {"data_ultima_amostra_enviada": now},
        )
    if pd_status == "retrabalho_interno":
        return (
            "amostra_em_desenvolvimento",
            "pd_card_rework",
            {"data_inicio_desenvolvimento": now},
        )
    return None


async def _mirror_client_stage_to_negociacao(project: dict, user: dict):
    """Quando CRM2 vai para em_negociacao, espelha o cliente no CRM1 para 'negociacao'."""
    cliente_id = project.get("cliente_id")
    if not cliente_id:
        return
    client = await db.crm_clients.find_one(
        {"id": cliente_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not client:
        return
    old_stage = client.get("stage", "")
    if old_stage in ("negociacao", "cliente_fechado", "cliente_perdido"):
        return
    now = _now_iso()
    movement = {
        "de": old_stage,
        "para": "negociacao",
        "data": now,
        "usuario": user["name"],
        "usuario_id": user["id"],
        "origem": "espelho_crm2_em_negociacao",
    }
    await db.crm_clients.update_one(
        {"id": cliente_id, "tenant_id": user["tenant_id"]},
        {
            "$set": {"stage": "negociacao", "updated_at": now},
            "$push": {"historico_movimentacoes": movement},
        },
    )


def _normalize_contact_payload(contact: Optional[dict]) -> dict:
    payload = contact or {}
    return {
        "nome": clean_text(payload.get("nome", "")),
        "whatsapp": normalize_phone(payload.get("whatsapp", "")),
        "email": normalize_email(payload.get("email", "")),
    }


def _normalize_additional_contacts_payload(contacts: Optional[List[dict]]) -> List[dict]:
    normalized = []
    for item in contacts or []:
        payload = item or {}
        contact = {
            "nome": clean_text(payload.get("nome", "")),
            "cargo": clean_text(payload.get("cargo", "")).lower(),
            "whatsapp": normalize_phone(payload.get("whatsapp", "")),
            "email": normalize_email(payload.get("email", "")),
        }
        if any(contact.values()):
            normalized.append(contact)
    return normalized


async def _validate_client_payload(
    tenant_id: str,
    payload: dict,
    exclude_id: Optional[str] = None,
    require_required_fields: bool = False,
    fields_being_updated: Optional[set] = None,
) -> dict:
    payload["nome_empresa"] = clean_text(payload.get("nome_empresa", ""))
    if not payload["nome_empresa"]:
        raise HTTPException(status_code=400, detail="Nome da empresa é obrigatório")

    payload["canal_origem"] = clean_text(payload.get("canal_origem", ""))
    payload["origem_lead"] = clean_text(payload.get("origem_lead", ""))
    payload["categoria_interesse"] = [clean_text(item) for item in (payload.get("categoria_interesse") or []) if clean_text(item)]
    payload["contato_principal"] = _normalize_contact_payload(payload.get("contato_principal"))
    payload["contatos_adicionais"] = _normalize_additional_contacts_payload(payload.get("contatos_adicionais"))
    payload["temperatura_lead"] = clean_text(payload.get("temperatura_lead", "morno")).lower() or "morno"
    payload["responsavel_comercial"] = clean_text(payload.get("responsavel_comercial", ""))
    payload["segmento"] = clean_text(payload.get("segmento", "")).lower()
    payload["porte"] = clean_text(payload.get("porte", "")).lower()
    payload["regiao"] = clean_text(payload.get("regiao", "")).upper()
    payload["site"] = clean_text(payload.get("site", ""))
    payload["instagram"] = clean_text(payload.get("instagram", ""))
    payload["observacoes"] = clean_text(payload.get("observacoes", ""))
    for contact in payload["contatos_adicionais"]:
        if contact["email"] and not is_valid_email(contact["email"]):
            raise HTTPException(status_code=400, detail=f"E-mail inválido em contato adicional: {contact['nome'] or contact['email']}")
        if contact["whatsapp"] and not is_valid_phone(contact["whatsapp"]):
            raise HTTPException(status_code=400, detail=f"WhatsApp inválido em contato adicional: {contact['nome'] or contact['whatsapp']}")
        if contact["cargo"] and contact["cargo"] not in CARGO_DECISOR_OPTIONS:
            raise HTTPException(status_code=400, detail="Cargo inválido em contato adicional")

    cnpj_normalized = normalize_cnpj(payload.get("cnpj", ""))
    payload["cnpj"] = clean_text(payload.get("cnpj", ""))
    payload["cnpj_normalized"] = cnpj_normalized
    if cnpj_normalized:
        query = {"tenant_id": tenant_id, "cnpj_normalized": cnpj_normalized}
        if exclude_id:
            query["id"] = {"$ne": exclude_id}
        existing = await db.crm_clients.find_one(query, {"_id": 0, "nome_empresa": 1})
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"CNPJ já cadastrado para o cliente '{existing.get('nome_empresa', '')}'.",
            )

    email = payload["contato_principal"].get("email")
    whatsapp = payload["contato_principal"].get("whatsapp")
    if email and not is_valid_email(email):
        raise HTTPException(status_code=400, detail="E-mail do contato principal inválido")
    if whatsapp and not is_valid_phone(whatsapp):
        raise HTTPException(status_code=400, detail="Telefone/WhatsApp do contato principal inválido")

    if payload["canal_origem"] and (fields_being_updated is None or "canal_origem" in fields_being_updated):
        valid_sources = await _get_valid_lead_sources(tenant_id)
        if payload["canal_origem"] not in valid_sources:
            raise HTTPException(status_code=400, detail="Canal de origem inválido")

    # Validar categorias de interesse (2 níveis)
    all_valid_categories = []
    for category, subcategories in CATEGORIA_INTERESSE_OPTIONS.items():
        all_valid_categories.append(category)
        all_valid_categories.extend(subcategories)
    
    invalid_categories = [item for item in payload["categoria_interesse"] if item not in all_valid_categories]
    if invalid_categories:
        raise HTTPException(status_code=400, detail=f"Categoria(s) inválida(s): {', '.join(invalid_categories)}")

    # Validar temperatura do lead
    temperatura = payload.get("temperatura_lead", "morno")
    if temperatura and temperatura not in TEMPERATURA_LEAD_OPTIONS:
        raise HTTPException(status_code=400, detail="Temperatura do lead inválida")

    # Validar segmento
    segmento = payload.get("segmento", "")
    if segmento and segmento not in SEGMENTO_CLIENTE_OPTIONS:
        raise HTTPException(status_code=400, detail="Segmento inválido")

    # Validar porte
    porte = payload.get("porte", "")
    if porte and porte not in PORTE_CLIENTE_OPTIONS:
        raise HTTPException(status_code=400, detail="Porte inválido")

    # Verificar se há categorias Grau 2 ANVISA e alertar
    has_grau2 = any(cat in CATEGORIAS_GRAU2 for cat in payload["categoria_interesse"])
    payload["has_grau2_anvisa"] = has_grau2

    if payload["regiao"] and payload["regiao"] not in UF_OPTIONS:
        raise HTTPException(status_code=400, detail="UF inválida")

    if payload["responsavel_comercial"]:
        responsible = await db.users.find_one(
            {"id": payload["responsavel_comercial"], "tenant_id": tenant_id},
            {"_id": 0, "id": 1},
        )
        if not responsible:
            raise HTTPException(status_code=400, detail="Responsável comercial inválido")

    if require_required_fields:
        # A2: lead de prospecção — criação inicial exige só nome_empresa. Os demais
        # campos (contato, canal_origem, categoria_interesse, temperatura, responsável,
        # segmento) só passam a ser obrigatórios na transição para "qualificado"
        # (ver _validate_client_transition_requirements).
        if not clean_text(payload.get("nome_empresa", "")):
            raise HTTPException(status_code=400, detail="Campo obrigatório ausente: nome_empresa")

    return payload


CLIENT_QUALIFICATION_REQUIRED_FIELDS = [
    ("canal_origem", "Canal de origem"),
    ("categoria_interesse", "Categoria de interesse"),
    ("temperatura_lead", "Temperatura"),
    ("responsavel_comercial", "Responsável comercial"),
    ("segmento", "Segmento"),
    ("contato_principal.nome", "Contato — nome"),
    ("contato_principal.whatsapp", "Contato — WhatsApp"),
]

CLIENT_PROJECT_GATE_REQUIRED_FIELDS = [
    ("canal_origem", "Canal de origem"),
    ("categoria_interesse", "Categoria de interesse"),
    ("temperatura_lead", "Temperatura"),
    ("responsavel_comercial", "ResponsÃ¡vel comercial"),
    ("segmento", "Segmento"),
    ("contato_principal.nome", "Contato â€” nome"),
    ("contato_principal.whatsapp", "Contato â€” WhatsApp"),
    ("decisores", "Decisores"),
    ("tem_anvisa", "ANVISA"),
    ("volume_estimado_mensal", "Volume estimado mensal"),
    ("fornecedor_atual", "Fornecedor atual"),
]


def get_missing_qualification_fields(client: dict) -> list:
    """Campos exigidos para avançar um lead de 'prospecção' para 'qualificado' (A2)."""
    contact = client.get("contato_principal") or {}
    missing = []
    if not client.get("canal_origem"):
        missing.append("canal_origem")
    if not client.get("categoria_interesse"):
        missing.append("categoria_interesse")
    if not client.get("temperatura_lead"):
        missing.append("temperatura_lead")
    if not client.get("responsavel_comercial"):
        missing.append("responsavel_comercial")
    if not client.get("segmento"):
        missing.append("segmento")
    if not clean_text(contact.get("nome", "")):
        missing.append("contato_principal.nome")
    if not contact.get("whatsapp"):
        missing.append("contato_principal.whatsapp")
    return missing


def get_missing_project_gate_fields(client: dict) -> list:
    """Campos exigidos para permitir criaÃ§Ã£o de projeto / avanÃ§o atÃ© Projeto em DiscussÃ£o."""
    missing = list(get_missing_qualification_fields(client))

    decisores = client.get("decisores") or []
    has_decisor = any(clean_text((item or {}).get("nome", "")) for item in decisores if isinstance(item, dict))
    if not has_decisor:
        missing.append("decisores")

    if not clean_text(client.get("tem_anvisa", "")):
        missing.append("tem_anvisa")

    if not clean_text(client.get("volume_estimado_mensal", "")):
        missing.append("volume_estimado_mensal")

    fornecedor_atual = client.get("fornecedor_atual")
    if not isinstance(fornecedor_atual, dict) or "tem" not in fornecedor_atual:
        missing.append("fornecedor_atual")

    return list(dict.fromkeys(missing))


def _normalize_tem_anvisa_value(value: Optional[str]) -> str:
    raw = clean_text(value or "").lower().replace(" ", "_")
    if raw in ("depende_de_nos", "depende_de_nós", "depende"):
        return "depende"
    if raw in ("sim", "nao"):
        return raw
    return raw


def _validate_client_transition_requirements(client: dict, target_stage: str):
    if target_stage != "qualificado":
        return
    missing = get_missing_qualification_fields(client)
    if missing:
        labels = dict(CLIENT_QUALIFICATION_REQUIRED_FIELDS)
        readable = ", ".join(labels.get(m, m) for m in missing)
        raise HTTPException(
            status_code=409,
            detail=f"Preencha os campos obrigatórios antes de avançar: {readable}",
        )


def _validate_project_gate_requirements(client: dict):
    missing = get_missing_project_gate_fields(client)
    if missing:
        labels = dict(CLIENT_PROJECT_GATE_REQUIRED_FIELDS)
        readable = ", ".join(labels.get(field, field) for field in missing)
        raise HTTPException(
            status_code=409,
            detail=f"Preencha a qualificaÃ§Ã£o do cliente antes de criar o projeto: {readable}",
        )


def _validate_project_transition_requirements(project: dict, target_stage: str):
    normalized_stage = _normalize_project_stage(target_stage)
    if normalized_stage != "amostra_solicitada":
        return
    missing = []
    if not clean_text(project.get("nome_projeto", "")):
        missing.append("nome_projeto")
    if not clean_text(project.get("categoria", "")):
        missing.append("categoria")
    if not clean_text(project.get("responsavel_comercial", "")):
        missing.append("responsavel_comercial")
    if not clean_text(project.get("ideia_conceito", "")) and not clean_text(project.get("briefing_tecnico", "")):
        missing.append("ideia_conceito")
    if not clean_text(project.get("posicionamento", "")):
        missing.append("posicionamento")
    if not project.get("volume_estimado_pedido"):
        missing.append("volume_estimado_pedido")
    if not clean_text(project.get("tipo_servico", "")):
        missing.append("tipo_servico")
    if not clean_text(project.get("prazo_desejado_amostra", "")) and not clean_text(project.get("prazo_prometido_cliente", "")):
        missing.append("prazo_desejado_amostra")
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Preencha o pré-briefing antes de avançar: {', '.join(missing)}",
        )

# ======================================================================
#  CRM 1 — CLIENTS (Pipeline Comercial)
# ======================================================================

@crm_router.get("/clients/suggest-cli4")
async def suggest_cli4_endpoint(nome: str, request: Request):
    """
    R23: Retorna sugestões de CLI4 (4 letras) para um nome de empresa,
    indicando disponibilidade de cada código.
    """
    user = await _get_current_user(request)
    candidates = suggest_cli4_candidates(nome)
    result = []
    for code in candidates[:6]:
        conflict = await db.crm_clients.find_one(
            {"tenant_id": user["tenant_id"], "cli4": code},
            {"_id": 0, "nome_empresa": 1},
        )
        result.append({
            "cli4": code,
            "disponivel": conflict is None,
            "ocupado_por": conflict["nome_empresa"] if conflict else None,
        })
    return {"sugestoes": result}


@crm_router.post("/clients")
async def create_client(data: ClientCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL)
    client_id = _new_id()

    now = _now_iso()
    create_payload = await _validate_client_payload(
        user["tenant_id"],
        {
            "nome_empresa": data.nome_empresa,
            "cnpj": data.cnpj,
            "contato_principal": data.contato_principal.model_dump() if data.contato_principal else {"nome": "", "whatsapp": "", "email": ""},
            "contatos_adicionais": [item.model_dump() for item in data.contatos_adicionais],
            "canal_origem": data.canal_origem,
            "categoria_interesse": data.categoria_interesse,
            "origem_lead": data.origem_lead,
            # Novos campos PRD
            "temperatura_lead": data.temperatura_lead or "morno",
            "responsavel_comercial": data.responsavel_comercial or user["id"],
            "segmento": data.segmento or "outro",
            "porte": data.porte,
            "regiao": data.regiao,
            "site": data.site,
            "instagram": data.instagram,
            "observacoes": data.observacoes,
        },
        require_required_fields=True,
    )

    client = {
        "id": client_id,
        "tenant_id": user["tenant_id"],
        "stage": "prospeccao",
        # Prospecção fields
        "nome_empresa": create_payload["nome_empresa"],
        "cnpj": create_payload["cnpj"],
        "cnpj_normalized": create_payload["cnpj_normalized"],
        "contato_principal": create_payload["contato_principal"],
        "contatos_adicionais": create_payload["contatos_adicionais"],
        "canal_origem": create_payload["canal_origem"],
        "categoria_interesse": create_payload["categoria_interesse"],
        "origem_lead": create_payload["origem_lead"],
        # Novos campos PRD
        "temperatura_lead": create_payload["temperatura_lead"],
        "responsavel_comercial": create_payload["responsavel_comercial"],
        "segmento": create_payload["segmento"],
        "porte": create_payload["porte"],
        "regiao": create_payload["regiao"],
        "site": create_payload["site"],
        "instagram": create_payload["instagram"],
        "observacoes": create_payload["observacoes"],
        "cli3": normalise_cli3(data.cli3 or ""),
        "cli4": await _resolve_cli4(user["tenant_id"], data.cli4, data.nome_empresa),
        "cli4_congelado": False,
        "has_grau2_anvisa": create_payload.get("has_grau2_anvisa", False),
        "ultima_atualizacao_temperatura": now,
        # Qualificado fields — pre-filled if provided at creation
        "decisores": [d.model_dump() for d in data.decisores] if data.decisores else [],
        "tem_marca_propria": None,
        "tem_anvisa": _normalize_tem_anvisa_value(data.tem_anvisa),
        "volume_estimado_mensal": data.volume_estimado_mensal or "",
        "fornecedor_atual": data.fornecedor_atual.model_dump() if data.fornecedor_atual else {"tem": False, "motivo_troca": ""},
        "prazo_urgencia": None,
        # Negociação fields (empty initially)
        "amostras_aprovadas": [],
        "valor_estimado_projeto": None,
        "moq_negociado": "",
        "condicao_pagamento": "",
        "anvisa_necessario": {"necessario": False, "status": ""},
        "concorrentes_envolvidos": [],
        # Fechado fields (empty initially)
        "data_pedido": None,
        "skus_confirmados": [],
        "valor_primeiro_pedido": None,
        "previsao_segundo_pedido": None,
        # Perdido
        "motivo_perda": "",
        # Meta
        "historico_movimentacoes": [],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }

    await db.crm_clients.insert_one(client)
    initial_task = await create_workflow_task(
        tenant_id=user["tenant_id"],
        entity_type="client",
        entity_id=client_id,
        title="Realizar primeiro contato comercial",
        description="Tarefa gerada automaticamente ao entrar em Prospecção.",
        category="comercial",
        blocking=False,
        due_in_days=3,
        responsible_id=client["responsavel_comercial"],
        created_by=user,
        metadata={"trigger": "client_created", "stage": "prospeccao"},
    )
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="client_created",
        entity_type="client",
        entity_id=client_id,
        after={"nome_empresa": client["nome_empresa"], "stage": client["stage"]},
        metadata={"tasks_generated": [initial_task["id"]]},
    )
    return _serialize(client)


@crm_router.get("/clients")
async def list_clients(
    request: Request,
    stage: Optional[str] = None,
    search: Optional[str] = None,
):
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if stage:
        query["stage"] = stage
    if search:
        search = clean_text(search)
        digits = normalize_phone(search)
        query["$or"] = [
            {"nome_empresa": {"$regex": search, "$options": "i"}},
            {"cnpj": {"$regex": search, "$options": "i"}},
            {"contato_principal.nome": {"$regex": search, "$options": "i"}},
            {"contato_principal.email": {"$regex": search, "$options": "i"}},
            {"categoria_interesse": {"$regex": search, "$options": "i"}},
        ]
        if digits:
            query["$or"].extend([
                {"cnpj_normalized": {"$regex": digits}},
                {"contato_principal.whatsapp": {"$regex": digits}},
            ])

    clients = await db.crm_clients.find(query, {"_id": 0}).sort("created_at", -1).to_list(5000)
    for c in clients:
        c["missing_qualification_fields"] = get_missing_qualification_fields(c) if c.get("stage") == "prospeccao" else []
    return clients


@crm_router.get("/clients/{client_id}")
async def get_client(client_id: str, request: Request):
    user = await _get_current_user(request)
    client = await db.crm_clients.find_one(
        {"id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    client["missing_qualification_fields"] = get_missing_qualification_fields(client) if client.get("stage") == "prospeccao" else []
    return client


@crm_router.put("/clients/{client_id}")
async def update_client(client_id: str, data: ClientUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL)
    existing = await db.crm_clients.find_one(
        {"id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    update_fields = {}
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            if isinstance(v, BaseModel):
                update_fields[k] = v.model_dump()
            else:
                update_fields[k] = v

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # RN-CL-04: Registrar data de atualização de temperatura
    if "temperatura_lead" in update_fields:
        update_fields["ultima_atualizacao_temperatura"] = _now_iso()

    # RN-SK-01: cli3 must be exactly 3 uppercase alpha chars
    if "cli3" in update_fields:
        raw = str(update_fields["cli3"] or "")
        letters = "".join(c for c in raw.upper() if c.isalpha())[:3]
        if letters and len(letters) < 3:
            raise HTTPException(status_code=400, detail=f"cli3 deve ter 3 letras (ex: 'ABC'). Recebido: '{raw}'")
        update_fields["cli3"] = letters or ""

    if "tem_anvisa" in update_fields:
        update_fields["tem_anvisa"] = _normalize_tem_anvisa_value(update_fields["tem_anvisa"])

    # R23: cli4 freeze — not editable after first SKU
    if "cli4" in update_fields:
        if existing.get("cli4_congelado"):
            raise HTTPException(
                status_code=409,
                detail=f"CLI4 '{existing.get('cli4')}' está congelado — já existe SKU gerado para este cliente e o código não pode mais ser alterado"
            )
        new_cli4 = normalise_cli4(str(update_fields["cli4"] or ""))
        conflict = await db.crm_clients.find_one(
            {"tenant_id": user["tenant_id"], "cli4": new_cli4, "id": {"$ne": client_id}},
            {"_id": 0, "nome_empresa": 1},
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"CLI4 '{new_cli4}' já está em uso pelo cliente '{conflict['nome_empresa']}'"
            )
        update_fields["cli4"] = new_cli4

    payload = dict(existing)
    payload.update(update_fields)
    payload = await _validate_client_payload(
        user["tenant_id"], payload, exclude_id=client_id,
        fields_being_updated=set(update_fields.keys()),
    )
    for field in (
        "nome_empresa",
        "cnpj",
        "cnpj_normalized",
        "contato_principal",
        "contatos_adicionais",
        "canal_origem",
        "categoria_interesse",
        "origem_lead",
        "temperatura_lead",
        "responsavel_comercial",
        "segmento",
        "porte",
        "regiao",
        "site",
        "instagram",
        "observacoes",
        "has_grau2_anvisa",
    ):
        if field in update_fields or field == "cnpj_normalized":
            update_fields[field] = payload[field]

    update_fields["updated_at"] = _now_iso()

    result = await db.crm_clients.update_one(
        {"id": client_id, "tenant_id": user["tenant_id"]},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    client = await db.crm_clients.find_one({"id": client_id}, {"_id": 0})
    client["missing_qualification_fields"] = get_missing_qualification_fields(client) if client.get("stage") == "prospeccao" else []

    # Auto-complete "qualificacao" blocking task when all 4 fields are present
    await _auto_complete_qualificacao_task(client, user["tenant_id"], user)

    return client


async def _auto_complete_qualificacao_task(client: dict, tenant_id: str, user: dict):
    """Mark the 'Qualificar lead' blocking task as done when all required fields are filled.
    The three fields below have no default value — only non-empty means 'filled'."""
    missing = get_missing_project_gate_fields(client)
    missing = [field for field in missing if field not in set(get_missing_qualification_fields(client))]
    if missing:
        return

    now = _now_iso()
    await db.workflow_tasks.update_many(
        {
            "tenant_id": tenant_id,
            "entity_type": "client",
            "entity_id": client["id"],
            "category": "qualificacao",
            "status": {"$in": ["pendente", "em_andamento", "em_atraso"]},
        },
        {
            "$set": {
                "status": "concluida",
                "completed_at": now,
                "completed_by": user["id"],
                "completed_by_name": user.get("name", ""),
                "completion_comment": "Concluído automaticamente — decisores, ANVISA, volume e fornecedor preenchidos.",
                "updated_at": now,
            }
        }
    )


@crm_router.put("/clients/{client_id}/move")
async def move_client(client_id: str, data: ClientMove, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL)
    client = await db.crm_clients.find_one(
        {"id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    old_stage = client["stage"]
    new_stage = data.stage

    if new_stage not in CLIENT_STAGES:
        raise HTTPException(status_code=400, detail=f"Estágio inválido: {new_stage}")

    allowed = CLIENT_TRANSITIONS.get(old_stage, [])
    if new_stage not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Transição não permitida: {STAGE_LABELS.get(old_stage)} → {STAGE_LABELS.get(new_stage)}"
        )

    old_idx = _CLIENT_STAGE_ORDER.index(old_stage) if old_stage in _CLIENT_STAGE_ORDER else 0
    new_idx = _CLIENT_STAGE_ORDER.index(new_stage) if new_stage in _CLIENT_STAGE_ORDER else 0
    is_regression = new_idx < old_idx

    if is_regression and not (data.justificativa or "").strip():
        raise HTTPException(status_code=400, detail="Justificativa obrigatória para movimentações retroativas")

    # Auto-complete qualificacao task if fields are already filled
    await _auto_complete_qualificacao_task(client, user["tenant_id"], user)

    # ERP v3.0: bloquear avanço se houver tarefas obrigatórias pendentes
    _validate_client_transition_requirements(client, new_stage)
    if new_stage == "projeto_em_discussao":
        _validate_project_gate_requirements(client)
    await assert_no_blocking_tasks(
        tenant_id=user["tenant_id"],
        entity_type="client",
        entity_id=client_id,
        target_stage=new_stage,
    )

    # Validate motivo_perda for cliente_perdido
    if new_stage == "cliente_perdido" and not data.motivo_perda:
        raise HTTPException(status_code=400, detail="Motivo da perda é obrigatório")

    now = _now_iso()
    if new_stage == "cliente_perdido" and clean_text(data.motivo_perda).lower() not in MOTIVO_PERDA_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Motivo da perda inválido. Use: {', '.join(MOTIVO_PERDA_OPTIONS)}",
        )

    update_data = {
        "stage": new_stage,
        "updated_at": now,
    }

    if new_stage == "cliente_perdido" and data.motivo_perda:
        update_data["motivo_perda"] = clean_text(data.motivo_perda).lower()

    # Add to historico_movimentacoes
    movement = {
        "de": old_stage,
        "para": new_stage,
        "data": now,
        "usuario": user["name"],
        "usuario_id": user["id"],
        "is_regression": is_regression,
    }
    if is_regression and data.justificativa:
        movement["justificativa"] = data.justificativa.strip()

    await db.crm_clients.update_one(
        {"id": client_id},
        {
            "$set": update_data,
            "$push": {"historico_movimentacoes": movement}
        }
    )

    updated = await db.crm_clients.find_one({"id": client_id}, {"_id": 0})

    # ERP v3.0: trigger workflow tasks for the new stage
    new_tasks = await trigger_tasks_for_transition(
        entity_type="client",
        entity_id=client_id,
        tenant_id=user["tenant_id"],
        old_stage=old_stage,
        new_stage=new_stage,
        user=user,
    )

    # ERP v3.0: immutable audit log of stage change
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="client_moved",
        entity_type="client",
        entity_id=client_id,
        before={"stage": old_stage},
        after={"stage": new_stage, "motivo_perda": update_data.get("motivo_perda")},
        metadata={"tasks_generated": [t["id"] for t in new_tasks]},
    )

    # Determine if batch project creation is triggered
    trigger_batch_projects = (new_stage == "projeto_em_discussao")

    return {
        "client": updated,
        "trigger_batch_projects": trigger_batch_projects,
        "from_stage": STAGE_LABELS.get(old_stage, old_stage),
        "to_stage": STAGE_LABELS.get(new_stage, new_stage),
        "tasks_generated": new_tasks,
    }


@crm_router.get("/clients/{client_id}/full")
async def get_client_full(client_id: str, request: Request):
    user = await _get_current_user(request)
    client = await db.crm_clients.find_one(
        {"id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    projects = await db.crm_projects.find(
        {"cliente_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    samples = await db.crm_samples.find(
        {"cliente_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    skus = await db.skus.find(
        {"cliente_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    alerts = await db.crm_alerts.find(
        {"tenant_id": user["tenant_id"], "entidade_ref": client_id, "status": {"$ne": "resolvido"}},
        {"_id": 0}
    ).to_list(100)

    # Enrich with orders history
    orders = await db.orders.find(
        {"client_card_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)

    # Computed summary fields
    projetos_ativos = [p for p in projects if p.get("stage") not in ("projeto_arquivado",)]
    ultimo_projeto = projects[0] if projects else None
    ultimo_pedido = orders[0] if orders else None

    # Item mais pedido across all orders
    item_counter: dict = {}
    for order in orders:
        for item in order.get("items", []):
            name = item.get("item") or item.get("codigo_kuryos") or ""
            if name:
                item_counter[name] = item_counter.get(name, 0) + 1
    item_mais_pedido = max(item_counter, key=item_counter.get) if item_counter else None

    return {
        "client": client,
        "projects": projects,
        "samples": samples,
        "skus": skus,
        "alerts": alerts,
        "orders": orders,
        "summary": {
            "projetos_ativos": len(projetos_ativos),
            "total_projetos": len(projects),
            "total_amostras": len(samples),
            "total_pedidos": len(orders),
            "ultimo_projeto": {
                "id": ultimo_projeto["id"],
                "nome": ultimo_projeto.get("nome_projeto", ""),
                "stage": ultimo_projeto.get("stage", ""),
                "created_at": ultimo_projeto.get("created_at", ""),
            } if ultimo_projeto else None,
            "ultimo_pedido": {
                "id": ultimo_pedido["id"],
                "numero": ultimo_pedido.get("numero_pedido", ""),
                "status": ultimo_pedido.get("status", ""),
                "total": ultimo_pedido.get("total_pedido", 0),
                "created_at": ultimo_pedido.get("created_at", ""),
            } if ultimo_pedido else None,
            "item_mais_pedido": item_mais_pedido,
        },
    }


# ======================================================================
#  CRM 2 — PROJECTS (Pipeline de Projetos)
# ======================================================================

@crm_router.post("/projects/batch")
async def batch_create_projects(data: ProjectBatchCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL)

    # ERP v3.0: hierarchy lock — child cannot exist without parent
    client = await assert_client_exists(user["tenant_id"], data.cliente_id)

    if client.get("stage") == "cliente_perdido":
        raise HTTPException(status_code=409, detail="Não é possível criar projeto para cliente perdido")
    if client.get("stage") in {"prospeccao", "qualificado"}:
        _validate_project_gate_requirements(client)
    if client.get("stage") == "prospeccao":
        _validate_client_transition_requirements(client, "qualificado")
        await assert_no_blocking_tasks(
            tenant_id=user["tenant_id"],
            entity_type="client",
            entity_id=data.cliente_id,
            target_stage="qualificado",
        )

    if not data.projects:
        raise HTTPException(status_code=400, detail="Nenhum projeto fornecido")

    now = _now_iso()
    created = []
    created_project_ids: List[str] = []
    created_task_ids: List[str] = []
    created_audit_ids: List[str] = []

    try:
        for item in data.projects:
            project_id = _new_id()
            project = {
                "id": project_id,
                "tenant_id": user["tenant_id"],
                "cliente_id": data.cliente_id,
                "cliente_nome": client["nome_empresa"],
                "stage": "projeto_em_discussao",
                "nome_projeto": item.nome_projeto,
                "categoria": item.categoria,
                "briefing_tecnico": item.briefing_resumido,
                "responsavel_comercial": item.responsavel_comercial or client.get("responsavel_comercial", ""),
                "ideia_conceito": item.ideia_conceito,
                "referencia_mercado": item.referencia_mercado,
                "publico_alvo": item.publico_alvo,
                "posicionamento": item.posicionamento,
                "faixa_preco_venda": item.faixa_preco_venda,
                "volume_estimado_pedido": item.volume_estimado_pedido,
                "tipo_servico": item.tipo_servico,
                "sensorial_desejado": item.sensorial_desejado,
                "restricoes_tecnicas": item.restricoes_tecnicas,
                "claims_desejados": item.claims_desejados,
                "prazo_desejado_amostra": item.prazo_desejado_amostra,
                "observacoes_livres": item.observacoes_livres,
                "responsavel_interno": "",
                "data_inicio_desenvolvimento": None,
                "prazo_prometido_cliente": item.prazo_desejado_amostra or None,
                "data_ultima_amostra_enviada": None,
                "numero_amostras_solicitadas": 0,
                "motivo_arquivamento": "",
                "historico_movimentacoes": [],
                "created_by": user["id"],
                "created_by_name": user["name"],
                "created_at": now,
                "updated_at": now,
            }
            inherit(project, client, INHERITED_FROM_CLIENT)

            await db.crm_projects.insert_one(project)
            created_project_ids.append(project_id)
            project.pop("_id", None)

            viability_task = await create_workflow_task(
                tenant_id=user["tenant_id"],
                entity_type="project",
                entity_id=project_id,
                title="Validar viabilidade tecnica do pre-briefing",
                description="Tarefa automatica ao criar projeto em discussao.",
                category="pd_dev",
                blocking=False,
                due_in_days=2,
                created_by=user,
            )
            if viability_task and viability_task.get("id"):
                created_task_ids.append(viability_task["id"])

            deadline_task = await _create_project_deadline_alert_task(project, user)
            if deadline_task and deadline_task.get("id"):
                created_task_ids.append(deadline_task["id"])

            audit_entry = await audit_log(
                tenant_id=user["tenant_id"],
                user_id=user["id"],
                user_name=user.get("name", ""),
                action="project_created",
                entity_type="project",
                entity_id=project_id,
                after={
                    "nome_projeto": project["nome_projeto"],
                    "cliente_id": data.cliente_id,
                    "stage": project["stage"],
                },
                metadata={
                    "tasks_generated": [
                        task_id for task_id in [
                            viability_task.get("id") if viability_task else None,
                            deadline_task.get("id") if deadline_task else None,
                        ] if task_id
                    ]
                },
            )
            if audit_entry and audit_entry.get("id"):
                created_audit_ids.append(audit_entry["id"])

            created.append(project)
    except Exception as exc:
        logger.exception("Failed to create project batch; rolling back persisted records")
        await _rollback_batch_created_projects(
            user["tenant_id"],
            project_ids=created_project_ids,
            workflow_task_ids=created_task_ids,
            audit_log_ids=created_audit_ids,
        )
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=500,
            detail="Falha ao criar projetos. Nenhum projeto foi persistido; revise os dados e tente novamente.",
        ) from exc

    logger.info(f"Batch created {len(created)} projects for client {data.cliente_id}")
    return {"created": created, "count": len(created)}


@crm_router.get("/projects")
async def list_projects(
    request: Request,
    cliente_id: Optional[str] = None,
    stage: Optional[str] = None,
    search: Optional[str] = None,
):
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if cliente_id:
        query["cliente_id"] = cliente_id
    if stage:
        query["stage"] = _normalize_project_stage(stage)
    if search:
        query["$or"] = [
            {"nome_projeto": {"$regex": search, "$options": "i"}},
            {"cliente_nome": {"$regex": search, "$options": "i"}},
            {"categoria": {"$regex": search, "$options": "i"}},
            {"briefing_tecnico": {"$regex": search, "$options": "i"}},
            {"ideia_conceito": {"$regex": search, "$options": "i"}},
            {"publico_alvo": {"$regex": search, "$options": "i"}},
            {"claims_desejados": {"$regex": search, "$options": "i"}},
        ]

    projects = await db.crm_projects.find(query, {"_id": 0}).sort("created_at", -1).to_list(5000)
    return projects


@crm_router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    user = await _get_current_user(request)
    project = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project


@crm_router.put("/projects/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL)
    update_fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    update_fields["updated_at"] = _now_iso()

    result = await db.crm_projects.update_one(
        {"id": project_id, "tenant_id": user["tenant_id"]},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    project = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if project and update_fields.get("prazo_desejado_amostra"):
        await _create_project_deadline_alert_task(project, user)
    return project


@crm_router.put("/projects/{project_id}/move")
async def move_project(project_id: str, data: ProjectMove, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL)
    project = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    old_stage = _normalize_project_stage(project["stage"])
    new_stage = _normalize_project_stage(data.stage)

    if new_stage not in PROJECT_STAGES:
        raise HTTPException(status_code=400, detail=f"Estágio inválido: {new_stage}")

    allowed = [_normalize_project_stage(stage) for stage in PROJECT_TRANSITIONS.get(old_stage, [])]
    if new_stage not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Transição não permitida: {STAGE_LABELS.get(old_stage)} → {STAGE_LABELS.get(new_stage)}"
        )
    if new_stage == "pedido_aprovado":
        from kickoff_routes import _resolve_registered_formula_for_project

        await _resolve_registered_formula_for_project(project_id, user["tenant_id"])

    _validate_project_transition_requirements(project, new_stage)
    if new_stage == "projeto_arquivado" and not clean_text(data.motivo_arquivamento or ""):
        raise HTTPException(status_code=400, detail="Motivo do arquivamento é obrigatório")
    await assert_no_blocking_tasks(
        tenant_id=user["tenant_id"],
        entity_type="project",
        entity_id=project_id,
        target_stage=new_stage,
    )

    now = _now_iso()
    movement = {
        "de": old_stage,
        "para": new_stage,
        "data": now,
        "usuario": user["name"],
        "usuario_id": user["id"],
    }

    update_fields = {"stage": new_stage, "updated_at": now}
    if new_stage == "amostra_em_desenvolvimento" and not project.get("data_inicio_desenvolvimento"):
        update_fields["data_inicio_desenvolvimento"] = now
    if new_stage == "amostra_enviada":
        update_fields["data_ultima_amostra_enviada"] = now
    if new_stage == "projeto_arquivado":
        update_fields["motivo_arquivamento"] = clean_text(data.motivo_arquivamento or "")

    await db.crm_projects.update_one(
        {"id": project_id, "tenant_id": user["tenant_id"]},
        {
            "$set": update_fields,
            "$push": {"historico_movimentacoes": movement}
        }
    )

    updated = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if new_stage == "amostra_solicitada":
        await _create_project_deadline_alert_task(updated, user)

    new_tasks = await trigger_tasks_for_transition(
        entity_type="project",
        entity_id=project_id,
        tenant_id=user["tenant_id"],
        old_stage=old_stage,
        new_stage=new_stage,
        user=user,
    )
    kickoff_created = None
    kickoff_tasks = []
    skus_gerados = []
    if new_stage == "pedido_aprovado":
        skus_gerados = await _generate_skus_for_project_approved_variations(project_id, user)

        from kickoff_routes import create_kickoff_for_project

        kickoff = await create_kickoff_for_project(project_id, user)
        kickoff_created = {
            "kickoff_id": kickoff["id"],
            "numero_kickoff": kickoff["numero_kickoff"],
        }
        kickoff_tasks.append({"tipo": "preencher_kickoff_bloco2", "responsavel": "comercial"})

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="project_moved",
        entity_type="project",
        entity_id=project_id,
        before={"stage": old_stage},
        after={"stage": new_stage, "motivo_arquivamento": update_fields.get("motivo_arquivamento")},
        metadata={"tasks_generated": [t["id"] for t in new_tasks]},
    )

    if new_stage == "em_negociacao" and updated:
        await _mirror_client_stage_to_negociacao(updated, user)

    trigger_batch_samples = (new_stage == "amostra_solicitada")

    return {
        "project": updated,
        "trigger_batch_samples": trigger_batch_samples,
        "from_stage": STAGE_LABELS.get(old_stage, old_stage),
        "to_stage": STAGE_LABELS.get(new_stage, new_stage),
        "tasks_generated": new_tasks,
        "kickoff_criado": kickoff_created,
        "tarefas_criadas": kickoff_tasks,
        "skus_gerados": skus_gerados,
    }


@crm_router.get("/projects/{project_id}/full")
async def get_project_full(project_id: str, request: Request):
    user = await _get_current_user(request)
    project = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    client = await db.crm_clients.find_one(
        {"id": project["cliente_id"]}, {"_id": 0}
    )

    samples = await db.crm_samples.find(
        {"projeto_id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    skus = await db.skus.find(
        {"projeto_id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    # Enrich each variation with live P&D status
    all_card_ids = []
    for s in samples:
        for v in s.get("variacoes", []) or []:
            if v.get("pd_card_id"):
                all_card_ids.append(v["pd_card_id"])

    if all_card_ids:
        pd_cards_docs = await db.pd_cards.find(
            {"id": {"$in": all_card_ids}, "tenant_id": user["tenant_id"]},
            {"_id": 0, "id": 1, "pd_request_id": 1, "status_pd": 1}
        ).to_list(1000)
        cards_map = {c["id"]: c for c in pd_cards_docs}

        req_ids = list({c["pd_request_id"] for c in pd_cards_docs if c.get("pd_request_id")})
        reqs_map: Dict[str, Any] = {}
        if req_ids:
            reqs_docs = await db.pd_requests.find(
                {"id": {"$in": req_ids}, "tenant_id": user["tenant_id"]},
                {"_id": 0, "id": 1, "status": 1, "updated_at": 1, "project_name": 1}
            ).to_list(500)
            reqs_map = {r["id"]: r for r in reqs_docs}

        for s in samples:
            for v in s.get("variacoes", []) or []:
                card = cards_map.get(v.get("pd_card_id"))
                if card:
                    req = reqs_map.get(card.get("pd_request_id"), {})
                    v["pd_request_id"] = card.get("pd_request_id")
                    v["pd_status"] = req.get("status")
                    v["pd_status_pd"] = card.get("status_pd")
                    v["pd_updated_at"] = req.get("updated_at")

    return {
        "project": project,
        "client": client,
        "samples": samples,
        "skus": skus,
    }


@crm_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, request: Request):
    """Deleta um projeto em cascata (samples + variações + pd_cards).
    Bloqueia se houver SKU já gerado a partir deste projeto."""
    user = await _get_current_user(request)
    require_roles(user, ADMIN_ONLY | {"sales_ops"})
    project = await db.crm_projects.find_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Bloquear se houver SKU vinculado
    sku_count = await db.skus.count_documents(
        {"projeto_id": project_id, "tenant_id": user["tenant_id"]}
    )
    if sku_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir: existem {sku_count} SKU(s) gerados a partir deste projeto."
        )

    # Coletar samples e pd_cards para deletar
    samples = await db.crm_samples.find(
        {"projeto_id": project_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "id": 1, "variacoes": 1}
    ).to_list(5000)

    sample_ids = [s["id"] for s in samples]
    pd_card_ids = []
    for s in samples:
        for v in s.get("variacoes", []) or []:
            if v.get("pd_card_id"):
                pd_card_ids.append(v["pd_card_id"])

    # Apagar pd_cards vinculados
    if pd_card_ids:
        await db.pd_cards.delete_many(
            {"id": {"$in": pd_card_ids}, "tenant_id": user["tenant_id"]}
        )
    # Apagar samples
    if sample_ids:
        await db.crm_samples.delete_many(
            {"id": {"$in": sample_ids}, "tenant_id": user["tenant_id"]}
        )
    # Apagar projeto
    await db.crm_projects.delete_one(
        {"id": project_id, "tenant_id": user["tenant_id"]}
    )

    logger.info(f"Deleted project {project_id} (samples={len(sample_ids)}, pd_cards={len(pd_card_ids)})")
    return {
        "deleted_project": project_id,
        "deleted_samples": len(sample_ids),
        "deleted_pd_cards": len(pd_card_ids),
    }


# ======================================================================
#  CRM 3 — SAMPLES (Pipeline de Amostras)
# ======================================================================

@crm_router.post("/samples/batch")
async def batch_create_samples(data: SampleBatchCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL | PD_FULL)

    # Verify project exists
    project = await db.crm_projects.find_one(
        {"id": data.projeto_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    if not data.samples:
        raise HTTPException(status_code=400, detail="Nenhuma amostra fornecida")

    now = _now_iso()
    created = []

    for item in data.samples:
        if item.tipo_amostra == "adaptacao_de_formula" and not clean_text(item.referencia_formula):
            raise HTTPException(status_code=400, detail="referencia_formula é obrigatória para adaptação de fórmula")
        sample_id = _new_id()
        item_payload = item.model_dump()
        briefing_record = _build_briefing_record(
            tenant_id=user["tenant_id"],
            project=project,
            sample_id=sample_id,
            sample_payload=item_payload,
            user=user,
            now=now,
            origem="crm_sample_legacy",
        )
        sample = {
            "id": sample_id,
            "tenant_id": user["tenant_id"],
            "projeto_id": data.projeto_id,
            "projeto_nome": project["nome_projeto"],
            "cliente_id": project["cliente_id"],
            "cliente_nome": project.get("cliente_nome", ""),
            "stage": "solicitada",
            "nome_amostra": item.nome_amostra,
            "codigo_referencia": item.codigo_referencia,
            "observacao_tecnica": item.observacao_tecnica,
            "responsavel_pd": "",
            "data_envio": None,
            **_initial_sample_test_state(now),
            "briefing_id": briefing_record["id"],
            "briefing_registro": briefing_record,
            "motivo_retrabalho": "",
            "historico_retrabalhos": [],
            "feedback_cliente": "",
            # Novos campos de briefing
            "produto": item.produto,
            "objetivo_projeto": item.objetivo_projeto,
            "aplicacoes_desenvolver": item.aplicacoes_desenvolver,
            "ativos_claims": item.ativos_claims,
            "referencias": item.referencias,
            "referencias_fotos": item.referencias_fotos,
            "orcamento_projeto": item.orcamento_projeto,
            "textura_esperada": item.textura_esperada,
            "aplicacao": item.aplicacao,
            "sensorial": item.sensorial,
            "ph": item.ph,
            "historico_movimentacoes": [],
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        await db.crm_samples.insert_one(sample)
        await _persist_briefing_record(briefing_record)
        sample.pop("_id", None)
        created.append(sample)

    logger.info(f"Batch created {len(created)} samples for project {data.projeto_id}")
    return {"created": created, "count": len(created)}


@crm_router.post("/samples/upload-image")
async def upload_sample_image(request: Request, file: UploadFile = File(...)):
    """Upload image for sample reference"""
    user = await _get_current_user(request)
    
    # Validate file type
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de arquivo não permitido. Use: JPG, PNG ou WEBP")
    
    # Create upload directory if not exists
    upload_dir = Path("/app/uploads/sample_images")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename
    file_ext = file.filename.split(".")[-1]
    unique_filename = f"{_new_id()}.{file_ext}"
    file_path = upload_dir / unique_filename
    
    # Save file
    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Return URL path
        file_url = f"/uploads/sample_images/{unique_filename}"
        return {"url": file_url, "filename": unique_filename}
    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        raise HTTPException(status_code=500, detail="Erro ao fazer upload da imagem")


@crm_router.post("/samples/batch/v2")
async def batch_create_samples_v2(data: SampleBatchCreateV2, request: Request):
    """Criar amostras em lote com suporte a variações (ERP v3.0: numeração GLOBAL)."""
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL | PD_FULL)

    # ERP v3.0: hierarchy lock
    project = await assert_project_exists(user["tenant_id"], data.projeto_id)

    if not data.samples:
        raise HTTPException(status_code=400, detail="Nenhuma amostra fornecida")

    for item in data.samples:
        if item.tipo_amostra == "adaptacao_de_formula" and not clean_text(item.referencia_formula):
            raise HTTPException(status_code=400, detail=f"referencia_formula é obrigatória para adaptação de fórmula (amostra '{item.nome_produto}')")

    # R02: atualizar campos do card antes de criar amostras (sync CRM→P&D)
    if data.projeto_updates:
        _ALLOWED_PROJETO_FIELDS = {
            "categoria", "responsavel_comercial", "responsavel_interno",
            "ideia_conceito", "referencia_mercado", "publico_alvo", "posicionamento",
            "tipo_servico", "faixa_preco_venda", "volume_estimado_pedido",
            "prazo_desejado_amostra", "sensorial_desejado", "claims_desejados",
            "restricoes_tecnicas", "observacoes_livres",
        }
        patch = {k: v for k, v in data.projeto_updates.items() if k in _ALLOWED_PROJETO_FIELDS}
        if patch:
            patch["updated_at"] = _now_iso()
            await db.crm_projects.update_one(
                {"id": data.projeto_id, "tenant_id": user["tenant_id"]},
                {"$set": patch},
            )
            # Recarregar projeto com campos atualizados
            project = await assert_project_exists(user["tenant_id"], data.projeto_id)

    now = _now_iso()
    created_samples = []

    for item in data.samples:
        # ERP v3.0: numeração GLOBAL sequencial (counter atômico no tenant)
        numero_amostra = await _get_next_sample_code(data.projeto_id, user["tenant_id"])

        # Criar amostra pai
        sample_id = _new_id()
        item_payload = item.model_dump()
        briefing_record = _build_briefing_record(
            tenant_id=user["tenant_id"],
            project=project,
            sample_id=sample_id,
            sample_payload=item_payload,
            user=user,
            now=now,
            origem="crm_sample_v2",
        )

        # Criar variações
        variacoes_data = []
        for idx, var in enumerate(item.variacoes):
            letra = int_to_letters(idx)
            codigo = f"{numero_amostra}-{letra}"
            variacao_id = _new_id()
            
            variacao = {
                "id": variacao_id,
                "codigo": codigo,
                "letra": letra,
                "descricao_aplicacao": var.descricao_aplicacao,
                "percentual_fragrancia": var.percentual_fragrancia,
                "referencia_fragrancia": var.referencia_fragrancia,
                "fr_codigo": var.fr_codigo or "",
                "custo_fragrancia": var.custo_fragrancia,
                "custo_fragrancia_currency": _normalize_currency_code(var.custo_fragrancia_currency),
                "observacoes_especificas": var.observacoes_especificas,
                "status": "solicitada",
                **_initial_sample_test_state(now),
                "aprovacao_interna": False,
                "aprovacao_externa": False,
                "historico_status": [{
                    "de": "",
                    "para": "solicitada",
                    "data": now,
                    "usuario": user["name"],
                    "usuario_id": user["id"]
                }],
                "motivo_retrabalho": "",
                "historico_retrabalhos": [],
                "feedback_cliente": "",
                "direcoes_retrabalho": "",
                "resultado": "",
                "enviado_comercial_em": None,
                "aprovado_cliente_em": None,
                "reprovacao_motivo": "",
                "gera_sku": False,
                "sku_id": None,
                "pd_card_id": None  # Será preenchido quando criar o card no P&D
            }
            variacoes_data.append(variacao)
        
        # Se não houver variações, criar uma padrão
        if not variacoes_data:
            letra = "a"
            codigo = f"{numero_amostra}-{letra}"
            variacao_id = _new_id()
            variacao = {
                "id": variacao_id,
                "codigo": codigo,
                "letra": letra,
                "descricao_aplicacao": "",
                "percentual_fragrancia": None,
                "referencia_fragrancia": "",
                "fr_codigo": "",
                "custo_fragrancia": None,
                "custo_fragrancia_currency": "USD",
                "observacoes_especificas": "",
                "status": "solicitada",
                "aprovacao_interna": False,
                "aprovacao_externa": False,
                "historico_status": [{
                    "de": "",
                    "para": "solicitada",
                    "data": now,
                    "usuario": user["name"],
                    "usuario_id": user["id"]
                }],
                "motivo_retrabalho": "",
                "historico_retrabalhos": [],
                "feedback_cliente": "",
                "direcoes_retrabalho": "",
                "resultado": "",
                "enviado_comercial_em": None,
                "aprovado_cliente_em": None,
                "reprovacao_motivo": "",
                "gera_sku": False,
                "sku_id": None,
                "pd_card_id": None
            }
            variacoes_data.append(variacao)
        
        sample = {
            "id": sample_id,
            "tenant_id": user["tenant_id"],
            "projeto_id": data.projeto_id,
            "projeto_nome": project["nome_projeto"],
            "cliente_id": project["cliente_id"],
            "cliente_nome": project.get("cliente_nome", ""),
            "numero_amostra": str(numero_amostra),
            "nome_produto": item.nome_produto,
            "categoria": item.categoria,
            "briefing_base": item.briefing_base,
            "responsavel_pd": item.responsavel_pd,
            "parametro_variacao": item.parametro_variacao,
            "tipo_amostra": item.tipo_amostra,
            "referencia_formula": item.referencia_formula,
            "quantidade_por_variacao": item.quantidade_por_variacao,
            "unidade_quantidade": item.unidade_quantidade,
            "prazo_entrega_cliente": item.prazo_entrega_cliente,
            "briefing_especifico": item.briefing_especifico,
            "feedback_cliente": item.feedback_cliente,
            "direcoes_retrabalho": item.direcoes_retrabalho,
            "resultado": item.resultado,
            "aprovacao_interna": False,
            "aprovacao_externa": False,
            **_initial_sample_test_state(now),
            "briefing_id": briefing_record["id"],
            "briefing_registro": briefing_record,
            "data_envio": None,
            "enviado_comercial_em": None,
            "aprovado_cliente_em": None,
            "reprovacao_motivo": "",
            "tem_variacoes": len(variacoes_data) > 1,
            "variacoes": variacoes_data,
            # Campos de briefing (herdados pelas variações)
            "produto": item.produto,
            "objetivo_projeto": item.objetivo_projeto,
            "aplicacoes_desenvolver": item.aplicacoes_desenvolver,
            "ativos_claims": item.ativos_claims,
            "referencias": item.referencias,
            "referencias_fotos": item.referencias_fotos,
            "orcamento_projeto": item.orcamento_projeto,
            "textura_esperada": item.textura_esperada,
            "aplicacao": item.aplicacao,
            "sensorial": item.sensorial,
            "ph": item.ph,
            "observacao_tecnica": item.observacao_tecnica,
            "stage": "solicitada",
            "rework_de_amostra_id": None,
            "rework_motivo": "",
            # R02: snapshot dos campos ricos do projeto no momento da criação
            "projeto_briefing": {
                "publico_alvo": project.get("publico_alvo", ""),
                "posicionamento": project.get("posicionamento", ""),
                "tipo_servico": project.get("tipo_servico", ""),
                "faixa_preco_venda": project.get("faixa_preco_venda"),
                "volume_estimado_pedido": project.get("volume_estimado_pedido"),
                "restricoes_tecnicas": project.get("restricoes_tecnicas", []),
                "observacoes_livres": project.get("observacoes_livres", ""),
                "responsavel_comercial": project.get("responsavel_comercial", ""),
            },
            "created_by": user["id"],
            "created_by_name": user["name"],
            "created_at": now,
            "updated_at": now,
        }
        # R02: inheritance do projeto → amostra (preenche campos vazios)
        inherit(sample, project, INHERITED_FROM_PROJECT)

        await db.crm_samples.insert_one(sample)
        await _persist_briefing_record(briefing_record)
        sample.pop("_id", None)

        await audit_log(
            tenant_id=user["tenant_id"],
            user_id=user["id"],
            user_name=user.get("name", ""),
            action="sample_created",
            entity_type="sample",
            entity_id=sample_id,
            after={
                "numero_amostra": sample["numero_amostra"],
                "projeto_id": data.projeto_id,
                "cliente_id": project["cliente_id"],
                "nome_produto": sample["nome_produto"],
                "variacoes": [v["codigo"] for v in variacoes_data],
            },
        )

        created_samples.append(sample)

        # Criar cards no P&D para cada variação
        for variacao in variacoes_data:
            await _create_pd_card_for_variacao(sample, variacao, user)

    if _project_stage_rank(project.get("stage")) < _project_stage_rank("amostra_solicitada"):
        await _advance_project_stage_if_needed(
            data.projeto_id,
            "amostra_solicitada",
            user,
            movement_source="sample_batch_created",
        )

    logger.info(f"Batch created {len(created_samples)} samples (v2) with variations for project {data.projeto_id}")
    return {"created": created_samples, "count": len(created_samples)}


async def _ensure_pd_request_for_card(card: dict, user: dict) -> str:
    """Garante que existe um pd_request linkado ao pd_card. Retorna o pd_request_id.
    Cria sob demanda quando o card é proveniente de variação CRM (sem pd_request prévio).
    Permite que o clique no card P&D abra a tela completa de PDDetail (/pd/{id}).
    """
    existing_id = card.get("pd_request_id")
    if existing_id:
        # Backfill: garantir que development + fórmula inicial existem
        # (cards criados antes do bootstrap automático ainda podem estar sem dev)
        try:
            existing_dev = await db.pd_developments.find_one(
                {"pd_request_id": existing_id, "tenant_id": user["tenant_id"]}
            )
            if not existing_dev and card.get("amostra_id") and card.get("amostra_variacao_id"):
                await _bootstrap_pd_development_for_variacao(
                    pd_request_id=existing_id, card=card, user=user
                )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Backfill bootstrap failed for pd_request {existing_id}: {exc}")
        return existing_id

    now = _now_iso()
    req_id = _new_id()

    sample_id = card.get("amostra_id")
    variacao_id = card.get("amostra_variacao_id")
    cliente_id = card.get("cliente_id")

    # Build a description from briefing data so the operator sees everything
    desc_parts = []
    if card.get("objetivo_projeto"):
        desc_parts.append(f"Objetivo: {card['objetivo_projeto']}")
    if card.get("textura_esperada"):
        desc_parts.append(f"Textura: {card['textura_esperada']}")
    if card.get("aplicacao"):
        desc_parts.append(f"Aplicação: {card['aplicacao']}")
    if card.get("sensorial"):
        desc_parts.append(f"Sensorial: {card['sensorial']}")
    if card.get("ph"):
        desc_parts.append(f"pH: {card['ph']}")
    if card.get("ativos_claims"):
        desc_parts.append(f"Ativos/Claims: {card['ativos_claims']}")
    if card.get("aplicacoes_desenvolver"):
        desc_parts.append(f"Aplicações a desenvolver: {card['aplicacoes_desenvolver']}")
    if card.get("briefing_base"):
        desc_parts.append(f"\nBriefing base:\n{card['briefing_base']}")
    if card.get("briefing_especifico"):
        desc_parts.append(f"\nBriefing específico:\n{card['briefing_especifico']}")
    if card.get("descricao_aplicacao"):
        desc_parts.append(f"\nDescrição da aplicação (variação): {card['descricao_aplicacao']}")
    if card.get("observacoes_especificas"):
        desc_parts.append(f"Observações específicas: {card['observacoes_especificas']}")

    description = "\n".join(desc_parts).strip()

    # Volume from sample — quantidade_por_variacao foi removido da criação de amostras (A9),
    # mas documentos legados ainda podem trazê-lo. Sem ele, cai num placeholder explícito em
    # vez de deixar o card do P&D com o campo de volume vazio.
    volume_str = "A definir"
    if card.get("quantidade_por_variacao"):
        volume_str = f"{card['quantidade_por_variacao']}{card.get('unidade_quantidade', 'g')}"

    pd_request = {
        "id": req_id,
        "tenant_id": user["tenant_id"],
        "client_card_id": None,  # CRM v3 uses crm_clients (not cards). Set null.
        "client_name": card.get("cliente", ""),
        "project_name": card.get("projeto_nome") or card.get("produto") or variacao_id or req_id,
        "technical_name": f"{card.get('produto', '')} - {card.get('numero_completo', '')}".strip(" -"),
        "commercial_name": card.get("produto", ""),
        "internal_code": card.get("numero_completo", ""),
        "request_type": "Amostra",
        "category": card.get("tipo_amostra", ""),
        "description": description,
        "references": card.get("referencias", ""),
        "restrictions": "",
        "volume": volume_str,
        "packaging": "",
        "priority": "Normal",
        "deadline": card.get("prazo_entrega_cliente") or None,
        "status": "OPEN",
        "is_internal_research": False,
        "kickoff_completed": False,
        # Link back to CRM source
        "linked_amostra_id": sample_id,
        "linked_variacao_id": variacao_id,
        "linked_cliente_id": cliente_id,
        "linked_projeto_id": card.get("projeto_id"),
        "linked_pd_card_id": card.get("id"),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
        "updated_at": now,
    }

    await db.pd_requests.insert_one(pd_request)
    await db.pd_request_status_history.insert_one({
        "id": _new_id(),
        "pd_request_id": req_id,
        "from_status": None,
        "to_status": "OPEN",
        "changed_by": user["id"],
        "changed_by_name": user.get("name", ""),
        "comment": "Criado automaticamente a partir de variação CRM",
        "created_at": now,
    })

    # Link card -> pd_request
    await db.pd_cards.update_one(
        {"id": card["id"], "tenant_id": user["tenant_id"]},
        {"$set": {"pd_request_id": req_id, "updated_at": now}},
    )
    card["pd_request_id"] = req_id

    # Auto-create development + initial formula pre-filled with briefing data
    # so the operator only needs to add raw materials/ingredients
    try:
        await _bootstrap_pd_development_for_variacao(
            pd_request_id=req_id, card=card, user=user
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Failed to bootstrap dev/formula for pd_request {req_id}: {exc}")

    logger.info(f"Auto-created pd_request {req_id} for pd_card {card.get('id')} (variação {card.get('numero_completo')})")
    return req_id


_PD_REQUEST_STATUS_TO_CARD_STATUS = {
    "OPEN": "solicitado",
    "IN_PROGRESS": "em_desenvolvimento",
    "IN_TESTS": "em_testes",
    "WAITING_APPROVAL": "aguardando_aprovacao",
    "REJECTED": "retrabalho_interno",
    "APPROVED": "aprovado",
    "COMPLETED": "concluido",
}


async def _sync_pd_request_pipeline_refs(
    *,
    pd_request_id: str,
    card: dict,
    user: dict,
    request_status: str,
    now: Optional[str] = None,
    observacao: str = "",
):
    """Mantém card do pipeline e variação CRM coerentes com o status real da requisição P&D."""
    kanban_status = _PD_REQUEST_STATUS_TO_CARD_STATUS.get(request_status)
    if not kanban_status:
        return

    now = now or _now_iso()
    old_status = card.get("status_pd", "")
    movement_entry = {
        "de": old_status,
        "para": kanban_status,
        "data": now,
        "usuario": user.get("name", ""),
        "usuario_id": user["id"],
        "observacao": observacao or f"Sincronizado automaticamente pela requisição P&D: {request_status}",
        "sincronizado_pd_request": True,
    }

    update_doc: Dict[str, Any] = {
        "$set": {
            "status_pd": kanban_status,
            "pd_request_id": pd_request_id,
            "updated_at": now,
        }
    }
    if old_status != kanban_status:
        update_doc["$push"] = {"historico_movimentacoes": movement_entry}

    await db.pd_cards.update_one(
        {"id": card["id"], "tenant_id": user["tenant_id"]},
        update_doc,
    )

    card["status_pd"] = kanban_status
    card["pd_request_id"] = pd_request_id
    card["updated_at"] = now
    if old_status != kanban_status:
        historico = list(card.get("historico_movimentacoes") or [])
        historico.append(movement_entry)
        card["historico_movimentacoes"] = historico

    crm_status, crm_label = PD_CARD_STATUS_TO_CRM_DISPLAY.get(
        kanban_status,
        (PD_TO_CRM_STATUS_MAP.get(kanban_status), PD_STATUS_LABELS.get(kanban_status, kanban_status)),
    )
    if card.get("amostra_id") and card.get("amostra_variacao_id"):
        set_ops = {
            "variacoes.$.status_pd_raw": kanban_status,
            "variacoes.$.status_pd_label": crm_label,
            "variacoes.$.ultima_atualizacao_pd": now,
            "variacoes.$.updated_at": now,
        }
        if crm_status:
            set_ops["variacoes.$.status"] = crm_status

        await db.crm_samples.update_one(
            {
                "id": card["amostra_id"],
                "tenant_id": user["tenant_id"],
                "variacoes.id": card["amostra_variacao_id"],
            },
            {
                "$set": set_ops,
                "$push": {
                    "variacoes.$.historico_status": {
                        "de": "",
                        "para": crm_status or "",
                        "data": now,
                        "usuario": user.get("name", ""),
                        "usuario_id": user["id"],
                        "sincronizado_pd": True,
                        "status_pd": kanban_status,
                        "label_pd": crm_label,
                        "observacao": observacao or f"P&D movido automaticamente para {crm_label}",
                    }
                },
            },
        )

    if _broadcast_event and old_status != kanban_status:
        await _broadcast_event(
            user["tenant_id"],
            "pd_card_moved",
            {
                "card": card,
                "from_status": old_status,
                "to_status": kanban_status,
            },
        )


async def _bootstrap_pd_development_for_variacao(pd_request_id: str, card: dict, user: dict):
    """Cria development + fórmula v1 pré-preenchida a partir da variação CRM.
    Inclui a fragrância da variação como primeiro item (P&D só adiciona MPs/insumos).
    """
    sample_id = card.get("amostra_id")
    variacao_id = card.get("amostra_variacao_id")
    if not sample_id or not variacao_id:
        return

    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        return
    variacao = next(
        (v for v in sample.get("variacoes", []) if v.get("id") == variacao_id), None
    )
    if not variacao:
        return

    now = _now_iso()

    # Move pd_request to IN_PROGRESS so the dev/formula appear active
    await db.pd_requests.update_one(
        {"id": pd_request_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "IN_PROGRESS", "updated_at": now}},
    )
    await db.pd_request_status_history.insert_one({
        "id": _new_id(),
        "pd_request_id": pd_request_id,
        "from_status": "OPEN",
        "to_status": "IN_PROGRESS",
        "changed_by": user["id"],
        "changed_by_name": user.get("name", ""),
        "comment": "Bootstrap automático: desenvolvimento + fórmula inicial criados a partir do briefing CRM",
        "created_at": now,
    })
    await _sync_pd_request_pipeline_refs(
        pd_request_id=pd_request_id,
        card=card,
        user=user,
        request_status="IN_PROGRESS",
        now=now,
        observacao="Movido automaticamente para desenvolvimento ao gerar o bootstrap do P&D",
    )

    # 1) Development
    dev_id = _new_id()
    await db.pd_developments.insert_one({
        "id": dev_id,
        "pd_request_id": pd_request_id,
        "tenant_id": user["tenant_id"],
        "assigned_to": user["id"],
        "assigned_to_name": user.get("name", ""),
        "lab_responsible": None,
        "current_version": 1,
        "status": "active",
        "started_at": now,
        "completed_at": None,
    })

    # 2) Initial formula pre-filled
    quantidade = sample.get("quantidade_por_variacao") or 0.0
    unidade = (sample.get("unidade_quantidade") or "g").lower()
    if unidade in ("ml", "l"):
        volume_unit = "mL" if unidade == "ml" else "L"
    elif unidade in ("g", "kg"):
        volume_unit = unidade
    else:
        volume_unit = "g"

    notes_lines = [
        "Pré-preenchido automaticamente a partir do briefing CRM.",
        "→ P&D: adicionar MPs/insumos/ingredientes. Fragrância já está como item nº 1.",
        "",
    ]
    if sample.get("ph"):
        notes_lines.append(f"pH alvo: {sample['ph']}")
    if sample.get("textura_esperada"):
        notes_lines.append(f"Textura esperada: {sample['textura_esperada']}")
    if sample.get("sensorial"):
        notes_lines.append(f"Sensorial: {sample['sensorial']}")
    if sample.get("aplicacao"):
        notes_lines.append(f"Aplicação: {sample['aplicacao']}")
    if sample.get("ativos_claims"):
        notes_lines.append(f"Ativos/Claims obrigatórios: {sample['ativos_claims']}")
    if sample.get("orcamento_projeto"):
        notes_lines.append(f"Orçamento alvo: {sample['orcamento_projeto']}")
    if variacao.get("descricao_aplicacao"):
        notes_lines.append("")
        notes_lines.append(f"Variação {variacao.get('codigo', '')}: {variacao['descricao_aplicacao']}")
    if variacao.get("observacoes_especificas"):
        notes_lines.append(f"Observações específicas: {variacao['observacoes_especificas']}")

    formula_id = _new_id()
    formula_name = f"Manipulação {variacao.get('codigo', '')} — {sample.get('nome_produto', '')} v1".strip()
    await db.pd_formulas.insert_one({
        "id": formula_id,
        "tenant_id": user["tenant_id"],
        "development_id": dev_id,
        "version": 1,
        "name": formula_name,
        "notes": "\n".join(notes_lines).strip(),
        "volume": float(quantidade or 0.0),
        "volume_unit": volume_unit,
        "indice_perdas": 0.0,
        "cotacao_usd": 6.00,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": now,
    })

    # 3) Fragrance pre-filled as first item (if available)
    if variacao.get("percentual_fragrancia") is not None and float(variacao.get("percentual_fragrancia") or 0) > 0:
        ref_frag = variacao.get("referencia_fragrancia") or "Fragrância da variação"
        pct = float(variacao.get("percentual_fragrancia") or 0)
        custo_kg = float(variacao.get("custo_fragrancia") or 0)
        custo_currency = _normalize_currency_code(variacao.get("custo_fragrancia_currency"), "USD")
        cotacao = 6.00
        price_usd = custo_kg if custo_currency == "USD" else None
        price_per_kg = round(custo_kg * cotacao, 4) if price_usd is not None else custo_kg
        cost_brl = round((pct / 100.0) * price_per_kg, 4)
        cost_kg_usd = round(price_usd if price_usd is not None else ((price_per_kg / cotacao) if cotacao else 0.0), 4)
        item_id = _new_id()
        await db.pd_formula_items.insert_one({
            "id": item_id,
            "formula_id": formula_id,
            "ingredient_name": ref_frag,
            "percentage": pct,
            "price_per_kg": price_per_kg,
            "price_usd": price_usd,
            "cost_brl": cost_brl,
            "cost_kg_usd": cost_kg_usd,
            "cost_brl_via_cambio": cost_brl if price_usd is not None else None,
            "fornecedor": "",
            "phase": "Fragrância",
            "function": "Fragrância",
            "catalog_id": None,
        })

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="pd_dev_bootstrap_from_variacao",
        entity_type="pd_request",
        entity_id=pd_request_id,
        after={
            "development_id": dev_id,
            "formula_id": formula_id,
            "variacao_codigo": variacao.get("codigo"),
            "amostra_id": sample_id,
        },
    )


async def _create_pd_card_for_variacao(sample: dict, variacao: dict, user: dict):
    """Cria um card no Pipeline P&D para uma variação de amostra (ERP v3.0)."""
    now = _now_iso()
    card_id = _new_id()
    
    card = {
        "id": card_id,
        "tenant_id": user["tenant_id"],
        "tipo": "amostra",
        "numero_completo": variacao["codigo"],
        "produto": sample.get("nome_produto", sample.get("produto", "")),
        "cliente": sample.get("cliente_nome", ""),
        "cliente_id": sample.get("cliente_id"),
        "projeto_id": sample.get("projeto_id"),
        "projeto_nome": sample.get("projeto_nome", ""),
        "amostra_id": sample["id"],
        "amostra_numero": sample.get("numero_amostra", ""),
        "amostra_variacao_id": variacao["id"],
        "descricao_aplicacao": variacao.get("descricao_aplicacao", ""),
        "briefing_base": sample.get("briefing_base", ""),
        "parametro_variacao": sample.get("parametro_variacao", ""),
        "tipo_amostra": sample.get("tipo_amostra", ""),
        "referencia_formula": sample.get("referencia_formula", ""),
        "quantidade_por_variacao": sample.get("quantidade_por_variacao"),
        "unidade_quantidade": sample.get("unidade_quantidade", ""),
        "prazo_entrega_cliente": sample.get("prazo_entrega_cliente", ""),
        "briefing_especifico": sample.get("briefing_especifico", ""),
        "feedback_cliente": variacao.get("feedback_cliente") or sample.get("feedback_cliente", ""),
        "direcoes_retrabalho": variacao.get("direcoes_retrabalho") or sample.get("direcoes_retrabalho", ""),
        # ERP v3.0: inheritance from sample (briefing técnico, ph, sensorial, etc.)
        "objetivo_projeto": sample.get("objetivo_projeto", ""),
        "aplicacoes_desenvolver": sample.get("aplicacoes_desenvolver", ""),
        "ativos_claims": sample.get("ativos_claims", ""),
        "referencias": sample.get("referencias", ""),
        "textura_esperada": sample.get("textura_esperada", ""),
        "aplicacao": sample.get("aplicacao", ""),
        "sensorial": sample.get("sensorial", ""),
        "ph": sample.get("ph", ""),
        "observacoes_especificas": variacao.get("observacoes_especificas", ""),
        "responsavel_pd": sample.get("responsavel_pd", ""),
        # R02: campos contextuais do projeto (para Detalhes da Solicitação no P&D)
        "publico_alvo": sample.get("projeto_briefing", {}).get("publico_alvo", ""),
        "posicionamento": sample.get("projeto_briefing", {}).get("posicionamento", ""),
        "tipo_servico": sample.get("projeto_briefing", {}).get("tipo_servico", ""),
        "faixa_preco_venda": sample.get("projeto_briefing", {}).get("faixa_preco_venda"),
        "volume_estimado_pedido": sample.get("projeto_briefing", {}).get("volume_estimado_pedido"),
        "restricoes_tecnicas": sample.get("projeto_briefing", {}).get("restricoes_tecnicas", []),
        "observacoes_livres": sample.get("projeto_briefing", {}).get("observacoes_livres", ""),
        "data_solicitacao": now,
        "prazo_prometido": None,
        "status_pd": "solicitado",
        "historico_movimentacoes": [{
            "de": "",
            "para": "solicitado",
            "data": now,
            "usuario": user["name"],
            "usuario_id": user["id"]
        }],
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    
    await db.pd_cards.insert_one(card)
    
    # Atualizar variação com o card_id e status inicial
    await db.crm_samples.update_one(
        {"id": sample["id"], "tenant_id": tenant_id, "variacoes.id": variacao["id"]},
        {"$set": {
            "variacoes.$.pd_card_id": card_id,
            "variacoes.$.status_pd_raw": "solicitado",
            "variacoes.$.status_pd_label": "Solicitado",
        }}
    )

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="pd_card_auto_created",
        entity_type="pd_card",
        entity_id=card_id,
        after={
            "numero_completo": variacao["codigo"],
            "amostra_id": sample["id"],
            "variacao_id": variacao["id"],
            "trigger": "sample_creation",
        },
    )

    logger.info(f"Created P&D card {card_id} for variação {variacao['codigo']}")
    # pd_request é criado sob demanda quando o formulador abre o card (GET /pd/cards/{id}).
    # Não criamos aqui para evitar o log "Auto-created pd_request" em toda variação CRM.


@crm_router.get("/samples")
async def list_samples(
    request: Request,
    projeto_id: Optional[str] = None,
    cliente_id: Optional[str] = None,
    stage: Optional[str] = None,
    search: Optional[str] = None,
):
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if projeto_id:
        query["projeto_id"] = projeto_id
    if cliente_id:
        query["cliente_id"] = cliente_id
    if stage:
        query["stage"] = stage
    if search:
        query["$or"] = [
            {"nome_amostra": {"$regex": search, "$options": "i"}},
            {"nome_produto": {"$regex": search, "$options": "i"}},
            {"numero_amostra": {"$regex": search, "$options": "i"}},
            {"projeto_nome": {"$regex": search, "$options": "i"}},
            {"cliente_nome": {"$regex": search, "$options": "i"}},
            {"variacoes.codigo": {"$regex": search, "$options": "i"}},
            {"variacoes.descricao_aplicacao": {"$regex": search, "$options": "i"}},
        ]

    samples = await db.crm_samples.find(query, {"_id": 0}).sort("created_at", -1).to_list(5000)
    return samples


@crm_router.get("/samples/{sample_id}")
async def get_sample(sample_id: str, request: Request):
    user = await _get_current_user(request)
    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")
    return sample


@crm_router.put("/samples/{sample_id}")
async def update_sample(sample_id: str, data: SampleUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL | PD_FULL)
    update_fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    update_fields["updated_at"] = _now_iso()

    result = await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")

    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    return sample


@crm_router.put("/samples/{sample_id}/move")
async def move_sample(sample_id: str, data: SampleMove, request: Request):
    user = await _get_current_user(request)
    require_roles(user, COMERCIAL_FULL | PD_FULL)
    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")

    old_stage = sample.get("stage", "solicitada")
    new_stage = data.stage

    if new_stage not in SAMPLE_STAGES:
        raise HTTPException(status_code=400, detail=f"Estágio inválido: {new_stage}")

    # ERP v3.0: Retrabalho NÃO é uma transição de estágio simples — exige criar NOVA amostra.
    if new_stage == "retrabalho":
        raise HTTPException(
            status_code=400,
            detail="Retrabalho deve gerar nova amostra (use POST /samples/{id}/rework). "
                   "Variações usam #N/letra; retrabalho gera novo número global."
        )

    allowed = SAMPLE_TRANSITIONS.get(old_stage, [])
    if new_stage not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Transição não permitida: {STAGE_LABELS.get(old_stage)} → {STAGE_LABELS.get(new_stage)}"
        )

    # Blocking tasks
    await assert_no_blocking_tasks(
        tenant_id=user["tenant_id"],
        entity_type="sample",
        entity_id=sample_id,
        target_stage=new_stage,
    )

    # Validate motivo for reprovada
    if new_stage == "reprovada" and not data.motivo_retrabalho:
        raise HTTPException(status_code=400, detail="Motivo da reprovação é obrigatório")
    if new_stage == "aprovada":
        raise HTTPException(
            status_code=422,
            detail="Aprovação direta não é permitida. Registre o envio e depois o resultado do cliente.",
        )

    now = _now_iso()
    update_data = {
        "stage": new_stage,
        "updated_at": now,
        "aprovacao_interna": sample.get("aprovacao_interna", False),
        "aprovacao_externa": sample.get("aprovacao_externa", False),
    }
    if new_stage == "enviada":
        update_data["data_envio"] = now
        update_data["enviado_comercial_em"] = now
        update_data["aprovacao_interna"] = True
    if new_stage == "reprovada":
        update_data["resultado"] = "reprovada"
        update_data["aprovacao_externa"] = False
        update_data["reprovacao_motivo"] = data.motivo_retrabalho or data.feedback_cliente or ""
        if data.feedback_cliente:
            update_data["feedback_cliente"] = data.feedback_cliente
    if data.direcoes_retrabalho:
        update_data["direcoes_retrabalho"] = data.direcoes_retrabalho

    push_ops = {
        "historico_movimentacoes": {
            "de": old_stage,
            "para": new_stage,
            "data": now,
            "usuario": user["name"],
            "usuario_id": user["id"],
        }
    }

    if new_stage == "reprovada" and data.motivo_retrabalho:
        update_data["motivo_retrabalho"] = data.motivo_retrabalho

    await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]},
        {
            "$set": update_data,
            "$push": push_ops,
        }
    )

    updated = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )

    new_tasks = await trigger_tasks_for_transition(
        entity_type="sample",
        entity_id=sample_id,
        tenant_id=user["tenant_id"],
        old_stage=old_stage,
        new_stage=new_stage,
        user=user,
    )

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="sample_moved",
        entity_type="sample",
        entity_id=sample_id,
        before={"stage": old_stage},
        after={"stage": new_stage, "motivo": update_data.get("motivo_retrabalho")},
        metadata={"tasks_generated": [t["id"] for t in new_tasks]},
    )

    # TRIGGER: Auto-create SKU when sample is approved
    sku_created = None
    if new_stage == "aprovada":
        sku_created = await _create_sku_from_sample(updated, user)
        await _advance_project_stage_if_needed(
            updated["projeto_id"],
            "em_negociacao",
            user,
            movement_source="sample_approved",
        )
    elif new_stage == "em_elaboracao":
        await _advance_project_stage_if_needed(
            updated["projeto_id"],
            "amostra_em_desenvolvimento",
            user,
            movement_source="sample_in_development",
            extra_set={"data_inicio_desenvolvimento": now},
        )
    elif new_stage == "enviada":
        await _advance_project_stage_if_needed(
            updated["projeto_id"],
            "amostra_enviada",
            user,
            movement_source="sample_sent",
            extra_set={"data_ultima_amostra_enviada": now},
        )

    await _sync_pd_cards_from_crm_stage(
        tenant_id=user["tenant_id"],
        sample_id=sample_id,
        user=user,
        now=now,
        crm_stage=new_stage,
        feedback_cliente=update_data.get("feedback_cliente", ""),
        direcoes_retrabalho=update_data.get("direcoes_retrabalho", ""),
        resultado_cliente=update_data.get("resultado", ""),
    )

    return {
        "sample": updated,
        "from_stage": STAGE_LABELS.get(old_stage, old_stage),
        "to_stage": STAGE_LABELS.get(new_stage, new_stage),
        "sku_created": sku_created,
        "tasks_generated": new_tasks,
    }


# ======================================================================
#  ERP v3.0 — REWORK = NEW SAMPLE WITH NEW GLOBAL NUMBER
# ======================================================================

class SampleReworkInput(BaseModel):
    motivo: str
    origem: str = "interna"  # interna | cliente
    variacao_id: Optional[str] = None  # se referencia uma variação específica
    nome_produto: Optional[str] = None
    observacoes_especificas: str = ""
    feedback_cliente: str = ""
    direcoes_retrabalho: str = ""


@crm_router.post("/samples/{sample_id}/rework")
async def create_rework_sample(sample_id: str, data: SampleReworkInput, request: Request):
    """ERP v3.0: Retrabalho gera NOVA amostra com NOVO número global.
    A amostra original permanece imutável (mas registra o retrabalho no histórico)."""
    user = await _get_current_user(request)

    original = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not original:
        raise HTTPException(status_code=404, detail="Amostra original não encontrada")

    if not data.motivo:
        raise HTTPException(status_code=400, detail="Motivo do retrabalho é obrigatório")

    if not clean_text(data.feedback_cliente) or not clean_text(data.direcoes_retrabalho):
        raise HTTPException(status_code=400, detail="Retrabalho exige feedback_cliente e direcoes_retrabalho")

    project = await assert_project_exists(user["tenant_id"], original["projeto_id"])

    now = _now_iso()
    novo_numero = await next_sample_code(user["tenant_id"])

    # Determinar variação base para herança (se especificada)
    base_variacao = None
    if data.variacao_id:
        base_variacao = next(
            (v for v in original.get("variacoes", []) if v["id"] == data.variacao_id), None
        )

    nova_letra = "a"
    nova_var_id = _new_id()
    nova_variacao = {
        "id": nova_var_id,
        "codigo": f"{novo_numero}-{nova_letra}",
        "letra": nova_letra,
        "descricao_aplicacao": (base_variacao or {}).get("descricao_aplicacao", ""),
        "percentual_fragrancia": (base_variacao or {}).get("percentual_fragrancia"),
        "referencia_fragrancia": (base_variacao or {}).get("referencia_fragrancia", ""),
        "custo_fragrancia": (base_variacao or {}).get("custo_fragrancia"),
        "observacoes_especificas": data.observacoes_especificas
            or (base_variacao or {}).get("observacoes_especificas", ""),
        "status": "solicitada",
        **_initial_sample_test_state(now),
        "aprovacao_interna": False,
        "aprovacao_externa": False,
        "historico_status": [{
            "de": "",
            "para": "solicitada",
            "data": now,
            "usuario": user["name"],
            "usuario_id": user["id"],
            "trigger": "retrabalho",
        }],
        "motivo_retrabalho": "",
        "historico_retrabalhos": [],
        "feedback_cliente": data.feedback_cliente or (base_variacao or {}).get("feedback_cliente", ""),
        "direcoes_retrabalho": data.direcoes_retrabalho,
        "resultado": "",
        "enviado_comercial_em": None,
        "aprovado_cliente_em": None,
        "reprovacao_motivo": "",
        "gera_sku": False,
        "sku_id": None,
        "pd_card_id": None,
    }

    nova_sample_id = _new_id()
    briefing_record = _build_briefing_record(
        tenant_id=user["tenant_id"],
        project=project,
        sample_id=nova_sample_id,
        sample_payload={
            **original,
            "nome_produto": data.nome_produto or original.get("nome_produto", ""),
            "briefing_especifico": original.get("briefing_especifico", ""),
            "observacao_tecnica": data.observacoes_especificas or original.get("observacao_tecnica", ""),
        },
        user=user,
        now=now,
        origem="crm_sample_rework",
    )
    nova_sample = {
        "id": nova_sample_id,
        "tenant_id": user["tenant_id"],
        "projeto_id": original["projeto_id"],
        "projeto_nome": original.get("projeto_nome", ""),
        "cliente_id": original["cliente_id"],
        "cliente_nome": original.get("cliente_nome", ""),
        "numero_amostra": str(novo_numero),
        "nome_produto": data.nome_produto or original.get("nome_produto", ""),
        "categoria": original.get("categoria", ""),
        "briefing_base": original.get("briefing_base", ""),
        "responsavel_pd": original.get("responsavel_pd", ""),
        "parametro_variacao": original.get("parametro_variacao", ""),
        "tipo_amostra": original.get("tipo_amostra", ""),
        "referencia_formula": original.get("referencia_formula", ""),
        "quantidade_por_variacao": original.get("quantidade_por_variacao"),
        "unidade_quantidade": original.get("unidade_quantidade", ""),
        "prazo_entrega_cliente": original.get("prazo_entrega_cliente", ""),
        "briefing_especifico": original.get("briefing_especifico", ""),
        "feedback_cliente": data.feedback_cliente,
        "direcoes_retrabalho": data.direcoes_retrabalho,
        "resultado": "",
        "aprovacao_interna": False,
        "aprovacao_externa": False,
        **_initial_sample_test_state(now),
        "briefing_id": briefing_record["id"],
        "briefing_registro": briefing_record,
        "data_envio": None,
        "enviado_comercial_em": None,
        "aprovado_cliente_em": None,
        "reprovacao_motivo": "",
        "tem_variacoes": False,
        "variacoes": [nova_variacao],
        "produto": original.get("produto", ""),
        "objetivo_projeto": original.get("objetivo_projeto", ""),
        "aplicacoes_desenvolver": original.get("aplicacoes_desenvolver", ""),
        "ativos_claims": original.get("ativos_claims", ""),
        "referencias": original.get("referencias", ""),
        "referencias_fotos": original.get("referencias_fotos", []),
        "orcamento_projeto": original.get("orcamento_projeto", ""),
        "textura_esperada": original.get("textura_esperada", ""),
        "aplicacao": original.get("aplicacao", ""),
        "sensorial": original.get("sensorial", ""),
        "ph": original.get("ph", ""),
        "observacao_tecnica": original.get("observacao_tecnica", ""),
        "stage": "solicitada",
        "rework_de_amostra_id": original["id"],
        "rework_de_variacao_id": data.variacao_id,
        "rework_de_numero": original.get("numero_amostra", ""),
        "rework_motivo": data.motivo,
        "rework_origem": data.origem,
        "created_by": user["id"],
        "created_by_name": user["name"],
        "created_at": now,
        "updated_at": now,
    }
    inherit(nova_sample, project, INHERITED_FROM_PROJECT)
    await db.crm_samples.insert_one(nova_sample)
    await _persist_briefing_record(briefing_record)
    nova_sample.pop("_id", None)

    # Marcar a original com referência ao retrabalho gerado
    await db.crm_samples.update_one(
        {"id": original["id"], "tenant_id": user["tenant_id"]},
        {
            "$push": {
                "historico_retrabalhos": {
                    "data": now,
                    "motivo": data.motivo,
                    "origem": data.origem,
                    "nova_amostra_id": nova_sample_id,
                    "novo_numero": str(novo_numero),
                    "usuario": user["name"],
                    "usuario_id": user["id"],
                }
            },
            "$set": {
                "updated_at": now,
                "feedback_cliente": data.feedback_cliente,
                "direcoes_retrabalho": data.direcoes_retrabalho,
                "resultado": "retrabalho",
            },
        },
    )
    if data.variacao_id:
        await db.crm_samples.update_one(
            {"id": original["id"], "tenant_id": user["tenant_id"], "variacoes.id": data.variacao_id},
            {
                "$set": {
                    "variacoes.$.motivo_retrabalho": data.motivo,
                    "variacoes.$.feedback_cliente": data.feedback_cliente,
                    "variacoes.$.direcoes_retrabalho": data.direcoes_retrabalho,
                    "variacoes.$.resultado": "retrabalho",
                },
                "$push": {
                    "variacoes.$.historico_retrabalhos": {
                        "data": now,
                        "motivo": data.motivo,
                        "origem": data.origem,
                        "nova_amostra_id": nova_sample_id,
                        "novo_numero": str(novo_numero),
                        "usuario": user["name"],
                        "usuario_id": user["id"],
                    }
                },
            },
        )

    # Criar P&D card para a nova variação
    await _create_pd_card_for_variacao(nova_sample, nova_variacao, user)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="sample_rework_created",
        entity_type="sample",
        entity_id=nova_sample_id,
        before={"original_id": original["id"], "original_numero": original.get("numero_amostra")},
        after={"novo_numero": str(novo_numero), "motivo": data.motivo, "origem": data.origem},
        metadata={"projeto_id": original["projeto_id"], "cliente_id": original["cliente_id"]},
    )

    return {
        "rework_sample": nova_sample,
        "original_id": original["id"],
        "novo_numero": str(novo_numero),
    }


@crm_router.put("/samples/{sample_id}/variacoes/{variacao_id}")
async def update_variacao(sample_id: str, variacao_id: str, data: VariacaoUpdate, request: Request):
    """Atualizar uma variação específica de uma amostra"""
    user = await _get_current_user(request)
    
    update_fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    if "custo_fragrancia_currency" in update_fields:
        update_fields["custo_fragrancia_currency"] = _normalize_currency_code(update_fields["custo_fragrancia_currency"])
    
    # Montar update com dot notation para variação específica
    set_fields = {f"variacoes.$.{k}": v for k, v in update_fields.items()}
    set_fields["updated_at"] = _now_iso()
    
    result = await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"], "variacoes.id": variacao_id},
        {"$set": set_fields}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Amostra ou variação não encontrada")
    
    sample = await db.crm_samples.find_one({"id": sample_id}, {"_id": 0})
    return sample


@crm_router.put("/samples/{sample_id}/variacoes/{variacao_id}/move")
async def move_variacao(sample_id: str, variacao_id: str, data: VariacaoMove, request: Request):
    """Mover uma variação entre status — bloqueado para perfis comerciais (CRM é read-only)."""
    user = await _get_current_user(request)

    # REGRA DE NEGÓCIO: status da variação é controlado exclusivamente pelo P&D.
    # Perfis comerciais não podem mover variações; apenas registram resultado do cliente
    # via POST /samples/{id}/variacoes/{vid}/resultado-cliente.
    _COMERCIAL_ROLES = {"vendedor", "sales_ops", "sucesso_cliente"}
    from rbac import normalize_role
    if normalize_role(user.get("role", "")) in _COMERCIAL_ROLES:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "sem_permissao",
                "message": "O status da variação é controlado pelo setor P&D. "
                           "Para atualizar, o formulador deve mover o card no Pipeline P&D.",
                "instrucao": "Acesse Pipeline P&D para ver o progresso desta amostra.",
            },
        )

    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")
    
    # Encontrar a variação
    variacao = next((v for v in sample.get("variacoes", []) if v["id"] == variacao_id), None)
    if not variacao:
        raise HTTPException(status_code=404, detail="Variação não encontrada")
    
    old_status = variacao["status"]
    new_status = data.status
    
    # Validar transição
    if new_status not in SAMPLE_STAGES:
        raise HTTPException(status_code=400, detail=f"Status inválido: {new_status}")

    # ERP v3.0: Retrabalho exige uso do endpoint /samples/{id}/rework (gera novo nº global)
    if new_status == "retrabalho":
        raise HTTPException(
            status_code=400,
            detail="Retrabalho não move variação — gera nova amostra. Use POST /api/crm/samples/{sample_id}/rework",
        )

    allowed = SAMPLE_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Transição não permitida: {STAGE_LABELS.get(old_status)} → {STAGE_LABELS.get(new_status)}"
        )

    # ERP v3.0: blocking tasks
    await assert_no_blocking_tasks(
        tenant_id=user["tenant_id"],
        entity_type="variacao",
        entity_id=variacao_id,
        target_stage=new_status,
    )

    # Validar motivo de reprovação
    if new_status == "reprovada" and not data.motivo_retrabalho:
        raise HTTPException(status_code=400, detail="Motivo da reprovação é obrigatório")
    if new_status == "aprovada":
        raise HTTPException(
            status_code=422,
            detail="Aprovação direta não é permitida. Registre o envio e depois o resultado do cliente.",
        )
    
    now = _now_iso()
    
    # Atualizar status da variação
    set_ops = {
        "variacoes.$.status": new_status,
        "variacoes.$.updated_at": now,
        "variacoes.$.aprovacao_interna": variacao.get("aprovacao_interna", False),
        "variacoes.$.aprovacao_externa": variacao.get("aprovacao_externa", False),
        "updated_at": now
    }
    if new_status == "enviada":
        set_ops["data_envio"] = now
        set_ops["variacoes.$.enviado_comercial_em"] = now
        set_ops["variacoes.$.aprovacao_interna"] = True
    if new_status == "reprovada":
        set_ops["variacoes.$.resultado"] = "reprovada"
        set_ops["variacoes.$.aprovacao_externa"] = False
        set_ops["variacoes.$.reprovacao_motivo"] = data.motivo_retrabalho or data.feedback_cliente or ""
    if data.feedback_cliente:
        set_ops["variacoes.$.feedback_cliente"] = data.feedback_cliente
    if data.direcoes_retrabalho:
        set_ops["variacoes.$.direcoes_retrabalho"] = data.direcoes_retrabalho
    
    push_ops = {
        "variacoes.$.historico_status": {
            "de": old_status,
            "para": new_status,
            "data": now,
            "usuario": user["name"],
            "usuario_id": user["id"]
        }
    }
    
    if new_status == "reprovada" and data.motivo_retrabalho:
        set_ops["variacoes.$.motivo_retrabalho"] = data.motivo_retrabalho
    if data.origem_retrabalho:
        set_ops["variacoes.$.origem_retrabalho"] = data.origem_retrabalho
    
    await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"], "variacoes.id": variacao_id},
        {
            "$set": set_ops,
            "$push": push_ops
        }
    )
    
    updated = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )

    new_tasks = await trigger_tasks_for_transition(
        entity_type="variacao",
        entity_id=variacao_id,
        tenant_id=user["tenant_id"],
        old_stage=old_status,
        new_stage=new_status,
        user=user,
    )

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="variacao_moved",
        entity_type="variacao",
        entity_id=variacao_id,
        before={"status": old_status},
        after={"status": new_status},
        metadata={"sample_id": sample_id, "tasks_generated": [t["id"] for t in new_tasks]},
    )

    # Auditoria de SKU: geração de SKU foi removida deste endpoint (formato antigo,
    # sem validação R25) — este endpoint é bloqueado para perfis comerciais e nunca é
    # chamado pelo front (só resultado_cliente, abaixo, é o caminho real de aprovação
    # pelo cliente). sku_created mantido no payload de resposta por compatibilidade.
    sku_created = None
    if new_status == "aprovada":
        await _advance_project_stage_if_needed(
            updated["projeto_id"],
            "em_negociacao",
            user,
            movement_source="variacao_approved",
        )
    elif new_status == "em_elaboracao":
        await _advance_project_stage_if_needed(
            updated["projeto_id"],
            "amostra_em_desenvolvimento",
            user,
            movement_source="variacao_in_development",
            extra_set={"data_inicio_desenvolvimento": now},
        )
    elif new_status == "enviada":
        await _advance_project_stage_if_needed(
            updated["projeto_id"],
            "amostra_enviada",
            user,
            movement_source="variacao_sent",
            extra_set={"data_ultima_amostra_enviada": now},
        )

    await _sync_pd_cards_from_crm_stage(
        tenant_id=user["tenant_id"],
        sample_id=sample_id,
        variacao_id=variacao_id,
        user=user,
        now=now,
        crm_stage=new_status,
        feedback_cliente=set_ops.get("variacoes.$.feedback_cliente", ""),
        direcoes_retrabalho=set_ops.get("variacoes.$.direcoes_retrabalho", ""),
        resultado_cliente=set_ops.get("variacoes.$.resultado", ""),
    )
    
    return {
        "sample": updated,
        "variacao_id": variacao_id,
        "from_status": STAGE_LABELS.get(old_status, old_status),
        "to_status": STAGE_LABELS.get(new_status, new_status),
        "sku_created": sku_created,
        "tasks_generated": new_tasks,
    }


# ======================================================================
#  VARIAÇÃO — RESULTADO DO CLIENTE (único ponto de escrita comercial pós-envio)
# ======================================================================

class ResultadoClienteRequest(BaseModel):
    resultado: str  # "aprovada" | "retrabalho" | "arquivado" ("reprovada" legado)
    feedback_cliente: Optional[str] = None
    direcoes_retrabalho: Optional[str] = None


@crm_router.post("/samples/{sample_id}/variacoes/{variacao_id}/resultado-cliente")
async def resultado_cliente(
    sample_id: str, variacao_id: str, data: ResultadoClienteRequest, request: Request
):
    """Ponto unico onde o Comercial registra a decisao do cliente."""
    user = await _get_current_user(request)

    if data.resultado not in ("aprovada", "arquivado", "reprovada", "retrabalho"):
        raise HTTPException(
            status_code=422,
            detail="resultado deve ser: aprovada, arquivado ou retrabalho",
        )
    canonical_resultado = "arquivado" if data.resultado == "reprovada" else data.resultado
    if canonical_resultado in ("retrabalho", "arquivado") and not (data.feedback_cliente or "").strip():
        raise HTTPException(
            status_code=422,
            detail="feedback_cliente e obrigatorio quando resultado='retrabalho' ou 'arquivado'",
        )

    tenant_id = user["tenant_id"]
    sample = await db.crm_samples.find_one({"id": sample_id, "tenant_id": tenant_id}, {"_id": 0})
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra nao encontrada")

    variacao = next((v for v in sample.get("variacoes", []) if v["id"] == variacao_id), None)
    if not variacao:
        raise HTTPException(status_code=404, detail="Variacao nao encontrada")

    status_atual = variacao.get("status")
    if status_atual != "enviada":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "status_invalido",
                "message": (
                    f"Resultado so pode ser registrado quando status='enviada'. "
                    f"Status atual: '{status_atual}'"
                ),
                "status_atual": status_atual,
            },
        )

    now = _now_iso()
    novo_status_crm = "reprovada" if canonical_resultado == "arquivado" else canonical_resultado
    aprovacao_interna = bool(
        variacao.get("aprovacao_interna")
        or variacao.get("enviado_comercial_em")
        or sample.get("aprovacao_interna")
        or sample.get("data_envio")
    )
    if not aprovacao_interna:
        raise HTTPException(
            status_code=409,
            detail="Aprovacao interna pendente antes do registro do cliente.",
        )

    pd_label = {
        "aprovada": "Aprovado pelo Cliente",
        "arquivado": "Arquivado pelo Cliente",
        "retrabalho": "Retrabalho Solicitado",
    }[canonical_resultado]

    set_ops = {
        "variacoes.$.status": novo_status_crm,
        "variacoes.$.status_pd_label": pd_label,
        "variacoes.$.feedback_cliente": data.feedback_cliente or "",
        "variacoes.$.resultado_cliente_registrado_por": user["id"],
        "variacoes.$.resultado_cliente_registrado_em": now,
        "variacoes.$.decisao_cliente": _build_client_decision(
            resultado=canonical_resultado,
            feedback_cliente=data.feedback_cliente or "",
            direcoes_retrabalho=data.direcoes_retrabalho or "",
            user=user,
            now=now,
        ),
        "variacoes.$.aprovacao_interna": True,
        "variacoes.$.updated_at": now,
    }
    if data.direcoes_retrabalho:
        set_ops["variacoes.$.direcoes_retrabalho"] = data.direcoes_retrabalho
    if canonical_resultado == "aprovada":
        set_ops["variacoes.$.resultado"] = "aprovada"
        set_ops["variacoes.$.aprovacao_externa"] = True
        set_ops["variacoes.$.aprovado_cliente_em"] = now
    if canonical_resultado == "arquivado":
        set_ops["variacoes.$.resultado"] = "arquivado"
        set_ops["variacoes.$.aprovacao_externa"] = False
        set_ops["variacoes.$.reprovacao_motivo"] = data.feedback_cliente or ""
        set_ops["variacoes.$.arquivada"] = True
    if canonical_resultado == "retrabalho":
        set_ops["variacoes.$.aprovacao_externa"] = False
        set_ops["variacoes.$.reprovacao_motivo"] = data.feedback_cliente or ""

    await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": tenant_id, "variacoes.id": variacao_id},
        {
            "$set": set_ops,
            "$push": {
                "variacoes.$.historico_status": {
                    "de": "enviada",
                    "para": novo_status_crm,
                    "data": now,
                    "usuario": user["name"],
                    "usuario_id": user["id"],
                    "origem": "resultado_cliente",
                    "resultado_cliente": canonical_resultado,
                }
            },
        },
    )

    await _sync_pd_cards_from_crm_stage(
        tenant_id=tenant_id,
        sample_id=sample_id,
        variacao_id=variacao_id,
        user=user,
        now=now,
        crm_stage="reprovada" if canonical_resultado in ("arquivado", "retrabalho") else "enviada",
        feedback_cliente=data.feedback_cliente or "",
        direcoes_retrabalho=data.direcoes_retrabalho or "",
        resultado_cliente=canonical_resultado,
    )

    pd_card = await db.pd_cards.find_one({"amostra_variacao_id": variacao_id, "tenant_id": tenant_id}, {"_id": 0})
    pd_card_notificado = False
    if pd_card:
        novo_status_pd = {
            "aprovada": "aguardando_aprovacao",
            "arquivado": "retrabalho_interno",
            "retrabalho": "retrabalho_interno",
        }[canonical_resultado]
        await db.pd_cards.update_one(
            {"id": pd_card["id"], "tenant_id": tenant_id},
            {
                "$set": {
                    "status_pd": novo_status_pd,
                    "feedback_cliente": data.feedback_cliente or "",
                    "direcoes_retrabalho": data.direcoes_retrabalho or "",
                    "resultado_cliente": canonical_resultado,
                    "updated_at": now,
                },
                "$push": {
                    "historico_movimentacoes": {
                        "de": pd_card.get("status_pd", ""),
                        "para": novo_status_pd,
                        "data": now,
                        "usuario": user["name"],
                        "usuario_id": user["id"],
                        "observacao": f"Resultado do cliente: {pd_label}",
                    }
                },
            },
        )
        pd_card_notificado = True
        logger.info(
            f"Resultado cliente: variacao {variacao_id} -> {novo_status_crm} / "
            f"pd_card {pd_card['id']} -> {novo_status_pd}"
        )

    await audit_log(
        tenant_id=tenant_id,
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="resultado_cliente_registrado",
        entity_type="variacao",
        entity_id=variacao_id,
        before={"status": "enviada"},
        after={"status": novo_status_crm, "resultado": canonical_resultado},
        metadata={"sample_id": sample_id, "pd_card_id": pd_card["id"] if pd_card else None},
    )

    sku_created = None
    if canonical_resultado == "aprovada":
        updated_sample = await db.crm_samples.find_one({"id": sample_id, "tenant_id": tenant_id}, {"_id": 0})
        updated_variacao = next((v for v in (updated_sample or {}).get("variacoes", []) if v["id"] == variacao_id), None)
        if updated_sample and updated_variacao:
            sku_created = await _create_sku_from_variacao_v2(updated_sample, updated_variacao, user)

    return {
        "success": True,
        "variacao_id": variacao_id,
        "resultado": canonical_resultado,
        "status_atualizado": novo_status_crm,
        "pd_card_notificado": pd_card_notificado,
        "sku_created": sku_created,
    }

# ======================================================================
#  SAMPLE / VARIAÇÃO — DELETE & ADD VARIAÇÕES (pós-envio)
# ======================================================================

class AddVariacoesRequest(BaseModel):
    variacoes: List[VariacaoItem]


@crm_router.delete("/samples/{sample_id}")
async def delete_sample(sample_id: str, request: Request):
    """Deleta uma amostra completa (todas variações + pd_cards).
    Bloqueia se alguma variação já gerou SKU."""
    user = await _get_current_user(request)
    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")

    # Bloquear se alguma variação tiver SKU
    for v in sample.get("variacoes", []) or []:
        if v.get("sku_id"):
            raise HTTPException(
                status_code=400,
                detail=f"Não é possível excluir: variação {v.get('codigo')} já gerou SKU."
            )

    # Coletar pd_cards vinculados
    pd_card_ids = [v["pd_card_id"] for v in (sample.get("variacoes") or []) if v.get("pd_card_id")]

    if pd_card_ids:
        await db.pd_cards.delete_many(
            {"id": {"$in": pd_card_ids}, "tenant_id": user["tenant_id"]}
        )
    await db.crm_samples.delete_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}
    )

    logger.info(f"Deleted sample {sample_id} with {len(pd_card_ids)} pd_cards")
    return {
        "deleted_sample": sample_id,
        "deleted_pd_cards": len(pd_card_ids),
    }


@crm_router.delete("/samples/{sample_id}/variacoes/{variacao_id}")
async def delete_variacao(sample_id: str, variacao_id: str, request: Request):
    """Deleta uma variação específica (e seu pd_card).
    Bloqueia se a variação já gerou SKU ou se é a última variação."""
    user = await _get_current_user(request)
    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")

    variacoes = sample.get("variacoes") or []
    variacao = next((v for v in variacoes if v["id"] == variacao_id), None)
    if not variacao:
        raise HTTPException(status_code=404, detail="Variação não encontrada")

    if variacao.get("sku_id"):
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir: variação {variacao.get('codigo')} já gerou SKU."
        )

    if len(variacoes) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Não é possível excluir a última variação. Exclua a amostra inteira."
        )

    # Remover pd_card vinculado
    if variacao.get("pd_card_id"):
        await db.pd_cards.delete_one(
            {"id": variacao["pd_card_id"], "tenant_id": user["tenant_id"]}
        )

    # Remover variação do array
    await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]},
        {
            "$pull": {"variacoes": {"id": variacao_id}},
            "$set": {"updated_at": _now_iso()}
        }
    )

    # Recalcular tem_variacoes
    updated = await db.crm_samples.find_one({"id": sample_id}, {"_id": 0})
    tem_variacoes = len(updated.get("variacoes") or []) > 1
    await db.crm_samples.update_one(
        {"id": sample_id},
        {"$set": {"tem_variacoes": tem_variacoes}}
    )

    logger.info(f"Deleted variação {variacao_id} from sample {sample_id}")
    return {"deleted_variacao": variacao_id, "sample_id": sample_id}


@crm_router.post("/samples/{sample_id}/variacoes")
async def add_variacoes_to_sample(sample_id: str, data: AddVariacoesRequest, request: Request):
    """Adiciona novas variações a uma amostra existente.
    Gera automaticamente próximas letras (se tem A,B,C → adiciona D, E...)."""
    user = await _get_current_user(request)
    sample = await db.crm_samples.find_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Amostra não encontrada")

    if not data.variacoes:
        raise HTTPException(status_code=400, detail="Nenhuma variação fornecida")

    now = _now_iso()
    existing = sample.get("variacoes") or []
    # Próximo índice baseado no número de variações existentes (mesmo deletadas no passado o usuario cria sequencia)
    start_index = len(existing)
    numero_amostra = sample.get("numero_amostra", "?")

    new_variacoes = []
    for offset, var in enumerate(data.variacoes):
        idx = start_index + offset
        letra = int_to_letters(idx)
        codigo = f"{numero_amostra}-{letra}"
        variacao_id = _new_id()
        variacao = {
            "id": variacao_id,
            "codigo": codigo,
            "letra": letra,
            "descricao_aplicacao": var.descricao_aplicacao,
            "percentual_fragrancia": var.percentual_fragrancia,
            "referencia_fragrancia": var.referencia_fragrancia,
            "fr_codigo": var.fr_codigo or "",
            "custo_fragrancia": var.custo_fragrancia,
            "custo_fragrancia_currency": _normalize_currency_code(var.custo_fragrancia_currency),
            "observacoes_especificas": var.observacoes_especificas,
            "status": "solicitada",
            "historico_status": [{
                "de": "",
                "para": "solicitada",
                "data": now,
                "usuario": user["name"],
                "usuario_id": user["id"]
            }],
            "motivo_retrabalho": "",
            "historico_retrabalhos": [],
            "feedback_cliente": "",
            "gera_sku": False,
            "sku_id": None,
            "pd_card_id": None,
        }
        new_variacoes.append(variacao)

    # Inserir no array
    await db.crm_samples.update_one(
        {"id": sample_id, "tenant_id": user["tenant_id"]},
        {
            "$push": {"variacoes": {"$each": new_variacoes}},
            "$set": {"tem_variacoes": True, "updated_at": now},
        }
    )

    # Criar pd_cards para cada nova variação
    updated = await db.crm_samples.find_one({"id": sample_id}, {"_id": 0})
    for new_var in new_variacoes:
        # Recuperar a variação recém-persistida para linkar pd_card
        await _create_pd_card_for_variacao(updated, new_var, user)

    final = await db.crm_samples.find_one({"id": sample_id}, {"_id": 0})
    logger.info(f"Added {len(new_variacoes)} variações to sample {sample_id}")
    return {
        "sample": final,
        "added": len(new_variacoes),
        "new_variacoes": new_variacoes,
    }


# ======================================================================
#  SKU (auto-generated from approved samples)
# ======================================================================

_SKU_CODE_RE = re.compile(r"^[A-Z]{3}-[A-Z]{4}-\d{4}$")


def _assert_valid_sku_code(codigo: str) -> None:
    """Rede de segurança pós-construção: build_sku_code_v2 já é determinística (força
    uppercase, comprimento fixo), então isso não deveria disparar nunca — mas um código
    de SKU malformado indo pro banco é caro demais de corrigir depois pra não ter uma
    checagem explícita. 13 caracteres: CAT3(3) + '-' + CLI4(4) + '-' + SEQ4(4)."""
    if not codigo or len(codigo) != 13 or not _SKU_CODE_RE.match(codigo):
        raise HTTPException(status_code=500, detail=f"Código de SKU gerado em formato inválido: '{codigo}' (esperado XXX-XXXX-0000)")


def _normalize_categoria_key(s: str) -> str:
    s = (s or "").lower().strip()
    for a, b in (("ã", "a"), ("é", "e"), ("ó", "o"), ("ç", "c"), (" ", "_"), ("/", "_"), ("-", "_")):
        s = s.replace(a, b)
    while "__" in s:
        s = s.replace("__", "_")
    return s


async def resolve_cat3_from_categoria(categoria: str, tenant_id: str) -> Optional[str]:
    """
    Resolve o CAT3 de uma categoria dinamicamente a partir de db.categorias (registro
    governado, R22) — não do dict estático CAT3_MAP/cat3_from_categoria (workflow_engine.py),
    que fica só como seed/fallback de migration.

    Tenta casar primeiro pelo valor exato da categoria escolhida na amostra/projeto
    (um sub-item de CATEGORIA_INTERESSE_OPTIONS, ex: "body_splash_colonia"), e só então
    pelo grupo pai (ex: "perfumaria"). Necessário porque alguns sub-itens têm categoria
    própria no registro de SKU mesmo pertencendo a outro grupo na taxonomia comercial —
    ex: "body_splash_colonia" é sub-item do grupo "perfumaria" em CATEGORIA_INTERESSE_OPTIONS,
    mas tem CAT3 próprio ("BSP", Body Splash) no registro de SKU; resolver só pelo grupo
    geraria PFM (Perfumaria) errado pra esse caso.

    Retorna None se nenhuma categoria ativa correspondente for encontrada.
    """
    if not categoria:
        return None

    ativas = await db.categorias.find(
        {"tenant_id": tenant_id, "status": "ativa"}, {"_id": 0, "cat3": 1, "nome": 1}
    ).to_list(500)
    if not ativas:
        return None
    by_name = {_normalize_categoria_key(c["nome"]): c["cat3"] for c in ativas}

    candidatos = [categoria]
    for grupo, subitens in CATEGORIA_INTERESSE_OPTIONS.items():
        if categoria in subitens:
            candidatos.append(grupo)
            break

    for candidato in candidatos:
        key = _normalize_categoria_key(candidato)
        if key in by_name:
            return by_name[key]
        for nome_norm, cat3 in by_name.items():
            if nome_norm in key or key in nome_norm:
                return cat3
    return None


async def _check_sku_dependency_chain(
    sample: dict,
    tenant_id: str,
    variacao: Optional[dict] = None,
    *,
    fasttrack_variacao: bool = False,
) -> str:
    """
    R25: Validate full dependency chain before generating SKU.
    Raises HTTPException 409 with the first missing prerequisite.
    Chain: Categoria exists -> Cliente com CLI4 -> Projeto ->
           Amostra/Variacao aprovada -> Negociacao/Pedido aprovado.
    O CGI/Kickoff vem depois do SKU no fluxo Prospect->Pedido; contrato nao pode
    bloquear a criacao do produto comercial.
    Retorna o CAT3 resolvido (reaproveitado pelo caller na montagem do código do SKU,
    garantindo que a checagem e a geração usam exatamente a mesma resolução).
    """
    cliente_id = sample.get("cliente_id")
    projeto_id = sample.get("projeto_id")

    # 1. Cliente with CLI4
    client = await db.crm_clients.find_one({"id": cliente_id, "tenant_id": tenant_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=409, detail="[R25] Cliente não encontrado — pré-requisito para geração de SKU")
    if not client.get("cli4"):
        raise HTTPException(status_code=409, detail="[R25] Cliente sem CLI4 definido — cadastre o código CLI4 antes de gerar o SKU")

    # 2. Categoria exists and is active (must be in db.categorias)
    categoria = sample.get("categoria") or ""
    if not categoria:
        project = await db.crm_projects.find_one({"id": projeto_id, "tenant_id": tenant_id}, {"_id": 0})
        categoria = (project or {}).get("categoria", "")
    cat3 = await resolve_cat3_from_categoria(categoria, tenant_id)
    if not cat3:
        raise HTTPException(status_code=409, detail=f"[R25] Categoria '{categoria}' não possui CAT3 ativo cadastrado — solicite a categoria antes de gerar o SKU")

    # 3. O CGI/Kickoff vem depois do SKU no fluxo Prospect->Pedido.
    # Contrato assinado nao pode bloquear a criacao do produto comercial.

    # 4. Amostra (ou variação, quando geração é por variação — R11) aprovada
    if variacao is not None:
        if variacao.get("status") != "aprovada":
            raise HTTPException(
                status_code=409,
                detail=f"[R25] Variação deve estar com status 'aprovada' — atual: {variacao.get('status')}"
            )
    elif sample.get("stage") != "aprovada":
        raise HTTPException(
            status_code=409,
            detail=f"[R25] Amostra deve estar em stage 'aprovada' — atual: {sample.get('stage')}"
        )

    # 5. Pedido de Industrialização aprovado (pedido_aprovado stage on project)
    project = await db.crm_projects.find_one({"id": projeto_id, "tenant_id": tenant_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=409, detail="[R25] Projeto nÃ£o encontrado â€” prÃ©-requisito para geraÃ§Ã£o de SKU")
    if not (variacao is not None and fasttrack_variacao) and project.get("stage") not in ("pedido_aprovado", "cliente_fechado"):
        proj_stage = (project or {}).get("stage", "não encontrado")
        raise HTTPException(
            status_code=409,
            detail=f"[R25] Projeto deve estar em 'pedido_aprovado' — atual: {proj_stage}"
        )

    return cat3


async def _create_sku_from_sample(sample: dict, user: dict) -> dict:
    """
    Auto-create SKU entity when a sample is approved.
    Uses new format [CAT3]-[CLI4]-[SEQ4] (R11). Validates R25 chain first.
    """
    tenant_id = sample["tenant_id"]

    # R25: dependency chain — cat3 resolvido aqui é reaproveitado abaixo, garantindo que a
    # checagem e a geração do código usam exatamente a mesma resolução (db.categorias).
    try:
        cat3 = await _check_sku_dependency_chain(sample, tenant_id)
    except HTTPException as exc:
        logger.warning(f"SKU generation blocked for sample {sample['id']}: {exc.detail}")
        return {"blocked": True, "reason": exc.detail}

    # Resolve category (só p/ campos legados cat2/categoria abaixo — cat3 já resolvido acima)
    project = await db.crm_projects.find_one({"id": sample["projeto_id"]}, {"_id": 0})
    categoria = sample.get("categoria") or (project.get("categoria") if project else "") or ""

    client = await db.crm_clients.find_one({"id": sample["cliente_id"], "tenant_id": tenant_id}, {"_id": 0})
    cli4 = normalise_cli4(client.get("cli4") or client.get("nome_empresa", ""))
    seq = await next_sku_per_pair_v2(tenant_id, cat3, cli4)
    codigo = build_sku_code_v2(cat3, cli4, seq)
    _assert_valid_sku_code(codigo)

    # Legacy fields preserved for backward compat queries
    cat2 = cat2_from_categoria(categoria)
    raw_cli3 = client.get("cli3") or client.get("nome_empresa", "")
    cli3 = normalise_cli3(raw_cli3)

    now = _now_iso()
    sku_id = _new_id()

    sku = {
        "id": sku_id,
        "tenant_id": tenant_id,
        "codigo_interno": codigo,
        "cat3": cat3,
        "cli4": cli4,
        "cat2": cat2,
        "cli3": cli3,
        "nome_produto": sample.get("nome_amostra", "") or sample.get("nome_produto", ""),
        "categoria": categoria,
        "formula_vinculada": "",
        "cliente_id": sample["cliente_id"],
        "cliente_nome": sample.get("cliente_nome", ""),
        "projeto_id": sample["projeto_id"],
        "projeto_nome": sample.get("projeto_nome", ""),
        "amostra_id": sample["id"],
        "produto_pai_id": None,
        "preco_unitario": 0.0,
        "moq": 0,
        "anvisa": {"numero": "", "validade": None},
        "status": "ativo",
        "pd_concluido": True,
        "pd_concluido_em": now,
        "pd_concluido_origem": "fluxo_comercial_aprovado",
        "descontinuado_motivo": None,
        "descontinuado_em": None,
        "descontinuado_por": None,
        "historico_pedidos": [],
        "data_ultimo_pedido": None,
        "frequencia_media_recompra_dias": 0,
        "medias_producao": {
            "media_geral_unh": None,
            "media_12m_unh": None,
            "media_3m_unh": None,
            "media_1m_unh": None,
            "meta_unh": None,
            "ajuste_percentual": 0,
            "meta_set_by": None,
            "meta_set_at": None,
            "historico_producao": [],
        },
        "created_at": now,
        "updated_at": now,
    }

    await db.skus.insert_one(sku)
    sku.pop("_id", None)

    # R23: freeze cli4 after first SKU
    if client and not client.get("cli4_congelado"):
        await db.crm_clients.update_one(
            {"id": sample["cliente_id"], "tenant_id": tenant_id},
            {"$set": {"cli4_congelado": True, "updated_at": now}},
        )

    logger.info(f"Auto-created SKU {codigo} from sample {sample['id']}")
    return sku


async def _create_sku_from_variacao_v2(sample: dict, variacao: dict, user: dict, *, fasttrack_variacao: bool = False) -> dict:
    """
    Geração de SKU no ponto real onde o cliente aprova (POST .../resultado-cliente) —
    formato novo [CAT3]-[CLI4]-[SEQ4] (R11), valida a cadeia R25 completa (agora
    verificando o status da própria variação, não o stage — geralmente desatualizado —
    da amostra), e auto-cria/reaproveita o Produto-Pai da família (R24).

    Substitui _create_sku_from_variacao (formato antigo, sem validação, nunca chamada
    pelo front) — ver RELATORIO_BETA_FIXES.md / auditoria de SKU.
    """
    tenant_id = sample["tenant_id"]
    existing_sku = None
    if variacao.get("sku_id"):
        existing_sku = await db.skus.find_one(
            {"id": variacao["sku_id"], "tenant_id": tenant_id},
            {"_id": 0},
        )
    if not existing_sku:
        existing_sku = await db.skus.find_one(
            {
                "tenant_id": tenant_id,
                "amostra_id": sample.get("id"),
                "amostra_variacao_id": variacao.get("id"),
                "status": {"$ne": "descontinuado"},
            },
            {"_id": 0},
        )
    if existing_sku:
        pd_patch = {
            "pd_concluido": True,
            "pd_concluido_em": _now_iso(),
            "pd_concluido_origem": "fluxo_comercial_aprovado",
            "updated_at": _now_iso(),
        }
        await db.skus.update_one(
            {"id": existing_sku["id"], "tenant_id": tenant_id},
            {"$set": pd_patch},
        )
        await db.crm_samples.update_one(
            {"id": sample["id"], "tenant_id": tenant_id, "variacoes.id": variacao["id"]},
            {"$set": {"variacoes.$.sku_id": existing_sku["id"], "variacoes.$.gera_sku": True}},
        )
        existing_sku.update(pd_patch)
        return existing_sku

    try:
        cat3 = await _check_sku_dependency_chain(
            sample,
            tenant_id,
            variacao=variacao,
            fasttrack_variacao=fasttrack_variacao,
        )
    except HTTPException as exc:
        logger.warning(f"SKU generation blocked for variação {variacao['id']}: {exc.detail}")
        return {"blocked": True, "reason": exc.detail}

    project = await db.crm_projects.find_one({"id": sample["projeto_id"]}, {"_id": 0})
    categoria = sample.get("categoria") or (project.get("categoria") if project else "") or ""

    client = await db.crm_clients.find_one({"id": sample["cliente_id"], "tenant_id": tenant_id}, {"_id": 0})
    cli4 = normalise_cli4(client.get("cli4") or client.get("nome_empresa", ""))
    seq = await next_sku_per_pair_v2(tenant_id, cat3, cli4)
    codigo = build_sku_code_v2(cat3, cli4, seq)
    _assert_valid_sku_code(codigo)

    # Legacy fields preserved for backward compat queries
    cat2 = cat2_from_categoria(categoria)
    raw_cli3 = client.get("cli3") or client.get("nome_empresa", "")
    cli3 = normalise_cli3(raw_cli3)

    now = _now_iso()
    sku_id = _new_id()
    nome_base = sample.get("nome_amostra", "") or sample.get("nome_produto", "")

    sku = {
        "id": sku_id,
        "tenant_id": tenant_id,
        "codigo_interno": codigo,
        "cat3": cat3,
        "cli4": cli4,
        "cat2": cat2,
        "cli3": cli3,
        "nome_produto": f"{nome_base} - {variacao.get('codigo', '')}".strip(" -"),
        "categoria": categoria,
        "formula_vinculada": "",
        "cliente_id": sample["cliente_id"],
        "cliente_nome": sample.get("cliente_nome", ""),
        "projeto_id": sample["projeto_id"],
        "projeto_nome": sample.get("projeto_nome", ""),
        "amostra_id": sample["id"],
        "amostra_variacao_id": variacao["id"],
        "descricao_aplicacao": variacao.get("descricao_aplicacao", ""),
        "produto_pai_id": None,
        "preco_unitario": variacao.get("custo_fragrancia") or 0.0,
        "moq": 0,
        "anvisa": {"numero": "", "validade": None},
        "status": "ativo",
        "pd_concluido": True,
        "pd_concluido_em": now,
        "pd_concluido_origem": "fluxo_comercial_aprovado",
        "descontinuado_motivo": None,
        "descontinuado_em": None,
        "descontinuado_por": None,
        "historico_pedidos": [],
        "data_ultimo_pedido": None,
        "frequencia_media_recompra_dias": 0,
        "medias_producao": {
            "media_geral_unh": None,
            "media_12m_unh": None,
            "media_3m_unh": None,
            "media_1m_unh": None,
            "meta_unh": None,
            "ajuste_percentual": 0,
            "meta_set_by": None,
            "meta_set_at": None,
            "historico_producao": [],
        },
        "created_at": now,
        "updated_at": now,
    }

    await db.skus.insert_one(sku)
    sku.pop("_id", None)

    # Atualizar variação com SKU ID
    await db.crm_samples.update_one(
        {"id": sample["id"], "tenant_id": tenant_id, "variacoes.id": variacao["id"]},
        {"$set": {"variacoes.$.sku_id": sku_id, "variacoes.$.gera_sku": True}}
    )

    # R23: freeze cli4 after first SKU
    if client and not client.get("cli4_congelado"):
        await db.crm_clients.update_one(
            {"id": sample["cliente_id"], "tenant_id": tenant_id},
            {"$set": {"cli4_congelado": True, "updated_at": now}},
        )

    # R24: auto-cria/reaproveita o Produto-Pai da família (mesmo cliente + mesmo nome
    # base, case-insensitive) e vincula o SKU como uma nova apresentação. Volume/embalagem
    # ficam em branco por ora — amostra/variação ainda não têm campo estruturado de volume;
    # preenchido manualmente depois, quando a tela de Produto-Pai existir (Fase 2).
    try:
        produto_pai = await find_or_create_produto_pai(
            nome=nome_base,
            cliente_id=sample["cliente_id"],
            tenant_id=tenant_id,
            user_id=user["id"],
            user_name=user.get("name", ""),
        )
        await _vincular_sku_ao_produto_pai_internal(
            produto_pai_id=produto_pai["id"],
            sku_id=sku_id,
            tenant_id=tenant_id,
        )
        await db.skus.update_one(
            {"id": sku_id, "tenant_id": tenant_id},
            {"$set": {"produto_pai_id": produto_pai["id"], "updated_at": _now_iso()}},
        )
        sku["produto_pai_id"] = produto_pai["id"]
    except HTTPException as exc:
        # Não bloqueia a geração do SKU em si — o vínculo pode ser feito manualmente
        # depois. Loga pra investigação, mas o SKU já foi criado e é válido.
        logger.error(f"SKU {codigo} criado mas falhou ao vincular Produto-Pai: {exc.detail}")

    logger.info(f"Auto-created SKU {codigo} from variação {variacao.get('codigo')} (sample {sample['id']})")
    return sku


async def _generate_skus_for_project_approved_variations(project_id: str, user: dict) -> List[dict]:
    """Gera SKUs pendentes quando a negociacao/projeto vira pedido_aprovado.

    O resultado do cliente pode aprovar a variacao antes do projeto estar em
    pedido_aprovado; nesse momento a geracao retorna bloqueada por etapa. Este helper
    e a segunda tentativa oficial no fechamento comercial e e idempotente porque
    _create_sku_from_variacao_v2 reaproveita SKU existente por variacao.
    """
    tenant_id = user["tenant_id"]
    samples = await db.crm_samples.find(
        {"tenant_id": tenant_id, "projeto_id": project_id},
        {"_id": 0},
    ).to_list(1000)
    results: List[dict] = []

    for sample in samples:
        variations = sample.get("variacoes") or []
        generated_for_sample = False
        for variacao in variations:
            if variacao.get("status") != "aprovada" and variacao.get("resultado") != "aprovada":
                continue
            sku = await _create_sku_from_variacao_v2(sample, variacao, user)
            results.append({
                "amostra_id": sample.get("id"),
                "variacao_id": variacao.get("id"),
                "sku": sku,
            })
            if sku and not sku.get("blocked"):
                generated_for_sample = True

        if not variations and sample.get("stage") == "aprovada":
            sku = await _create_sku_from_sample(sample, user)
            results.append({
                "amostra_id": sample.get("id"),
                "variacao_id": None,
                "sku": sku,
            })
            if sku and not sku.get("blocked"):
                generated_for_sample = True

        if generated_for_sample:
            await db.crm_samples.update_one(
                {"tenant_id": tenant_id, "id": sample["id"]},
                {"$set": {"stage": "aprovada", "updated_at": _now_iso()}},
            )

    return results


@crm_router.get("/skus")
async def list_skus(
    request: Request,
    cliente_id: Optional[str] = None,
    status: Optional[str] = None,
    cat3: Optional[str] = None,
    cat2: Optional[str] = None,
    search: Optional[str] = None,
    pd_concluidos: bool = False,
):
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if cliente_id:
        query["cliente_id"] = cliente_id
    if status:
        query["status"] = status
    if cat3:
        query["cat3"] = clean_text(cat3).upper()
    elif cat2:
        query["cat2"] = clean_text(cat2).upper()
    if search:
        query["$or"] = [
            {"nome_produto": {"$regex": search, "$options": "i"}},
            {"codigo_interno": {"$regex": search, "$options": "i"}},
        ]

    skus = await db.skus.find(query, {"_id": 0}).sort("created_at", -1).to_list(5000)
    if skus:
        sample_ids = list({sku.get("amostra_id") for sku in skus if sku.get("amostra_id")})
        if sample_ids:
            approved_requests = await db.pd_requests.find(
                {
                    "tenant_id": user["tenant_id"],
                    "status": {"$in": ["APPROVED", "COMPLETED", "aprovado", "concluido"]},
                    "linked_amostra_id": {"$in": sample_ids},
                },
                {"_id": 0, "id": 1, "status": 1, "linked_amostra_id": 1, "linked_variacao_id": 1, "updated_at": 1},
            ).to_list(5000)
            approved_by_pair = {}
            approved_by_sample = {}
            for doc in approved_requests:
                sample_id = doc.get("linked_amostra_id")
                variation_id = doc.get("linked_variacao_id")
                if not sample_id:
                    continue
                if variation_id:
                    approved_by_pair[(sample_id, variation_id)] = doc
                approved_by_sample[sample_id] = doc

            enriched = []
            for sku in skus:
                approved = approved_by_pair.get((sku.get("amostra_id"), sku.get("amostra_variacao_id")))
                if not approved:
                    approved = approved_by_sample.get(sku.get("amostra_id"))
                stored_concluded = bool(sku.get("pd_concluido"))
                sku["pd_concluido"] = bool(approved) or stored_concluded
                if approved:
                    sku["pd_request_id"] = approved.get("id")
                    sku["pd_status"] = approved.get("status")
                elif stored_concluded:
                    sku["pd_status"] = sku.get("pd_status") or "concluido_fluxo_comercial"
                if not pd_concluidos or approved or stored_concluded:
                    enriched.append(sku)
            skus = enriched
        else:
            if pd_concluidos:
                skus = [sku for sku in skus if sku.get("pd_concluido")]
            else:
                for sku in skus:
                    sku["pd_concluido"] = bool(sku.get("pd_concluido"))

    # Regra de exibição: SKU nunca "pelado" — anexa nome do Produto-Pai (família) pra
    # cada SKU que já tiver o vínculo (apresentacao/volume ficam no próprio doc do SKU).
    pai_ids = list({s["produto_pai_id"] for s in skus if s.get("produto_pai_id")})
    if pai_ids:
        pais = await db.produtos_pai.find(
            {"tenant_id": user["tenant_id"], "id": {"$in": pai_ids}}, {"_id": 0, "id": 1, "nome": 1}
        ).to_list(len(pai_ids))
        pai_nome_by_id = {p["id"]: p["nome"] for p in pais}
        for s in skus:
            s["produto_pai_nome"] = pai_nome_by_id.get(s.get("produto_pai_id"))

    return skus


@crm_router.get("/skus/preview-code")
async def preview_sku_code(cliente_id: str, categoria: str, request: Request):
    """Return the code that would be generated for a new SKU (without consuming the sequence)."""
    user = await _get_current_user(request)
    cat2 = cat2_from_categoria(categoria)
    client = await db.crm_clients.find_one({"id": cliente_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    raw_cli3 = client.get("cli3") or client.get("nome_empresa", "")
    cli3 = normalise_cli3(raw_cli3)
    # Peek at next seq without incrementing (counters keyed as "name:tenant_id")
    counter_key = f"sku_{cat2}_{cli3}:{user['tenant_id']}"
    seq_doc = await db.counters.find_one({"_id": counter_key})
    next_seq = (seq_doc.get("seq", 0) if seq_doc else 0) + 1
    return {
        "codigo": f"{cat2}-{cli3}-{str(next_seq).zfill(4)}",
        "cat2": cat2,
        "cli3": cli3,
        "seq": next_seq,
        "cli3_source": "campo_cli3" if client.get("cli3") else "nome_empresa",
    }


@crm_router.get("/skus/{sku_id}")
async def get_sku(sku_id: str, request: Request):
    user = await _get_current_user(request)
    sku = await db.skus.find_one(
        {"id": sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU não encontrado")
    return sku


@crm_router.put("/skus/{sku_id}")
async def update_sku(sku_id: str, data: SKUUpdate, request: Request):
    """Limited update — SKU code is immutable (RN-SK-04), other fields are editable."""
    user = await _get_current_user(request)
    update_fields = {}

    if data.nome_produto is not None:
        update_fields["nome_produto"] = data.nome_produto
    if data.preco_unitario is not None:
        update_fields["preco_unitario"] = data.preco_unitario
    if data.preco_unitario_currency is not None:
        update_fields["preco_unitario_currency"] = data.preco_unitario_currency
    if data.moq is not None:
        update_fields["moq"] = data.moq
    if data.status is not None:
        if data.status not in ("ativo", "suspenso", "descontinuado"):
            raise HTTPException(status_code=400, detail="Status inválido")
        update_fields["status"] = data.status
    if data.anvisa_numero is not None:
        update_fields["anvisa.numero"] = data.anvisa_numero
    if data.anvisa_validade is not None:
        update_fields["anvisa.validade"] = data.anvisa_validade

    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    update_fields["updated_at"] = _now_iso()

    result = await db.skus.update_one(
        {"id": sku_id, "tenant_id": user["tenant_id"]},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="SKU não encontrado")

    sku = await db.skus.find_one({"id": sku_id}, {"_id": 0})
    return sku


@crm_router.post("/skus/{sku_id}/meta")
async def update_sku_meta(sku_id: str, data: SKUMetaUpdate, request: Request):
    """Update manual Meta un/h and ajuste percentual (RN-SK-05)."""
    user = await _get_current_user(request)
    sku = await db.skus.find_one({"id": sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not sku:
        raise HTTPException(status_code=404, detail="SKU não encontrado")

    now = _now_iso()
    updates = {}
    if data.meta_unh is not None:
        if data.meta_unh < 0:
            raise HTTPException(status_code=422, detail="meta_unh não pode ser negativa")
        updates["medias_producao.meta_unh"] = data.meta_unh
        updates["medias_producao.meta_set_by"] = user["name"]
        updates["medias_producao.meta_set_at"] = now
    if data.ajuste_percentual is not None:
        if not (-100 <= data.ajuste_percentual <= 100):
            raise HTTPException(status_code=422, detail="ajuste_percentual deve estar entre -100 e +100")
        updates["medias_producao.ajuste_percentual"] = data.ajuste_percentual
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    updates["updated_at"] = now
    await db.skus.update_one({"id": sku_id, "tenant_id": user["tenant_id"]}, {"$set": updates})
    return await db.skus.find_one({"id": sku_id}, {"_id": 0})


@crm_router.post("/skus/{sku_id}/descontinuar")
async def descontinuar_sku(sku_id: str, data: SKUDescontinuar, request: Request):
    """Mark SKU as discontinued with mandatory reason (RN-SK-03)."""
    user = await _get_current_user(request)
    sku = await db.skus.find_one({"id": sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not sku:
        raise HTTPException(status_code=404, detail="SKU não encontrado")
    if sku.get("status") == "descontinuado":
        raise HTTPException(status_code=400, detail="SKU já está descontinuado")
    if not data.motivo.strip():
        raise HTTPException(status_code=422, detail="Motivo obrigatório para descontinuar (RN-SK-03)")

    now = _now_iso()
    await db.skus.update_one(
        {"id": sku_id, "tenant_id": user["tenant_id"]},
        {"$set": {
            "status": "descontinuado",
            "descontinuado_motivo": data.motivo.strip(),
            "descontinuado_em": now,
            "descontinuado_por": user["name"],
            "updated_at": now,
        }}
    )
    return await db.skus.find_one({"id": sku_id}, {"_id": 0})


@crm_router.get("/skus/{sku_id}/saldo")
async def get_sku_saldo(sku_id: str, request: Request):
    """Return consolidated open balance (saldo aberto) view per order for a SKU."""
    user = await _get_current_user(request)
    sku = await db.skus.find_one({"id": sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0})
    if not sku:
        raise HTTPException(status_code=404, detail="SKU não encontrado")

    # Find all orders that contain this SKU's code
    codigo = sku.get("codigo_interno", "")
    orders_cursor = db.orders.find(
        {"tenant_id": user["tenant_id"], "items.codigo_kuryos": codigo},
        {"_id": 0}
    )
    orders = await orders_cursor.to_list(500)

    result = []
    for order in orders:
        items_for_sku = [it for it in (order.get("items") or []) if it.get("codigo_kuryos") == codigo]
        for item in items_for_sku:
            qtd_pedido = item.get("qtd", 0)
            # Find OPs for this order
            ops_cursor = db.ops.find(
                {"tenant_id": user["tenant_id"], "pedido_id": order["id"]},
                {"_id": 0}
            )
            ops = await ops_cursor.to_list(100)
            ops_info = []
            qtd_realizada_total = 0
            qtd_perda_total = 0
            for op in ops:
                qtd_apontada = sum(a.get("qtd_produzida", 0) for a in (op.get("apontamentos") or []))
                qtd_perda = sum(p.get("quantidade", 0) for p in (op.get("perdas") or []))
                qtd_realizada_total += qtd_apontada
                qtd_perda_total += qtd_perda
                # PCP slot for this OP
                pcp_slot = await db.pcp_programacao.find_one({"op_id": op["id"]}, {"_id": 0})
                ops_info.append({
                    "op_id": op["id"],
                    "numero_op": op.get("numero_op"),
                    "status": op.get("status"),
                    "qtd_planejada": op.get("items", [{}])[0].get("qtd", 0) if op.get("items") else 0,
                    "qtd_realizada": qtd_apontada,
                    "qtd_perda": qtd_perda,
                    "pcp_data_inicio": pcp_slot.get("data_inicio") if pcp_slot else None,
                    "pcp_linha": pcp_slot.get("linha_nome") if pcp_slot else None,
                    "pcp_status": pcp_slot.get("status") if pcp_slot else None,
                })
            saldo_aberto = max(qtd_pedido - qtd_realizada_total, 0)
            checklist_ok = all(
                (ci.get("status") == "recebido" or not ci.get("ativo"))
                for ci in (order.get("checklist_insumos") or [])
            )
            result.append({
                "pedido_id": order["id"],
                "numero_pedido": order.get("numero_pedido"),
                "cliente_nome": order.get("cliente", {}).get("nome"),
                "order_status": order.get("status"),
                "item_nome": item.get("item"),
                "qtd_pedido": qtd_pedido,
                "qtd_realizada": qtd_realizada_total,
                "qtd_perda": qtd_perda_total,
                "saldo_aberto": saldo_aberto,
                "checklist_insumos_ok": checklist_ok,
                "ops": ops_info,
            })
    return result


@crm_router.post("/skus/{sku_id}/orders")
async def add_order_to_sku(sku_id: str, data: OrderAdd, request: Request):
    """Add an order to SKU history and recalculate metrics"""
    user = await _get_current_user(request)
    sku = await db.skus.find_one(
        {"id": sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU não encontrado")

    now = _now_iso()
    order = {
        "id": _new_id(),
        "data_pedido": data.data_pedido,
        "quantidade": data.quantidade,
        "valor_total": data.valor_total,
        "observacao": data.observacao,
        "registrado_por": user["name"],
        "registrado_em": now,
    }

    # Calculate reorder frequency
    historico = sku.get("historico_pedidos", [])
    historico.append(order)

    freq = 0
    if len(historico) >= 2:
        dates = sorted([h["data_pedido"] for h in historico])
        try:
            date_objs = [datetime.fromisoformat(d.replace("Z", "+00:00")) if isinstance(d, str) else d for d in dates]
            if len(date_objs) >= 2:
                diffs = [(date_objs[i+1] - date_objs[i]).days for i in range(len(date_objs)-1)]
                freq = sum(diffs) / len(diffs) if diffs else 0
        except Exception:
            freq = 0

    await db.skus.update_one(
        {"id": sku_id},
        {
            "$push": {"historico_pedidos": order},
            "$set": {
                "data_ultimo_pedido": data.data_pedido,
                "frequencia_media_recompra_dias": round(freq),
                "updated_at": now,
            }
        }
    )

    updated = await db.skus.find_one({"id": sku_id}, {"_id": 0})
    return updated


# ======================================================================
#  PIPELINE P&D (Cards de desenvolvimento)
# ======================================================================

PD_STATUSES = ["solicitado", "em_desenvolvimento", "em_testes", "aguardando_aprovacao", "retrabalho_interno"]

PD_STATUS_LABELS = {
    "solicitado": "Aberto",
    "em_desenvolvimento": "Em Desenvolvimento",
    "em_testes": "Em Testes",
    "aguardando_aprovacao": "Aguardando Aprovação",
    "retrabalho_interno": "Retrabalho Interno"
}

# Mapeamento: Status P&D → Status CRM3 Variação (simplificado, retrocompatível)
PD_TO_CRM_STATUS_MAP = {
    "solicitado": "solicitada",
    "em_desenvolvimento": "em_elaboracao",
    "em_testes": None,  # Não muda CRM3, só adiciona ao histórico
    "aguardando_aprovacao": "enviada",
    "retrabalho_interno": "retrabalho"
}

# Mapeamento rico: Status P&D → (status_CRM_simplificado, label_visível_ao_comercial)
PD_CARD_STATUS_TO_CRM_DISPLAY = {
    "solicitado":           ("solicitada",    "Aguardando P&D"),
    "em_desenvolvimento":   ("em_elaboracao", "Em Desenvolvimento"),
    "em_testes":            ("em_elaboracao", "Em Testes"),
    "aguardando_aprovacao": ("enviada",       "Aguardando Aprovação CQ"),
    "retrabalho_interno":   ("retrabalho",    "Em Retrabalho"),
}

@crm_router.get("/pd/cards")
async def list_pd_cards(
    request: Request,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    """Listar cards do Pipeline P&D"""
    user = await _get_current_user(request)
    require_roles(user, PD_READ | COMERCIAL_FULL)
    query = {"tenant_id": user["tenant_id"]}
    
    if status:
        query["status_pd"] = status
    if search:
        query["$or"] = [
            {"numero_completo": {"$regex": search, "$options": "i"}},
            {"produto": {"$regex": search, "$options": "i"}},
            {"cliente": {"$regex": search, "$options": "i"}},
        ]
    
    cards = await db.pd_cards.find(query, {"_id": 0}).sort("created_at", -1).to_list(5000)
    return cards


@crm_router.get("/pd/cards/{card_id}")
async def get_pd_card(card_id: str, request: Request):
    """Obter detalhes de um card P&D"""
    user = await _get_current_user(request)
    require_roles(user, PD_READ | COMERCIAL_FULL)
    card = await db.pd_cards.find_one(
        {"id": card_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not card:
        raise HTTPException(status_code=404, detail="Card não encontrado")

    # Lazy: garante que existe um pd_request linkado para abrir a tela completa do PDDetail
    if not card.get("pd_request_id"):
        try:
            await _ensure_pd_request_for_card(card, user)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Lazy pd_request creation failed for card {card_id}: {exc}")

    # Buscar amostra e variação relacionadas
    if card.get("amostra_id"):
        sample = await db.crm_samples.find_one(
            {"id": card["amostra_id"]}, {"_id": 0}
        )
        if sample:
            card["amostra_completa"] = sample
            # Encontrar variação específica
            variacao = next((v for v in sample.get("variacoes", []) if v["id"] == card.get("amostra_variacao_id")), None)
            if variacao:
                card["variacao"] = variacao
    
    return card


@crm_router.post("/pd/cards/sync-all-to-crm")
async def sync_all_pd_cards_to_crm(request: Request):
    """Admin/lider_pd: re-sincroniza todos os pd_cards com suas variações CRM.
    Usar uma vez para corrigir dados inconsistentes já no banco.
    """
    user = await _get_current_user(request)
    require_roles(user, {"admin", "lider_pd"})

    tenant_id = user["tenant_id"]
    pd_cards = await db.pd_cards.find(
        {"tenant_id": tenant_id, "amostra_variacao_id": {"$exists": True}},
        {"_id": 0},
    ).to_list(5000)

    synced = 0
    errors = 0
    now = _now_iso()

    for card in pd_cards:
        try:
            status_pd = card.get("status_pd", "solicitado")
            crm_status, crm_label = PD_CARD_STATUS_TO_CRM_DISPLAY.get(
                status_pd,
                (PD_TO_CRM_STATUS_MAP.get(status_pd), PD_STATUS_LABELS.get(status_pd, status_pd)),
            )
            if not crm_status:
                continue
            result = await db.crm_samples.update_one(
                {
                    "id": card["amostra_id"],
                    "tenant_id": tenant_id,
                    "variacoes.id": card["amostra_variacao_id"],
                },
                {
                    "$set": {
                        "variacoes.$.status": crm_status,
                        "variacoes.$.status_pd_label": crm_label,
                        "variacoes.$.status_pd_raw": status_pd,
                        "variacoes.$.ultima_atualizacao_pd": now,
                    }
                },
            )
            if result.matched_count:
                synced += 1
        except Exception as exc:
            logger.error(f"sync-all error card {card.get('id')}: {exc}")
            errors += 1

    logger.info(f"sync-all-to-crm: {synced} synced, {errors} errors (tenant={tenant_id})")
    return {
        "synced": synced,
        "errors": errors,
        "total": len(pd_cards),
        "message": f"Sincronizados {synced} de {len(pd_cards)} cards",
    }


class PDCardMove(BaseModel):
    status: str
    observacao: str = ""

@crm_router.put("/pd/cards/{card_id}/move")
async def move_pd_card(card_id: str, data: PDCardMove, request: Request):
    """Mover card no Pipeline P&D e sincronizar com CRM (ERP v3.0: gera tasks de CQ)."""
    user = await _get_current_user(request)
    require_roles(user, PD_WRITE | QA_APPROVERS)
    
    card = await db.pd_cards.find_one(
        {"id": card_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not card:
        raise HTTPException(status_code=404, detail="Card não encontrado")
    
    old_status = card["status_pd"]
    new_status = data.status
    
    if new_status not in PD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status inválido: {new_status}")

    # ERP v3.0: blocking tasks (e.g., CQ approval before closing)
    await assert_no_blocking_tasks(
        tenant_id=user["tenant_id"],
        entity_type="pd_card",
        entity_id=card_id,
        target_stage=new_status,
    )

    # Bloqueio por insumos nao homologados / suspensos antes de aprovacao
    if new_status in ("aguardando_aprovacao",):
        from pd_routes import assert_pd_card_ready_for_approval
        await assert_pd_card_ready_for_approval(card_id, user["tenant_id"])

    now = _now_iso()
    
    # Atualizar card P&D
    await db.pd_cards.update_one(
        {"id": card_id},
        {
            "$set": {
                "status_pd": new_status,
                "updated_at": now
            },
            "$push": {
                "historico_movimentacoes": {
                    "de": old_status,
                    "para": new_status,
                    "data": now,
                    "usuario": user["name"],
                    "usuario_id": user["id"],
                    "observacao": data.observacao
                }
            }
        }
    )

    # ERP v3.0: trigger tasks (CQ approval, lab tests)
    new_tasks = await trigger_tasks_for_transition(
        entity_type="pd_card",
        entity_id=card_id,
        tenant_id=user["tenant_id"],
        old_stage=old_status,
        new_stage=new_status,
        user=user,
    )

    stability_study = None
    if new_status == "em_testes":
        from pd_routes import _ensure_stability_study_for_pd_card
        stability_study = await _ensure_stability_study_for_pd_card(
            {
                **card,
                "status_pd": new_status,
                "updated_at": now,
            },
            user,
        )

    # SINCRONIZAÇÃO: Atualizar status da variação no CRM (sentido único P&D → CRM)
    if card.get("amostra_id") and card.get("amostra_variacao_id"):
        crm_status, crm_label = PD_CARD_STATUS_TO_CRM_DISPLAY.get(
            new_status,
            (PD_TO_CRM_STATUS_MAP.get(new_status), PD_STATUS_LABELS.get(new_status, new_status))
        )
        test_patch, test_history = _sample_test_patch_for_pd_status(new_status, now)
        test_set_ops = {f"variacoes.$.{key}": value for key, value in test_patch.items()}

        if crm_status:
            # Atualiza status, label rico e histórico
            await db.crm_samples.update_one(
                {"id": card["amostra_id"], "variacoes.id": card["amostra_variacao_id"]},
                {
                    "$set": {
                        "variacoes.$.status": crm_status,
                        "variacoes.$.status_pd_label": crm_label,
                        "variacoes.$.status_pd_raw": new_status,
                        "variacoes.$.ultima_atualizacao_pd": now,
                        "variacoes.$.updated_at": now,
                        **test_set_ops,
                    },
                    "$push": {
                        "variacoes.$.historico_status": {
                            "de": "",
                            "para": crm_status,
                            "data": now,
                            "usuario": user["name"],
                            "usuario_id": user["id"],
                            "sincronizado_pd": True,
                            "status_pd": new_status,
                            "label_pd": crm_label,
                        }
                    }
                }
            )
            logger.info(f"Sincronizado P&D→CRM: Card {card_id} ({new_status}) → Variação {card['amostra_variacao_id']} ({crm_status} / {crm_label})")
        else:
            # Apenas adiciona ao histórico sem mudar status (ex: em_testes sem mapeamento direto)
            crm_label_obs = PD_CARD_STATUS_TO_CRM_DISPLAY.get(new_status, (None, PD_STATUS_LABELS.get(new_status, new_status)))[1]
            await db.crm_samples.update_one(
                {"id": card["amostra_id"], "variacoes.id": card["amostra_variacao_id"]},
                {
                    "$set": {
                        "variacoes.$.status_pd_label": crm_label_obs,
                        "variacoes.$.status_pd_raw": new_status,
                        "variacoes.$.ultima_atualizacao_pd": now,
                        "variacoes.$.updated_at": now,
                        **test_set_ops,
                    },
                    "$push": {
                        "variacoes.$.historico_status": {
                            "de": "",
                            "para": "",
                            "data": now,
                            "usuario": user["name"],
                            "usuario_id": user["id"],
                            "sincronizado_pd": True,
                            "status_pd": new_status,
                            "observacao": f"P&D movido para: {crm_label_obs}",
                        }
                    }
                }
            )
            logger.info(f"Histórico P&D→CRM: Card {card_id} ({new_status} / {crm_label_obs}) registrado na variação {card['amostra_variacao_id']}")

    project_sync = _pd_status_to_project_stage_sync(new_status, now)
    if project_sync:
        project_id = card.get("projeto_id")
        if not project_id and card.get("amostra_id"):
            linked_sample = await db.crm_samples.find_one(
                {"id": card["amostra_id"], "tenant_id": user["tenant_id"]},
                {"_id": 0, "projeto_id": 1},
            )
            project_id = (linked_sample or {}).get("projeto_id")
        if project_id:
            target_stage, movement_source, extra_set = project_sync
            await _advance_project_stage_if_needed(
                project_id,
                target_stage,
                user,
                movement_source=movement_source,
                extra_set=extra_set,
            )

    updated = await db.pd_cards.find_one({"id": card_id}, {"_id": 0})
    await _broadcast_pd_card_update(user["tenant_id"], updated, old_status, new_status)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="pd_card_moved",
        entity_type="pd_card",
        entity_id=card_id,
        before={"status_pd": old_status},
        after={"status_pd": new_status, "observacao": data.observacao},
        metadata={
            "amostra_variacao_id": card.get("amostra_variacao_id"),
            "tasks_generated": [t["id"] for t in new_tasks],
        },
    )

    return {
        "card": updated,
        "from_status": PD_STATUS_LABELS.get(old_status, old_status),
        "to_status": PD_STATUS_LABELS.get(new_status, new_status),
        "synced_to_crm": True,
        "stability_study": stability_study,
        "tasks_generated": new_tasks,
    }


class PDCardUpdate(BaseModel):
    responsavel_pd: Optional[str] = None
    prazo_prometido: Optional[str] = None
    observacoes_especificas: Optional[str] = None

@crm_router.put("/pd/cards/{card_id}")
async def update_pd_card(card_id: str, data: PDCardUpdate, request: Request):
    """Atualizar informações de um card P&D"""
    user = await _get_current_user(request)
    require_roles(user, PD_WRITE)
    
    update_fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    update_fields["updated_at"] = _now_iso()
    
    result = await db.pd_cards.update_one(
        {"id": card_id, "tenant_id": user["tenant_id"]},
        {"$set": update_fields}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Card não encontrado")
    
    card = await db.pd_cards.find_one({"id": card_id}, {"_id": 0})
    return card


# ======================================================================
#  ALERTS
# ======================================================================

@crm_router.get("/alerts")
async def list_alerts(
    request: Request,
    status: Optional[str] = None,
    tipo: Optional[str] = None,
):
    user = await _get_current_user(request)
    query = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    if tipo:
        query["tipo"] = tipo

    alerts = await db.crm_alerts.find(query, {"_id": 0}).sort("data_criacao", -1).to_list(500)
    return alerts


@crm_router.put("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str, request: Request):
    user = await _get_current_user(request)
    result = await db.crm_alerts.update_one(
        {"id": alert_id, "tenant_id": user["tenant_id"]},
        {"$set": {"status": "lido"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return {"message": "Alerta marcado como lido"}


@crm_router.put("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, data: AlertResolve, request: Request):
    user = await _get_current_user(request)
    now = _now_iso()
    result = await db.crm_alerts.update_one(
        {"id": alert_id, "tenant_id": user["tenant_id"]},
        {"$set": {
            "status": "resolvido",
            "resolved_at": now,
            "resolved_by": user["id"],
            "resolved_comment": data.comment,
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return {"message": "Alerta resolvido"}


@crm_router.post("/alerts/check")
async def trigger_alert_check(request: Request):
    """Manual trigger for alert check"""
    user = await _get_current_user(request)
    count = await check_alerts_for_tenant(user["tenant_id"])
    return {"message": f"{count} alerta(s) gerado(s)", "count": count}


@crm_router.post("/follow-up/schedule")
async def schedule_follow_up(data: FollowUpSchedule, request: Request):
    """RN-FU-03: Agendamento de follow-up manual com data/hora"""
    user = await _get_current_user(request)
    
    # Validar que o cliente existe
    client = await db.crm_clients.find_one(
        {"id": data.client_id, "tenant_id": user["tenant_id"]},
        {"_id": 0, "nome_empresa": 1}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    
    # Validar data
    try:
        follow_up_date = datetime.fromisoformat(data.data_follow_up.replace("Z", "+00:00"))
        if follow_up_date < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Data de follow-up deve ser futura")
    except ValueError:
        raise HTTPException(status_code=400, detail="Data inválida. Use formato ISO 8601")
    
    # Criar tarefa pendente de follow-up
    task_id = _new_id()
    task = {
        "id": task_id,
        "tenant_id": user["tenant_id"],
        "tipo": "follow_up_manual",
        "entidade_tipo": "client",
        "entidade_ref": data.client_id,
        "entidade_nome": client.get("nome_empresa", ""),
        "titulo": f"Follow-up agendado: {client.get('nome_empresa', '')}",
        "descricao": data.observacao or "Follow-up manual agendado",
        "data_agendada": data.data_follow_up,
        "status": "pendente",
        "responsavel": user["id"],
        "criado_por": user["id"],
        "criado_por_nome": user.get("name", ""),
        "data_criacao": _now_iso(),
    }
    
    await db.crm_tasks.insert_one(task)
    
    return {
        "message": "Follow-up agendado com sucesso",
        "task": task
    }


@crm_router.get("/follow-up/scheduled")
async def list_scheduled_follow_ups(request: Request):
    """Listar follow-ups agendados"""
    user = await _get_current_user(request)
    
    tasks = await db.crm_tasks.find(
        {"tenant_id": user["tenant_id"], "tipo": "follow_up_manual", "status": "pendente"},
        {"_id": 0}
    ).sort("data_agendada", 1).to_list(500)
    
    return tasks


async def check_alerts_for_tenant(tenant_id: str) -> int:
    """Check and generate alerts for a tenant"""
    now = datetime.now(timezone.utc)
    created_count = 0

    try:
        # ALERT_001: Sample in "enviada" > 7 days
        samples_enviadas = await db.crm_samples.find(
            {"tenant_id": tenant_id, "stage": "enviada"}, {"_id": 0}
        ).to_list(1000)
        for s in samples_enviadas:
            updated = s.get("updated_at") or s.get("created_at", "")
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if (now - dt).days > 7:
                    exists = await db.crm_alerts.find_one({
                        "tenant_id": tenant_id, "tipo": "ALERT_001",
                        "entidade_ref": s["id"], "status": {"$ne": "resolvido"}
                    })
                    if not exists:
                        await db.crm_alerts.insert_one({
                            "id": _new_id(), "tenant_id": tenant_id,
                            "tipo": "ALERT_001",
                            "entidade_ref": s["id"],
                            "entidade_tipo": "sample",
                            "entidade_nome": s.get("nome_amostra", ""),
                            "mensagem": f"Amostra '{s.get('nome_amostra', '')}' está em 'Enviada' há mais de 7 dias sem movimentação.",
                            "data_criacao": _now_iso(),
                            "status": "pendente",
                            "responsavel": s.get("responsavel_pd") or s.get("created_by", ""),
                        })
                        created_count += 1
            except Exception:
                pass

        # ALERT_002: Client in "negociacao" > 30 days
        clients_neg = await db.crm_clients.find(
            {"tenant_id": tenant_id, "stage": "negociacao"}, {"_id": 0}
        ).to_list(1000)
        for c in clients_neg:
            updated = c.get("updated_at") or c.get("created_at", "")
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if (now - dt).days > 30:
                    exists = await db.crm_alerts.find_one({
                        "tenant_id": tenant_id, "tipo": "ALERT_002",
                        "entidade_ref": c["id"], "status": {"$ne": "resolvido"}
                    })
                    if not exists:
                        await db.crm_alerts.insert_one({
                            "id": _new_id(), "tenant_id": tenant_id,
                            "tipo": "ALERT_002",
                            "entidade_ref": c["id"],
                            "entidade_tipo": "client",
                            "entidade_nome": c.get("nome_empresa", ""),
                            "mensagem": f"Cliente '{c.get('nome_empresa', '')}' está em 'Negociação' há mais de 30 dias.",
                            "data_criacao": _now_iso(),
                            "status": "pendente",
                            "responsavel": c.get("created_by", ""),
                        })
                        created_count += 1
            except Exception:
                pass

        # ALERT_003: Active SKU without order > 60 days
        active_skus = await db.skus.find(
            {"tenant_id": tenant_id, "status": "ativo"}, {"_id": 0}
        ).to_list(1000)
        clients_perdidos = await db.crm_clients.find(
            {"tenant_id": tenant_id, "stage": "cliente_perdido"}, {"_id": 0}
        ).to_list(1000)
        for c in clients_perdidos:
            ref_date = c.get("updated_at") or c.get("created_at", "")
            try:
                dt = datetime.fromisoformat(str(ref_date).replace("Z", "+00:00"))
                if (now - dt).days >= 90:
                    exists = await db.crm_alerts.find_one({
                        "tenant_id": tenant_id, "tipo": "ALERT_008",
                        "entidade_ref": c["id"], "status": {"$ne": "resolvido"}
                    })
                    if not exists:
                        await db.crm_alerts.insert_one({
                            "id": _new_id(), "tenant_id": tenant_id,
                            "tipo": "ALERT_008",
                            "entidade_ref": c["id"],
                            "entidade_tipo": "client",
                            "entidade_nome": c.get("nome_empresa", ""),
                            "mensagem": f"Cliente perdido '{c.get('nome_empresa', '')}' pode ser reativado após 90 dias.",
                            "data_criacao": _now_iso(),
                            "status": "pendente",
                            "responsavel": c.get("created_by", ""),
                        })
                        created_count += 1
            except Exception:
                pass

        for sku in active_skus:
            last_order = sku.get("data_ultimo_pedido")
            ref_date = sku.get("created_at", "")
            if last_order:
                ref_date = last_order
            try:
                dt = datetime.fromisoformat(str(ref_date).replace("Z", "+00:00"))
                if (now - dt).days > 60:
                    exists = await db.crm_alerts.find_one({
                        "tenant_id": tenant_id, "tipo": "ALERT_003",
                        "entidade_ref": sku["id"], "status": {"$ne": "resolvido"}
                    })
                    if not exists:
                        await db.crm_alerts.insert_one({
                            "id": _new_id(), "tenant_id": tenant_id,
                            "tipo": "ALERT_003",
                            "entidade_ref": sku["id"],
                            "entidade_tipo": "sku",
                            "entidade_nome": f"{sku.get('codigo_interno', '')} - {sku.get('nome_produto', '')}",
                            "mensagem": f"SKU '{sku.get('codigo_interno', '')}' ativo sem pedido registrado há mais de 60 dias.",
                            "data_criacao": _now_iso(),
                            "status": "pendente",
                            "responsavel": "",
                        })
                        created_count += 1
            except Exception:
                pass

        # ALERT_004: Client in "cliente_fechado" without new project > 90 days
        clients_fechado = await db.crm_clients.find(
            {"tenant_id": tenant_id, "stage": "cliente_fechado"}, {"_id": 0}
        ).to_list(1000)
        for c in clients_fechado:
            # Check last project creation date
            last_proj = await db.crm_projects.find_one(
                {"cliente_id": c["id"], "tenant_id": tenant_id},
                sort=[("created_at", -1)]
            )
            ref_date = c.get("updated_at") or c.get("created_at", "")
            if last_proj:
                ref_date = last_proj.get("created_at", ref_date)
            try:
                dt = datetime.fromisoformat(str(ref_date).replace("Z", "+00:00"))
                if (now - dt).days > 90:
                    exists = await db.crm_alerts.find_one({
                        "tenant_id": tenant_id, "tipo": "ALERT_004",
                        "entidade_ref": c["id"], "status": {"$ne": "resolvido"}
                    })
                    if not exists:
                        await db.crm_alerts.insert_one({
                            "id": _new_id(), "tenant_id": tenant_id,
                            "tipo": "ALERT_004",
                            "entidade_ref": c["id"],
                            "entidade_tipo": "client",
                            "entidade_nome": c.get("nome_empresa", ""),
                            "mensagem": f"Cliente fechado '{c.get('nome_empresa', '')}' sem novo projeto há mais de 90 dias.",
                            "data_criacao": _now_iso(),
                            "status": "pendente",
                            "responsavel": c.get("created_by", ""),
                        })
                        created_count += 1
            except Exception:
                pass

        # ALERT_005: SKU ANVISA expiring in ≤ 60 days
        for sku in active_skus:
            anvisa_val = sku.get("anvisa", {}).get("validade")
            if anvisa_val:
                try:
                    dt = datetime.fromisoformat(str(anvisa_val).replace("Z", "+00:00"))
                    if 0 <= (dt - now).days <= 60:
                        exists = await db.crm_alerts.find_one({
                            "tenant_id": tenant_id, "tipo": "ALERT_005",
                            "entidade_ref": sku["id"], "status": {"$ne": "resolvido"}
                        })
                        if not exists:
                            await db.crm_alerts.insert_one({
                                "id": _new_id(), "tenant_id": tenant_id,
                                "tipo": "ALERT_005",
                                "entidade_ref": sku["id"],
                                "entidade_tipo": "sku",
                                "entidade_nome": f"{sku.get('codigo_interno', '')} - {sku.get('nome_produto', '')}",
                                "mensagem": f"ANVISA do SKU '{sku.get('codigo_interno', '')}' vence em {(dt - now).days} dias.",
                                "data_criacao": _now_iso(),
                                "status": "pendente",
                                "responsavel": "",
                            })
                            created_count += 1
                except Exception:
                    pass

        # ALERT_006: previsao_segundo_pedido D-7
        clients_with_previsao = await db.crm_clients.find(
            {"tenant_id": tenant_id, "previsao_segundo_pedido": {"$ne": None}},
            {"_id": 0}
        ).to_list(1000)
        for c in clients_with_previsao:
            previsao = c.get("previsao_segundo_pedido")
            if previsao:
                try:
                    dt = datetime.fromisoformat(str(previsao).replace("Z", "+00:00"))
                    days_until = (dt - now).days
                    if 0 <= days_until <= 7:
                        exists = await db.crm_alerts.find_one({
                            "tenant_id": tenant_id, "tipo": "ALERT_006",
                            "entidade_ref": c["id"], "status": {"$ne": "resolvido"}
                        })
                        if not exists:
                            await db.crm_alerts.insert_one({
                                "id": _new_id(), "tenant_id": tenant_id,
                                "tipo": "ALERT_006",
                                "entidade_ref": c["id"],
                                "entidade_tipo": "client",
                                "entidade_nome": c.get("nome_empresa", ""),
                                "mensagem": f"Previsão de segundo pedido de '{c.get('nome_empresa', '')}' em {days_until} dia(s).",
                                "data_criacao": _now_iso(),
                                "status": "pendente",
                                "responsavel": c.get("created_by", ""),
                            })
                            created_count += 1
                except Exception:
                    pass

        # ALERT_007: Variação em "solicitada" sem P&D aceitar > 2 dias úteis
        samples_with_variacoes = await db.crm_samples.find(
            {"tenant_id": tenant_id, "variacoes": {"$exists": True, "$ne": []}},
            {"_id": 0}
        ).to_list(1000)
        
        for sample in samples_with_variacoes:
            for variacao in sample.get("variacoes", []):
                if variacao.get("status") == "solicitada":
                    # Verificar se tem card P&D associado
                    pd_card = await db.pd_cards.find_one({
                        "amostra_variacao_id": variacao["id"],
                        "status_pd": "solicitado"
                    })
                    
                    if pd_card:
                        created = pd_card.get("created_at", "")
                        try:
                            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            # Calcular dias úteis (aproximação simples: dias corridos * 0.7)
                            days_elapsed = (now - dt).days
                            if days_elapsed > 2:
                                exists = await db.crm_alerts.find_one({
                                    "tenant_id": tenant_id,
                                    "tipo": "ALERT_007",
                                    "entidade_ref": variacao["id"],
                                    "status": {"$ne": "resolvido"}
                                })
                                if not exists:
                                    await db.crm_alerts.insert_one({
                                        "id": _new_id(),
                                        "tenant_id": tenant_id,
                                        "tipo": "ALERT_007",
                                        "entidade_ref": variacao["id"],
                                        "entidade_tipo": "variacao",
                                        "entidade_nome": f"{sample.get('nome_produto', '')} - {variacao.get('codigo', '')}",
                                        "mensagem": f"Variação '{variacao.get('codigo', '')}' está em 'Solicitada' há {days_elapsed} dias sem aceite do P&D.",
                                        "data_criacao": _now_iso(),
                                        "status": "pendente",
                                        "responsavel": sample.get("responsavel_pd", ""),
                                    })
                                    created_count += 1
                        except Exception:
                            pass

        # RN-FU-01: Follow-up automático por etapa (alerta quando cliente sem interação por X dias)
        # Prazo configurável: Prospecção 3d / Qualificado 5d / Projeto em Discussão 7d / Negociação 5d
        for stage, prazo_dias in FOLLOW_UP_PRAZOS.items():
            if stage in ["cliente_fechado", "cliente_perdido"]:
                continue  # Não gera follow-up para etapas finais
            
            clients_in_stage = await db.crm_clients.find(
                {"tenant_id": tenant_id, "stage": stage}, {"_id": 0}
            ).to_list(1000)
            
            for c in clients_in_stage:
                # Usar a data da última interação (updated_at ou última movimentação)
                last_interaction = c.get("updated_at") or c.get("created_at", "")
                historico = c.get("historico_movimentacoes", [])
                if historico:
                    last_interaction = historico[-1].get("data", last_interaction)
                
                try:
                    dt = datetime.fromisoformat(str(last_interaction).replace("Z", "+00:00"))
                    days_without_interaction = (now - dt).days
                    
                    if days_without_interaction > prazo_dias:
                        exists = await db.crm_alerts.find_one({
                            "tenant_id": tenant_id,
                            "tipo": "FOLLOW_UP",
                            "entidade_ref": c["id"],
                            "status": {"$ne": "resolvido"}
                        })
                        if not exists:
                            stage_label = STAGE_LABELS.get(stage, stage)
                            await db.crm_alerts.insert_one({
                                "id": _new_id(),
                                "tenant_id": tenant_id,
                                "tipo": "FOLLOW_UP",
                                "entidade_ref": c["id"],
                                "entidade_tipo": "client",
                                "entidade_nome": c.get("nome_empresa", ""),
                                "mensagem": f"Cliente '{c.get('nome_empresa', '')}' está em '{stage_label}' há {days_without_interaction} dias sem interação (prazo: {prazo_dias} dias).",
                                "data_criacao": _now_iso(),
                                "status": "pendente",
                                "responsavel": c.get("responsavel_comercial") or c.get("created_by", ""),
                            })
                            created_count += 1
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Alert check error for tenant {tenant_id}: {e}")

    return created_count


async def run_alert_scheduler():
    """Background task that checks alerts every hour for all tenants"""
    await asyncio.sleep(30)  # Wait 30s after startup
    while True:
        try:
            tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(500)
            total = 0
            for t in tenants:
                count = await check_alerts_for_tenant(t["id"])
                total += count
            if total > 0:
                logger.info(f"Alert scheduler: created {total} alerts across {len(tenants)} tenants")
        except Exception as e:
            logger.error(f"Alert scheduler error: {e}")
        await asyncio.sleep(3600)  # Every hour


# ======================================================================
#  DASHBOARD & REPORTS
# ======================================================================

@crm_router.get("/dashboard")
async def crm_dashboard(request: Request):
    user = await _get_current_user(request)
    tid = user["tenant_id"]

    # Funnel: count per stage
    funnel = []
    for stage in CLIENT_STAGES:
        count = await db.crm_clients.count_documents({"tenant_id": tid, "stage": stage})
        funnel.append({"stage": stage, "label": STAGE_LABELS.get(stage, stage), "count": count})

    # Conversion rates
    total_clients = sum(s["count"] for s in funnel)
    for s in funnel:
        s["percentage"] = round((s["count"] / total_clients * 100), 1) if total_clients > 0 else 0

    # Metrics
    active_clients = await db.crm_clients.count_documents({
        "tenant_id": tid,
        "stage": {"$nin": ["cliente_perdido"]}
    })
    samples_in_progress = await db.crm_samples.count_documents({
        "tenant_id": tid,
        "stage": {"$in": ["solicitada", "em_elaboracao", "retrabalho", "enviada"]}
    })
    active_skus = await db.skus.count_documents({"tenant_id": tid, "status": "ativo"})
    pending_alerts = await db.crm_alerts.count_documents({"tenant_id": tid, "status": "pendente"})
    total_projects = await db.crm_projects.count_documents({"tenant_id": tid})

    # Today's alerts
    today_alerts = await db.crm_alerts.find(
        {"tenant_id": tid, "status": "pendente"},
        {"_id": 0}
    ).sort("data_criacao", -1).to_list(20)

    return {
        "funnel": funnel,
        "metrics": {
            "total_clients": total_clients,
            "active_clients": active_clients,
            "total_projects": total_projects,
            "samples_in_progress": samples_in_progress,
            "active_skus": active_skus,
            "pending_alerts": pending_alerts,
        },
        "today_alerts": today_alerts,
    }


@crm_router.get("/reports/client/{client_id}")
async def client_report(client_id: str, request: Request):
    user = await _get_current_user(request)
    client = await db.crm_clients.find_one(
        {"id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # SKUs linked to this client
    skus = await db.skus.find(
        {"cliente_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).to_list(500)

    # Aggregate orders across all SKUs
    all_orders = []
    for sku in skus:
        for order in sku.get("historico_pedidos", []):
            order["sku_codigo"] = sku["codigo_interno"]
            order["sku_nome"] = sku["nome_produto"]
            all_orders.append(order)

    total_orders = len(all_orders)
    total_value = sum(o.get("valor_total", 0) for o in all_orders)
    quantities = [o.get("quantidade", 0) for o in all_orders]

    avg_quantity = sum(quantities) / len(quantities) if quantities else 0
    max_quantity = max(quantities) if quantities else 0
    min_quantity = min(quantities) if quantities else 0

    # Last order
    last_order = None
    if all_orders:
        sorted_orders = sorted(all_orders, key=lambda x: x.get("data_pedido", ""), reverse=True)
        last_order = sorted_orders[0]

    # Reorder frequency (average across SKUs)
    freqs = [s.get("frequencia_media_recompra_dias", 0) for s in skus if s.get("frequencia_media_recompra_dias", 0) > 0]
    avg_freq = sum(freqs) / len(freqs) if freqs else 0

    # Projects
    projects = await db.crm_projects.find(
        {"cliente_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    # Samples
    samples = await db.crm_samples.find(
        {"cliente_id": client_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    return {
        "client": client,
        "orders": {
            "total_orders": total_orders,
            "total_value": total_value,
            "last_order": last_order,
            "avg_quantity": round(avg_quantity, 1),
            "max_quantity": max_quantity,
            "min_quantity": min_quantity,
            "avg_reorder_frequency_days": round(avg_freq),
        },
        "skus_ativos": [s for s in skus if s.get("status") == "ativo"],
        "all_skus": skus,
        "projects": projects,
        "samples": samples,
        "timeline": client.get("historico_movimentacoes", []),
    }


@crm_router.get("/reports/sku/{sku_id}")
async def sku_report(sku_id: str, request: Request):
    user = await _get_current_user(request)
    sku = await db.skus.find_one(
        {"id": sku_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU não encontrado")

    orders = sku.get("historico_pedidos", [])
    total_produced = sum(o.get("quantidade", 0) for o in orders)
    total_orders = len(orders)

    # Last production date
    last_production = None
    if orders:
        sorted_orders = sorted(orders, key=lambda x: x.get("data_pedido", ""), reverse=True)
        last_production = sorted_orders[0].get("data_pedido")

    # Find all clients that have this SKU (via amostras_aprovadas or skus_confirmados)
    clients_with_sku = await db.crm_clients.find(
        {
            "tenant_id": user["tenant_id"],
            "$or": [
                {"amostras_aprovadas": sku_id},
                {"skus_confirmados": sku_id},
            ]
        },
        {"_id": 0, "id": 1, "nome_empresa": 1}
    ).to_list(100)

    # Also check via the direct cliente_id
    main_client = await db.crm_clients.find_one(
        {"id": sku["cliente_id"]}, {"_id": 0, "id": 1, "nome_empresa": 1}
    )

    all_client_ids = set(c["id"] for c in clients_with_sku)
    if main_client and main_client["id"] not in all_client_ids:
        clients_with_sku.append(main_client)

    # ANVISA status
    anvisa = sku.get("anvisa", {})
    anvisa_status = "N/A"
    if anvisa.get("numero"):
        if anvisa.get("validade"):
            try:
                val_dt = datetime.fromisoformat(str(anvisa["validade"]).replace("Z", "+00:00"))
                days_left = (val_dt - datetime.now(timezone.utc)).days
                if days_left < 0:
                    anvisa_status = "Vencido"
                elif days_left <= 60:
                    anvisa_status = f"Vence em {days_left} dias"
                else:
                    anvisa_status = "Válido"
            except Exception:
                anvisa_status = "Válido"
        else:
            anvisa_status = "Sem validade"

    return {
        "sku": sku,
        "last_production_date": last_production,
        "total_produced": total_produced,
        "total_orders": total_orders,
        "order_frequency_days": sku.get("frequencia_media_recompra_dias", 0),
        "clients": clients_with_sku,
        "anvisa_status": anvisa_status,
        "orders": orders,
    }


# ======================================================================
#  CRM CONFIG — Customizable Columns & Fields (Pipefy-style)
# ======================================================================

DEFAULT_CRM_COLUMNS = {
    "clients": [
        {"key": "prospeccao", "label": "Prospecção", "color": "bg-blue-500", "order": 0, "is_system": True},
        {"key": "qualificado", "label": "Qualificado", "color": "bg-cyan-500", "order": 1, "is_system": True},
        {"key": "projeto_em_discussao", "label": "Projeto em Discussão", "color": "bg-violet-500", "order": 2, "is_system": True},
        {"key": "negociacao", "label": "Negociação", "color": "bg-amber-500", "order": 3, "is_system": True},
        {"key": "cliente_fechado", "label": "Cliente Fechado", "color": "bg-emerald-500", "order": 4, "is_system": True},
        {"key": "cliente_perdido", "label": "Cliente Perdido", "color": "bg-red-500", "order": 5, "is_system": True},
    ],
    "projects": [
        {"key": "projeto_em_discussao", "label": "Projeto em Discussão", "color": "bg-violet-500", "order": 0, "is_system": True},
        {"key": "amostras", "label": "Amostras", "color": "bg-emerald-500", "order": 1, "is_system": True},
    ],
    "samples": [
        {"key": "solicitada", "label": "Solicitada", "color": "bg-slate-400", "order": 0, "is_system": True},
        {"key": "em_elaboracao", "label": "Em Elaboração", "color": "bg-blue-500", "order": 1, "is_system": True},
        {"key": "retrabalho", "label": "Retrabalho", "color": "bg-amber-500", "order": 2, "is_system": True},
        {"key": "enviada", "label": "Enviada", "color": "bg-cyan-500", "order": 3, "is_system": True},
        {"key": "aprovada", "label": "Aprovada", "color": "bg-emerald-500", "order": 4, "is_system": True},
        {"key": "reprovada", "label": "Reprovada", "color": "bg-red-500", "order": 5, "is_system": True},
    ],
}

FIELD_TYPES = ["text", "number", "date", "select", "textarea", "boolean", "email", "phone"]


class CRMColumnCreate(BaseModel):
    crm_type: str
    label: str
    color: str = "bg-gray-500"

class CRMColumnUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None

class CRMColumnReorder(BaseModel):
    column_ids: List[str]

class CRMFieldCreate(BaseModel):
    column_id: str
    label: str
    type: str = "text"
    required: bool = False
    options: List[str] = []

class CRMFieldUpdate(BaseModel):
    label: Optional[str] = None
    type: Optional[str] = None
    required: Optional[bool] = None
    options: Optional[List[str]] = None


async def _ensure_crm_config(tenant_id: str, crm_type: str):
    """Seed default CRM config if not exists"""
    existing = await db.crm_column_configs.find_one({"tenant_id": tenant_id, "crm_type": crm_type})
    if existing:
        return

    defaults = DEFAULT_CRM_COLUMNS.get(crm_type, [])
    for col_def in defaults:
        col_id = _new_id()
        await db.crm_column_configs.insert_one({
            "id": col_id,
            "tenant_id": tenant_id,
            "crm_type": crm_type,
            "key": col_def["key"],
            "label": col_def["label"],
            "color": col_def["color"],
            "order": col_def["order"],
            "is_system": col_def.get("is_system", False),
            "created_at": _now_iso(),
        })
    logger.info(f"Seeded CRM config for {crm_type} tenant {tenant_id}")


# ======================================================================
#  LEAD SOURCES CONFIG (CRM-12: configurable canal_origem)
# ======================================================================

class LeadSourceCreate(BaseModel):
    nome: str
    valor: str
    grupo: str = ""
    ativo: bool = True

class LeadSourceUpdate(BaseModel):
    nome: Optional[str] = None
    ativo: Optional[bool] = None
    grupo: Optional[str] = None


async def _get_valid_lead_sources(tenant_id: str) -> list:
    """Returns valid valor slugs: hardcoded defaults plus any DB-added sources."""
    sources = await db.lead_sources.find(
        {"tenant_id": tenant_id, "ativo": True}, {"_id": 0, "valor": 1}
    ).to_list(200)
    # DB entries EXTEND the hardcoded list — never replace it.
    # This ensures existing clients don't break if someone adds a custom channel.
    combined = list(CANAL_ORIGEM_OPTIONS)
    for s in sources:
        if s["valor"] not in combined:
            combined.append(s["valor"])
    return combined


@crm_router.get("/config/lead-sources")
async def list_lead_sources(request: Request):
    user = await _get_current_user(request)
    sources = await db.lead_sources.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("grupo", 1).to_list(200)
    if not sources:
        # Bootstrap from hardcoded list on first access
        return [
            {"id": v, "valor": v, "nome": v.replace("_", " ").title(), "grupo": _slug_to_group(v), "ativo": True}
            for v in CANAL_ORIGEM_OPTIONS
        ]
    return sources


def _slug_to_group(valor: str) -> str:
    for group, members in CANAL_ORIGEM_GROUPS.items():
        if valor in members:
            return group
    return "outros"


@crm_router.post("/config/lead-sources")
async def create_lead_source(body: LeadSourceCreate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, ADMIN_ONLY)
    existing = await db.lead_sources.find_one({"tenant_id": user["tenant_id"], "valor": body.valor})
    if existing:
        raise HTTPException(status_code=409, detail="Já existe uma fonte com esse valor/slug")
    doc = {
        "id": body.valor,
        "valor": body.valor,
        "nome": body.nome.strip(),
        "grupo": body.grupo.strip(),
        "ativo": body.ativo,
        "tenant_id": user["tenant_id"],
        "created_at": _now_iso(),
    }
    await db.lead_sources.insert_one(doc)
    doc.pop("_id", None)
    return doc


@crm_router.patch("/config/lead-sources/{source_id}")
async def update_lead_source(source_id: str, body: LeadSourceUpdate, request: Request):
    user = await _get_current_user(request)
    require_roles(user, ADMIN_ONLY)
    source = await db.lead_sources.find_one({"tenant_id": user["tenant_id"], "id": source_id})
    if not source:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    # Cannot deactivate if any client still uses this canal_origem
    if body.ativo is False and source.get("ativo", True):
        in_use = await db.crm_clients.find_one(
            {"tenant_id": user["tenant_id"], "canal_origem": source_id}
        )
        if in_use:
            raise HTTPException(
                status_code=409,
                detail="Não é possível desativar: há clientes usando este canal de origem"
            )
    update: dict = {}
    if body.nome is not None:
        update["nome"] = body.nome.strip()
    if body.ativo is not None:
        update["ativo"] = body.ativo
    if body.grupo is not None:
        update["grupo"] = body.grupo.strip()
    if update:
        await db.lead_sources.update_one({"tenant_id": user["tenant_id"], "id": source_id}, {"$set": update})
    return {"ok": True}


# ======================================================================
#  CONSTANTS ENDPOINT (PRD Lists)
# ======================================================================

@crm_router.get("/constants")
async def get_crm_constants(request: Request):
    """Retorna todas as constantes do PRD para o frontend"""
    user = await _get_current_user(request)
    # Use DB lead sources when available, else fallback to hardcoded
    db_sources = await db.lead_sources.find(
        {"tenant_id": user["tenant_id"], "ativo": True}, {"_id": 0}
    ).sort("grupo", 1).to_list(200)
    if db_sources:
        canal_origem_list = [s["valor"] for s in db_sources]
        canal_origem_groups: dict = {}
        for s in db_sources:
            g = s.get("grupo", "outros") or "outros"
            canal_origem_groups.setdefault(g, []).append(s["valor"])
    else:
        canal_origem_list = CANAL_ORIGEM_OPTIONS
        canal_origem_groups = CANAL_ORIGEM_GROUPS

    return {
        "canal_origem": canal_origem_list,
        "canal_origem_grupos": canal_origem_groups,
        "categoria_interesse": CATEGORIA_INTERESSE_OPTIONS,
        "categorias_grau2": CATEGORIAS_GRAU2,
        "origem_lead": ORIGEM_LEAD_OPTIONS,
        "volume_estimado": VOLUME_ESTIMADO_OPTIONS,
        "tem_anvisa": TEM_ANVISA_OPTIONS,
        "motivo_perda": MOTIVO_PERDA_OPTIONS,
        "segmento": SEGMENTO_CLIENTE_OPTIONS,
        "porte": PORTE_CLIENTE_OPTIONS,
        "temperatura_lead": TEMPERATURA_LEAD_OPTIONS,
        "cargo_decisor": CARGO_DECISOR_OPTIONS,
        "ufs": UF_OPTIONS,
        "project_posicionamento": PROJECT_POSICIONAMENTO_OPTIONS,
        "project_tipo_servico": PROJECT_TIPO_SERVICO_OPTIONS,
        "project_restricoes_tecnicas": PROJECT_RESTRICAO_TECNICA_OPTIONS,
        "sample_tipos": TIPO_AMOSTRA_OPTIONS,
        "sample_unidades": UNIDADE_QUANTIDADE_AMOSTRA_OPTIONS,
        "sample_parametros_variacao": SAMPLE_VARIATION_PARAM_OPTIONS,
        "sample_resultados": SAMPLE_RESULTADO_OPTIONS,
        "follow_up_prazos": FOLLOW_UP_PRAZOS,
        "client_stages": CLIENT_STAGES,
        "project_stages": PROJECT_STAGES,
        "sample_stages": SAMPLE_STAGES,
        "stage_labels": STAGE_LABELS,
    }


@crm_router.get("/config/{crm_type}/columns")
async def get_crm_columns(crm_type: str, request: Request):
    user = await _get_current_user(request)
    if crm_type not in ("clients", "projects", "samples"):
        raise HTTPException(status_code=400, detail="Tipo de CRM inválido")

    await _ensure_crm_config(user["tenant_id"], crm_type)

    columns = await db.crm_column_configs.find(
        {"tenant_id": user["tenant_id"], "crm_type": crm_type}, {"_id": 0}
    ).sort("order", 1).to_list(100)

    # Load fields for each column
    col_ids = [c["id"] for c in columns]
    fields = await db.crm_field_configs.find(
        {"column_id": {"$in": col_ids}, "tenant_id": user["tenant_id"]}, {"_id": 0}
    ).sort("order", 1).to_list(500)

    fields_by_col = {}
    for f in fields:
        fields_by_col.setdefault(f["column_id"], []).append(f)

    for col in columns:
        col["fields"] = fields_by_col.get(col["id"], [])

    return {"columns": columns, "field_types": FIELD_TYPES}


@crm_router.post("/config/columns")
async def create_crm_column(data: CRMColumnCreate, request: Request):
    user = await _get_current_user(request)
    if data.crm_type not in ("clients", "projects", "samples"):
        raise HTTPException(status_code=400, detail="Tipo de CRM inválido")

    await _ensure_crm_config(user["tenant_id"], data.crm_type)

    # Get next order
    max_order_docs = await db.crm_column_configs.find(
        {"tenant_id": user["tenant_id"], "crm_type": data.crm_type}
    ).sort("order", -1).to_list(1)
    next_order = (max_order_docs[0]["order"] + 1) if max_order_docs else 0

    col_id = _new_id()
    key = data.label.lower().replace(" ", "_").replace("/", "_")
    col = {
        "id": col_id,
        "tenant_id": user["tenant_id"],
        "crm_type": data.crm_type,
        "key": key,
        "label": data.label,
        "color": data.color,
        "order": next_order,
        "is_system": False,
        "created_at": _now_iso(),
    }
    await db.crm_column_configs.insert_one(col)
    col.pop("_id", None)
    col["fields"] = []

    # Add key to allowed stages and transitions
    _update_stage_config(data.crm_type, key)

    return col


@crm_router.put("/config/columns/{column_id}")
async def update_crm_column(column_id: str, data: CRMColumnUpdate, request: Request):
    user = await _get_current_user(request)
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nada para atualizar")

    result = await db.crm_column_configs.update_one(
        {"id": column_id, "tenant_id": user["tenant_id"]},
        {"$set": updates}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Coluna não encontrada")
    updated = await db.crm_column_configs.find_one({"id": column_id}, {"_id": 0})
    return updated


@crm_router.delete("/config/columns/{column_id}")
async def delete_crm_column(column_id: str, request: Request):
    user = await _get_current_user(request)
    col = await db.crm_column_configs.find_one(
        {"id": column_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not col:
        raise HTTPException(status_code=404, detail="Coluna não encontrada")

    if col.get("is_system"):
        raise HTTPException(status_code=400, detail="Não é possível excluir coluna do sistema")

    # Check for items in this column
    crm_type = col["crm_type"]
    collection_map = {"clients": "crm_clients", "projects": "crm_projects", "samples": "crm_samples"}
    coll_name = collection_map.get(crm_type)
    if coll_name:
        coll = db[coll_name]
        count = await coll.count_documents({"stage": col["key"], "tenant_id": user["tenant_id"]})
        if count > 0:
            raise HTTPException(status_code=400, detail=f"Não é possível excluir: {count} item(ns) nesta coluna")

    await db.crm_field_configs.delete_many({"column_id": column_id})
    await db.crm_column_configs.delete_one({"id": column_id})
    return {"message": "Coluna removida"}


@crm_router.put("/config/columns/reorder")
async def reorder_crm_columns(data: CRMColumnReorder, request: Request):
    user = await _get_current_user(request)
    for i, cid in enumerate(data.column_ids):
        await db.crm_column_configs.update_one(
            {"id": cid, "tenant_id": user["tenant_id"]},
            {"$set": {"order": i}}
        )
    return {"message": "Colunas reordenadas"}


@crm_router.post("/config/fields")
async def create_crm_field(data: CRMFieldCreate, request: Request):
    user = await _get_current_user(request)
    col = await db.crm_column_configs.find_one({"id": data.column_id, "tenant_id": user["tenant_id"]})
    if not col:
        raise HTTPException(status_code=404, detail="Coluna não encontrada")

    if data.type not in FIELD_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo de campo inválido: {data.type}")

    max_order_docs = await db.crm_field_configs.find(
        {"column_id": data.column_id}
    ).sort("order", -1).to_list(1)
    next_order = (max_order_docs[0]["order"] + 1) if max_order_docs else 0

    field_id = _new_id()
    field = {
        "id": field_id,
        "tenant_id": user["tenant_id"],
        "column_id": data.column_id,
        "label": data.label,
        "type": data.type,
        "required": data.required,
        "options": data.options,
        "order": next_order,
        "created_at": _now_iso(),
    }
    await db.crm_field_configs.insert_one(field)
    field.pop("_id", None)
    return field


@crm_router.put("/config/fields/{field_id}")
async def update_crm_field(field_id: str, data: CRMFieldUpdate, request: Request):
    user = await _get_current_user(request)
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nada para atualizar")

    result = await db.crm_field_configs.update_one(
        {"id": field_id, "tenant_id": user["tenant_id"]},
        {"$set": updates}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Campo não encontrado")
    return await db.crm_field_configs.find_one({"id": field_id}, {"_id": 0})


@crm_router.delete("/config/fields/{field_id}")
async def delete_crm_field(field_id: str, request: Request):
    user = await _get_current_user(request)
    result = await db.crm_field_configs.delete_one({"id": field_id, "tenant_id": user["tenant_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Campo não encontrado")
    return {"message": "Campo removido"}


def _update_stage_config(crm_type: str, new_key: str):
    """Add new custom key to runtime stage/transition configs"""
    global CLIENT_STAGES, CLIENT_TRANSITIONS, PROJECT_STAGES, PROJECT_TRANSITIONS, SAMPLE_STAGES, SAMPLE_TRANSITIONS
    if crm_type == "clients":
        if new_key not in CLIENT_STAGES:
            # Insert before last 2 (fechado, perdido)
            idx = max(0, len(CLIENT_STAGES) - 2)
            CLIENT_STAGES.insert(idx, new_key)
            CLIENT_TRANSITIONS[new_key] = [CLIENT_STAGES[idx + 1] if idx + 1 < len(CLIENT_STAGES) else "cliente_perdido", "cliente_perdido"]
            # Allow previous stage to transition to new stage
            if idx > 0:
                prev = CLIENT_STAGES[idx - 1]
                if new_key not in CLIENT_TRANSITIONS.get(prev, []):
                    CLIENT_TRANSITIONS[prev].insert(0, new_key)
    elif crm_type == "projects":
        if new_key not in PROJECT_STAGES:
            PROJECT_STAGES.insert(-1, new_key)
            PROJECT_TRANSITIONS[new_key] = [PROJECT_STAGES[-1]]
    elif crm_type == "samples":
        if new_key not in SAMPLE_STAGES:
            idx = max(0, len(SAMPLE_STAGES) - 2)
            SAMPLE_STAGES.insert(idx, new_key)
            SAMPLE_TRANSITIONS[new_key] = [SAMPLE_STAGES[idx + 1] if idx + 1 < len(SAMPLE_STAGES) else "reprovada"]


# ======================================================================
#  ENUM OPTIONS (for frontend forms)
# ======================================================================

@crm_router.get("/options")
async def get_options(request: Request):
    """Return all enum options for frontend forms"""
    await _get_current_user(request)
    return {
        "canal_origem": CANAL_ORIGEM_OPTIONS,
        "canal_origem_grupos": CANAL_ORIGEM_GROUPS,
        "categoria_interesse": CATEGORIA_INTERESSE_OPTIONS,
        "origem_lead": ORIGEM_LEAD_OPTIONS,
        "volume_estimado_mensal": VOLUME_ESTIMADO_OPTIONS,
        "tem_anvisa": TEM_ANVISA_OPTIONS,
        "segmento": SEGMENTO_CLIENTE_OPTIONS,
        "porte": PORTE_CLIENTE_OPTIONS,
        "temperatura_lead": TEMPERATURA_LEAD_OPTIONS,
        "cargo_decisor": CARGO_DECISOR_OPTIONS,
        "ufs": UF_OPTIONS,
        "client_stages": [{"value": s, "label": STAGE_LABELS.get(s, s)} for s in CLIENT_STAGES],
        "project_stages": [{"value": s, "label": STAGE_LABELS.get(s, s)} for s in PROJECT_STAGES],
        "sample_stages": [{"value": s, "label": STAGE_LABELS.get(s, s)} for s in SAMPLE_STAGES],
    }


@crm_router.get("/users-list")
async def list_crm_users(request: Request):
    """List users for assignment dropdowns"""
    user = await _get_current_user(request)
    users = await db.users.find(
        {"tenant_id": user["tenant_id"]},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
    ).to_list(100)
    return users
