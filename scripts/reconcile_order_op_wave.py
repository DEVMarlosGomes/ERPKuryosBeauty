#!/usr/bin/env python3
"""Read-only reconciliation of Firebase commercial orders, order lines and OPs."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apply_firebase_clients_hml import SOURCE_SHA


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def normalize_number(value: Any) -> str:
    text = clean(value)
    return str(int(text)) if text.isdigit() else text.upper()


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarized(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sku-map", type=Path, default=Path("reports/firebase_migration/SKU_ID_MAP_APPLIED.json"))
    parser.add_argument("--client-map", type=Path, default=Path("reports/firebase_migration/CLIENT_ID_MAP.json"))
    parser.add_argument("--client-apply", type=Path, default=Path("reports/firebase_migration/CLIENT_WAVE_APPLY_RESULT.json"))
    parser.add_argument("--order-map", type=Path, default=Path("reports/firebase_migration/ORDER_ID_MAP.json"))
    parser.add_argument("--op-map", type=Path, default=Path("reports/firebase_migration/OP_ID_MAP.json"))
    parser.add_argument("--snapshot-report", type=Path, default=Path("reports/firebase_migration/FORMULA_BOM_WAVE_SNAPSHOT.json"))
    parser.add_argument("--json-output", type=Path, default=Path("reports/firebase_migration/ORDER_OP_WAVE_PREFLIGHT.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("reports/firebase_migration/ORDER_OP_WAVE_PREFLIGHT.md"))
    args = parser.parse_args()

    import hashlib
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    source = load_json(args.source)
    sku_map_doc = load_json(args.sku_map)
    client_map_doc = load_json(args.client_map)
    client_apply_doc = load_json(args.client_apply)
    order_map_doc = load_json(args.order_map)
    op_map_doc = load_json(args.op_map)
    snapshot_doc = load_json(args.snapshot_report)
    if snapshot_doc.get("status") != "VERIFIED":
        raise RuntimeError("A verified HML snapshot report is required")
    sku_by_legacy = {
        clean(entry.get("legacy_sku") or entry.get("legacy_id")).upper(): entry
        for entry in sku_map_doc.get("entries", [])
    }
    aliases = {
        clean(alias).upper(): clean(canonical).upper()
        for alias, canonical in (source.get("sku_historico") or {}).items()
    }

    def resolve_sku(value: Any) -> tuple[str, dict[str, Any] | None, str]:
        code = clean(value).upper()
        if code in sku_by_legacy:
            return code, sku_by_legacy[code], "direct"
        canonical = aliases.get(code)
        if canonical in sku_by_legacy:
            return canonical, sku_by_legacy[canonical], "alias"
        return canonical or code, None, "unresolved"

    inserted_clients = {item["legacy_id"]: item["target_id"] for item in client_apply_doc.get("operations", [])}
    client_target_by_legacy = {
        entry["legacy_id"]: entry.get("current_client_id") or inserted_clients.get(entry["legacy_id"])
        for entry in client_map_doc.get("entries", [])
    }
    clients_by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for legacy_id, payload in (source.get("clientes") or {}).items():
        target_id = client_target_by_legacy.get(legacy_id)
        if target_id:
            clients_by_name[normalize_text(payload.get("nome"))].append({"id": target_id, "legacy_id": legacy_id})
    current_order_numbers = {
        normalize_number(entry.get("legacy_number"))
        for entry in order_map_doc.get("entries", [])
        if entry.get("current_order_id") and entry.get("legacy_number")
    }
    current_op_refs = {
        normalize_text(value)
        for entry in op_map_doc.get("entries", [])
        if entry.get("current_op_id")
        for value in (entry.get("legacy_id"), entry.get("legacy_lot"))
        if value
    }
    inventory = snapshot_doc["inventory"]
    target_baseline = {
        "orders": inventory.get("orders", {}).get("count", 0),
        "ops": inventory.get("ops", {}).get("count", 0),
        "clients": inventory.get("crm_clients", {}).get("count", 0),
    }

    commercial_records: list[dict[str, Any]] = []
    commercial_ids: defaultdict[str, list[str]] = defaultdict(list)
    commercial_stats: Counter[str] = Counter()
    item_stats: Counter[str] = Counter()
    for source_key, payload in sorted((source.get("pedidos_comerciais") or {}).items()):
        source_numbers = {
            normalize_number(source_key), normalize_number(payload.get("numero")), normalize_number(payload.get("numeroFormatado"))
        } - {""}
        for value in source_numbers:
            commercial_ids[value].append(source_key)
        items = payload.get("itens") or []
        if isinstance(items, dict):
            items = list(items.values())
        analysed_items = []
        inferred_clients = set()
        blockers = []
        for index, item in enumerate(items):
            canonical, sku_entry, resolution = resolve_sku(item.get("sku"))
            quantity = as_float(item.get("qtd") if item.get("qtd") is not None else item.get("quantidade"))
            item_stats[resolution] += 1
            if sku_entry:
                inferred_clients.add(sku_entry.get("cliente_id"))
            else:
                blockers.append(f"item_{index + 1}:sku_unresolved")
            if quantity is None or quantity <= 0:
                blockers.append(f"item_{index + 1}:invalid_quantity")
            analysed_items.append({
                "index": index, "legacy_sku": clean(item.get("sku")), "canonical_legacy_sku": canonical,
                "sku_resolution": resolution, "target_sku_id": sku_entry.get("target_id") if sku_entry else None,
                "target_sku_code": sku_entry.get("target_codigo_interno") if sku_entry else None,
                "cliente_id_from_sku": sku_entry.get("cliente_id") if sku_entry else None,
                "quantity": quantity, "unit_price": as_float(item.get("valorUnitario")), "description": clean(item.get("descricao")),
            })
        provided_name = normalize_text(payload.get("cliente"))
        name_matches = clients_by_name.get(provided_name, [])
        inferred_clients.discard(None)
        client_resolution = "sku_consensus" if len(inferred_clients) == 1 else "ambiguous_skus" if len(inferred_clients) > 1 else "unresolved"
        target_client_id = next(iter(inferred_clients)) if len(inferred_clients) == 1 else None
        if not target_client_id and len(name_matches) == 1:
            target_client_id = name_matches[0]["id"]
            client_resolution = "name_exact"
        if not target_client_id:
            blockers.append("client_unresolved")
        if len(inferred_clients) > 1:
            blockers.append("items_from_multiple_clients")
        if not analysed_items:
            blockers.append("empty_order")
        conflict = bool(source_numbers & current_order_numbers)
        if conflict:
            blockers.append("current_order_number_conflict")
        classification = "archive_ready" if not blockers else "manual_review"
        commercial_stats[classification] += 1
        commercial_records.append({
            "source_key": source_key, "source_numbers": sorted(source_numbers), "legacy_client": clean(payload.get("cliente")),
            "target_client_id": target_client_id, "client_resolution": client_resolution,
            "legacy_status": clean(payload.get("status")) or None, "date": payload.get("dataPedido"),
            "items": analysed_items, "item_count": len(analysed_items), "blockers": blockers,
            "classification": classification, "current_number_conflict": conflict,
        })

    line_records: list[dict[str, Any]] = []
    line_stats: Counter[str] = Counter()
    line_statuses: Counter[str] = Counter()
    line_by_key: dict[str, dict[str, Any]] = {}
    for source_key, payload in sorted((source.get("pedidos") or {}).items()):
        canonical, sku_entry, resolution = resolve_sku(payload.get("sku"))
        parent = normalize_number(payload.get("parentPedidoId") or payload.get("id"))
        commercial_matches = commercial_ids.get(parent, [])
        quantity = as_float(payload.get("qtdTotal"))
        produced = as_float(payload.get("produzido"))
        blockers = []
        if not sku_entry:
            blockers.append("sku_unresolved")
        if quantity is None or quantity <= 0:
            blockers.append("invalid_quantity")
        if len(commercial_matches) != 1:
            blockers.append("commercial_order_not_unique")
        classification = "archive_ready" if not blockers else "manual_review"
        line_stats[classification] += 1
        line_statuses[clean(payload.get("status")) or "SEM_STATUS"] += 1
        record = {
            "source_key": source_key, "legacy_parent_order": parent,
            "commercial_order_source_key": commercial_matches[0] if len(commercial_matches) == 1 else None,
            "legacy_sku": clean(payload.get("sku")), "canonical_legacy_sku": canonical,
            "sku_resolution": resolution, "target_sku_id": sku_entry.get("target_id") if sku_entry else None,
            "target_sku_code": sku_entry.get("target_codigo_interno") if sku_entry else None,
            "target_client_id": sku_entry.get("cliente_id") if sku_entry else None,
            "quantity": quantity, "produced": produced, "legacy_status": clean(payload.get("status")) or None,
            "classification": classification, "blockers": blockers,
        }
        line_records.append(record)
        line_by_key[source_key] = record

    op_records: list[dict[str, Any]] = []
    op_stats: Counter[str] = Counter()
    op_statuses: Counter[str] = Counter()
    active_op_count = 0
    for source_key, payload in sorted((source.get("ops") or {}).items()):
        canonical, sku_entry, resolution = resolve_sku(payload.get("sku"))
        line_key = clean(payload.get("skuPedidoKey"))
        linked_line = line_by_key.get(line_key)
        planned = as_float(payload.get("qtdPlanejada"))
        produced = as_float(payload.get("produzido"))
        status = clean(payload.get("status"))
        normalized_status = normalize_text(status)
        terminal = normalized_status.startswith("CONCLU") or normalized_status.startswith("CANCEL")
        if not terminal:
            active_op_count += 1
        blockers = []
        if not sku_entry:
            blockers.append("sku_unresolved")
        if planned is None or planned <= 0:
            blockers.append("invalid_planned_quantity")
        if not linked_line:
            blockers.append("order_line_unresolved")
        elif linked_line.get("target_sku_id") != (sku_entry or {}).get("target_id"):
            blockers.append("op_order_line_sku_mismatch")
        references = {normalize_text(source_key), normalize_text(payload.get("lote"))} - {""}
        conflict = bool(references & current_op_refs)
        if conflict:
            blockers.append("current_op_reference_conflict")
        classification = "historical_archive_ready" if terminal and not blockers else "open_requires_decision" if not terminal else "manual_review"
        op_stats[classification] += 1
        op_statuses[status or "SEM_STATUS"] += 1
        op_records.append({
            "source_key": source_key, "legacy_lot": clean(payload.get("lote")), "legacy_status": status or None,
            "is_terminal": terminal, "legacy_sku": clean(payload.get("sku")), "canonical_legacy_sku": canonical,
            "sku_resolution": resolution, "target_sku_id": sku_entry.get("target_id") if sku_entry else None,
            "target_sku_code": sku_entry.get("target_codigo_interno") if sku_entry else None,
            "order_line_source_key": line_key or None, "order_line_resolved": bool(linked_line),
            "planned": planned, "produced": produced, "classification": classification,
            "blockers": blockers, "current_reference_conflict": conflict,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "READ_ONLY_HML_RECONCILIATION",
        "production_written": False, "homologation_written": False, "source_sha256": SOURCE_SHA,
        "target_baseline": target_baseline,
        "commercial_orders": {"count": len(commercial_records), "classifications": summarized(commercial_stats), "item_resolution": summarized(item_stats), "records": commercial_records},
        "order_lines": {"count": len(line_records), "classifications": summarized(line_stats), "statuses": summarized(line_statuses), "records": line_records},
        "ops": {"count": len(op_records), "classifications": summarized(op_stats), "statuses": summarized(op_statuses), "open_nonterminal": active_op_count, "records": op_records},
        "decision_gate": {
            "status": "PAUSED_BEFORE_APPLY",
            "reason": "Historical records may be archived, but non-terminal OPs require an explicit cutoff/activation policy and no stock movements will be replayed automatically.",
        },
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def rows(values: dict[str, int]) -> str:
        return "\n".join(f"| `{key}` | {value} |" for key, value in values.items())

    md = f"""# Orders and OP wave — preflight

