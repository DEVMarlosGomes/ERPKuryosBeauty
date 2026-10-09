#!/usr/bin/env python3
"""Reconcile Firebase formulas/BOMs against already-applied HML ID maps.

This command is deliberately read-only: it reads the Firebase export and the
material/SKU maps and writes only local reports. It never opens a MongoDB
connection.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def version_number(value: Any) -> int | None:
    match = re.fullmatch(r"[vV]?(\d+)", clean(value))
    return int(match.group(1)) if match else None


def summarize_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--material-map",
        type=Path,
        default=Path("reports/firebase_migration/MATERIAL_ID_MAP_APPLIED.json"),
    )
    parser.add_argument(
        "--sku-map",
        type=Path,
        default=Path("reports/firebase_migration/SKU_ID_MAP_APPLIED.json"),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("reports/firebase_migration/FORMULA_BOM_WAVE_PREFLIGHT.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("reports/firebase_migration/FORMULA_BOM_WAVE_PREFLIGHT.md"),
    )
    args = parser.parse_args()

    source = load_json(args.source)
    material_map_doc = load_json(args.material_map)
    sku_map_doc = load_json(args.sku_map)

    material_by_legacy = {
        clean(entry["legacy_id"]): entry for entry in material_map_doc.get("entries", [])
    }
    blocked_materials = {clean(value) for value in material_map_doc.get("blocked_legacy_ids", [])}
    sku_by_legacy = {
        clean(entry.get("legacy_sku") or entry.get("legacy_id")): entry
        for entry in sku_map_doc.get("entries", [])
    }
    blocked_skus = {
        clean(entry.get("codigo") or entry.get("legacy_id")): entry
        for entry in sku_map_doc.get("blocked", [])
    }
    sku_aliases = {
        clean(alias): clean(canonical)
        for alias, canonical in (source.get("sku_historico") or {}).items()
        if clean(alias) and clean(canonical)
    }

    def resolve_sku(code: str) -> tuple[str, dict[str, Any] | None, str]:
        if code in sku_by_legacy:
            return code, sku_by_legacy[code], "direct"
        canonical = sku_aliases.get(code)
        if canonical and canonical in sku_by_legacy:
            return canonical, sku_by_legacy[canonical], "alias"
        if code in blocked_skus:
            return code, None, "blocked"
        return canonical or code, None, "unresolved"

    def analyse_node(node: str, code_field: str, quantity_field: str) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        item_states: Counter[str] = Counter()
        sku_states: Counter[str] = Counter()
        statuses: Counter[str] = Counter()
        versions: Counter[str] = Counter()
        blocked_codes: Counter[str] = Counter()
        source_codes: Counter[str] = Counter()
        target_sku_records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

        for source_key, raw in (source.get(node) or {}).items():
            key_sku, separator, key_version = source_key.rpartition("__")
            sku_from_payload = clean(raw.get("codProduto"))
            sku_code = sku_from_payload or (clean(key_sku) if separator else "")
            sku_code_origin = "payload" if sku_from_payload else "firebase_key"
            canonical, sku_entry, sku_state = resolve_sku(sku_code)
            sku_states[sku_state] += 1
            statuses[clean(raw.get("status")) or "SEM_STATUS"] += 1
            record_version = clean(raw.get("versao")) or (clean(key_version) if separator else "")
            versions[record_version or "SEM_VERSAO"] += 1

            state_counts: Counter[str] = Counter()
            mapped_items: list[dict[str, Any]] = []
            total_quantity = 0.0
            for item_key, item in (raw.get("itens") or {}).items():
                material_code = clean(item.get(code_field))
                quantity = as_float(item.get(quantity_field))
                pending = bool(item.get("pendente"))
                if not material_code:
                    state = "blank_pending" if pending else "blank"
                elif material_code in material_by_legacy:
                    state = "mapped_pending" if pending else "mapped"
                elif material_code in blocked_materials:
                    state = "blocked_material"
                    blocked_codes[material_code] += 1
                else:
                    state = "unresolved_material"
                    blocked_codes[material_code or "<vazio>"] += 1
                if quantity is None:
                    state = "invalid_quantity" if state == "mapped" else state
                elif quantity <= 0:
                    state = "nonpositive_quantity" if state == "mapped" else state
                elif state == "mapped":
                    total_quantity += quantity
                state_counts[state] += 1
                item_states[state] += 1
                if material_code:
                    source_codes[material_code] += 1
                if state == "mapped":
                    target = material_by_legacy[material_code]
                    mapped_items.append(
                        {
                            "source_item_key": item_key,
                            "legacy_material_code": material_code,
                            "target_material_id": target["target_id"],
                            "target_material_code": target["target_codigo_interno"],
                            "target_domain": target["target_domain"],
                            "target_type": target["target_tipo2"],
                            "quantity": quantity,
                        }
                    )

            has_items = sum(state_counts.values()) > 0
            all_items_safe = has_items and set(state_counts).issubset({"mapped"})
            percent_ok = True
            if node == "formulas":
                source_total = as_float(raw.get("somaPercentual"))
                comparison_total = source_total if source_total is not None else total_quantity
                percent_ok = abs(comparison_total - 100.0) <= 0.01
            else:
                source_total = None

            if sku_entry is None:
                classification = "blocked_sku" if sku_state == "blocked" else "unresolved_sku"
            elif not has_items:
                classification = "empty"
            elif all_items_safe and percent_ok:
                classification = "safe_full"
            elif all_items_safe and not percent_ok:
                classification = "review_total"
            else:
                classification = "partial_pending"

            record = {
                "source_key": source_key,
                "legacy_sku": sku_code,
                "legacy_sku_origin": sku_code_origin,
                "canonical_legacy_sku": canonical,
                "sku_resolution": sku_state,
                "target_sku_id": sku_entry.get("target_id") if sku_entry else None,
                "target_sku_code": sku_entry.get("target_codigo_interno") if sku_entry else None,
                "cliente_id": sku_entry.get("cliente_id") if sku_entry else None,
                "status": clean(raw.get("status")) or None,
                "version": record_version or None,
                "version_origin": "payload" if clean(raw.get("versao")) else "firebase_key",
                "version_number": version_number(record_version),
                "classification": classification,
                "item_states": dict(state_counts),
                "mapped_item_count": len(mapped_items),
                "source_total": source_total,
                "mapped_total": round(total_quantity, 8),
                "mapped_items": mapped_items,
            }
            records.append(record)
            if sku_entry:
                target_sku_records[sku_entry["target_id"]].append(record)

        classifications = Counter(record["classification"] for record in records)
        multi_version_targets = {
            sku_id: [record["source_key"] for record in target_records]
            for sku_id, target_records in target_sku_records.items()
            if len(target_records) > 1
        }
        return {
            "record_count": len(records),
            "records": records,
            "record_classifications": summarize_counter(classifications),
            "sku_resolution": summarize_counter(sku_states),
            "statuses": summarize_counter(statuses),
            "versions": summarize_counter(versions),
            "item_states": summarize_counter(item_states),
            "unique_source_material_codes": len(source_codes),
            "blocked_material_codes": summarize_counter(blocked_codes),
            "resolved_target_sku_count": len(target_sku_records),
            "targets_with_multiple_records": multi_version_targets,
        }

    formulas = analyse_node("formulas", "mpCodigo", "percentualMM")
    boms = analyse_node("bom", "materialCodigo", "qtdPorPeca")

    formula_by_sku: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    bom_by_sku: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in formulas["records"]:
        if record["target_sku_id"]:
            formula_by_sku[record["target_sku_id"]].append(record)
    for record in boms["records"]:
        if record["target_sku_id"]:
            bom_by_sku[record["target_sku_id"]].append(record)

    all_target_skus = set(formula_by_sku) | set(bom_by_sku)
    pairing = Counter()
    for sku_id in all_target_skus:
        safe_formula = any(r["classification"] == "safe_full" for r in formula_by_sku[sku_id])
        safe_bom = any(r["classification"] == "safe_full" for r in bom_by_sku[sku_id])
        if safe_formula and safe_bom:
            pairing["safe_formula_and_bom"] += 1
        elif safe_formula:
            pairing["safe_formula_only"] += 1
        elif safe_bom:
            pairing["safe_bom_only"] += 1
        else:
            pairing["no_fully_safe_pair"] += 1

    approved_safe_formula_records = [
        record for record in formulas["records"]
        if record["status"] == "APROVADA" and record["classification"] == "safe_full"
    ]
    approved_safe_bom_records = [
        record for record in boms["records"]
        if record["status"] == "APROVADA" and record["classification"] == "safe_full"
    ]
    approved_safe_formula_skus = {
        record["target_sku_id"] for record in approved_safe_formula_records
    }
    approved_safe_bom_skus = {
        record["target_sku_id"] for record in approved_safe_bom_records
    }
    approved_complete_skus = approved_safe_formula_skus & approved_safe_bom_skus

    approval_readiness = {
        "approved_safe_formula_records": len(approved_safe_formula_records),
        "approved_safe_formula_target_skus": len(approved_safe_formula_skus),
        "approved_safe_bom_records": len(approved_safe_bom_records),
        "approved_safe_bom_target_skus": len(approved_safe_bom_skus),
        "approved_complete_target_skus": len(approved_complete_skus),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_LOCAL_RECONCILIATION",
        "production_written": False,
        "mongo_connection_opened": False,
        "source_file": str(args.source),
        "material_map_status": material_map_doc.get("status"),
        "sku_map_status": sku_map_doc.get("status"),
        "mapped_material_count": len(material_by_legacy),
        "blocked_material_count": len(blocked_materials),
        "mapped_sku_count": len(sku_by_legacy),
        "blocked_sku_count": len(blocked_skus),
        "sku_alias_count": len(sku_aliases),
        "formulas": formulas,
        "boms": boms,
        "target_sku_pairing": summarize_counter(pairing),
        "approval_readiness": approval_readiness,
        "decision_gate": {
            "status": "PAUSED_BEFORE_APPLY",
            "reason": (
                "Product-parent grouping, active-version selection and treatment of partial/pending "
                "legacy rows require an explicit migration policy before HML writes."
            ),
        },
    }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    def table_rows(values: dict[str, int]) -> str:
        return "\n".join(f"| `{key}` | {value} |" for key, value in values.items())

    md = f"""# Formula/BOM wave — preflight

