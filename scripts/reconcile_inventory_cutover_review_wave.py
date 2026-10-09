#!/usr/bin/env python3
"""Build a read-only review queue for legacy WMS addresses and physical lots."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from apply_firebase_clients_hml import SOURCE_SHA


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--address-map", type=Path, default=Path("reports/firebase_migration/ADDRESS_ID_MAP.json"))
    parser.add_argument("--lot-map", type=Path, default=Path("reports/firebase_migration/LOT_ID_MAP.json"))
    parser.add_argument("--material-map", type=Path, default=Path("reports/firebase_migration/MATERIAL_ID_MAP_APPLIED.json"))
    parser.add_argument("--json-output", type=Path, default=Path("reports/firebase_migration/INVENTORY_CUTOVER_REVIEW_PREFLIGHT.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("reports/firebase_migration/INVENTORY_CUTOVER_REVIEW_PREFLIGHT.md"))
    args = parser.parse_args()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")

    source = load(args.source)
    address_map = load(args.address_map)
    lot_map = load(args.lot_map)
    material_map = load(args.material_map)
    material_by_legacy = {entry["legacy_id"]: entry for entry in material_map["entries"]}
    records = []

    for entry in address_map["entries"]:
        key = entry["legacy_id"]
        payload = (source.get("enderecos_estoque") or {}).get(key)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Address missing in source: {key}")
        records.append({
            "record_type": "address", "source_node": "enderecos_estoque", "source_key": key,
            "legacy_code": str(payload.get("codigo") or entry.get("legacy_code") or key),
            "legacy_name": str(payload.get("area") or payload.get("sigla") or "Endereco WMS"),
            "classification": "manual_review", "reason": entry.get("reason"),
            "required_decision": "conferencia_fisica_e_definicao_de_uso",
            "physical_status": "nao_conferido",
        })

    for entry in lot_map["entries"]:
        material_code = entry["legacy_parent_material_code"]
        lot_key = entry["legacy_id"]
        payload = ((source.get("estoque_lotes") or {}).get(material_code) or {}).get(lot_key)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Lot missing in source: {material_code}/{lot_key}")
        material = material_by_legacy.get(material_code)
        records.append({
            "record_type": "lot", "source_node": "estoque_lotes",
            "source_key": f"{material_code}::{lot_key}", "source_parent_key": material_code,
            "source_child_key": lot_key, "legacy_code": str(entry.get("legacy_lot") or lot_key),
            "legacy_name": str(payload.get("itemNome") or material_code),
            "classification": "manual_review", "reason": entry.get("reason"),
            "required_decision": "corte_fisico_cq_wms_e_saldo_inicial",
            "physical_status": "nao_conferido", "legacy_material_code": material_code,
            "target_material_id": material.get("target_id") if material else None,
            "target_material_domain": material.get("target_domain") if material else None,
            "legacy_address_code": payload.get("enderecoCodigo"),
            "legacy_quantity": payload.get("saldoLote"), "legacy_unit": payload.get("unidade"),
            "legacy_quality_status": payload.get("status"),
        })

    counts = {"address": sum(row["record_type"] == "address" for row in records),
              "lot": sum(row["record_type"] == "lot" for row in records)}
    if counts != {"address": 250, "lot": 39} or len(records) != 289:
        raise RuntimeError(f"Unexpected inventory cutover counts: {counts}")
    if len({(row["source_node"], row["source_key"]) for row in records}) != len(records):
        raise RuntimeError("Duplicate source identity in inventory cutover queue")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_LOCAL_RECONCILIATION", "production_written": False,
        "homologation_written": False, "source_sha256": SOURCE_SHA,
        "counts": counts, "total": len(records), "records": records,
        "decision_gate": "STAGE_AS_BLOCKED_PHYSICAL_REVIEW_ONLY",
    }
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(
        "# Inventory cutover review preflight\n\n"
        f"Generated at `{report['generated_at']}`. No MongoDB write was performed.\n\n"
        "- **250** WMS addresses require physical confirmation.\n"
        "- **39** lots require material/address/CQ/WMS reconciliation and a physical count.\n\n"
        "No balance, ledger movement, pallet, reservation or operational address may be created by this wave.\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