Generated at `{report['generated_at']}`.

## Safety boundary

- Mode: **read-only reconciliation against HML**.
- Production writes: **no**.
- Homologation writes: **no**.
- Verified HML snapshot baseline: **{target_baseline['orders']} orders**, **{target_baseline['ops']} OPs**, **{target_baseline['clients']} clients**.
- Decision gate: **paused before apply**.

## Commercial orders

- Source commercial orders: **{len(commercial_records)}**.

| Classification | Count |
|---|---:|
{rows(summarized(commercial_stats))}

| Item SKU resolution | Count |
|---|---:|
{rows(summarized(item_stats))}

## Production order lines

- Source order lines: **{len(line_records)}**.

| Classification | Count |
|---|---:|
{rows(summarized(line_stats))}

| Legacy status | Count |
|---|---:|
{rows(summarized(line_statuses))}

## Production orders (OPs)

- Source OPs: **{len(op_records)}**.
- Non-terminal OPs requiring an explicit business decision: **{active_op_count}**.

| Classification | Count |
|---|---:|
{rows(summarized(op_stats))}

| Legacy status | Count |
|---|---:|
{rows(summarized(op_statuses))}

## Recommended controlled policy

1. Import terminal orders/OPs only as immutable legacy history, with no inventory, reservation, ledger or accounting side effects.
2. Keep non-terminal OPs in a review queue; do not schedule or consume stock automatically.
3. Preserve the commercial-order → order-line → OP relationship when uniquely resolved.
4. Do not fabricate CGI, approval, BOM, lot balance, PA pallet or shipment events.
5. Promote an open legacy demand only through a separate reviewed action that validates current SKU/BOM and available stock.

Detailed per-record reconciliation is in `{args.json_output.as_posix()}`.
"""
    args.markdown_output.write_text(md, encoding="utf-8")
    print(json.dumps({
        "commercial_orders": report["commercial_orders"]["classifications"],
        "order_lines": report["order_lines"]["classifications"],
        "ops": report["ops"]["classifications"],
        "open_nonterminal_ops": active_op_count,
        "markdown": str(args.markdown_output), "json": str(args.json_output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