Generated at `{report['generated_at']}`.

## Safety boundary

- Mode: **read-only local reconciliation**.
- MongoDB connections opened: **no**.
- Production writes: **no**.
- HML writes: **no**.
- Applied maps used: {len(material_by_legacy)} materials and {len(sku_by_legacy)} SKUs.
- Decision gate: **paused before apply**.

## Formulas (bulk)

- Source records: **{formulas['record_count']}**.
- Resolved target SKUs: **{formulas['resolved_target_sku_count']}**.
- Target SKUs with more than one formula/version: **{len(formulas['targets_with_multiple_records'])}**.

| Record classification | Count |
|---|---:|
{table_rows(formulas['record_classifications'])}

| Formula item state | Count |
|---|---:|
{table_rows(formulas['item_states'])}

## BOMs (packaging)

- Source records: **{boms['record_count']}**.
- Resolved target SKUs: **{boms['resolved_target_sku_count']}**.
- Target SKUs with more than one BOM/version: **{len(boms['targets_with_multiple_records'])}**.

| Record classification | Count |
|---|---:|
{table_rows(boms['record_classifications'])}

| BOM item state | Count |
|---|---:|
{table_rows(boms['item_states'])}

## Pairing by resolved target SKU

| Situation | Count |
|---|---:|
{table_rows(report['target_sku_pairing'])}

