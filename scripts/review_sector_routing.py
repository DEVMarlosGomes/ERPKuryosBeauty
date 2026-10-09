#!/usr/bin/env python3
"""Shared, deterministic sector routing for Firebase legacy review queues."""
from __future__ import annotations

import hashlib
import json
from typing import Any


COLLECTIONS = (
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

DISPATCH_RULE = "firebase_review_sector_distribution_v1"
ROUTING_FIELDS = (
    "assigned_sector", "next_sector", "review_stage", "sector_status",
    "dispatched_at", "dispatch_rule", "sector_history",
)


def canonical_hash(document: dict) -> str:
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def source_identity(document: dict) -> str:
    node = str(document.get("source_node") or "")
    group = str(document.get("source_group_key") or "")
    key = str(document.get("source_key") or document.get("legacy_id") or document.get("id") or "")
    return f"{node}|{group}|{key}"


def route(collection: str, document: dict) -> dict[str, Any]:
    record_type = str(document.get("record_type") or "")
    source_node = str(document.get("source_node") or "")

    if collection == "legacy_master_data_reviews":
        if record_type == "supplier":
            return _route("compras", "cadastros", "saneamento_fornecedor_legado")
        return _route("cadastros", None, f"saneamento_{record_type}_legado")
    if collection == "legacy_formula_bom_reviews":
        if record_type == "formula":
            return _route("pd", "cadastros", "validacao_formula_legada")
        return _route("cadastros", "compras", "validacao_bom_legado")
    if collection == "legacy_order_reviews":
        return _route("comercial", "pcp", f"validacao_{record_type}_legado")
    if collection == "legacy_op_reviews":
        return _route("pcp", None, "validacao_op_legada")
    if collection == "legacy_inventory_cutover_reviews":
        if record_type == "address":
            return _route("logistica", None, "conferencia_endereco_wms")
        return _route("qualidade", "logistica", "validacao_cq_lote_legado")
    if collection == "legacy_procurement_reviews":
        return _route("compras", None, f"validacao_{record_type}_legado")
    if collection == "legacy_receipt_reviews":
        return _route("qualidade", "logistica", "validacao_recebimento_legado")
    if collection == "legacy_quality_reviews":
        return _route("qualidade", None, f"validacao_{record_type}_legado")
    if collection == "legacy_expedition_reviews":
        return _route("expedicao", None, "validacao_expedicao_legada")
    if collection == "legacy_hr_reviews":
        status = "concluido" if document.get("review_status") == "promovido" else "pendente"
        return _route("rh", None, f"validacao_{record_type}_legado", status)
    if collection == "legacy_supplemental_history_reviews":
        if record_type == "specification":
            return _route("qualidade", "cadastros", "validacao_especificacao_legada")
        if record_type == "sale_price":
            return _route("comercial", None, "validacao_preco_venda_legado")
        if record_type == "quotation_process":
            return _route("compras", None, "validacao_cotacao_legada")
        return _route("pcp", None, f"validacao_{record_type}_legado")
    if collection == "legacy_source_archive_reviews":
        by_node = {
            "ajustes_planejamento": ("pcp", None),
            "comercial_eventos": ("comercial", None),
            "config": ("administracao_ti", None),
            "contadores_lote_interno": ("cadastros", None),
            "email_notifications_state": ("administracao_ti", None),
            "emails_diretoria": ("administracao_ti", None),
            "estado_linhas": ("pcp", None),
            "estoque": ("logistica", None),
            "estrutura_ruas": ("logistica", None),
            "historico_materiais": ("logistica", None),
            "insumos": ("logistica", None),
            "movimentos_estoque": ("logistica", None),
            "notificacoes_comercial": ("comercial", None),
            "notificacoes_op_encerrada": ("pcp", None),
            "parametros_pa": ("qualidade", "cadastros"),
            "registros": ("pcp", None),
        }
        if source_node not in by_node:
            raise RuntimeError(f"No archive route for source node: {source_node}")
        sector, next_sector = by_node[source_node]
        return _route(sector, next_sector, f"auditoria_historica_{source_node}")
    raise RuntimeError(f"No routing rule for {collection}/{record_type}")


def _route(sector: str, next_sector: str | None, stage: str, status: str = "pendente") -> dict[str, Any]:
    return {"assigned_sector": sector, "next_sector": next_sector, "review_stage": stage, "sector_status": status}
