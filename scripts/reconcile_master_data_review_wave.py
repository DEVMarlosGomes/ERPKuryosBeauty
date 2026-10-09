#!/usr/bin/env python3
"""Build the deterministic review queue for blocked suppliers, materials and SKUs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apply_firebase_clients_hml import SOURCE_SHA


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--supplier-map", type=Path, default=Path("reports/firebase_migration/SUPPLIER_ID_MAP.json"))
    parser.add_argument("--material-map", type=Path, default=Path("reports/firebase_migration/MATERIAL_ID_MAP.json"))
    parser.add_argument("--material-applied", type=Path, default=Path("reports/firebase_migration/MATERIAL_ID_MAP_APPLIED.json"))
    parser.add_argument("--sku-applied", type=Path, default=Path("reports/firebase_migration/SKU_ID_MAP_APPLIED.json"))
    parser.add_argument("--json-output", type=Path, default=Path("reports/firebase_migration/MASTER_DATA_REVIEW_PREFLIGHT.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("reports/firebase_migration/MASTER_DATA_REVIEW_PREFLIGHT.md"))
    args = parser.parse_args()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")

    source = load(args.source)
    supplier_map = load(args.supplier_map)
    material_map = load(args.material_map)
    material_applied = load(args.material_applied)
    sku_applied = load(args.sku_applied)
    material_by_id = {entry["legacy_id"]: entry for entry in material_map["entries"]}

    records = []
    for entry in supplier_map["entries"]:
        if entry.get("classification") not in {"MANUAL_REVIEW", "CONFLICT"}:
            continue
        key = entry["legacy_id"]
        records.append({
            "record_type": "supplier", "source_node": "fornecedores", "source_key": key,
            "legacy_code": entry.get("normalized_cnpj") or key,
            "legacy_name": (source["fornecedores"][key].get("razaoSocial") or source["fornecedores"][key].get("nomeFantasia")),
            "classification": entry["classification"].lower(), "reason": entry.get("reason"),
            "suggested_domain": "compras_fornecedores", "required_decision": "corrigir_cnpj_ou_consolidar_duplicidade",
        })
    for key in material_applied["blocked_legacy_ids"]:
        entry = material_by_id[key]
        payload = source["materiais"][key]
        records.append({
            "record_type": "material", "source_node": "materiais", "source_key": key,
            "legacy_code": key, "legacy_name": payload.get("mpNome"),
            "classification": "manual_review", "reason": entry.get("reason"),
            "suggested_domain": entry.get("target_domain"),
            "legacy_type": entry.get("legacy_type"), "legacy_unit": payload.get("unidade"),
            "required_decision": "definir_dominio_e_unidade",
        })
    for blocked in sku_applied["blocked"]:
        key = blocked["legacy_id"]
        payload = source["produtos"][key]
        records.append({
            "record_type": "sku", "source_node": "produtos", "source_key": key,
            "legacy_code": payload.get("sku") or key, "legacy_name": payload.get("descricao"),
            "classification": "manual_review", "reason": blocked.get("reason"),
            "suggested_domain": "skus", "legacy_client_key": payload.get("clienteKey"),
            "required_decision": "resolver_cliente_e_codigo_duplicado",
        })

    expected = {"supplier": 20, "material": 93, "sku": 3}
    counts = Counter(record["record_type"] for record in records)
    if dict(counts) != expected:
        raise RuntimeError(f"Unexpected blocked counts: {dict(counts)}")
    if len({(record["source_node"], record["source_key"]) for record in records}) != len(records):
        raise RuntimeError("Duplicate source identity in review queue")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_LOCAL_RECONCILIATION",
        "production_written": False,
        "homologation_written": False,
        "source_sha256": SOURCE_SHA,
        "counts": expected,
        "total": len(records),
        "records": records,
        "decision_gate": "STAGE_AS_BLOCKED_REVIEW_ONLY",
    }
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(
        "# Master-data blocked review preflight\n\n"
        f"Generated at `{report['generated_at']}`.\n\n"
        "No MongoDB write was performed. The proposed queue contains:\n\n"
        "- **20** blocked suppliers;\n- **93** blocked materials;\n- **3** blocked SKUs.\n\n"
        "All records must remain non-operational until a human decision resolves the listed reason.\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