## Approved operational readiness

| Check | Count |
|---|---:|
{table_rows(approval_readiness)}

There are **{approval_readiness['approved_complete_target_skus']}** target SKUs with both an approved, fully resolved formula and an approved, fully resolved packaging BOM. Therefore no complete legacy structure is eligible for automatic operational activation under an approval-preserving policy.

## Blocking decisions before HML apply

1. Define product-parent grouping: one parent per legacy SKU, or consolidate SKUs that truly share the same bulk formula.
2. Define which version becomes active when a target SKU has multiple formula/BOM records.
3. Decide whether rows marked `RASCUNHO` can become operational, or must remain legacy drafts.
4. Keep blank/pending and blocked-material lines outside the operational BOM until their material IDs are resolved.
5. Preserve original Firebase keys, versions, status and payload hashes as migration provenance.

No apply plan should link an SKU to a product-parent or create operational `bom_items` until these rules are approved.

Detailed per-record reconciliation is in `{args.json_output.as_posix()}`.
"""
    args.markdown_output.write_text(md, encoding="utf-8")
    print(json.dumps({
        "markdown": str(args.markdown_output),
        "json": str(args.json_output),
        "formula_classifications": formulas["record_classifications"],
        "bom_classifications": boms["record_classifications"],
        "pairing": report["target_sku_pairing"],
        "approval_readiness": approval_readiness,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
