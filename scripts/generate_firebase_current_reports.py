"""Generate phases E-G reports without reading or writing the ERP database.

This utility consumes the immutable Firebase export and the current workspace
source files. Target identifiers are deliberately left unresolved until an ERP
Mongo URI, database name and tenant are explicitly supplied and approved.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EXPECTED_SHA = "7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4"
STAGING_DB = "kuryos_firebase_staging_current"
REQUIRED_FILES = [
    "backend/server.py",
    "backend/crm_routes.py",
    "backend/pd_routes.py",
    "backend/produtos_routes.py",
    "backend/cadastros_master_routes.py",
    "backend/materiais_routes.py",
    "backend/fragrancias_routes.py",
    "backend/compras_routes.py",
    "backend/orders_routes.py",
    "backend/pcp_routes.py",
    "backend/estoque_routes.py",
    "backend/stock_ledger.py",
    "backend/recebimento_routes.py",
    "backend/cq_routes.py",
    "backend/expedicao_routes.py",
    "backend/rh_routes.py",
]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c for c in raw if not unicodedata.combining(c)).upper().split())


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def source_records(source: dict[str, Any], node: str) -> Iterable[tuple[str, Any]]:
    value = source.get(node, {})
    if isinstance(value, dict):
        return ((str(key), payload) for key, payload in value.items())
    return (("__root__", value),)


def duplicate_groups(records: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in records:
        key = str(record.get(field) or "")
        if key:
            grouped[key].append(record["legacy_id"])
    return [
        {field: key, "legacy_ids": ids, "count": len(ids)}
        for key, ids in sorted(grouped.items())
        if len(ids) > 1
    ]


def flatten_nested(source: dict[str, Any], node: str) -> list[dict[str, Any]]:
    flattened = []
    outer = source.get(node, {})
    if not isinstance(outer, dict):
        return flattened
    for parent_id, children in outer.items():
        if not isinstance(children, dict):
            continue
        for legacy_id, payload in children.items():
            if isinstance(payload, dict):
                flattened.append({"parent_id": str(parent_id), "legacy_id": str(legacy_id), "payload": payload})
    return flattened


def material_domain(payload: dict[str, Any]) -> tuple[str | None, str, str]:
    legacy_type = norm_text(payload.get("tipo"))
    if legacy_type == "MPGR":
        return "materiais:MP", "medium", "Tipo semantico legado MPGR; exige validacao humana, sem conversao por prefixo."
    if legacy_type == "MPES" or payload.get("casaFragrancia") or payload.get("inspiracao"):
        return "fragrancias", "medium", "Campos semanticos de essencia/fragrancia; confirmar no dominio separado."
    if legacy_type == "EP":
        return "materiais:EP", "medium", "Tipo semantico legado EP; confirmar embalagem primaria."
    if legacy_type == "ES":
        return "materiais:ES", "medium", "Tipo semantico legado ES; nomes indicam mistura de tampa/embalagem, requer revisao."
    if legacy_type == "ET":
        return "materiais:RT|ES", "low", "ET mistura etiquetas e caixas; classificacao final depende do item."
    return None, "low", "Familia legada sem correspondencia governada segura."


def safe_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect_date_anomalies(source: dict[str, Any]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    timestamp_suffixes = (
        "criadoem", "atualizadoem", "concluidoem", "abertoem", "finalizadoem",
        "canceladoem", "confirmadoem", "importadoem", "recebidoem", "emitidoem",
        "alteradoem", "encerradoem", "enviadoem", "registradoem", "apontadoem",
        "resolvidoem", "solicitadoem", "iniciadoem",
    )

    def is_date_field(path: str) -> bool:
        key = re.sub(r"\[\d+\]", "", path.rsplit(".", 1)[-1]).lower()
        return (
            key.startswith("data")
            or key in {"timestamp", "ultimaatualizacao", "ultimomovimento", "ultimoapontamento"}
            or key.endswith(timestamp_suffixes)
        )

    def visit(node: str, legacy_id: str, value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(node, legacy_id, child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(node, legacy_id, child, f"{path}[{index}]")
        elif isinstance(value, str) and is_date_field(path):
            text = value.strip()
            if not text:
                return
            year_match = re.search(r"(?:19|20)\d{2}", text)
            if not year_match:
                anomalies.append({"node": node, "legacy_id": legacy_id, "field": path, "value": text, "reason": "data_sem_ano_reconhecivel"})
                return
            year = int(year_match.group(0))
            if year < 2000 or year > 2035:
                anomalies.append({"node": node, "legacy_id": legacy_id, "field": path, "value": text, "reason": "ano_fora_da_janela_2000_2035"})

    for node, value in source.items():
        for legacy_id, payload in source_records(source, node):
            visit(node, legacy_id, payload, "")
    return anomalies


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: generate_firebase_current_reports.py SOURCE_JSON REPO_ROOT OUTPUT_DIR")
    source_path = Path(sys.argv[1]).resolve()
    repo = Path(sys.argv[2]).resolve()
    output = Path(sys.argv[3]).resolve()
    output.mkdir(parents=True, exist_ok=True)

    actual_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_sha != EXPECTED_SHA:
        raise RuntimeError(f"Firebase source SHA mismatch: {actual_sha}")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    generated_at = datetime.now(timezone.utc).isoformat()

    modules = []
    collection_union: set[str] = set()
    for relative in REQUIRED_FILES:
        path = repo / relative
        text = path.read_text(encoding="utf-8")
        collections = set(re.findall(r"(?<![A-Za-z0-9_])(?:db|database)\.([A-Za-z_][A-Za-z0-9_]*)", text))
        collections -= {"client", "command"}
        collection_union.update(collections)
        modules.append({
            "file": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "lines": len(text.splitlines()),
            "collections": sorted(collections),
            "route_count": len(re.findall(r"@[A-Za-z_][A-Za-z0-9_]*\.(?:get|post|put|patch|delete)\(", text)),
        })

    schema_report = {
        "generated_at": generated_at,
        "basis": "workspace_current_over_head_1b1ca49add9fd59fd1798deb2ad82f0a22f55d6b",
        "previous_schema_map": {"found": False, "divergence": "reports/current_erp_schema_map.json inexistente"},
        "required_files_read": modules,
        "collections_referenced": sorted(collection_union),
        "invariants": {
            "tenant_scope": "Documentos ERP usam tenant_id; matching futuro deve restringir ao tenant explicitamente aprovado.",
            "clients": "crm_clients; CNPJ exato normalizado, fallback por nome normalizado; cli4_congelado nunca sobrescrito.",
            "suppliers": "compras_fornecedores; indice unico tenant_id+cnpj_normalizado quando informado.",
            "materials": "materiais usa codigo TIPO2-SEQ5; familias governadas MP, EP, ES, RT; fragrancias e dominio separado.",
            "skus": "skus usa CAT3-CLI4-SEQ4; cli4 congela apos primeiro SKU; historicos nao devem ser renomeados.",
            "bom": "bom_items em duas camadas: bulk no produtos_pai e embalagem no SKU; versoes preservam vigencia.",
            "stock": "estoque_movimentos_lote e ledger imutavel/idempotente; estoque_saldos_lote e saldo materializado; disponivel=fisico-reservado.",
            "receiving_quality": "recebimento cria quarentena; CQ decide aprovado/reprovado/concessao e propaga para WMS/palete.",
            "orders_ops": "orders e ops possuem estados governados; consumo ocorre por lote reservado e expedicao baixa o mesmo saldo por lote.",
            "soft_delete": "Documentos operacionais correntes usam is_deleted/archived_at e ficam fora das consultas ativas.",
        },
    }
    write_json(output / "CURRENT_ERP_SCHEMA.json", schema_report)

    clients = []
    for legacy_id, payload in source_records(source, "clientes"):
        payload = payload if isinstance(payload, dict) else {}
        clients.append({
            "legacy_id": legacy_id,
            "normalized_cnpj": digits(payload.get("cnpj")),
            "normalized_name": norm_text(payload.get("nome")),
            "current_client_id": None,
            "classification": "MANUAL_REVIEW",
            "reason": "Mongo ERP/tenant nao fornecidos; matching CNPJ/nome nao executado.",
            "preserve_frozen_cli4": True,
        })
    write_json(output / "CLIENT_ID_MAP.json", {"source_node": "clientes", "entries": clients})

    suppliers = []
    supplier_cnpj_counts = Counter()
    for _, payload in source_records(source, "fornecedores"):
        if isinstance(payload, dict) and digits(payload.get("cnpj")):
            supplier_cnpj_counts[digits(payload.get("cnpj"))] += 1
    for legacy_id, payload in source_records(source, "fornecedores"):
        payload = payload if isinstance(payload, dict) else {}
        cnpj = digits(payload.get("cnpj"))
        duplicate = bool(cnpj and supplier_cnpj_counts[cnpj] > 1)
        suppliers.append({
            "legacy_id": legacy_id,
            "normalized_cnpj": cnpj,
            "normalized_name": norm_text(payload.get("razaoSocial") or payload.get("nomeFantasia")),
            "current_supplier_id": None,
            "classification": "MANUAL_REVIEW",
            "reason": "CNPJ duplicado na fonte." if duplicate else "Mongo ERP/tenant nao fornecidos; nome e apenas sugestao.",
        })
    write_json(output / "SUPPLIER_ID_MAP.json", {"source_node": "fornecedores", "entries": suppliers})

    materials = []
    for legacy_id, payload in source_records(source, "materiais"):
        payload = payload if isinstance(payload, dict) else {}
        domain, confidence, reason = material_domain(payload)
        materials.append({
            "legacy_id": legacy_id,
            "legacy_material_code": payload.get("mpCodigo") or legacy_id,
            "legacy_type": payload.get("tipo"),
            "target_domain": domain,
            "target_id": None,
            "target_codigo_interno": None,
            "confidence": confidence,
            "classification": "MANUAL_REVIEW",
            "reason": reason + " Mongo ERP/tenant nao fornecidos.",
            "firebase_sugestaoMatch_used": False,
        })
    write_json(output / "MATERIAL_ID_MAP.json", {"source_node": "materiais", "entries": materials})

    sku_entries = []
    seen_aliases = set()
    for legacy_id, payload in source_records(source, "produtos"):
        payload = payload if isinstance(payload, dict) else {}
        alias = str(payload.get("sku") or legacy_id)
        seen_aliases.add(alias)
        sku_entries.append({
            "source_node": "produtos",
            "legacy_id": legacy_id,
            "legacy_sku": alias,
            "current_sku_id": None,
            "current_codigo": None,
            "classification": "MANUAL_REVIEW",
            "reason": "SKU historico nao pode ser renomeado ou gerado automaticamente; alvo nao consultado.",
        })
    for legacy_sku, current_alias in source_records(source, "sku_historico"):
        sku_entries.append({
            "source_node": "sku_historico",
            "legacy_id": legacy_sku,
            "legacy_sku": legacy_sku,
            "firebase_alias_value": current_alias,
            "current_sku_id": None,
            "current_codigo": None,
            "classification": "MANUAL_REVIEW",
            "reason": "Alias legado preservado somente como evidencia; confirmar contra cadastro ERP.",
        })
    write_json(output / "SKU_ID_MAP.json", {"entries": sku_entries, "automatic_generation_allowed": False})

    order_entries = []
    for node in ("pedidos", "pedidos_comerciais"):
        for legacy_id, payload in source_records(source, node):
            payload = payload if isinstance(payload, dict) else {}
            order_entries.append({
                "source_node": node,
                "legacy_id": legacy_id,
                "legacy_number": payload.get("numeroFormatado") or payload.get("id") or legacy_id,
                "current_order_id": None,
                "classification": "MANUAL_REVIEW",
                "reason": "Pedido depende de cliente, SKU, CGI e tenant reconciliados.",
            })
    write_json(output / "ORDER_ID_MAP.json", {"entries": order_entries})

    op_entries = []
    for legacy_id, payload in source_records(source, "ops"):
        payload = payload if isinstance(payload, dict) else {}
        op_entries.append({
            "legacy_id": legacy_id,
            "legacy_lot": payload.get("lote"),
            "legacy_sku": payload.get("sku"),
            "current_op_id": None,
            "classification": "MANUAL_REVIEW",
            "reason": "OP depende de pedido/SKU/lote reconciliados; nao replayar apontamentos.",
        })
    write_json(output / "OP_ID_MAP.json", {"source_node": "ops", "entries": op_entries})

    address_entries = []
    for legacy_id, payload in source_records(source, "enderecos_estoque"):
        payload = payload if isinstance(payload, dict) else {}
        address_entries.append({
            "legacy_id": legacy_id,
            "legacy_code": payload.get("codigo") or legacy_id,
            "current_address_id": None,
            "classification": "MANUAL_REVIEW",
            "reason": "Endereco deve ser conferido fisicamente e contra wms_enderecos do tenant.",
        })
    write_json(output / "ADDRESS_ID_MAP.json", {"source_node": "enderecos_estoque", "entries": address_entries})

    lot_rows = flatten_nested(source, "estoque_lotes")
    lot_entries = []
    for row in lot_rows:
        payload = row["payload"]
        lot_entries.append({
            "legacy_parent_material_code": row["parent_id"],
            "legacy_id": row["legacy_id"],
            "legacy_lot": payload.get("loteInterno") or payload.get("loteOrigem") or row["legacy_id"],
            "current_lot_balance_id": None,
            "classification": "MANUAL_REVIEW",
            "reason": "Lote exige material, endereco, CQ/WMS e corte fisico reconciliados.",
        })
    write_json(output / "LOT_ID_MAP.json", {"source_node": "estoque_lotes", "entries": lot_entries})

    movements = flatten_nested(source, "movimentos_estoque")
    negative_stock = []
    for legacy_id, payload in source_records(source, "estoque"):
        payload = payload if isinstance(payload, dict) else {}
        balance = safe_number(payload.get("saldoAtual"))
        if balance is not None and balance < 0:
            negative_stock.append({"legacy_id": legacy_id, "material_code": payload.get("materialCodigo"), "saldoAtual": balance})
    ambiguous_movements = []
    for row in movements:
        payload = row["payload"]
        quantity = safe_number(payload.get("qtd"))
        movement_type = str(payload.get("tipo") or "")
        if quantity is None or quantity == 0 or (quantity > 0 and movement_type in {"consumo_producao", "qualidade"}):
            ambiguous_movements.append({
                "material_code": row["parent_id"],
                "legacy_id": row["legacy_id"],
                "tipo": movement_type,
                "qtd": quantity,
                "reason": "Sinal nao representa delta contabil com seguranca; manter apenas como historia.",
            })

    client_ids = set((source.get("clientes") or {}).keys())
    supplier_ids = set((source.get("fornecedores") or {}).keys())
    material_codes = {
        str(payload.get("mpCodigo") or legacy_id)
        for legacy_id, payload in source_records(source, "materiais")
        if isinstance(payload, dict)
    }
    product_skus = {
        str(payload.get("sku") or legacy_id)
        for legacy_id, payload in source_records(source, "produtos")
        if isinstance(payload, dict)
    }
    order_ids = set((source.get("pedidos") or {}).keys())
    address_ids = set((source.get("enderecos_estoque") or {}).keys())
    orphan_refs = []
    for legacy_id, payload in source_records(source, "produtos"):
        if isinstance(payload, dict) and payload.get("clienteKey") and payload["clienteKey"] not in client_ids:
            orphan_refs.append({"node": "produtos", "legacy_id": legacy_id, "field": "clienteKey", "value": payload["clienteKey"]})
    for node in ("formulas", "bom"):
        for legacy_id, payload in source_records(source, node):
            if isinstance(payload, dict) and payload.get("codProduto") and payload["codProduto"] not in product_skus:
                orphan_refs.append({"node": node, "legacy_id": legacy_id, "field": "codProduto", "value": payload["codProduto"]})
    for legacy_id, payload in source_records(source, "ops"):
        if not isinstance(payload, dict):
            continue
        if payload.get("sku") and payload["sku"] not in product_skus:
            orphan_refs.append({"node": "ops", "legacy_id": legacy_id, "field": "sku", "value": payload["sku"]})
        if payload.get("skuPedidoKey") and payload["skuPedidoKey"] not in order_ids:
            orphan_refs.append({"node": "ops", "legacy_id": legacy_id, "field": "skuPedidoKey", "value": payload["skuPedidoKey"]})
    for legacy_id, payload in source_records(source, "pedidos_compra"):
        if isinstance(payload, dict) and payload.get("fornecedorKey") and payload["fornecedorKey"] not in supplier_ids:
            orphan_refs.append({"node": "pedidos_compra", "legacy_id": legacy_id, "field": "fornecedorKey", "value": payload["fornecedorKey"]})
    for row in lot_rows:
        if row["parent_id"] not in material_codes:
            orphan_refs.append({"node": "estoque_lotes", "legacy_id": row["legacy_id"], "field": "material", "value": row["parent_id"]})
        endereco = row["payload"].get("enderecoKey")
        if endereco and endereco not in address_ids:
            orphan_refs.append({"node": "estoque_lotes", "legacy_id": row["legacy_id"], "field": "enderecoKey", "value": endereco})

    suspect_dates = collect_date_anomalies(source)
    stock_report = {
        "source_of_opening_balance": "physical_lots_plus_cq_wms_plus_physical_cutoff",
        "estoque_saldoAtual_allowed_as_opening": False,
        "legacy_movements_replayed": False,
        "aggregate_stock_records": len(source.get("estoque", {})),
        "physical_lot_candidates": len(lot_rows),
        "negative_legacy_stock": negative_stock,
        "ambiguous_sign_movements": ambiguous_movements,
        "orphan_references": orphan_refs,
        "suspect_dates": suspect_dates,
        "classification": "MANUAL_REVIEW",
        "reason": "Corte fisico, CQ/WMS e target ERP nao foram fornecidos/aprovados.",
    }
    write_json(output / "STOCK_RECONCILIATION.json", stock_report)

    client_dupes = duplicate_groups(clients, "normalized_cnpj") + duplicate_groups(clients, "normalized_name")
    supplier_dupes = duplicate_groups(suppliers, "normalized_cnpj")
    legacy_sku_counts = Counter(entry["legacy_sku"] for entry in sku_entries if entry.get("legacy_sku"))
    sku_dupes = [{"legacy_sku": key, "count": count} for key, count in sorted(legacy_sku_counts.items()) if count > 1]
    conflicts = {
        "client_duplicate_keys": client_dupes,
        "supplier_duplicate_cnpj": supplier_dupes,
        "legacy_sku_duplicates_or_alias_collisions": sku_dupes,
        "target_conflicts": [],
        "target_conflicts_status": "NOT_EVALUATED_TARGET_NOT_PROVIDED",
    }
    write_json(output / "CONFLICTS.json", conflicts)

    manual_review = {
        "status": "BLOCKED_AWAITING_EXPLICIT_ERP_READ_TARGET",
        "blockers": [
            "ERP Mongo URI nao fornecida explicitamente.",
            "ERP DB_NAME nao fornecido explicitamente.",
            "tenant_id alvo nao fornecido explicitamente.",
            "Corte fisico de estoque e decisao CQ/WMS nao fornecidos.",
        ],
        "queues": {
            "clients": len(clients),
            "suppliers": len(suppliers),
            "materials": len(materials),
            "skus_and_aliases": len(sku_entries),
            "orders": len(order_entries),
            "ops": len(op_entries),
            "addresses": len(address_entries),
            "lots": len(lot_entries),
            "formulas": len(source.get("formulas", {})),
            "bom": len(source.get("bom", {})),
        },
        "high_risk": {
            "negative_stock": negative_stock,
            "ambiguous_movements_count": len(ambiguous_movements),
            "orphan_references_count": len(orphan_refs),
            "suspect_dates_count": len(suspect_dates),
        },
    }
    write_json(output / "MANUAL_REVIEW.json", manual_review)

    node_counts = {
        node: len(value) if isinstance(value, (dict, list)) else 1
        for node, value in sorted(source.items())
    }
    classification_total = (
        len(clients) + len(suppliers) + len(materials) + len(sku_entries)
        + len(order_entries) + len(op_entries) + len(address_entries) + len(lot_entries)
    )
    migration_counts = {
        "source_sha256": EXPECTED_SHA,
        "staging_database": STAGING_DB,
        "staging_nodes": len(source),
        "staging_documents": sum(node_counts.values()),
        "node_counts": node_counts,
        "reconciliation": {
            "MATCH": 0,
            "INSERT_CANDIDATE": 0,
            "MERGE_CANDIDATE": 0,
            "CONFLICT": 0,
            "MANUAL_REVIEW": classification_total,
            "SKIP": 0,
            "target_evaluation_complete": False,
        },
        "domain_counts": {
            "clientes": len(clients),
            "fornecedores": len(suppliers),
            "materiais": len(materials),
            "skus_aliases": len(sku_entries),
            "formulas": len(source.get("formulas", {})),
            "bom": len(source.get("bom", {})),
            "pedidos": len(order_entries),
            "pcp_orders": len(source.get("pedidos", {})),
            "ops": len(op_entries),
            "compras": len(source.get("pedidos_compra", {})) + len(source.get("solicitacoes_compra", {})),
            "recebimentos": len(flatten_nested(source, "recebimentos_operacoes")),
            "estoque_agregado": len(source.get("estoque", {})),
            "estoque_lotes": len(lot_entries),
            "cq": len(source.get("nao_conformidades", {})) + len(source.get("conferencias_pa", {})),
            "expedicao": len(source.get("expedicoes_comerciais", {})),
            "rh": len(source.get("rh_cargos", {})) + len(source.get("usuarios", {})),
        },
    }
    write_json(output / "MIGRATION_COUNTS.json", migration_counts)

    reconciliation = {
        "status": "NOT_EXECUTED_MISSING_EXPLICIT_TARGET",
        "generated_at": generated_at,
        "mongo": {"uri": None, "db_name": None, "tenant_id": None, "mode": "READ_ONLY_NOT_STARTED"},
        "allowed_operations": ["find", "aggregate", "count", "list_indexes"],
        "write_operations_performed": [],
        "classifications": migration_counts["reconciliation"],
        "maps": {
            "clients": "CLIENT_ID_MAP.json",
            "suppliers": "SUPPLIER_ID_MAP.json",
            "materials": "MATERIAL_ID_MAP.json",
            "skus": "SKU_ID_MAP.json",
            "orders": "ORDER_ID_MAP.json",
            "ops": "OP_ID_MAP.json",
            "addresses": "ADDRESS_ID_MAP.json",
            "lots": "LOT_ID_MAP.json",
        },
        "blocking_reason": "Fase D exige URI, DB_NAME e tenant_id recebidos explicitamente; nenhum foi inferido.",
    }
    write_json(output / "RECONCILIATION_CURRENT_MONGO.json", reconciliation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
