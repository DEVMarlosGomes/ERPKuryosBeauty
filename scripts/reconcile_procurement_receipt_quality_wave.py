#!/usr/bin/env python3
"""Build a read-only preflight for legacy procurement, receipts and quality data."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apply_firebase_clients_hml import SOURCE_SHA


EXPECTED = {
    "purchase_request": 4,
    "purchase_order": 16,
    "receipt": 7,
    "finished_goods_check": 7,
    "nonconformity": 2,
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--supplier-apply", type=Path, default=Path("reports/firebase_migration/SUPPLIER_WAVE_APPLY_RESULT.json"))
    parser.add_argument("--material-map", type=Path, default=Path("reports/firebase_migration/MATERIAL_ID_MAP_APPLIED.json"))
    parser.add_argument("--sku-map", type=Path, default=Path("reports/firebase_migration/SKU_ID_MAP_APPLIED.json"))
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    source = json.loads(source_bytes.decode("utf-8"))
    supplier_apply = json.loads(args.supplier_apply.read_text(encoding="utf-8"))
    material_map = json.loads(args.material_map.read_text(encoding="utf-8"))
    sku_map = json.loads(args.sku_map.read_text(encoding="utf-8"))
    if supplier_apply.get("status") != "APPLIED_HOMOLOGATION":
        raise RuntimeError("Applied supplier map required")
    if material_map.get("status") != "APPLIED_HOMOLOGATION_VERIFIED":
        raise RuntimeError("Verified material map required")
    if sku_map.get("status") != "APPLIED_HOMOLOGATION_VERIFIED":
        raise RuntimeError("Verified SKU map required")

    suppliers = {item["legacy_id"]: item["target_id"] for item in supplier_apply.get("operations", [])}
    materials = {}
    for item in material_map.get("entries", []):
        for key in (item.get("legacy_id"), item.get("target_codigo_interno")):
            if clean(key):
                materials[clean(key).upper()] = item
    skus = {}
    for item in sku_map.get("entries", []):
        for key in (item.get("legacy_id"), item.get("legacy_sku"), item.get("target_codigo_interno")):
            if clean(key):
                skus[clean(key).upper()] = item

    purchase_requests = []
    for key, raw in sorted((source.get("solicitacoes_compra") or {}).items()):
        item_rows, blockers = [], []
        for item in values(raw.get("itens")):
            code = clean(item.get("materialCodigo")).upper()
            resolved = materials.get(code)
            if not resolved:
                blockers.append(f"material_unresolved:{code or 'sem_codigo'}")
            item_rows.append({"legacy_material_code": code, "target_material_id": (resolved or {}).get("target_id"), "quantity": item.get("qtd"), "unit": item.get("unidade")})
        purchase_requests.append({"source_key": key, "legacy_number": raw.get("numeroFormatado") or raw.get("numero"), "legacy_status": raw.get("status"), "items": item_rows, "blockers": sorted(set(blockers)), "classification": "archive_ready" if not blockers else "manual_review"})

    purchase_orders = []
    purchase_keys = set((source.get("pedidos_compra") or {}).keys())
    for key, raw in sorted((source.get("pedidos_compra") or {}).items()):
        supplier_id = suppliers.get(clean(raw.get("fornecedorKey")))
        blockers = [] if supplier_id else ["supplier_unresolved"]
        item_rows = []
        for item in values(raw.get("itens")):
            code = clean(item.get("materialCodigo")).upper()
            resolved = materials.get(code)
            if not resolved:
                blockers.append(f"material_unresolved:{code or 'sem_codigo'}")
            item_rows.append({"legacy_material_code": code, "target_material_id": (resolved or {}).get("target_id"), "quantity": item.get("qtd"), "received_quantity": item.get("qtdRecebida"), "unit": item.get("unidade")})
        purchase_orders.append({"source_key": key, "legacy_number": raw.get("numeroFormatado") or raw.get("numero"), "legacy_status": raw.get("status"), "target_supplier_id": supplier_id, "items": item_rows, "blockers": sorted(set(blockers)), "classification": "archive_ready" if not blockers else "manual_review"})

    receipts = []
    for actor_key, operations in sorted((source.get("recebimentos_operacoes") or {}).items()):
        for operation_key, raw in sorted((operations or {}).items()):
            po_key = clean(raw.get("pedidoKey") or (raw.get("resultado") or {}).get("pedidoKey"))
            blockers = [] if po_key in purchase_keys else ["purchase_order_unresolved"]
            lots = []
            for lot in values((raw.get("resultado") or {}).get("lotes")):
                code = clean(lot.get("materialCodigo") or lot.get("materialKey")).upper()
                resolved = materials.get(code)
                if not resolved:
                    blockers.append(f"material_unresolved:{code or 'sem_codigo'}")
                if not clean(lot.get("enderecoCodigo")):
                    blockers.append("address_missing")
                lots.append({"legacy_material_code": code, "target_material_id": (resolved or {}).get("target_id"), "legacy_lot": lot.get("loteInterno") or lot.get("loteKey"), "address_code": lot.get("enderecoCodigo"), "quantity": lot.get("quantidade"), "unit": lot.get("unidade")})
            receipts.append({"source_key": operation_key, "source_group_key": actor_key, "legacy_purchase_order_key": po_key, "legacy_status": raw.get("status"), "lots": lots, "blockers": sorted(set(blockers + ["stock_replay_prohibited"])), "classification": "historical_review"})

    finished_goods_checks = []
    for key, raw in sorted((source.get("conferencias_pa") or {}).items()):
        sku_code = clean(raw.get("sku")).upper()
        sku = skus.get(sku_code)
        blockers = [] if sku else ["sku_unresolved"]
        blockers.append("pa_stock_replay_prohibited")
        finished_goods_checks.append({"source_key": key, "legacy_status": raw.get("status"), "legacy_op_key": raw.get("opKey"), "legacy_sku": sku_code, "target_sku_id": (sku or {}).get("target_id"), "blockers": blockers, "classification": "historical_review"})

    nonconformities = []
    checks = set((source.get("conferencias_pa") or {}).keys())
    for key, raw in sorted((source.get("nao_conformidades") or {}).items()):
        check_key = clean(raw.get("conferenciaOpKey"))
        blockers = [] if check_key in checks else ["finished_goods_check_unresolved"]
        nonconformities.append({"source_key": key, "legacy_status": raw.get("status"), "legacy_check_key": check_key, "blockers": blockers, "classification": "archive_ready" if not blockers else "manual_review"})

    groups = {
        "purchase_requests": purchase_requests,
        "purchase_orders": purchase_orders,
        "receipts": receipts,
        "finished_goods_checks": finished_goods_checks,
        "nonconformities": nonconformities,
    }
    counts = {
        "purchase_request": len(purchase_requests), "purchase_order": len(purchase_orders),
        "receipt": len(receipts), "finished_goods_check": len(finished_goods_checks),
        "nonconformity": len(nonconformities),
    }
    if counts != EXPECTED:
        raise RuntimeError(f"Unexpected source counts: {counts}")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_HML_RECONCILIATION",
        "source_sha256": SOURCE_SHA,
        "production_written": False,
        "homologation_written": False,
        "counts": counts,
        "classification_counts": {name: dict(Counter(row["classification"] for row in rows)) for name, rows in groups.items()},
        **groups,
        "decision_gate": {"status": "READY_FOR_ISOLATED_HML_REVIEW", "operational_activation_allowed": False},
    }
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Compras, recebimentos e CQ - preflight HML", "", f"Gerado em: {report['generated_at']}", "",
        "Modo: somente leitura. Nenhuma escrita no Mongo.", "", "## Contagens", "",
        *[f"- `{key}`: {value}" for key, value in counts.items()], "",
        "## Regra", "", "Os documentos podem seguir apenas para filas isoladas de revisão. Recebimentos e conferências de PA não podem reproduzir saldo, lote, palete, RA ou ledger.",
    ]
    args.markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PREFLIGHT_VALID", "counts": counts, "classification_counts": report["classification_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
