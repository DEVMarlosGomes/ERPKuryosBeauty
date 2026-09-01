"""
Contratos Module (CGI - Contrato Geral de Industrializacao) - PDF generator.

Implements Modulo 6 of the KURYOS ERP specification.

Endpoints:
- POST /api/contratos/gerar  - generates a CGI PDF from an approved Kickoff
- POST /api/contratos/{id}/assinar - marks the CGI as signed through the official API
- GET  /api/contratos        - lists generated contracts (filterable by kickoff/cliente)
- GET  /api/contratos/{id}   - retrieves a specific contract record
- GET  /api/contratos/{id}/pdf - downloads the PDF inline

Business rules:
- The Kickoff must be in status "aprovado".
- The CONTRATANTE data is pulled from the linked client; missing legal fields
  (inscricao_estadual, endereco completo, representante_legal CPF/RG) can be
  provided as overrides in the request payload.
- The FABRICANTE block is fixed to KURYOS BEAUTY PACKING INDUSTRIAL LTDA.
- Generated contracts are persisted in the `contratos` collection. PDF/legal
  contents are immutable once generated; operational status transitions are
  recorded in status_history and audit_logs.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import io

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from rbac import require_roles
from workflow_engine import audit_log, next_sequence


contratos_router = APIRouter(prefix="/api/contratos")

db = None
get_current_user = None
new_id_func = None
now_iso_func = None


def init_contratos(database, auth_func, id_func, iso_func):
    global db, get_current_user, new_id_func, now_iso_func
    db = database
    get_current_user = auth_func
    new_id_func = id_func
    now_iso_func = iso_func


def new_id() -> str:
    return new_id_func()


def now_iso() -> str:
    return now_iso_func()


# ============ FIXED COMPANY DATA ============
KURYOS_FABRICANTE = {
    "razao_social": "KURYOS BEAUTY PACKING INDUSTRIAL LTDA",
    "cnpj": "00.767.554/0001-19",
    "endereco": "Rua Lagoa Tai Grande, n. 1130, CEP 08290-425, Sao Paulo/SP",
    "anvisa": "355030801-206-000078-1-1",
    "foro": "Comarca de Sao Paulo/SP",
}

WRITE_ROLES = {"admin", "sales_ops", "vendedor", "compras"}
READ_ROLES = {"admin", "sales_ops", "vendedor", "compras", "lider_pd", "qa", "engenharia_produto", "sucesso_cliente"}


# ============ MODELS ============
class ContratanteOverride(BaseModel):
    """Optional overrides for fields not stored on the CRM client record."""
    inscricao_estadual: Optional[str] = ""
    endereco_completo: Optional[str] = ""
    representante_nome: Optional[str] = ""
    representante_cpf: Optional[str] = ""
    representante_rg: Optional[str] = ""
    representante_cargo: Optional[str] = ""


class ContratoGerarInput(BaseModel):
    kickoff_id: str
    contratante: Optional[ContratanteOverride] = None
    observacoes: Optional[str] = ""


class ContratoAssinarInput(BaseModel):
    observacoes: Optional[str] = ""
    assinatura_ref: Optional[str] = Field(default="", description="Optional external signature/document reference")


# ============ HELPERS ============
async def _get_kickoff_aprovado(kickoff_id: str, tenant_id: str) -> dict:
    kickoff = await db.kickoffs.find_one({"id": kickoff_id, "tenant_id": tenant_id}, {"_id": 0})
    if not kickoff:
        raise HTTPException(status_code=404, detail="Kickoff nao encontrado.")
    if kickoff.get("status") != "aprovado":
        raise HTTPException(
            status_code=400,
            detail=f"Contrato so pode ser gerado a partir de Kickoff aprovado. Status atual: {kickoff.get('status')}.",
        )
    return kickoff


async def _get_client(client_id: Optional[str], tenant_id: str) -> Optional[dict]:
    if not client_id:
        return None
    return await db.crm_clients.find_one({"id": client_id, "tenant_id": tenant_id}, {"_id": 0})


async def _generate_contrato_number(tenant_id: str) -> str:
    seq = await next_sequence(tenant_id, "contrato_cgi", start=0)
    return f"CGI-{datetime.now(timezone.utc).year}-{seq:04d}"


def _format_date_br(iso_str: Optional[str]) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(iso_str)


def _format_brl(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "R$ 0,00"
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_clauses(kickoff: dict, contratante: dict) -> List[Dict[str, str]]:
    """Cláusulas 1-29 do CGI Kuryos (resumo executivo de cada cláusula).

    The full legal text of the CGI is reproduced here in a condensed,
    professional Brazilian Portuguese style. This template can be customized
    by the company's legal team without code changes (edit this function).
    """
    bloco1 = kickoff.get("bloco1") or {}
    bloco2 = kickoff.get("bloco2") or {}
    bloco3 = kickoff.get("bloco3") or {}
    produto = bloco3.get("nome_tecnico_produto") or bloco1.get("formula_vinculada") or "Produto a definir"
    volume_total = bloco2.get("volume_primeiro_pedido") or 0
    volume_mes = bloco2.get("volume_estimado_mes") or 0
    preco = bloco2.get("preco_venda_cliente_rs_un") or 0
    cond_pgto = bloco2.get("condicao_pagamento") or "a vista"
    if cond_pgto == "outro":
        cond_pgto = bloco2.get("condicao_pagamento_outro") or cond_pgto
    incoterm = bloco2.get("incoterm") or "FOB"
    prazo_entrega = _format_date_br(bloco2.get("data_entrega_contratada"))
    lead_time = bloco2.get("lead_time_producao_dias_uteis") or 0
    validade_meses = bloco2.get("prazo_validade_produto_meses") or 0
    valor_total = float(volume_total) * float(preco)

    return [
        {
            "titulo": "CLAUSULA PRIMEIRA - DO OBJETO",
            "texto": (
                f"O presente contrato tem por objeto a industrializacao, sob encomenda, do produto "
                f"<b>{produto}</b>, conforme especificacoes tecnicas detalhadas no Kickoff "
                f"{kickoff.get('numero_kickoff')} versao {kickoff.get('versao')}, anexo a este instrumento."
            ),
        },
        {
            "titulo": "CLAUSULA SEGUNDA - DAS ESPECIFICACOES TECNICAS",
            "texto": (
                "As especificacoes tecnicas do produto, criterios de liberacao de lote, parametros "
                "fisico-quimicos, microbiologicos e de embalagem sao aquelas constantes no Bloco 3 e Bloco 4 "
                "do Kickoff aprovado, considerando a Ficha Tecnica (FT) e o EPA (Especificacao de Produto Acabado) "
                "vigentes na data de emissao deste contrato."
            ),
        },
        {
            "titulo": "CLAUSULA TERCEIRA - DAS QUANTIDADES E PRAZOS",
            "texto": (
                f"O primeiro pedido contratado corresponde a {volume_total:,} unidades, com volume mensal estimado "
                f"de {volume_mes:,} unidades. O prazo contratado para entrega do primeiro pedido e {prazo_entrega}, "
                f"com lead time de producao de {lead_time} dias uteis a partir da liberacao formal pelo CONTRATANTE."
            ).replace(",", "."),
        },
        {
            "titulo": "CLAUSULA QUARTA - DO PRECO E CONDICOES DE PAGAMENTO",
            "texto": (
                f"O preco unitario praticado e de {_format_brl(preco)} por unidade, totalizando "
                f"{_format_brl(valor_total)} para o primeiro pedido. As condicoes de pagamento sao "
                f"<b>{cond_pgto}</b> a contar da emissao da nota fiscal."
            ),
        },
        {
            "titulo": "CLAUSULA QUINTA - DO TRANSPORTE E ENTREGA",
            "texto": (
                f"O regime de entrega adotado e <b>{incoterm}</b>. "
                + (f"O endereco de entrega declarado e: {bloco2.get('endereco_entrega', '')}." if incoterm == "CIF" else
                   "A retirada das mercadorias sera realizada pelo CONTRATANTE diretamente na unidade fabril da FABRICANTE.")
            ),
        },
        {
            "titulo": "CLAUSULA SEXTA - DA PROPRIEDADE INTELECTUAL",
            "texto": (
                "A formulacao desenvolvida pela FABRICANTE permanece de sua exclusiva propriedade industrial, "
                "salvo manifestacao expressa em contrario. As marcas, artes, identidade visual e direitos de "
                "imagem do CONTRATANTE permanecem de sua propriedade exclusiva."
            ),
        },
        {
            "titulo": "CLAUSULA SETIMA - DA QUALIDADE E LIBERACAO DE LOTE",
            "texto": (
                "Cada lote produzido sera submetido aos criterios de liberacao definidos no Bloco 3 do Kickoff. "
                "Os ensaios fisico-quimicos e microbiologicos serao realizados conforme plano de amostragem, "
                "com retencao obrigatoria de amostra para o periodo definido na especificacao."
            ),
        },
        {
            "titulo": "CLAUSULA OITAVA - DA VALIDADE DO PRODUTO",
            "texto": (
                f"O prazo de validade do produto acabado e de {validade_meses} meses a contar da data de fabricacao, "
                "respeitadas as condicoes de armazenamento previstas no EPA."
            ),
        },
        {
            "titulo": "CLAUSULA NONA - DAS RESPONSABILIDADES DO CONTRATANTE",
            "texto": (
                "Compete ao CONTRATANTE: (i) homologar formalmente as artes de embalagem secundaria e rotulagem; "
                "(ii) fornecer registros, notificacoes ou autorizacoes ANVISA, quando aplicavel; "
                "(iii) honrar prazos de pagamento; (iv) prover informacoes legais para rotulagem."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA - DAS RESPONSABILIDADES DA FABRICANTE",
            "texto": (
                "A FABRICANTE compromete-se a: (i) cumprir as Boas Praticas de Fabricacao (BPF) aplicaveis a industria "
                "cosmetica; (ii) manter sua autorizacao ANVISA vigente; (iii) garantir rastreabilidade integral dos lotes; "
                "(iv) entregar produto conforme as especificacoes do Kickoff aprovado."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA PRIMEIRA - DA HOMOLOGACAO DE FORNECEDORES",
            "texto": (
                "A homologacao de fornecedores de materias-primas e materiais de embalagem e prerrogativa da FABRICANTE, "
                "que adota processo proprio de qualificacao tecnica, documental e de qualidade, registrado no sistema interno."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA SEGUNDA - DAS ALTERACOES TECNICAS",
            "texto": (
                "Alteracoes em formula, embalagem ou criterios de liberacao apos a aprovacao do Kickoff exigirao "
                "nova versao formal do Kickoff, com aprovacao sequencial de Lider de P&D, CQ, Engenharia de Produto e "
                "Direcao da FABRICANTE."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA TERCEIRA - DA CONFIDENCIALIDADE",
            "texto": (
                "As partes obrigam-se a manter sigilo absoluto sobre informacoes tecnicas, comerciais e estrategicas "
                "trocadas em razao deste contrato, durante sua vigencia e por 5 (cinco) anos apos o termino, "
                "sob pena de responder por perdas e danos."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA QUARTA - DA NAO CONCORRENCIA",
            "texto": (
                "A FABRICANTE compromete-se a nao replicar a formulacao especifica desenvolvida sob este contrato "
                "para concorrentes diretos do CONTRATANTE, durante sua vigencia, salvo previa autorizacao por escrito."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA QUINTA - DAS GARANTIAS",
            "texto": (
                "A FABRICANTE garante a conformidade do produto com as especificacoes tecnicas durante todo o prazo de "
                "validade. Eventuais nao conformidades de fabricacao deverao ser comunicadas em ate 30 (trinta) dias do "
                "recebimento, sob pena de decadencia."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA SEXTA - DA RETENCAO DE AMOSTRAS",
            "texto": (
                "A FABRICANTE retera amostras de cada lote produzido pelo prazo definido no Bloco 3 do Kickoff, "
                "para fins de controle de qualidade, rastreabilidade e atendimento a eventuais auditorias."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA SETIMA - DA RECUSA DE LOTE",
            "texto": (
                "Lotes que nao atenderem aos criterios de liberacao serao retidos. O CONTRATANTE sera notificado "
                "imediatamente para alinhamento de tratativa (re-trabalho, devolucao ou destruicao)."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA OITAVA - DA SUSPENSAO E RESCISAO",
            "texto": (
                "O contrato podera ser rescindido por qualquer das partes, mediante notificacao previa de 60 (sessenta) "
                "dias. Inadimplemento contratual de qualquer das partes configurara hipotese de rescisao imediata "
                "sem prejuizo das perdas e danos cabiveis."
            ),
        },
        {
            "titulo": "CLAUSULA DECIMA NONA - DA INADIMPLENCIA",
            "texto": (
                "O atraso no pagamento sujeitara o CONTRATANTE a multa de 2% (dois por cento) sobre o valor devido, "
                "juros de 1% (um por cento) ao mes e correcao monetaria pelo IGP-M ou indice equivalente."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA - DA TRIBUTACAO",
            "texto": (
                "Os tributos incidentes sobre a operacao serao suportados na forma da legislacao vigente. O CFOP "
                "aplicavel a operacao e o de industrializacao por encomenda, salvo se outro for expressamente acordado."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA PRIMEIRA - DAS NOTIFICACOES",
            "texto": (
                "As comunicacoes oficiais entre as partes serao realizadas por meio dos contatos formais cadastrados, "
                "preferencialmente por e-mail com confirmacao de recebimento, ou por correspondencia postal com aviso "
                "de recebimento."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA SEGUNDA - DA CESSAO",
            "texto": (
                "Nenhuma das partes podera ceder, total ou parcialmente, os direitos e obrigacoes decorrentes deste "
                "contrato sem previa anuencia por escrito da outra parte."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA TERCEIRA - DO CASO FORTUITO E FORCA MAIOR",
            "texto": (
                "Nao havera responsabilizacao das partes por descumprimento decorrente de caso fortuito, forca maior, "
                "atos de autoridade ou eventos que estejam fora de seu controle razoavel."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA QUARTA - DA INDEPENDENCIA",
            "texto": (
                "Este contrato nao estabelece qualquer vinculo trabalhista, societario ou de representacao comercial "
                "entre as partes, que se mantem economicamente e juridicamente independentes."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA QUINTA - DA TOLERANCIA",
            "texto": (
                "A tolerancia, por qualquer das partes, quanto ao descumprimento de obrigacao prevista neste contrato "
                "nao implicara renuncia, novacao ou alteracao do pactuado."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA SEXTA - DA INTEGRALIDADE",
            "texto": (
                "Este instrumento, juntamente com o Kickoff aprovado, FT e EPA vinculados, representa a integralidade "
                "do acordo entre as partes, prevalecendo sobre quaisquer entendimentos verbais ou escritos anteriores."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA SETIMA - DAS ALTERACOES",
            "texto": (
                "Quaisquer alteracoes ou aditivos a este contrato deverao ser formalizados por escrito e assinados por "
                "ambas as partes, registrados no sistema de gestao da FABRICANTE."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA OITAVA - DA AUTORIZACAO ANVISA",
            "texto": (
                f"A FABRICANTE declara possuir Autorizacao de Funcionamento ANVISA n. {KURYOS_FABRICANTE['anvisa']}, "
                "vigente, atendendo aos requisitos sanitarios para fabricacao de produtos cosmeticos."
            ),
        },
        {
            "titulo": "CLAUSULA VIGESIMA NONA - DO FORO",
            "texto": (
                f"Fica eleito o foro da {KURYOS_FABRICANTE['foro']}, com renuncia expressa a qualquer outro, por "
                "mais privilegiado que seja, para dirimir quaisquer questoes oriundas do presente contrato."
            ),
        },
    ]


def _build_pdf(kickoff: dict, contratante: dict, numero_contrato: str, observacoes: str) -> bytes:
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"CGI - {numero_contrato}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CGITitle", parent=styles["Title"], fontSize=16,
        textColor=rl_colors.HexColor("#0F172A"), spaceAfter=6 * mm, alignment=1,
    )
    subtitle_style = ParagraphStyle(
        "CGISubtitle", parent=styles["Heading2"], fontSize=11,
        textColor=rl_colors.HexColor("#334155"), spaceAfter=4 * mm, alignment=1,
    )
    section_style = ParagraphStyle(
        "CGISection", parent=styles["Heading3"], fontSize=10,
        textColor=rl_colors.HexColor("#0F172A"), spaceBefore=4 * mm, spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "CGIBody", parent=styles["BodyText"], fontSize=9.5,
        leading=13, spaceAfter=2 * mm, alignment=4,  # justify
    )
    label_style = ParagraphStyle(
        "CGILabel", parent=styles["BodyText"], fontSize=9,
        textColor=rl_colors.HexColor("#475569"),
    )

    elements: List[Any] = []

    # Header
    elements.append(Paragraph("CONTRATO GERAL DE INDUSTRIALIZACAO", title_style))
    elements.append(Paragraph(f"<b>{numero_contrato}</b>", subtitle_style))
    elements.append(Spacer(1, 4 * mm))

    # Parties block
    fab = KURYOS_FABRICANTE
    parties = [
        [
            Paragraph("<b>FABRICANTE</b>", label_style),
            Paragraph(
                f"<b>{fab['razao_social']}</b><br/>"
                f"CNPJ: {fab['cnpj']}<br/>"
                f"Endereco: {fab['endereco']}<br/>"
                f"Autorizacao ANVISA: {fab['anvisa']}",
                body_style,
            ),
        ],
        [
            Paragraph("<b>CONTRATANTE</b>", label_style),
            Paragraph(
                f"<b>{contratante.get('razao_social', '')}</b><br/>"
                f"CNPJ: {contratante.get('cnpj', '')}<br/>"
                + (f"Inscricao Estadual: {contratante['inscricao_estadual']}<br/>" if contratante.get('inscricao_estadual') else "")
                + (f"Endereco: {contratante['endereco_completo']}<br/>" if contratante.get('endereco_completo') else "")
                + (f"Representante: {contratante['representante_nome']}"
                   + (f", {contratante['representante_cargo']}" if contratante.get('representante_cargo') else "")
                   + (f", CPF {contratante['representante_cpf']}" if contratante.get('representante_cpf') else "")
                   + (f", RG {contratante['representante_rg']}" if contratante.get('representante_rg') else "")
                   + "<br/>" if contratante.get('representante_nome') else ""),
                body_style,
            ),
        ],
    ]
    parties_table = Table(parties, colWidths=[35 * mm, 130 * mm])
    parties_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(parties_table)
    elements.append(Spacer(1, 5 * mm))

    # Preamble
    bloco1 = kickoff.get("bloco1") or {}
    elements.append(
        Paragraph(
            f"As partes acima identificadas, por seus representantes legais, tem, entre si, justa e acordada a "
            f"celebracao do presente <b>CONTRATO GERAL DE INDUSTRIALIZACAO (CGI)</b>, vinculado ao Kickoff "
            f"{kickoff.get('numero_kickoff')} versao {kickoff.get('versao')}, do projeto "
            f"<b>{bloco1.get('projeto_vinculado', '')}</b>, regendo-se pelas clausulas e condicoes a seguir.",
            body_style,
        )
    )
    elements.append(Spacer(1, 4 * mm))

    # Clauses
    for clause in _build_clauses(kickoff, contratante):
        elements.append(Paragraph(clause["titulo"], section_style))
        elements.append(Paragraph(clause["texto"], body_style))

    if observacoes:
        elements.append(Paragraph("OBSERVACOES ADICIONAIS", section_style))
        elements.append(Paragraph(observacoes, body_style))

    elements.append(PageBreak())

    # Signature block
    elements.append(Paragraph("DAS ASSINATURAS", section_style))
    elements.append(
        Paragraph(
            f"E por estarem assim justas e contratadas, as partes assinam o presente em duas vias de igual teor "
            f"e forma, na cidade de Sao Paulo/SP, em {datetime.now(timezone.utc).strftime('%d/%m/%Y')}.",
            body_style,
        )
    )
    elements.append(Spacer(1, 18 * mm))

    sig_table = Table(
        [
            [
                Paragraph("_______________________________________<br/><b>FABRICANTE</b><br/>"
                          f"{fab['razao_social']}<br/>CNPJ {fab['cnpj']}", body_style),
                Paragraph("_______________________________________<br/><b>CONTRATANTE</b><br/>"
                          f"{contratante.get('razao_social', '')}<br/>CNPJ {contratante.get('cnpj', '')}", body_style),
            ]
        ],
        colWidths=[82 * mm, 82 * mm],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(sig_table)
    elements.append(Spacer(1, 14 * mm))
    elements.append(
        Paragraph(
            "_______________________________________<br/><b>TESTEMUNHA 1</b><br/>Nome: ________________________ CPF: ____________________"
            "<br/><br/>"
            "_______________________________________<br/><b>TESTEMUNHA 2</b><br/>Nome: ________________________ CPF: ____________________",
            body_style,
        )
    )

    pdf.build(elements)
    buffer.seek(0)
    return buffer.read()


# ============ ENDPOINTS ============

@contratos_router.post("/gerar")
async def gerar_contrato(data: ContratoGerarInput, request: Request):
    user = await get_current_user(request)
    require_roles(user, WRITE_ROLES)
    kickoff = await _get_kickoff_aprovado(data.kickoff_id, user["tenant_id"])

    client = await _get_client(kickoff.get("projeto_id_client_id") or kickoff.get("client_id"), user["tenant_id"])
    if not client and kickoff.get("projeto_id"):
        # Try via project
        project = await db.crm_projects.find_one(
            {"id": kickoff["projeto_id"], "tenant_id": user["tenant_id"]}, {"_id": 0}
        )
        if project:
            client = await _get_client(project.get("client_id"), user["tenant_id"])

    bloco1 = kickoff.get("bloco1") or {}
    overrides = (data.contratante.dict() if data.contratante else {}) or {}

    contratante = {
        "razao_social": (client or {}).get("nome_empresa", bloco1.get("cliente", "")),
        "cnpj": (client or {}).get("cnpj", bloco1.get("cnpj", "")),
        "inscricao_estadual": overrides.get("inscricao_estadual", ""),
        "endereco_completo": overrides.get("endereco_completo", ""),
        "representante_nome": overrides.get("representante_nome", ""),
        "representante_cpf": overrides.get("representante_cpf", ""),
        "representante_rg": overrides.get("representante_rg", ""),
        "representante_cargo": overrides.get("representante_cargo", ""),
    }

    numero_contrato = await _generate_contrato_number(user["tenant_id"])
    pdf_bytes = _build_pdf(kickoff, contratante, numero_contrato, data.observacoes or "")

    contrato_doc = {
        "id": new_id(),
        "tenant_id": user["tenant_id"],
        "numero_contrato": numero_contrato,
        "kickoff_id": kickoff["id"],
        "numero_kickoff": kickoff.get("numero_kickoff"),
        "kickoff_versao": kickoff.get("versao"),
        "projeto_id": kickoff.get("projeto_id"),
        "client_id": (client or {}).get("id"),
        "contratante": contratante,
        "fabricante": KURYOS_FABRICANTE,
        "observacoes": data.observacoes or "",
        "pdf_size_bytes": len(pdf_bytes),
        "pdf_data": pdf_bytes,  # stored inline; switch to GridFS/object storage if needed
        "created_at": now_iso(),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "status": "gerado",
        "status_history": [{
            "from": None,
            "to": "gerado",
            "at": now_iso(),
            "by": user["id"],
            "by_name": user.get("name", ""),
            "observacoes": "",
        }],
        "version": 1,
    }
    await db.contratos.insert_one(contrato_doc)

    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="contrato_gerado",
        entity_type="contrato_cgi",
        entity_id=contrato_doc["id"],
        before=None,
        after={
            "numero_contrato": numero_contrato,
            "kickoff_id": kickoff["id"],
            "client_id": (client or {}).get("id"),
        },
    )

    response = {k: v for k, v in contrato_doc.items() if k not in ("_id", "pdf_data")}
    return response


@contratos_router.post("/{contrato_id}/assinar")
async def assinar_contrato(contrato_id: str, data: ContratoAssinarInput, request: Request):
    """Official CGI signature transition used by the order confirmation gate."""
    user = await get_current_user(request)
    require_roles(user, WRITE_ROLES)
    contrato = await db.contratos.find_one(
        {"id": contrato_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "pdf_data": 0}
    )
    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato nao encontrado.")

    current_status = contrato.get("status") or "gerado"
    if current_status in {"assinado", "vigente"}:
        return contrato
    if current_status not in {"gerado", "enviado"}:
        raise HTTPException(
            status_code=409,
            detail=f"Contrato em status '{current_status}' nao pode ser assinado.",
        )

    ts = now_iso()
    assinatura = {
        "status": "assinado",
        "assinado_em": ts,
        "assinado_por": user["id"],
        "assinado_por_nome": user.get("name", ""),
        "assinatura_ref": data.assinatura_ref or "",
        "observacoes": data.observacoes or "",
    }
    history = {
        "from": current_status,
        "to": "assinado",
        "at": ts,
        "by": user["id"],
        "by_name": user.get("name", ""),
        "observacoes": data.observacoes or "",
    }
    await db.contratos.update_one(
        {"id": contrato_id, "tenant_id": user["tenant_id"]},
        {"$set": {
            "status": "assinado",
            "assinatura": assinatura,
            "signed_at": ts,
            "signed_by": user["id"],
            "signed_by_name": user.get("name", ""),
            "updated_at": ts,
        }, "$push": {"status_history": history}},
    )
    await audit_log(
        tenant_id=user["tenant_id"],
        user_id=user["id"],
        user_name=user.get("name", ""),
        action="contrato_assinado",
        entity_type="contrato_cgi",
        entity_id=contrato_id,
        before={"status": current_status},
        after={"status": "assinado", "assinatura": assinatura},
        metadata={
            "kickoff_id": contrato.get("kickoff_id"),
            "projeto_id": contrato.get("projeto_id"),
            "client_id": contrato.get("client_id"),
        },
    )
    updated = await db.contratos.find_one(
        {"id": contrato_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "pdf_data": 0}
    )
    return updated


@contratos_router.get("")
async def list_contratos(
    request: Request,
    kickoff_id: Optional[str] = None,
    client_id: Optional[str] = None,
):
    user = await get_current_user(request)
    require_roles(user, READ_ROLES)
    query: Dict[str, Any] = {"tenant_id": user["tenant_id"]}
    if kickoff_id:
        query["kickoff_id"] = kickoff_id
    if client_id:
        query["client_id"] = client_id
    cursor = db.contratos.find(query, {"_id": 0, "pdf_data": 0}).sort("created_at", -1)
    docs = await cursor.to_list(500)
    return {"contratos": docs, "count": len(docs)}


@contratos_router.get("/{contrato_id}")
async def get_contrato(contrato_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, READ_ROLES)
    doc = await db.contratos.find_one(
        {"id": contrato_id, "tenant_id": user["tenant_id"]}, {"_id": 0, "pdf_data": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Contrato nao encontrado.")
    return doc


@contratos_router.get("/{contrato_id}/pdf")
async def download_contrato_pdf(contrato_id: str, request: Request):
    user = await get_current_user(request)
    require_roles(user, READ_ROLES)
    doc = await db.contratos.find_one(
        {"id": contrato_id, "tenant_id": user["tenant_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Contrato nao encontrado.")
    pdf_bytes = doc.get("pdf_data")
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="PDF do contrato indisponivel.")
    filename = f"{doc['numero_contrato']}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
