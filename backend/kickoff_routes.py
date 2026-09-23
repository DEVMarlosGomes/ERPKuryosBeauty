from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import csv
import io
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from rbac import require_roles, has_role
from workflow_engine import audit_log, create_workflow_task, next_sequence


kickoff_router = APIRouter(prefix="/api")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_kickoff(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def new_id() -> str:
    return new_id_func()


def now_iso() -> str:
    return now_iso_func()


def _bom_registration_key(line: Dict[str, Any]) -> str:
    raw = "|".join([
        str(line.get("tipo") or "").strip().lower(),
        str(line.get("codigo_interno") or "").strip().lower(),
        str(line.get("descricao") or "").strip().lower(),
    ])
    return " ".join(raw.split())


KICKOFF_STATUSES = {
    "em_preenchimento",
    "aguardando_aprovacao",
    "aprovado",
    "em_revisao",
    "substituida",
    "arquivado",
}

APPROVAL_SEQUENCE = ["lider_pd", "cq", "eng_produto", "direcao"]
APPROVAL_ROLE_MAP = {
    "lider_pd": {"admin", "lider_pd"},
    "cq": {"admin", "qa"},
    "eng_produto": {"admin", "engenharia_produto"},
    "direcao": {"admin"},
}
APPROVAL_LABELS = {
    "lider_pd": "Lider P&D",
    "cq": "CQ",
    "eng_produto": "Engenharia de Produto",
    "direcao": "Direcao",
}
BLOCK_2_ROLES = {"admin", "vendedor", "sales_ops"}
BLOCK_3_ROLES = {"admin", "formulador", "lider_pd"}
BLOCK_4_ROLES = {"admin", "engenharia_produto"}


EMPRESA_KURYOS = {
    "razao_social": "KURYOS BEAUTY PACKING INDUSTRIAL LTDA",
    "cnpj": "00.767.554/0001-19",
    "endereco": "Rua Lagoa Tai Grande, 1130, Sao Paulo/SP, CEP 08290-425",
    "anvisa": "355030801-206-000078-1-1",
    "foro": "Comarca de Sao Paulo/SP",
}

QUESTIONARIO_COMPOSICAO_VERSION = "questionario_composicao_projeto_2"

QUESTIONARIO_BLOCO2_COMPONENTS = [
    ("frasco_pote_bisnaga", "Frasco / pote / bisnaga"),
    ("airless_rollon_ampola", "Airless / roll-on / ampola"),
    ("tampa", "Tampa (rosca / flip-top / pressao)"),
    ("valvula_pump", "Valvula pump / bomba dosadora"),
    ("valvula_spray", "Valvula spray / atomizador"),
    ("valvula_aerossol_atuador", "Valvula aerossol + atuador"),
    ("gatilho_trigger", "Gatilho / trigger"),
    ("batoque_redutor_orificio", "Batoque / redutor / orificio"),
    ("lacre_inducao_disco", "Lacre de inducao / disco de vedacao"),
    ("aplicador", "Aplicador (pincel / espatula / esponja)"),
]

QUESTIONARIO_BLOCO3_COMPONENTS = [
    ("rotulo", "Rotulo (frontal / contra)"),
    ("cartucho", "Cartucho"),
    ("bula_folheto", "Bula / folheto"),
    ("selo_lacre_seguranca", "Selo / lacre de seguranca"),
    ("celofane_shrink", "Celofane / shrink"),
    ("berco_suporte_interno", "Berco / suporte interno"),
]

QUESTIONARIO_BLOCO4_COMPONENTS = [
    ("display_expositor_pdv", "Display / expositor de PDV"),
    ("caixa_master", "Caixa de embarque (master)"),
    ("divisoria_colmeia", "Divisoria / separador / colmeia"),
    ("cantoneira", "Cantoneira"),
    ("paletizacao", "Especificacao de paletizacao"),
]


class KickoffCreateInput(BaseModel):
    projeto_id: str
    formula_id: Optional[str] = None


class KickoffQuestionarioInput(BaseModel):
    questionario: Dict[str, Any] = Field(default_factory=dict)


class KickoffDeleteInput(BaseModel):
    motivo: str = ""


class KickoffBloco2Input(BaseModel):
    volume_primeiro_pedido: Optional[int] = None
    volume_estimado_mes: Optional[int] = None
    unidade_venda: Optional[str] = None
    quantidade_por_caixa: Optional[int] = None
    data_entrega_contratada: Optional[str] = None
    lead_time_producao_dias_uteis: Optional[int] = None
    prazo_validade_produto_meses: Optional[int] = None
    preco_venda_cliente_rs_un: Optional[float] = None
    condicao_pagamento: Optional[str] = None
    condicao_pagamento_outro: Optional[str] = None
    incoterm: Optional[str] = None
    endereco_entrega: Optional[str] = None
    nota_fiscal_cfop: Optional[str] = None
    contrato_assinado_file_id: Optional[str] = None
    contrato_assinado_data: Optional[str] = None
    numero_pedido_cliente: Optional[str] = None
    observacoes_comerciais: Optional[str] = None


class KickoffBloco3Input(BaseModel):
    nome_tecnico_produto: Optional[str] = None
    nome_comercial_cliente: Optional[str] = None
    categoria_anvisa: Optional[str] = None
    tipo_produto: Optional[str] = None
    forma_apresentacao: Optional[str] = None
    volume_peso_liquido_valor: Optional[float] = None
    volume_peso_liquido_unidade: Optional[str] = None
    aspecto_visual: Optional[str] = None
    foto_amostra_aprovada_file_id: Optional[str] = None
    cor_descricao: Optional[str] = None
    cor_codigo: Optional[str] = None
    odor: Optional[str] = None
    ph_minimo: Optional[float] = None
    ph_maximo: Optional[float] = None
    viscosidade_minima_cp: Optional[float] = None
    viscosidade_maxima_cp: Optional[float] = None
    viscosidade_spindle: Optional[str] = None
    viscosidade_rpm: Optional[str] = None
    densidade_minima: Optional[float] = None
    densidade_maxima: Optional[float] = None
    teor_alcool_minimo: Optional[float] = None
    teor_alcool_maximo: Optional[float] = None
    parametros_microbiologicos: Dict[str, Any] = Field(default_factory=dict)
    estabilidade_minima_comprovada_meses: Optional[int] = None
    restricoes_claims: List[str] = Field(default_factory=list)
    registro_anvisa_numero: Optional[str] = None
    registro_anvisa_file_id: Optional[str] = None
    criterios_fisicoquimicos: List[Dict[str, Any]] = Field(default_factory=list)
    criterios_microbiologicos: List[Dict[str, Any]] = Field(default_factory=list)
    analises_obrigatorias_por_lote: List[str] = Field(default_factory=list)
    plano_amostragem: Optional[str] = None
    quantidade_retencao: Optional[float] = None
    unidade_retencao: Optional[str] = None
    prazo_retencao_meses: Optional[int] = None
    responsavel_liberacao_lote: Optional[str] = None


class KickoffBloco4Input(BaseModel):
    embalagem_primaria_tipo: Optional[str] = None
    embalagem_primaria_material: Optional[str] = None
    embalagem_primaria_volume_nominal: Optional[float] = None
    embalagem_primaria_fornecedor_id: Optional[str] = None
    embalagem_primaria_fornecedor_alternativo_id: Optional[str] = None
    embalagem_primaria_codigo_interno: Optional[str] = None
    embalagem_primaria_cor: Optional[str] = None
    embalagem_primaria_acabamento: Optional[str] = None
    embalagem_primaria_tolerancia_dimensional: Optional[str] = None
    embalagem_primaria_laudo_file_id: Optional[str] = None
    fechamento_tipo: Optional[str] = None
    fechamento_material: Optional[str] = None
    fechamento_cor: Optional[str] = None
    fechamento_rosca_encaixe: Optional[str] = None
    fechamento_fornecedor_id: Optional[str] = None
    fechamento_codigo_interno: Optional[str] = None
    fechamento_quantidade_por_unidade: Optional[int] = None
    fechamento_acessorio: Optional[str] = None
    embalagem_secundaria_tipo: Optional[str] = None
    embalagem_secundaria_material: Optional[str] = None
    embalagem_secundaria_dimensoes: Optional[str] = None
    embalagem_secundaria_gramatura: Optional[float] = None
    embalagem_secundaria_fornecedor_id: Optional[str] = None
    embalagem_secundaria_codigo_interno: Optional[str] = None
    embalagem_secundaria_unidades_por_caixa: Optional[int] = None
    embalagem_secundaria_arte_file_id: Optional[str] = None
    embalagem_secundaria_arte_data_aprovacao: Optional[str] = None
    embalagem_secundaria_arte_aprovador_nome: Optional[str] = None
    embalagem_secundaria_arte_aprovador_email: Optional[str] = None
    caixa_master_tipo: Optional[str] = None
    caixa_master_dimensoes: Optional[str] = None
    caixa_master_unidades: Optional[int] = None
    caixa_master_peso_bruto_kg: Optional[float] = None
    configuracao_palete: Optional[str] = None
    tipo_palete: Optional[str] = None
    filme_stretch: Optional[bool] = None
    caixa_master_codigo_interno: Optional[str] = None
    tipo_rotulagem: Optional[str] = None
    rotulo_material: Optional[str] = None
    rotulo_dimensoes: Optional[str] = None
    rotulo_fornecedor_id: Optional[str] = None
    rotulo_codigo_interno: Optional[str] = None
    rotulo_arte_file_id: Optional[str] = None
    rotulo_arte_data_aprovacao: Optional[str] = None
    rotulo_arte_aprovador: Optional[str] = None
    rotulo_informacoes_obrigatorias_checklist: Dict[str, Any] = Field(default_factory=dict)
    rotulo_quantidade_por_pedido: Optional[int] = None


class KickoffApprovalInput(BaseModel):
    etapa: str
    decisao: str
    justificativa: Optional[str] = None
    observacoes: Optional[str] = None


class BomExportInput(BaseModel):
    formato: str = "csv"


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clone_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clone_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clone_value(v) for v in value]
    return value


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _as_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return str(value)


def _map_questionario_categoria(value: Any) -> str:
    mapping = {
        "capilares": "capilar",
        "capilar": "capilar",
        "skin_care": "skin_care",
        "skincare": "skin_care",
        "skin_care_dermocosmeticos": "skin_care",
        "perfumaria": "perfumaria",
        "maquiagem": "maquiagem",
        "home_care": "home_care",
    }
    key = str(value or "").strip().lower()
    return mapping.get(key, key)


def _map_questionario_modelo_servico(value: Any) -> str:
    mapping = {
        "formula_do_cliente": "industrializacao_pura",
        "co_desenvolvimento": "industrializacao_com_desenvolvimento",
        "full_service": "full_service_marca_propria",
        "full_service_kuryos": "full_service_marca_propria",
        "full_service_marca_propria": "full_service_marca_propria",
    }
    key = str(value or "").strip().lower()
    return mapping.get(key, key)


def _to_float_or_none(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        text = str(value).replace(".", "").replace(",", ".") if isinstance(value, str) else value
        return float(text)
    except (TypeError, ValueError):
        return None


def _component_rows(rows: List[Tuple[str, str]], *, has_art: bool = False) -> List[Dict[str, Any]]:
    result = []
    for row_id, label in rows:
        row = {
            "id": row_id,
            "componente": label,
            "aplicavel": "",
            "definido": "",
            "fornecido_por": "",
            "observacoes": "",
        }
        if has_art:
            row["arte_cria_aprova"] = ""
            row["arte_aprovada"] = ""
        else:
            row["especificacao_fornecedor_codigo"] = ""
        result.append(row)
    return result


def _questionario_template() -> Dict[str, Any]:
    return {
        "schema_version": QUESTIONARIO_COMPOSICAO_VERSION,
        "bloco0": {
            "cliente": "",
            "nome_produto": "",
            "categoria": "",
            "categoria_outro": "",
            "forma_fisica": "",
            "forma_fisica_outro": "",
            "volume_gramatura": "",
            "numero_skus_variacoes": "",
            "varia_entre_skus": [],
            "varia_entre_skus_outro": "",
            "unidades_por_display": "",
            "displays_ou_unidades_por_caixa_master": "",
            "registro_notificacao_anvisa": "",
            "detentor_registro": "",
            "responsavel_tecnico": "",
            "modelo_servico": "",
        },
        "bloco1": {
            "formula": "",
            "cliente_fornece": [],
            "tem_cor": "",
            "tem_brilho_mica_glitter": "",
            "viscosidade": "",
            "densidade": "",
            "fragrancia_essencia": "",
            "compra_fragrancia_por": "",
            "observacoes_formulacao": "",
        },
        "bloco2": {"componentes": _component_rows(QUESTIONARIO_BLOCO2_COMPONENTS)},
        "bloco3": {"componentes": _component_rows(QUESTIONARIO_BLOCO3_COMPONENTS, has_art=True)},
        "bloco4": {"componentes": _component_rows(QUESTIONARIO_BLOCO4_COMPONENTS)},
        "bloco5": {
            "especificacoes_cq_componentes": "",
            "especificacoes_cq_anexos": [],
            "testes_aprovacoes_obrigatorios": "",
            "amostra_referencia_fornecida_cliente": "",
        },
        "fechamento": {
            "data_prevista_inicio_producao": "",
            "volume_primeiro_lote": "",
            "responsavel_kuryos": "",
            "responsavel_cliente": "",
            "data_preenchimento": "",
        },
        "autopopulated_from": [],
    }


def _merge_questionario(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = _clone_value(base)
    incoming = incoming or {}
    for key, value in incoming.items():
        if key in ("bloco2", "bloco3", "bloco4") and isinstance(value, dict):
            current = merged.setdefault(key, {})
            if "componentes" in value and isinstance(value["componentes"], list):
                current["componentes"] = [_clone_value(item) for item in value["componentes"]]
            for sub_key, sub_value in value.items():
                if sub_key != "componentes":
                    current[sub_key] = _clone_value(sub_value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **_clone_value(value)}
        else:
            merged[key] = _clone_value(value)
    merged["schema_version"] = QUESTIONARIO_COMPOSICAO_VERSION
    return merged


async def _find_project_proposta(project_id: str, tenant_id: str) -> Dict[str, Any]:
    collection = getattr(db, "propostas_comerciais", None)
    if collection is None:
        return {}
    doc = await collection.find_one({"projeto_id": project_id, "tenant_id": tenant_id}, {"_id": 0})
    return doc or {}


async def _find_project_samples(project_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    collection = getattr(db, "crm_samples", None)
    if collection is None:
        return []
    cursor = collection.find({"projeto_id": project_id, "tenant_id": tenant_id}, {"_id": 0})
    return await cursor.to_list(500)


def _approved_variations(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    approved = []
    for sample in samples:
        for variation in sample.get("variacoes", []) or []:
            if variation.get("resultado") == "aprovada" or variation.get("status") == "aprovada" or variation.get("aprovacao_externa"):
                approved.append({"sample": sample, "variation": variation})
    return approved


def _formula_fragrance_text(formula_items: List[Dict[str, Any]]) -> str:
    fragrances = []
    for item in formula_items:
        blob = " ".join(str(item.get(key, "")) for key in ("ingredient_name", "phase", "function")).lower()
        if "fragr" in blob or "essenc" in blob:
            fragrances.append(item.get("ingredient_name", ""))
    return ", ".join(item for item in fragrances if item)


async def _build_questionario_composicao(project: dict, client: dict, formula_ctx: dict, auto_block: Dict[str, Any]) -> Dict[str, Any]:
    questionario = _questionario_template()
    tenant_id = project["tenant_id"]
    proposta = await _find_project_proposta(project["id"], tenant_id)
    samples = await _find_project_samples(project["id"], tenant_id)
    approved = _approved_variations(samples)
    formula = formula_ctx.get("formula") or {}
    formula_items = []
    if formula.get("id") and getattr(db, "pd_formula_items", None) is not None:
        formula_items = await db.pd_formula_items.find({"formula_id": formula["id"]}, {"_id": 0}).to_list(1000)

    first_item = (proposta.get("items_pedido") or [{}])[0] if proposta.get("items_pedido") else {}
    first_sample = samples[0] if samples else {}
    first_variation = (approved[0]["variation"] if approved else ((first_sample.get("variacoes") or [{}])[0] if first_sample.get("variacoes") else {}))
    contato = client.get("contato_principal") or {}

    formula_volume = ""
    if formula.get("volume") not in (None, ""):
        formula_volume = f"{formula.get('volume')} {formula.get('volume_unit', '')}".strip()

    source = []
    for label, condition in (
        ("crm_projects", bool(project)),
        ("crm_clients", bool(client)),
        ("propostas_comerciais", bool(proposta)),
        ("crm_samples", bool(samples)),
        ("pd_formulas", bool(formula)),
    ):
        if condition:
            source.append(label)

    questionario["bloco0"].update({
        "cliente": _first_value(project.get("cliente_nome"), client.get("nome_empresa")),
        "nome_produto": _first_value(proposta.get("tipo_produto"), first_item.get("item"), first_sample.get("nome_produto"), project.get("nome_projeto")),
        "categoria": _map_questionario_categoria(_first_value(project.get("categoria"), first_sample.get("categoria"))),
        "forma_fisica": _first_value(first_sample.get("textura_esperada"), project.get("forma_fisica")),
        "volume_gramatura": _first_value(first_item.get("volume_gramatura"), formula_volume, project.get("volume_gramatura")),
        "numero_skus_variacoes": _as_text(_first_value(len(proposta.get("items_pedido") or []) or "", len(approved) or "", project.get("numero_skus_variacoes"))),
        "varia_entre_skus": [first_sample.get("parametro_variacao")] if first_sample.get("parametro_variacao") else [],
        "displays_ou_unidades_por_caixa_master": _as_text(first_item.get("quantidade_por_caixa", "")),
        "registro_notificacao_anvisa": _first_value(project.get("registro_notificacao_anvisa"), client.get("tem_anvisa"), "a_providenciar"),
        "detentor_registro": _first_value(project.get("detentor_registro"), client.get("nome_empresa")),
        "responsavel_tecnico": _first_value(project.get("responsavel_tecnico"), client.get("responsavel_tecnico")),
        "modelo_servico": _map_questionario_modelo_servico(_first_value(project.get("tipo_servico"), proposta.get("modelo_servico"))),
    })
    questionario["bloco1"].update({
        "formula": "desenvolvida_kuryos" if formula.get("id") else _first_value(project.get("formula_origem"), ""),
        "cliente_fornece": ["formula_documento"] if project.get("tipo_servico") == "formula_do_cliente" else [],
        "tem_cor": "sim" if first_variation.get("cor") else "",
        "viscosidade": _first_value(first_sample.get("viscosidade"), project.get("viscosidade")),
        "densidade": _first_value(first_sample.get("densidade"), project.get("densidade")),
        "fragrancia_essencia": _first_value(_formula_fragrance_text(formula_items), first_variation.get("referencia_fragrancia")),
        "compra_fragrancia_por": _first_value(first_variation.get("compra_fragrancia_por"), "kuryos" if _formula_fragrance_text(formula_items) else ""),
        "observacoes_formulacao": _first_value(formula.get("notes"), first_sample.get("observacao_tecnica"), proposta.get("observacoes_proposta")),
    })
    questionario["bloco5"].update({
        "especificacoes_cq_componentes": _first_value(project.get("especificacoes_cq_componentes"), first_sample.get("observacao_tecnica")),
        "testes_aprovacoes_obrigatorios": _first_value(project.get("testes_aprovacoes_obrigatorios"), ""),
        "amostra_referencia_fornecida_cliente": "sim" if samples else "",
    })
    questionario["fechamento"].update({
        "data_prevista_inicio_producao": _first_value(project.get("data_prevista_inicio_producao"), first_item.get("prazo_entrega")),
        "volume_primeiro_lote": _as_text(_first_value(first_item.get("qtd"), proposta.get("volume_primeiro_lote"), project.get("volume_estimado_pedido"))),
        "responsavel_kuryos": _first_value(project.get("responsavel_comercial"), auto_block.get("responsavel_comercial")),
        "responsavel_cliente": _first_value(contato.get("nome"), client.get("responsavel_cliente")),
        "data_preenchimento": now_iso()[:10],
    })
    questionario["autopopulated_from"] = source
    return questionario


def _version_code(number: int) -> str:
    return f"v{number}"


def _approval_template() -> List[Dict[str, Any]]:
    return [
        {
            "etapa": etapa,
            "label": APPROVAL_LABELS[etapa],
            "status": "pendente",
            "decisao": None,
            "justificativa": "",
            "observacoes": "",
            "decidido_por": None,
            "decidido_por_nome": "",
            "decidido_em": None,
        }
        for etapa in APPROVAL_SEQUENCE
    ]


def _diff_entries(prefix: str, before_doc: Dict[str, Any], after_doc: Dict[str, Any], user: dict) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    keys = set(before_doc.keys()) | set(after_doc.keys())
    for key in sorted(keys):
        before_value = before_doc.get(key)
        after_value = after_doc.get(key)
        if before_value == after_value:
            continue
        entries.append(
            {
                "campo": f"{prefix}.{key}",
                "valor_anterior": before_value,
                "valor_novo": after_value,
                "usuario_id": user["id"],
                "usuario_nome": user.get("name", ""),
                "datetime": now_iso(),
            }
        )
    return entries


def _has_values(data: Dict[str, Any]) -> bool:
    for value in data.values():
        if value not in (None, "", [], {}):
            return True
    return False


def _row_ready(row: Dict[str, Any], *, has_art: bool = False) -> bool:
    aplicavel = row.get("aplicavel")
    if aplicavel in (None, ""):
        return False
    if str(aplicavel).lower() in {"nao", "false", "0"}:
        return True
    required = ["definido", "fornecido_por", "arte_cria_aprova" if has_art else "especificacao_fornecedor_codigo"]
    if has_art:
        required.append("arte_aprovada")
    return all(row.get(field) not in (None, "", [], {}) for field in required)


def _questionario_section_ready(questionario: Dict[str, Any], section: str) -> Tuple[bool, List[str]]:
    data = questionario.get(section) or {}
    missing: List[str] = []
    required_by_section = {
        "bloco0": ["cliente", "nome_produto", "categoria", "forma_fisica", "volume_gramatura", "numero_skus_variacoes", "modelo_servico"],
        "bloco1": ["formula", "cliente_fornece", "tem_cor", "tem_brilho_mica_glitter", "viscosidade", "densidade", "compra_fragrancia_por"],
        "bloco5": ["especificacoes_cq_componentes", "testes_aprovacoes_obrigatorios", "amostra_referencia_fornecida_cliente"],
        "fechamento": ["data_prevista_inicio_producao", "volume_primeiro_lote", "responsavel_kuryos", "responsavel_cliente", "data_preenchimento"],
    }
    for field in required_by_section.get(section, []):
        if data.get(field) in (None, "", [], {}):
            missing.append(field)
    if section in {"bloco2", "bloco3", "bloco4"}:
        has_art = section == "bloco3"
        for index, row in enumerate(data.get("componentes") or []):
            if not _row_ready(row, has_art=has_art):
                missing.append(f"componentes[{index}]")
    return len(missing) == 0, missing


def _questionario_ready(questionario: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    sections = ["bloco0", "bloco1", "bloco2", "bloco3", "bloco4", "bloco5", "fechamento"]
    status = {}
    for section in sections:
        ok, missing = _questionario_section_ready(questionario, section)
        status[section] = {"completo": ok, "campos_pendentes": missing}
    return all(item["completo"] for item in status.values()), status


def _find_component(questionario: Dict[str, Any], section: str, component_id: str) -> Dict[str, Any]:
    for row in (questionario.get(section) or {}).get("componentes") or []:
        if row.get("id") == component_id:
            return row
    return {}


def _component_answered(row: Dict[str, Any]) -> bool:
    return any(
        value not in (None, "", [], {})
        for key, value in row.items()
        if key not in {"id", "componente"}
    )


def _legacy_blocks_from_questionario(questionario: Dict[str, Any], kickoff: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    bloco0 = questionario.get("bloco0") or {}
    bloco1 = questionario.get("bloco1") or {}
    bloco5 = questionario.get("bloco5") or {}
    fechamento = questionario.get("fechamento") or {}
    old2 = kickoff.get("bloco2") or {}
    old3 = kickoff.get("bloco3") or {}
    old4 = kickoff.get("bloco4") or {}

    primary_candidate = _find_component(questionario, "bloco2", "frasco_pote_bisnaga")
    tampa_candidate = _find_component(questionario, "bloco2", "tampa")
    rotulo_candidate = _find_component(questionario, "bloco3", "rotulo")
    caixa_candidate = _find_component(questionario, "bloco4", "caixa_master")
    palete_candidate = _find_component(questionario, "bloco4", "paletizacao")
    primary = primary_candidate if _component_answered(primary_candidate) else {}
    tampa = tampa_candidate if _component_answered(tampa_candidate) else {}
    rotulo = rotulo_candidate if _component_answered(rotulo_candidate) else {}
    caixa = caixa_candidate if _component_answered(caixa_candidate) else {}
    palete = palete_candidate if _component_answered(palete_candidate) else {}

    bloco2 = {
        **old2,
        "volume_primeiro_pedido": _to_float_or_none(fechamento.get("volume_primeiro_lote")) or old2.get("volume_primeiro_pedido"),
        "unidade_venda": _first_value(bloco0.get("volume_gramatura"), old2.get("unidade_venda")),
        "quantidade_por_caixa": _to_float_or_none(bloco0.get("displays_ou_unidades_por_caixa_master")) or old2.get("quantidade_por_caixa"),
        "data_entrega_contratada": _first_value(fechamento.get("data_prevista_inicio_producao"), old2.get("data_entrega_contratada")),
        "condicao_pagamento": _first_value(old2.get("condicao_pagamento"), "a_definir"),
        "preco_venda_cliente_rs_un": _first_value(old2.get("preco_venda_cliente_rs_un"), 0),
        "observacoes_comerciais": _first_value(old2.get("observacoes_comerciais"), bloco5.get("testes_aprovacoes_obrigatorios")),
    }
    bloco3 = {
        **old3,
        "nome_tecnico_produto": _first_value(bloco0.get("nome_produto"), old3.get("nome_tecnico_produto")),
        "nome_comercial_cliente": _first_value(bloco0.get("nome_produto"), old3.get("nome_comercial_cliente")),
        "categoria_anvisa": _first_value(bloco0.get("categoria"), old3.get("categoria_anvisa")),
        "tipo_produto": _first_value(bloco0.get("categoria"), old3.get("tipo_produto")),
        "forma_apresentacao": _first_value(bloco0.get("forma_fisica"), old3.get("forma_apresentacao")),
        "volume_peso_liquido_valor": _to_float_or_none(bloco0.get("volume_gramatura")) or old3.get("volume_peso_liquido_valor"),
        "aspecto_visual": _first_value(old3.get("aspecto_visual"), bloco0.get("forma_fisica")),
        "cor_descricao": _first_value(old3.get("cor_descricao"), bloco1.get("tem_cor")),
        "odor": _first_value(old3.get("odor"), bloco1.get("fragrancia_essencia")),
        "registro_anvisa_numero": _first_value(old3.get("registro_anvisa_numero"), bloco0.get("registro_notificacao_anvisa")),
        "analises_obrigatorias_por_lote": old3.get("analises_obrigatorias_por_lote") or ([bloco5.get("testes_aprovacoes_obrigatorios")] if bloco5.get("testes_aprovacoes_obrigatorios") else []),
        "plano_amostragem": _first_value(old3.get("plano_amostragem"), bloco5.get("especificacoes_cq_componentes")),
        "responsavel_liberacao_lote": _first_value(old3.get("responsavel_liberacao_lote"), fechamento.get("responsavel_kuryos")),
    }
    bloco4 = {
        **old4,
        "embalagem_primaria_tipo": _first_value(primary.get("componente"), old4.get("embalagem_primaria_tipo")),
        "embalagem_primaria_material": _first_value(primary.get("especificacao_fornecedor_codigo"), old4.get("embalagem_primaria_material")),
        "embalagem_primaria_fornecedor_id": _first_value(primary.get("fornecido_por"), old4.get("embalagem_primaria_fornecedor_id")),
        "fechamento_tipo": _first_value(tampa.get("componente"), old4.get("fechamento_tipo")),
        "fechamento_fornecedor_id": _first_value(tampa.get("fornecido_por"), old4.get("fechamento_fornecedor_id")),
        "caixa_master_tipo": _first_value(caixa.get("especificacao_fornecedor_codigo"), caixa.get("componente"), old4.get("caixa_master_tipo")),
        "caixa_master_unidades": _to_float_or_none(bloco0.get("displays_ou_unidades_por_caixa_master")) or old4.get("caixa_master_unidades"),
        "configuracao_palete": _first_value(palete.get("especificacao_fornecedor_codigo"), old4.get("configuracao_palete")),
        "tipo_rotulagem": _first_value(rotulo.get("componente"), old4.get("tipo_rotulagem")),
        "rotulo_fornecedor_id": _first_value(rotulo.get("fornecido_por"), old4.get("rotulo_fornecedor_id")),
        "rotulo_arte_aprovador": _first_value(rotulo.get("arte_cria_aprova"), old4.get("rotulo_arte_aprovador")),
    }
    return {"bloco2": bloco2, "bloco3": bloco3, "bloco4": bloco4}


def _block2_ready(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    missing = []
    required = [
        "volume_primeiro_pedido",
        "data_entrega_contratada",
        "preco_venda_cliente_rs_un",
        "condicao_pagamento",
    ]
    for field in required:
        if data.get(field) in (None, "", [], {}):
            missing.append(field)
    return len(missing) == 0, missing


def _block3_ready(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    missing = []
    required = [
        "nome_tecnico_produto",
        "tipo_produto",
        "forma_apresentacao",
        "categoria_anvisa",
    ]
    for field in required:
        if data.get(field) in (None, "", [], {}):
            missing.append(field)
    return len(missing) == 0, missing


def _block4_ready(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    missing = []
    required = [
        "embalagem_primaria_tipo",
        "embalagem_primaria_material",
        "tipo_rotulagem",
    ]
    for field in required:
        if data.get(field) in (None, "", [], {}):
            missing.append(field)
    return len(missing) == 0, missing


async def _get_user_for_roles(tenant_id: str, roles: List[str]) -> Optional[Dict[str, Any]]:
    for role in roles:
        doc = await db.users.find_one(
            {"tenant_id": tenant_id, "role": role},
            {"_id": 0, "id": 1, "name": 1, "role": 1},
        )
        if doc:
            return doc
    return None


async def _find_formula_context(
    formula_id: str,
    tenant_id: str,
    *,
    database=None,
) -> Optional[Dict[str, Any]]:
    source_db = database if database is not None else db
    formula = await source_db.pd_formulas.find_one({"id": formula_id, "tenant_id": tenant_id}, {"_id": 0})
    if not formula:
        return None
    development = await source_db.pd_developments.find_one(
        {"id": formula.get("development_id"), "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not development:
        return None
    pd_request = await source_db.pd_requests.find_one(
        {"id": development.get("pd_request_id"), "tenant_id": tenant_id},
        {"_id": 0},
    )
    approval = await source_db.pd_approvals.find_one(
        {"development_id": development["id"]},
        {"_id": 0},
    )
    return {
        "formula": formula,
        "development": development,
        "pd_request": pd_request,
        "approval": approval or {},
    }


async def _resolve_registered_formula_for_project(
    project_id: str,
    tenant_id: str,
    explicit_formula_id: Optional[str] = None,
    *,
    database=None,
) -> Dict[str, Any]:
    source_db = database if database is not None else db
    project = await source_db.crm_projects.find_one({"id": project_id, "tenant_id": tenant_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")

    if explicit_formula_id:
        ctx = await _find_formula_context(explicit_formula_id, tenant_id, database=source_db)
        if not ctx:
            raise HTTPException(status_code=404, detail="Formula nao encontrada")
        pd_request = ctx.get("pd_request") or {}
        if pd_request.get("linked_projeto_id") != project_id:
            raise HTTPException(status_code=400, detail="Formula informada nao pertence ao projeto")
        approval = ctx.get("approval") or {}
        if not (approval.get("approved_by_client") and approval.get("approved_by_internal")):
            raise HTTPException(status_code=400, detail="A formula informada ainda nao esta registrada no Banco P&D.")
        return {"project": project, **ctx}

    requests_docs = await source_db.pd_requests.find(
        {"tenant_id": tenant_id, "linked_projeto_id": project_id},
        {"_id": 0},
    ).to_list(500)
    if not requests_docs:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma formula registrada encontrada para este projeto. Registre a formula no Banco P&D antes de avancar.",
        )

    req_map = {req["id"]: req for req in requests_docs if req.get("id")}
    devs = await source_db.pd_developments.find(
        {"tenant_id": tenant_id, "pd_request_id": {"$in": list(req_map.keys())}},
        {"_id": 0},
    ).to_list(500)
    if not devs:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma formula registrada encontrada para este projeto. Registre a formula no Banco P&D antes de avancar.",
        )

    dev_map = {dev["id"]: dev for dev in devs if dev.get("id")}
    approvals = await source_db.pd_approvals.find(
        {"development_id": {"$in": list(dev_map.keys())}},
        {"_id": 0},
    ).to_list(500)
    approvals_map = {doc["development_id"]: doc for doc in approvals if doc.get("development_id")}

    formulas = await source_db.pd_formulas.find(
        {"tenant_id": tenant_id, "development_id": {"$in": list(dev_map.keys())}},
        {"_id": 0},
    ).sort([("version", -1), ("created_at", -1)]).to_list(1000)

    selected = None
    for formula in formulas:
        approval = approvals_map.get(formula.get("development_id"), {})
        if not (approval.get("approved_by_client") and approval.get("approved_by_internal")):
            continue
        selected = {
            "formula": formula,
            "development": dev_map.get(formula.get("development_id")),
            "pd_request": req_map.get(dev_map.get(formula.get("development_id"), {}).get("pd_request_id")),
            "approval": approval,
        }
        break

    if not selected:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma formula registrada encontrada para este projeto. Registre a formula no Banco P&D antes de avancar.",
        )
    return {"project": project, **selected}


async def _approved_sample_payload(project: dict, pd_request: Optional[dict]) -> Dict[str, Any]:
    sample = None
    variation = None
    if pd_request and pd_request.get("linked_amostra_id"):
        sample = await db.crm_samples.find_one(
            {"id": pd_request["linked_amostra_id"], "tenant_id": project["tenant_id"]},
            {"_id": 0},
        )
    if sample and pd_request.get("linked_variacao_id"):
        variation = next(
            (item for item in sample.get("variacoes", []) if item.get("id") == pd_request.get("linked_variacao_id")),
            None,
        )
    if not sample:
        sample = await db.crm_samples.find_one(
            {"projeto_id": project["id"], "tenant_id": project["tenant_id"]},
            {"_id": 0},
            sort=[("updated_at", -1)],
        )
        if sample:
            variation = next(
                (item for item in sample.get("variacoes", []) if item.get("status") == "aprovada" or item.get("gera_sku")),
                None,
            )
    approved_code = ""
    feedback = ""
    if variation:
        approved_code = variation.get("codigo", "")
        feedback = variation.get("observacoes_especificas") or variation.get("descricao_aplicacao") or ""
    elif sample:
        approved_code = str(sample.get("numero_amostra", ""))
        feedback = sample.get("feedback_cliente", "") or sample.get("briefing_especifico", "") or ""
    return {
        "amostra_aprovada": approved_code,
        "feedback_cliente": feedback,
    }


async def _build_kickoff_auto_block(project: dict, client: dict, formula_ctx: dict) -> Dict[str, Any]:
    formula = formula_ctx["formula"]
    pd_request = formula_ctx.get("pd_request") or {}
    approved_sample = await _approved_sample_payload(project, pd_request)
    kickoff_number_seq = await next_sequence(project["tenant_id"], "kickoff", start=0)
    kickoff_number = f"KO-{datetime.now(timezone.utc).year}-{kickoff_number_seq:04d}"
    return {
        "numero_kickoff": kickoff_number,
        "data_abertura": now_iso(),
        "versao": _version_code(1),
        "versao_numero": 1,
        "status": "em_preenchimento",
        "cliente": project.get("cliente_nome") or client.get("nome_empresa", ""),
        "cnpj": client.get("cnpj", ""),
        "projeto_vinculado": project.get("nome_projeto", ""),
        "amostra_aprovada": approved_sample.get("amostra_aprovada", ""),
        "formula_vinculada": formula.get("name", ""),
        "formulador_responsavel": formula.get("created_by_name", ""),
        "responsavel_comercial": project.get("responsavel_comercial") or client.get("responsavel_comercial", ""),
        "pre_briefing_origem": project.get("briefing_resumido", ""),
        "feedback_cliente": approved_sample.get("feedback_cliente", ""),
        "categoria_anvisa_herdada": project.get("categoria", ""),
    }


async def _ensure_project_and_client(project_id: str, tenant_id: str) -> Tuple[dict, dict]:
    project = await db.crm_projects.find_one({"id": project_id, "tenant_id": tenant_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    client = await db.crm_clients.find_one({"id": project.get("cliente_id"), "tenant_id": tenant_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente do projeto nao encontrado")
    return project, client


async def _get_latest_kickoff_by_group(group_id: str, tenant_id: str) -> Optional[dict]:
    return await db.kickoffs.find_one(
        {"tenant_id": tenant_id, "kickoff_group_id": group_id},
        {"_id": 0},
        sort=[("versao_numero", -1)],
    )


async def _get_kickoff_or_404(kickoff_id: str, tenant_id: str) -> dict:
    doc = await db.kickoffs.find_one({"id": kickoff_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Kickoff nao encontrado")
    return doc


def _current_approval_step(kickoff: dict) -> Optional[Dict[str, Any]]:
    for step in kickoff.get("aprovacoes", []):
        if step.get("status") == "pendente":
            return step
    return None


async def _sync_project_kickoff_summary(kickoff: dict):
    updates = {
        "kickoff_id": kickoff["id"],
        "kickoff_numero": kickoff["numero_kickoff"],
        "kickoff_status": kickoff["status"],
        "kickoff_versao": kickoff["versao"],
        "kickoff_group_id": kickoff["kickoff_group_id"],
        "updated_at": now_iso(),
    }
    await db.crm_projects.update_one(
        {"id": kickoff["projeto_id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": updates},
    )


async def _create_or_reuse_task(
    *,
    kickoff: dict,
    title: str,
    task_code: str,
    category: str,
    due_in_days: int,
    created_by: dict,
    responsible_roles: List[str],
    description: str = "",
    blocking: bool = False,
) -> Optional[dict]:
    existing = await db.workflow_tasks.find_one(
        {
            "tenant_id": kickoff["tenant_id"],
            "entity_type": "kickoff",
            "entity_id": kickoff["id"],
            "status": {"$in": ["pendente", "em_andamento", "em_atraso"]},
            "metadata.kickoff_task_code": task_code,
        },
        {"_id": 0},
    )
    if existing:
        return existing
    responsible = await _get_user_for_roles(kickoff["tenant_id"], responsible_roles)
    return await create_workflow_task(
        tenant_id=kickoff["tenant_id"],
        entity_type="kickoff",
        entity_id=kickoff["id"],
        title=title,
        description=description,
        category=category,
        blocking=blocking,
        due_in_days=due_in_days,
        responsible_id=(responsible or {}).get("id"),
        created_by=created_by,
        metadata={
            "module_origin": "kickoff",
            "kickoff_task_code": task_code,
            "kickoff_id": kickoff["id"],
            "kickoff_numero": kickoff["numero_kickoff"],
        },
    )


async def _enqueue_block_tasks_after_create(kickoff: dict, user: dict):
    await _create_or_reuse_task(
        kickoff=kickoff,
        title=f"Preencher Bloco 2 do Kickoff {kickoff['numero_kickoff']}",
        task_code="preencher_kickoff_bloco2",
        category="comercial",
        due_in_days=2,
        created_by=user,
        responsible_roles=["sales_ops", "vendedor", "admin"],
        description="Preencher especificacao comercial e anexar contrato assinado.",
        blocking=False,
    )


async def _enqueue_after_block2(kickoff: dict, user: dict):
    await _create_or_reuse_task(
        kickoff=kickoff,
        title=f"Preencher Bloco 3 do Kickoff {kickoff['numero_kickoff']}",
        task_code="preencher_kickoff_bloco3",
        category="pd_dev",
        due_in_days=2,
        created_by=user,
        responsible_roles=["formulador", "lider_pd", "admin"],
        description="Completar especificacao tecnica e foto da amostra aprovada.",
        blocking=False,
    )


async def _enqueue_after_block3(kickoff: dict, user: dict):
    await _create_or_reuse_task(
        kickoff=kickoff,
        title=f"Preencher Bloco 4 do Kickoff {kickoff['numero_kickoff']}",
        task_code="preencher_kickoff_bloco4",
        category="engenharia_produto",
        due_in_days=2,
        created_by=user,
        responsible_roles=["engenharia_produto", "admin"],
        description="Completar embalagem, fornecedores e BOM consolidado.",
        blocking=False,
    )


async def _enqueue_approval_task(kickoff: dict, user: dict, etapa: str):
    role_targets = {
        "lider_pd": ["lider_pd", "admin"],
        "cq": ["qa", "admin"],
        "eng_produto": ["engenharia_produto", "admin"],
        "direcao": ["admin"],
    }
    category_targets = {
        "lider_pd": "pd_dev",
        "cq": "qa",
        "eng_produto": "engenharia_produto",
        "direcao": "manual",
    }
    await _create_or_reuse_task(
        kickoff=kickoff,
        title=f"Aprovar Kickoff {kickoff['numero_kickoff']} - {APPROVAL_LABELS[etapa]}",
        task_code=f"aprovar_kickoff_{etapa}",
        category=category_targets[etapa],
        due_in_days=2,
        created_by=user,
        responsible_roles=role_targets[etapa],
        description=f"Registrar aprovacao ou reprovacao da etapa {APPROVAL_LABELS[etapa]}.",
        blocking=True,
    )


async def _enqueue_revision_task(kickoff: dict, user: dict, etapa: str):
    mapping = {
        "lider_pd": ("preencher_kickoff_bloco3", "pd_dev", ["formulador", "lider_pd", "admin"], "Revisar Bloco 3 do Kickoff"),
        "cq": ("preencher_kickoff_bloco3", "pd_dev", ["formulador", "lider_pd", "admin"], "Ajustar criterios tecnicos do Kickoff"),
        "eng_produto": ("preencher_kickoff_bloco4", "engenharia_produto", ["engenharia_produto", "admin"], "Revisar Bloco 4 do Kickoff"),
        "direcao": ("preencher_kickoff_bloco2", "comercial", ["sales_ops", "vendedor", "admin"], "Revisar condicoes comerciais do Kickoff"),
    }
    task_code, category, roles, title = mapping[etapa]
    await _create_or_reuse_task(
        kickoff=kickoff,
        title=f"{title} {kickoff['numero_kickoff']}",
        task_code=task_code,
        category=category,
        due_in_days=2,
        created_by=user,
        responsible_roles=roles,
        description="Kickoff reprovado em fluxo de aprovacao. Ajustar bloco responsavel.",
        blocking=False,
    )


async def _get_supplier_doc(supplier_id: Optional[str], tenant_id: str) -> Optional[dict]:
    if not supplier_id:
        return None
    return await db.homologacao_fornecedores.find_one(
        {"id": supplier_id, "tenant_id": tenant_id},
        {"_id": 0},
    )


async def _find_mp_doc(tenant_id: str, ingredient_name: str, catalog_id: Optional[str] = None) -> Optional[dict]:
    keys = []
    if catalog_id:
        catalog = await db.pd_catalog.find_one({"id": catalog_id, "tenant_id": tenant_id}, {"_id": 0})
        if catalog:
            for key in (catalog.get("nome"), catalog.get("inci"), catalog.get("codigo_interno")):
                if key:
                    keys.append(str(key).strip().lower())
    if ingredient_name:
        keys.append(str(ingredient_name).strip().lower())
    if not keys:
        return None
    docs = await db.homologacao_mps.find({"tenant_id": tenant_id}, {"_id": 0}).to_list(5000)
    normalized = {key for key in keys if key}
    for doc in docs:
        for candidate in (doc.get("nome"), doc.get("inci"), doc.get("codigo_interno")):
            if candidate and str(candidate).strip().lower() in normalized:
                return doc
    return None


async def _build_bom_lines(kickoff: dict) -> List[Dict[str, Any]]:
    formula = await db.pd_formulas.find_one({"id": kickoff["formula_id"], "tenant_id": kickoff["tenant_id"]}, {"_id": 0})
    items = await db.pd_formula_items.find({"formula_id": kickoff["formula_id"]}, {"_id": 0}).to_list(2000)
    bloco3 = kickoff.get("bloco3") or {}
    bloco4 = kickoff.get("bloco4") or {}
    bloco2 = kickoff.get("bloco2") or {}
    volume_un = bloco3.get("volume_peso_liquido_unidade") or "mL"
    volume_value = bloco3.get("volume_peso_liquido_valor") or 0
    pedido_volume = bloco2.get("volume_primeiro_pedido") or 0

    lines: List[Dict[str, Any]] = []
    for item in items:
        mp_doc = await _find_mp_doc(kickoff["tenant_id"], item.get("ingredient_name", ""), item.get("catalog_id"))
        unit = "L" if str(volume_un).lower() == "ml" else "kg"
        per_unit = round(((item.get("percentage") or 0) / 100.0) * ((volume_value or 0) / 1000.0), 6)
        lines.append(
            {
                "id": item.get("id") or new_id(),
                "codigo_interno": (mp_doc or {}).get("codigo_interno") or item.get("catalog_id") or item.get("ingredient_name", ""),
                "descricao": item.get("ingredient_name", ""),
                "tipo": "mp_formula",
                "fornecedor_principal": {
                    "id": (mp_doc or {}).get("fornecedor_id"),
                    "nome": (mp_doc or {}).get("fornecedor_nome", ""),
                },
                "fornecedor_alternativo": None,
                "unidade": unit,
                "quantidade_por_unidade": per_unit,
                "custo_unitario_estimado_rs": round(item.get("cost_brl") or 0, 4),
                "status_homologacao": (mp_doc or {}).get("status", "pendente"),
                "quantidade_total_pedido": round(per_unit * pedido_volume, 4),
            }
        )

    packaging_specs = [
        (
            "embalagem_primaria",
            bloco4.get("embalagem_primaria_codigo_interno"),
            f"Embalagem primaria {bloco4.get('embalagem_primaria_tipo', '')} {bloco4.get('embalagem_primaria_material', '')}".strip(),
            bloco4.get("embalagem_primaria_fornecedor_id"),
            bloco4.get("embalagem_primaria_fornecedor_alternativo_id"),
            1,
        ),
        (
            "tampa",
            bloco4.get("fechamento_codigo_interno"),
            f"Fechamento {bloco4.get('fechamento_tipo', '')}".strip(),
            bloco4.get("fechamento_fornecedor_id"),
            None,
            bloco4.get("fechamento_quantidade_por_unidade") or 1,
        ),
        (
            "emb_secundaria",
            bloco4.get("embalagem_secundaria_codigo_interno"),
            f"Embalagem secundaria {bloco4.get('embalagem_secundaria_tipo', '')}".strip(),
            bloco4.get("embalagem_secundaria_fornecedor_id"),
            None,
            1 if bloco4.get("embalagem_secundaria_tipo") != "sem_caixa" else 0,
        ),
        (
            "emb_terciaria",
            bloco4.get("caixa_master_codigo_interno"),
            f"Caixa master {bloco4.get('caixa_master_tipo', '')}".strip(),
            None,
            None,
            1 / max(int(bloco4.get("caixa_master_unidades") or 1), 1),
        ),
        (
            "rotulo",
            bloco4.get("rotulo_codigo_interno"),
            f"Rotulo {bloco4.get('tipo_rotulagem', '')}".strip(),
            bloco4.get("rotulo_fornecedor_id"),
            None,
            1,
        ),
    ]
    for tipo, codigo, descricao, supplier_id, alternative_id, qty in packaging_specs:
        if qty in (None, 0) and tipo != "emb_terciaria":
            continue
        supplier = await _get_supplier_doc(supplier_id, kickoff["tenant_id"])
        supplier_alt = await _get_supplier_doc(alternative_id, kickoff["tenant_id"])
        status = supplier.get("status", "pendente") if supplier else "pendente"
        lines.append(
            {
                "id": new_id(),
                "codigo_interno": codigo or f"{kickoff['numero_kickoff']}-{tipo}",
                "descricao": descricao,
                "tipo": tipo,
                "fornecedor_principal": {
                    "id": (supplier or {}).get("id"),
                    "nome": (supplier or {}).get("nome_fantasia") or (supplier or {}).get("razao_social", ""),
                },
                "fornecedor_alternativo": {
                    "id": (supplier_alt or {}).get("id"),
                    "nome": (supplier_alt or {}).get("nome_fantasia") or (supplier_alt or {}).get("razao_social", ""),
                } if supplier_alt else None,
                "unidade": "un",
                "quantidade_por_unidade": round(qty, 6),
                "custo_unitario_estimado_rs": 0.0,
                "status_homologacao": status,
                "quantidade_total_pedido": round((qty or 0) * pedido_volume, 4),
            }
        )
    return lines


async def _refresh_bom(kickoff: dict) -> dict:
    if not _has_values(kickoff.get("bloco4") or {}):
        kickoff["bom"] = []
        return kickoff
    bom_lines = await _build_bom_lines(kickoff)
    previous_by_key = {
        _bom_registration_key(line): line
        for line in (kickoff.get("bom") or [])
    }
    registration_fields = (
        "cadastro_status",
        "cadastro_solicitacao_id",
        "material_id",
        "compras_item_id",
        "cadastro_concluido_em",
    )
    for line in bom_lines:
        line["cadastro_chave"] = _bom_registration_key(line)
        previous = previous_by_key.get(line["cadastro_chave"]) or {}
        for field in registration_fields:
            if previous.get(field) not in (None, ""):
                line[field] = previous[field]
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": {"bom": bom_lines, "updated_at": now_iso()}},
    )
    kickoff["bom"] = bom_lines
    return kickoff


async def _find_registered_bom_item(kickoff: dict, line: Dict[str, Any]) -> Tuple[Optional[dict], Optional[dict]]:
    tenant_id = kickoff["tenant_id"]
    code = str(line.get("codigo_interno") or "").strip()
    description = str(line.get("descricao") or "").strip()
    alternatives = []
    if code:
        alternatives.append({"codigo_interno": code})
    if description:
        alternatives.extend([
            {"descricao": {"$regex": f"^{re.escape(description)}$", "$options": "i"}},
            {"nome": {"$regex": f"^{re.escape(description)}$", "$options": "i"}},
        ])
    if not alternatives:
        return None, None
    compras_item = await db.compras_itens.find_one(
        {"tenant_id": tenant_id, "$or": alternatives}, {"_id": 0}
    )
    material = await db.materiais.find_one(
        {"tenant_id": tenant_id, "$or": alternatives}, {"_id": 0}
    )
    return compras_item, material


async def _sync_bom_registration_requests(kickoff: dict, user: dict) -> Dict[str, Any]:
    """Create an idempotent Cadastros queue for BOM lines not yet available to Compras."""
    tenant_id = kickoff["tenant_id"]
    now = now_iso()
    bom = list(kickoff.get("bom") or [])
    created = 0
    reused = 0
    registered = 0
    kickoff_file_ids = []
    for block_name in ("bloco2", "bloco3", "bloco4"):
        for key, value in (kickoff.get(block_name) or {}).items():
            if key.endswith("_file_id") and value and value not in kickoff_file_ids:
                kickoff_file_ids.append(value)

    for line in bom:
        key = line.get("cadastro_chave") or _bom_registration_key(line)
        line["cadastro_chave"] = key
        compras_item, material = await _find_registered_bom_item(kickoff, line)
        if compras_item:
            line.update({
                "cadastro_status": "cadastrado",
                "compras_item_id": compras_item.get("id"),
                "material_id": (material or {}).get("id"),
            })
            registered += 1
            continue

        request_key = {
            "tenant_id": tenant_id,
            "kickoff_id": kickoff["id"],
            "bom_chave": key,
        }
        existing = await db.cadastro_bom_solicitacoes.find_one(request_key, {"_id": 0})
        if existing:
            request_doc = existing
            reused += 1
        else:
            request_doc = {
                "id": new_id(),
                **request_key,
                "numero_kickoff": kickoff.get("numero_kickoff", ""),
                "projeto_id": kickoff.get("projeto_id"),
                "cliente_id": kickoff.get("cliente_id"),
                "cliente_nome": (kickoff.get("bloco1") or {}).get("cliente", ""),
                "descricao": line.get("descricao", ""),
                "codigo_sugerido": line.get("codigo_interno", ""),
                "tipo_bom": line.get("tipo", ""),
                "unidade": line.get("unidade") or "un",
                "quantidade_por_unidade": line.get("quantidade_por_unidade") or 0,
                "quantidade_total_pedido": line.get("quantidade_total_pedido") or 0,
                "fornecedor_principal": line.get("fornecedor_principal"),
                "especificacoes": {
                    "bom": line,
                    "bloco3": kickoff.get("bloco3") or {},
                    "bloco4": kickoff.get("bloco4") or {},
                },
                "anexo_file_ids": kickoff_file_ids,
                "status": "pendente_cadastro",
                "material_id": (material or {}).get("id"),
                "compras_item_id": None,
                "demanda_compra_id": None,
                "created_by": user.get("id", ""),
                "created_by_name": user.get("name", ""),
                "created_at": now,
                "updated_at": now,
            }
            await db.cadastro_bom_solicitacoes.insert_one(request_doc)
            request_doc.pop("_id", None)
            created += 1

        line.update({
            "cadastro_status": request_doc.get("status") or "pendente_cadastro",
            "cadastro_solicitacao_id": request_doc["id"],
            "material_id": request_doc.get("material_id"),
            "compras_item_id": request_doc.get("compras_item_id"),
        })
        await _create_or_reuse_task(
            kickoff=kickoff,
            title=f"Cadastrar item novo do BOM: {line.get('descricao', '')}",
            task_code=f"cadastrar_item_bom:{request_doc['id']}",
            category="cadastros",
            due_in_days=2,
            created_by=user,
            responsible_roles=["engenharia_produto", "compras", "admin"],
            description=(
                "Item novo identificado no BOM. Anexe a ficha/especificacao, conclua o cadastro "
                "operacional e libere-o para cotacao em Compras."
            ),
            blocking=True,
        )

    pending = sum(1 for line in bom if line.get("cadastro_status") != "cadastrado")
    summary = {
        "status": "liberado_compras" if pending == 0 else "aguardando_cadastros",
        "total_bom": len(bom),
        "cadastrados": registered,
        "pendentes": pending,
        "solicitacoes_criadas": created,
        "solicitacoes_reutilizadas": reused,
        "updated_at": now,
    }
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": tenant_id},
        {"$set": {"bom": bom, "cadastro_bom": summary, "updated_at": now}},
    )
    kickoff["bom"] = bom
    kickoff["cadastro_bom"] = summary
    return summary


async def _create_homologation_tasks_for_bom(kickoff: dict, user: dict):
    for line in kickoff.get("bom", []):
        if line.get("status_homologacao") == "homologado":
            continue
        await _create_or_reuse_task(
            kickoff=kickoff,
            title=f"Homologar item do BOM {line.get('descricao', '')}",
            task_code=f"homologar_fornecedor_mp:{line.get('codigo_interno', '')}",
            category="qa",
            due_in_days=2,
            created_by=user,
            responsible_roles=["qa", "lider_pd", "admin"],
            description="Item do BOM sem homologacao concluida bloqueia aprovacao final do Kickoff.",
            blocking=False,
        )


def _validate_block3_vs_block4(bloco3: dict, bloco4: dict):
    vol3 = bloco3.get("volume_peso_liquido_valor")
    vol4 = bloco4.get("embalagem_primaria_volume_nominal")
    if vol3 not in (None, "") and vol4 not in (None, "") and float(vol3) != float(vol4):
        raise HTTPException(
            status_code=400,
            detail="O volume nominal da embalagem primaria deve coincidir com o volume/peso liquido do Bloco 3.",
        )


def _validate_kickoff_editable(kickoff: dict):
    if kickoff.get("status") == "substituida":
        raise HTTPException(status_code=409, detail="Versao substituida. Edite a versao vigente do Kickoff.")
    if kickoff.get("status") == "arquivado":
        raise HTTPException(status_code=409, detail="Kickoff arquivado nao pode ser alterado.")


async def _create_revision_version(kickoff: dict, user: dict, reason: str) -> dict:
    latest = await _get_latest_kickoff_by_group(kickoff["kickoff_group_id"], kickoff["tenant_id"])
    if latest and latest.get("id") != kickoff["id"]:
        kickoff = latest
    new_version_number = int(kickoff.get("versao_numero") or 1) + 1
    revision = _clone_value(kickoff)
    revision["id"] = new_id()
    revision["versao_numero"] = new_version_number
    revision["versao"] = _version_code(new_version_number)
    revision["status"] = "em_revisao"
    revision["aprovacoes"] = _approval_template()
    revision["created_at"] = now_iso()
    revision["updated_at"] = now_iso()
    revision["created_by"] = user["id"]
    revision["created_by_name"] = user.get("name", "")
    revision["approved_at"] = None
    revision["approved_by"] = None
    revision["approved_by_name"] = ""
    revision["parent_kickoff_id"] = kickoff["id"]
    revision["log_auditoria"] = list(kickoff.get("log_auditoria") or [])
    revision["log_auditoria"].append(
        {
            "campo": "versao",
            "valor_anterior": kickoff.get("versao"),
            "valor_novo": revision["versao"],
            "usuario_id": user["id"],
            "usuario_nome": user.get("name", ""),
            "datetime": now_iso(),
            "motivo": reason,
        }
    )
    await db.kickoffs.insert_one(revision)
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": {"status": "substituida", "updated_at": now_iso()}},
    )
    await _sync_project_kickoff_summary(revision)
    await audit_log(
        tenant_id=kickoff["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_version_created",
        entity_type="kickoff",
        entity_id=revision["id"],
        before={"kickoff_id": kickoff["id"], "versao": kickoff.get("versao")},
        after={"kickoff_id": revision["id"], "versao": revision["versao"], "motivo": reason},
    )
    return revision


async def _ensure_mutable_version(kickoff: dict, user: dict, reason: str) -> dict:
    if kickoff.get("status") == "aprovado":
        return await _create_revision_version(kickoff, user, reason)
    return kickoff


async def _decorate_kickoff(kickoff: dict) -> dict:
    kickoff = await _refresh_bom(kickoff)
    questionario = kickoff.get("questionario_composicao") or {}
    if questionario:
        q_ok, q_status = _questionario_ready(questionario)
        complete_count = sum(1 for item in q_status.values() if item["completo"])
        current_step = _current_approval_step(kickoff)
        kickoff["progress"] = {
            "questionario_composicao": q_ok,
            "percentual": round((complete_count / max(len(q_status), 1)) * 100),
        }
        kickoff["locks"] = {
            "questionario_composicao": None,
            "aprovacao": None if q_ok else "Aprovacao liberada somente apos concluir o questionario de composicao.",
        }
        kickoff["blocos_status"] = q_status
        kickoff["aprovacao_pendente"] = current_step
        return kickoff
    block2_ok, block2_missing = _block2_ready(kickoff.get("bloco2") or {})
    block3_ok, block3_missing = _block3_ready(kickoff.get("bloco3") or {})
    block4_ok, block4_missing = _block4_ready(kickoff.get("bloco4") or {})
    current_step = _current_approval_step(kickoff)
    kickoff["progress"] = {
        "bloco1": True,
        "bloco2": block2_ok,
        "bloco3": block3_ok,
        "bloco4": block4_ok,
        "percentual": round((1 + int(block2_ok) + int(block3_ok) + int(block4_ok)) / 4 * 100),
    }
    kickoff["locks"] = {
        "bloco2": None,
        "bloco3": None if block2_ok else "Bloco 3 bloqueado: complete todos os campos comerciais do Bloco 2 primeiro.",
        "bloco4": None if block3_ok else "Bloco 4 bloqueado: complete os criterios tecnicos e especificacoes do Bloco 3 primeiro.",
        "aprovacao": None if (block2_ok and block3_ok and block4_ok) else "Aprovacao liberada somente apos concluir Blocos 2, 3 e 4.",
    }
    kickoff["blocos_status"] = {
        "bloco2": {"completo": block2_ok, "campos_pendentes": block2_missing},
        "bloco3": {"completo": block3_ok, "campos_pendentes": block3_missing},
        "bloco4": {"completo": block4_ok, "campos_pendentes": block4_missing},
    }
    kickoff["aprovacao_pendente"] = current_step
    return kickoff


async def _validate_kickoff_ready_for_approval(kickoff: dict):
    questionario = kickoff.get("questionario_composicao") or {}
    if questionario:
        q_ok, q_status = _questionario_ready(questionario)
        if not q_ok:
            missing = []
            for section, info in q_status.items():
                if not info["completo"]:
                    missing.append(f"{section}: {', '.join(info['campos_pendentes'])}")
            raise HTTPException(status_code=400, detail=f"Questionario incompleto: {'; '.join(missing)}")
        return
    block2_ok, block2_missing = _block2_ready(kickoff.get("bloco2") or {})
    block3_ok, block3_missing = _block3_ready(kickoff.get("bloco3") or {})
    block4_ok, block4_missing = _block4_ready(kickoff.get("bloco4") or {})
    if not block2_ok:
        raise HTTPException(status_code=400, detail=f"Bloco 2 incompleto: {', '.join(block2_missing)}")
    if not block3_ok:
        raise HTTPException(status_code=400, detail=f"Bloco 3 incompleto: {', '.join(block3_missing)}")
    if not block4_ok:
        raise HTTPException(status_code=400, detail=f"Bloco 4 incompleto: {', '.join(block4_missing)}")
    pass


async def _mark_pd_request_kickoff_complete(kickoff: dict, user: dict) -> List[Dict[str, Any]]:
    generated: List[Dict[str, Any]] = []
    formula_ctx = await _find_formula_context(kickoff["formula_id"], kickoff["tenant_id"])
    pd_request = (formula_ctx or {}).get("pd_request") or {}
    if not pd_request:
        return generated
    await db.pd_requests.update_one(
        {"id": pd_request["id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": {"kickoff_completed": True, "updated_at": now_iso()}},
    )
    try:
        from pd_routes import _generate_live_document_version

        generated_doc = await _generate_live_document_version(
            req_id=pd_request["id"],
            doc_type="epa",
            user=user,
            reason=f"Gerado apos aprovacao final do Kickoff {kickoff['numero_kickoff']}",
            changed_fields=[
                "identificacao_produto",
                "bom_bulk_formula",
                "bom_embalagem_primaria",
                "bom_embalagem_secundaria",
                "criterios_liberacao_lote",
            ],
            trigger="kickoff_aprovado",
            source_changes=[{"field": "kickoff", "label": "Kickoff aprovado", "before": None, "after": kickoff["numero_kickoff"]}],
        )
        generated.append({"tipo": "epa", "id": generated_doc.get("id"), "version_code": generated_doc.get("version_code")})
    except Exception:
        pass
    return generated


async def create_kickoff_for_project(project_id: str, user: dict, explicit_formula_id: Optional[str] = None) -> dict:
    project, client = await _ensure_project_and_client(project_id, user["tenant_id"])
    if project.get("stage") != "pedido_aprovado":
        raise HTTPException(status_code=400, detail="O Kickoff so pode ser aberto quando o projeto estiver em Pedido Aprovado.")

    existing = await db.kickoffs.find_one(
        {
            "tenant_id": user["tenant_id"],
            "projeto_id": project_id,
            "status": {"$in": ["em_preenchimento", "aguardando_aprovacao", "aprovado", "em_revisao"]},
        },
        {"_id": 0},
        sort=[("versao_numero", -1)],
    )
    if existing:
        return await _decorate_kickoff(existing)

    formula_ctx = await _resolve_registered_formula_for_project(project_id, user["tenant_id"], explicit_formula_id)
    auto_block = await _build_kickoff_auto_block(project, client, formula_ctx)
    questionario = await _build_questionario_composicao(project, client, formula_ctx, auto_block)
    legacy_blocks = _legacy_blocks_from_questionario(questionario, {"bloco2": {}, "bloco3": {}, "bloco4": {}})
    group_id = new_id()
    kickoff = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "kickoff_group_id": group_id,
        "parent_kickoff_id": None,
        "projeto_id": project_id,
        "formula_id": formula_ctx["formula"]["id"],
        "numero_kickoff": auto_block["numero_kickoff"],
        "data_abertura": auto_block["data_abertura"],
        "versao": auto_block["versao"],
        "versao_numero": auto_block["versao_numero"],
        "status": auto_block["status"],
        "bloco1": auto_block,
        "bloco2": legacy_blocks["bloco2"],
        "bloco3": legacy_blocks["bloco3"],
        "bloco4": legacy_blocks["bloco4"],
        "questionario_composicao": questionario,
        "questionario_composicao_version": QUESTIONARIO_COMPOSICAO_VERSION,
        "bom": [],
        "aprovacoes": _approval_template(),
        "log_auditoria": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "approved_at": None,
        "approved_by": None,
        "approved_by_name": "",
    }
    await db.kickoffs.insert_one(kickoff)
    # O driver adiciona `_id` (ObjectId) ao proprio dicionario inserido. Esse
    # detalhe interno nao pode vazar para respostas JSON do FastAPI.
    kickoff.pop("_id", None)
    await _sync_project_kickoff_summary(kickoff)
    await _enqueue_block_tasks_after_create(kickoff, user)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_created",
        entity_type="kickoff",
        entity_id=kickoff["id"],
        after={
            "numero_kickoff": kickoff["numero_kickoff"],
            "projeto_id": kickoff["projeto_id"],
            "formula_id": kickoff["formula_id"],
        },
    )
    return await _decorate_kickoff(kickoff)


@kickoff_router.post("/kickoff")
async def create_kickoff(data: KickoffCreateInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, {"admin", "sales_ops", "vendedor", "lider_pd"})
    kickoff = await create_kickoff_for_project(data.projeto_id, user, data.formula_id)
    return kickoff


@kickoff_router.get("/kickoff/{kickoff_id}")
async def get_kickoff(kickoff_id: str, request: Request):
    user = await get_current_user(request)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    return await _decorate_kickoff(kickoff)


@kickoff_router.get("/kickoff/{kickoff_id}/historico")
async def kickoff_history(kickoff_id: str, request: Request):
    user = await get_current_user(request)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    history = await db.kickoffs.find(
        {"tenant_id": user["tenant_id"], "kickoff_group_id": kickoff["kickoff_group_id"]},
        {"_id": 0},
    ).sort("versao_numero", -1).to_list(100)
    return history


@kickoff_router.get("/kickoffs")
async def list_kickoffs(
    request: Request,
    status: Optional[str] = None,
    responsavel: Optional[str] = None,
    periodo_de: Optional[str] = None,
    periodo_ate: Optional[str] = None,
):
    user = await get_current_user(request)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if status:
        query["status"] = status
    docs = await db.kickoffs.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    filtered: List[Dict[str, Any]] = []
    start_dt = _parse_iso(periodo_de)
    end_dt = _parse_iso(periodo_ate)
    for doc in docs:
        if responsavel:
            current_step = _current_approval_step(doc)
            current_name = (current_step or {}).get("decidido_por_nome") or ""
            if responsavel.lower() not in f"{doc.get('created_by_name', '')} {current_name}".lower():
                continue
        opened_at = _parse_iso(doc.get("data_abertura")) or _parse_iso(doc.get("created_at"))
        if start_dt and opened_at and opened_at < start_dt:
            continue
        if end_dt and opened_at and opened_at > end_dt + timedelta(days=1):
            continue
        current_step = _current_approval_step(doc)
        filtered.append(
            {
                **doc,
                "responsavel_aprovacao_pendente": (current_step or {}).get("label"),
                "data_aprovacao": doc.get("approved_at"),
            }
        )
    return filtered


@kickoff_router.put("/kickoff/{kickoff_id}/questionario-composicao")
async def update_kickoff_questionario(kickoff_id: str, data: KickoffQuestionarioInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, {"admin", "sales_ops", "vendedor", "lider_pd", "formulador", "engenharia_produto", "qa"})
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    _validate_kickoff_editable(kickoff)
    kickoff = await _ensure_mutable_version(kickoff, user, "Alteracao no questionario de composicao apos aprovacao")

    existing = kickoff.get("questionario_composicao") or _questionario_template()
    merged = _merge_questionario(existing, data.questionario or {})
    legacy_blocks = _legacy_blocks_from_questionario(merged, kickoff)
    complete, _ = _questionario_ready(merged)

    new_status = kickoff.get("status", "em_preenchimento")
    if complete and new_status in {"em_preenchimento", "em_revisao"}:
        new_status = "aguardando_aprovacao"
    elif not complete and new_status == "aguardando_aprovacao":
        new_status = "em_preenchimento"

    changes = _diff_entries("questionario_composicao", existing, merged, user)
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {
            "$set": {
                "questionario_composicao": merged,
                "questionario_composicao_version": QUESTIONARIO_COMPOSICAO_VERSION,
                "bloco2": legacy_blocks["bloco2"],
                "bloco3": legacy_blocks["bloco3"],
                "bloco4": legacy_blocks["bloco4"],
                "status": new_status,
                "updated_at": now_iso(),
            },
            "$push": {"log_auditoria": {"$each": changes}},
        },
    )
    updated = await _get_kickoff_or_404(kickoff["id"], user["tenant_id"])
    if complete:
        await _enqueue_approval_task(updated, user, "lider_pd")
    await _sync_project_kickoff_summary(updated)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_questionario_composicao_updated",
        entity_type="kickoff",
        entity_id=updated["id"],
        before=existing,
        after=merged,
        metadata={"complete": complete, "schema_version": QUESTIONARIO_COMPOSICAO_VERSION},
    )
    return await _decorate_kickoff(updated)


@kickoff_router.delete("/kickoff/{kickoff_id}")
async def archive_kickoff(kickoff_id: str, data: KickoffDeleteInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, {"admin", "sales_ops", "vendedor"})
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    if kickoff.get("status") == "arquivado":
        return await _decorate_kickoff(kickoff)
    now = now_iso()
    await db.kickoffs.update_one(
        {"id": kickoff_id, "tenant_id": user["tenant_id"]},
        {
            "$set": {
                "status": "arquivado",
                "archived_at": now,
                "archived_by": user["id"],
                "archived_by_name": user.get("name", ""),
                "archive_reason": data.motivo or "",
                "updated_at": now,
            },
            "$push": {
                "log_auditoria": {
                    "campo": "status",
                    "valor_anterior": kickoff.get("status"),
                    "valor_novo": "arquivado",
                    "usuario_id": user["id"],
                    "usuario_nome": user.get("name", ""),
                    "datetime": now,
                    "motivo": data.motivo or "",
                }
            },
        },
    )
    updated = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    await _sync_project_kickoff_summary(updated)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_archived",
        entity_type="kickoff",
        entity_id=kickoff_id,
        before={"status": kickoff.get("status")},
        after={"status": "arquivado", "motivo": data.motivo or ""},
    )
    return await _decorate_kickoff(updated)


@kickoff_router.post("/kickoff/{kickoff_id}/restore")
async def restore_kickoff(kickoff_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, {"admin", "sales_ops", "vendedor"})
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    if kickoff.get("status") != "arquivado":
        return await _decorate_kickoff(kickoff)
    now = now_iso()
    questionario = kickoff.get("questionario_composicao") or {}
    complete, _ = _questionario_ready(questionario) if questionario else (False, {})
    restored_status = "aguardando_aprovacao" if complete else "em_preenchimento"
    await db.kickoffs.update_one(
        {"id": kickoff_id, "tenant_id": user["tenant_id"]},
        {
            "$set": {
                "status": restored_status,
                "restored_at": now,
                "restored_by": user["id"],
                "restored_by_name": user.get("name", ""),
                "updated_at": now,
            },
            "$push": {
                "log_auditoria": {
                    "campo": "status",
                    "valor_anterior": "arquivado",
                    "valor_novo": restored_status,
                    "usuario_id": user["id"],
                    "usuario_nome": user.get("name", ""),
                    "datetime": now,
                }
            },
        },
    )
    updated = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    await _sync_project_kickoff_summary(updated)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_restored",
        entity_type="kickoff",
        entity_id=kickoff_id,
        before={"status": "arquivado"},
        after={"status": restored_status},
    )
    return await _decorate_kickoff(updated)


@kickoff_router.put("/kickoff/{kickoff_id}/bloco2")
async def update_kickoff_bloco2(kickoff_id: str, data: KickoffBloco2Input, request: Request):
    user = await get_current_user(request)
    require_roles(user, BLOCK_2_ROLES)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    _validate_kickoff_editable(kickoff)
    kickoff = await _ensure_mutable_version(kickoff, user, "Alteracao no Bloco 2 apos aprovacao")
    existing = kickoff.get("bloco2") or {}
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    merged = {**existing, **updates}
    changes = _diff_entries("bloco2", existing, merged, user)
    new_status = kickoff["status"]
    if new_status == "em_revisao":
        new_status = "em_preenchimento"
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": {"bloco2": merged, "status": new_status, "updated_at": now_iso()}, "$push": {"log_auditoria": {"$each": changes}}},
    )
    kickoff = await _get_kickoff_or_404(kickoff["id"], user["tenant_id"])
    block2_ok, _ = _block2_ready(merged)
    if block2_ok:
        await _enqueue_after_block2(kickoff, user)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_bloco2_updated",
        entity_type="kickoff",
        entity_id=kickoff["id"],
        before=existing,
        after=merged,
    )
    return await _decorate_kickoff(kickoff)


@kickoff_router.put("/kickoff/{kickoff_id}/bloco3")
async def update_kickoff_bloco3(kickoff_id: str, data: KickoffBloco3Input, request: Request):
    user = await get_current_user(request)
    require_roles(user, BLOCK_3_ROLES)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    _validate_kickoff_editable(kickoff)
    kickoff = await _ensure_mutable_version(kickoff, user, "Alteracao no Bloco 3 apos aprovacao")
    block2_ok, _ = _block2_ready(kickoff.get("bloco2") or {})
    existing = kickoff.get("bloco3") or {}
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    merged = {**existing, **updates}
    if merged.get("ph_minimo") not in (None, "") and merged.get("ph_maximo") not in (None, ""):
        if float(merged["ph_minimo"]) > float(merged["ph_maximo"]):
            raise HTTPException(status_code=400, detail="ph_minimo nao pode ser maior que ph_maximo")
    changes = _diff_entries("bloco3", existing, merged, user)
    new_status = kickoff["status"]
    if new_status == "em_revisao":
        new_status = "em_preenchimento"
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": {"bloco3": merged, "status": new_status, "updated_at": now_iso()}, "$push": {"log_auditoria": {"$each": changes}}},
    )
    kickoff = await _get_kickoff_or_404(kickoff["id"], user["tenant_id"])
    block3_ok, _ = _block3_ready(merged)
    if block3_ok:
        await _enqueue_after_block3(kickoff, user)
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_bloco3_updated",
        entity_type="kickoff",
        entity_id=kickoff["id"],
        before=existing,
        after=merged,
    )
    return await _decorate_kickoff(kickoff)


@kickoff_router.put("/kickoff/{kickoff_id}/bloco4")
async def update_kickoff_bloco4(kickoff_id: str, data: KickoffBloco4Input, request: Request):
    user = await get_current_user(request)
    require_roles(user, BLOCK_4_ROLES)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    _validate_kickoff_editable(kickoff)
    kickoff = await _ensure_mutable_version(kickoff, user, "Alteracao no Bloco 4 apos aprovacao")
    existing = kickoff.get("bloco4") or {}
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    merged = {**existing, **updates}
    _validate_block3_vs_block4(kickoff.get("bloco3") or {}, merged)
    changes = _diff_entries("bloco4", existing, merged, user)
    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {"$set": {"bloco4": merged, "status": "aguardando_aprovacao", "updated_at": now_iso()}, "$push": {"log_auditoria": {"$each": changes}}},
    )
    kickoff = await _get_kickoff_or_404(kickoff["id"], user["tenant_id"])
    kickoff = await _refresh_bom(kickoff)
    await _sync_bom_registration_requests(kickoff, user)
    await _create_homologation_tasks_for_bom(kickoff, user)
    await _enqueue_approval_task(kickoff, user, "lider_pd")
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_bloco4_updated",
        entity_type="kickoff",
        entity_id=kickoff["id"],
        before=existing,
        after=merged,
        metadata={"bom_lines": len(kickoff.get("bom", []))},
    )
    return await _decorate_kickoff(kickoff)


@kickoff_router.get("/kickoff/{kickoff_id}/bom")
async def get_kickoff_bom(kickoff_id: str, request: Request):
    user = await get_current_user(request)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    kickoff = await _refresh_bom(kickoff)
    return kickoff.get("bom", [])


@kickoff_router.post("/kickoff/{kickoff_id}/bom/export")
async def export_kickoff_bom(kickoff_id: str, data: BomExportInput, request: Request):
    user = await get_current_user(request)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    kickoff = await _refresh_bom(kickoff)
    bom = kickoff.get("bom", [])
    formato = (data.formato or "csv").lower()
    if formato == "pdf":
        buffer = io.BytesIO()
        pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("KickoffBOMTitle", parent=styles["Title"], fontSize=18, textColor=rl_colors.HexColor("#111827"))
        body_style = ParagraphStyle("KickoffBOMBody", parent=styles["BodyText"], fontSize=9)
        rows = [["Codigo", "Descricao", "Tipo", "Fornecedor", "Qtd/Un", "Qtd Pedido", "Status"]]
        for line in bom:
            rows.append(
                [
                    str(line.get("codigo_interno", "")),
                    str(line.get("descricao", "")),
                    str(line.get("tipo", "")),
                    str((line.get("fornecedor_principal") or {}).get("nome", "")),
                    str(line.get("quantidade_por_unidade", "")),
                    str(line.get("quantidade_total_pedido", "")),
                    str(line.get("status_homologacao", "")),
                ]
            )
        table = Table(rows, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#E5E7EB")),
                    ("GRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#D1D5DB")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements = [
            Paragraph(f"BOM Kickoff {kickoff['numero_kickoff']} {kickoff['versao']}", title_style),
            Spacer(1, 4 * mm),
            Paragraph(f"Cliente: {kickoff.get('bloco1', {}).get('cliente', '')}", body_style),
            Spacer(1, 4 * mm),
            table,
        ]
        pdf.build(elements)
        buffer.seek(0)
        filename = f"bom_{kickoff['numero_kickoff']}_{kickoff['versao']}.pdf"
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    text_buffer = io.StringIO()
    writer = csv.writer(text_buffer)
    writer.writerow(["codigo_interno", "descricao", "tipo", "fornecedor_principal", "unidade", "quantidade_por_unidade", "quantidade_total_pedido", "status_homologacao"])
    for line in bom:
        writer.writerow(
            [
                line.get("codigo_interno", ""),
                line.get("descricao", ""),
                line.get("tipo", ""),
                (line.get("fornecedor_principal") or {}).get("nome", ""),
                line.get("unidade", ""),
                line.get("quantidade_por_unidade", ""),
                line.get("quantidade_total_pedido", ""),
                line.get("status_homologacao", ""),
            ]
        )
    byte_buffer = io.BytesIO(text_buffer.getvalue().encode("utf-8"))
    filename = f"bom_{kickoff['numero_kickoff']}_{kickoff['versao']}.csv"
    return StreamingResponse(
        byte_buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@kickoff_router.post("/kickoff/{kickoff_id}/aprovacao")
async def approve_kickoff(kickoff_id: str, data: KickoffApprovalInput, request: Request):
    user = await get_current_user(request)
    kickoff = await _get_kickoff_or_404(kickoff_id, user["tenant_id"])
    if data.etapa not in APPROVAL_SEQUENCE:
        raise HTTPException(status_code=400, detail="Etapa de aprovacao invalida")
    if data.decisao not in {"aprovado", "reprovado"}:
        raise HTTPException(status_code=400, detail="Decisao invalida")
    require_roles(user, APPROVAL_ROLE_MAP[data.etapa])
    kickoff = await _refresh_bom(kickoff)
    cadastro_summary = await _sync_bom_registration_requests(kickoff, user)
    if data.etapa == "direcao" and cadastro_summary.get("pendentes"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Aprovacao final bloqueada: existem itens novos do BOM aguardando cadastro e anexo.",
                "pendentes_cadastro": cadastro_summary.get("pendentes"),
                "acao": "Conclua os itens em Cadastros > Pendencias BOM para liberar Compras.",
            },
        )
    await _validate_kickoff_ready_for_approval(kickoff)

    current_step = _current_approval_step(kickoff)
    if not current_step:
        raise HTTPException(status_code=409, detail="O fluxo de aprovacao deste Kickoff ja foi concluido.")
    if current_step["etapa"] != data.etapa:
        raise HTTPException(
            status_code=409,
            detail=f"Etapa atual de aprovacao: {APPROVAL_LABELS[current_step['etapa']]}. Nao e permitido pular etapas.",
        )
    if data.decisao == "reprovado" and not data.justificativa:
        raise HTTPException(status_code=400, detail="Justificativa obrigatoria quando a decisao for reprovado.")

    updated_steps = []
    for step in kickoff.get("aprovacoes", []):
        if step["etapa"] == data.etapa:
            updated_steps.append(
                {
                    **step,
                    "status": "concluida" if data.decisao == "aprovado" else "reprovada",
                    "decisao": data.decisao,
                    "justificativa": data.justificativa or "",
                    "observacoes": data.observacoes or "",
                    "decidido_por": user["id"],
                    "decidido_por_nome": user.get("name", ""),
                    "decidido_em": now_iso(),
                }
            )
        else:
            updated_steps.append(step)

    status = kickoff.get("status", "aguardando_aprovacao")
    generated_docs: List[Dict[str, Any]] = []
    if data.decisao == "reprovado":
        status = "em_preenchimento"
    else:
        next_index = APPROVAL_SEQUENCE.index(data.etapa) + 1
        if next_index >= len(APPROVAL_SEQUENCE):
            status = "aprovado"
            generated_docs = await _mark_pd_request_kickoff_complete(kickoff, user)
        else:
            status = "aguardando_aprovacao"

    await db.kickoffs.update_one(
        {"id": kickoff["id"], "tenant_id": kickoff["tenant_id"]},
        {
            "$set": {
                "aprovacoes": updated_steps,
                "status": status,
                "updated_at": now_iso(),
                "approved_at": now_iso() if status == "aprovado" else kickoff.get("approved_at"),
                "approved_by": user["id"] if status == "aprovado" else kickoff.get("approved_by"),
                "approved_by_name": user.get("name", "") if status == "aprovado" else kickoff.get("approved_by_name", ""),
            },
            "$push": {
                "log_auditoria": {
                    "campo": f"aprovacao.{data.etapa}",
                    "valor_anterior": "pendente",
                    "valor_novo": data.decisao,
                    "usuario_id": user["id"],
                    "usuario_nome": user.get("name", ""),
                    "datetime": now_iso(),
                    "observacoes": data.observacoes or "",
                    "justificativa": data.justificativa or "",
                }
            },
        },
    )
    kickoff = await _get_kickoff_or_404(kickoff["id"], user["tenant_id"])
    await _sync_project_kickoff_summary(kickoff)
    if data.decisao == "reprovado":
        await _enqueue_revision_task(kickoff, user, data.etapa)
    elif status != "aprovado":
        await _enqueue_approval_task(kickoff, user, APPROVAL_SEQUENCE[APPROVAL_SEQUENCE.index(data.etapa) + 1])
    else:
        await _create_or_reuse_task(
            kickoff=kickoff,
            title=f"Gerar EPA do Kickoff {kickoff['numero_kickoff']}",
            task_code="gerar_epa",
            category="pd_dev",
            due_in_days=2,
            created_by=user,
            responsible_roles=["lider_pd", "qa", "engenharia_produto", "admin"],
            description="Kickoff aprovado: EPA foi disparado e precisa seguir fluxo de revisao.",
            blocking=False,
        )
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="kickoff_approval_decision",
        entity_type="kickoff",
        entity_id=kickoff["id"],
        before={"status": kickoff.get("status"), "etapa": data.etapa},
        after={"status": status, "etapa": data.etapa, "decisao": data.decisao},
        metadata={"generated_docs": generated_docs},
    )
    decorated = await _decorate_kickoff(kickoff)
    decorated["documentos_gerados"] = generated_docs
    return decorated
