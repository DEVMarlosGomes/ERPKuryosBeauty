#!/usr/bin/env python3
"""Build a read-only preflight for legacy commercial expedition history."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apply_firebase_clients_hml import SOURCE_SHA


EXPECTED = 338


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def values(value: Any) -> list[Any]:
    if isinstance(value, dict): return list(value.values())
    if isinstance(value, list): return value
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--client-map", type=Path, default=Path("reports/firebase_migration/CLIENT_ID_MAP.json"))
    parser.add_argument("--client-apply", type=Path, default=Path("reports/firebase_migration/CLIENT_WAVE_APPLY_RESULT.json"))
    parser.add_argument("--sku-map", type=Path, default=Path("reports/firebase_migration/SKU_ID_MAP_APPLIED.json"))
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    source = json.loads(source_bytes.decode("utf-8"))
    client_map = json.loads(args.client_map.read_text(encoding="utf-8"))
    client_apply = json.loads(args.client_apply.read_text(encoding="utf-8"))
    sku_map = json.loads(args.sku_map.read_text(encoding="utf-8"))
    if client_apply.get("status") != "APPLIED_HOMOLOGATION" or sku_map.get("status") != "APPLIED_HOMOLOGATION_VERIFIED":
        raise RuntimeError("Verified client and SKU waves are required")

    inserted_clients = {item["legacy_id"]: item["target_id"] for item in client_apply.get("operations", [])}
    client_ids = {}
    for item in client_map.get("entries", []):
        target_id = item.get("current_client_id") or inserted_clients.get(item.get("legacy_id"))
        if target_id: client_ids[item["legacy_id"]] = target_id
    clients_by_name: defaultdict[str, list[str]] = defaultdict(list)
    for legacy_id, raw in (source.get("clientes") or {}).items():
        if legacy_id in client_ids:
            for candidate in (legacy_id, raw.get("nome"), raw.get("nomeFantasia"), raw.get("razaoSocial")):
                if normalize(candidate): clients_by_name[normalize(candidate)].append(client_ids[legacy_id])

    sku_ids = {}
    for item in sku_map.get("entries", []):
        for candidate in (item.get("legacy_id"), item.get("legacy_sku"), item.get("target_codigo_interno")):
            if clean(candidate): sku_ids[clean(candidate).upper()] = item
    aliases = {clean(k).upper(): clean(v).upper() for k, v in (source.get("sku_historico") or {}).items()}
    order_keys = set((source.get("pedidos") or {}).keys())
    op_keys = set((source.get("ops") or {}).keys())

    records, classifications, statuses, types = [], Counter(), Counter(), Counter()
    item_resolution = Counter()
    for source_key, raw in sorted((source.get("expedicoes_comerciais") or {}).items()):
        blockers, analysed_items = [], []
        client_matches = list(dict.fromkeys(clients_by_name.get(normalize(raw.get("cliente")), [])))
        target_client_id = client_matches[0] if len(client_matches) == 1 else None
        if not target_client_id: blockers.append("client_unresolved" if not client_matches else "client_ambiguous")
        for index, item in enumerate(values(raw.get("itens"))):
            legacy_sku = clean(item.get("sku") or item.get("itemCodigo")).upper()
            canonical = aliases.get(legacy_sku, legacy_sku)
            sku = sku_ids.get(legacy_sku) or sku_ids.get(canonical)
            resolution = "direct" if legacy_sku in sku_ids else "alias" if canonical in sku_ids else "unresolved"
            item_resolution[resolution] += 1
            if not sku: blockers.append(f"item_{index + 1}:sku_unresolved")
            order_key = clean(item.get("skuPedidoKey") or item.get("pedidoKey"))
            op_key = clean(item.get("opKey"))
            if order_key and order_key not in order_keys: blockers.append(f"item_{index + 1}:order_unresolved")
            if op_key and op_key not in op_keys: blockers.append(f"item_{index + 1}:op_unresolved")
            analysed_items.append({
                "legacy_sku": legacy_sku, "canonical_legacy_sku": canonical,
                "sku_resolution": resolution, "target_sku_id": (sku or {}).get("target_id"),
                "legacy_order_key": order_key or None, "legacy_op_key": op_key or None,
                "quantity": item.get("qtd"), "unit": item.get("unidade"),
                "legacy_lot": item.get("loteOrigem") or item.get("opLote"),
            })
        if not analysed_items: blockers.append("empty_expedition")
        classification = "historical_archive_ready" if not blockers else "manual_review"
        legacy_status = clean(raw.get("status")) or None
        legacy_type = clean(raw.get("tipoLegado")) or None
        classifications[classification] += 1; statuses[legacy_status or "SEM_STATUS"] += 1; types[legacy_type or "SEM_TIPO"] += 1
        records.append({
            "source_key": source_key, "legacy_number": raw.get("numero"), "legacy_status": legacy_status,
            "legacy_type": legacy_type, "legacy_client": raw.get("cliente"), "target_client_id": target_client_id,
            "date": raw.get("data"), "total_units": raw.get("totalUnidades"), "total_pallets": raw.get("totalPaletes"),
            "items": analysed_items, "blockers": sorted(set(blockers)), "classification": classification,
        })
    if len(records) != EXPECTED:
        raise RuntimeError(f"Unexpected expedition count: {len(records)}")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "READ_ONLY_HML_RECONCILIATION",
        "source_sha256": SOURCE_SHA, "production_written": False, "homologation_written": False,
        "count": len(records), "classifications": dict(classifications), "statuses": dict(statuses),
        "legacy_types": dict(types), "item_resolution": dict(item_resolution), "records": records,
        "decision_gate": {"status": "READY_FOR_ISOLATED_HML_REVIEW", "stock_replay_allowed": False, "operational_activation_allowed": False},
    }
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Expedições comerciais legadas - preflight HML", "", f"Gerado em: {report['generated_at']}", "", "Modo: somente leitura. Nenhuma escrita no Mongo.", "", f"- Total: {len(records)}", f"- Classificações: `{dict(classifications)}`", f"- Tipos legados: `{dict(types)}`", "", "Nenhuma expedição poderá baixar PA, alterar pedido, criar carga, NF ou movimento de ledger nesta onda."]
    args.markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PREFLIGHT_VALID", "count": len(records), "classifications": dict(classifications), "types": dict(types), "item_resolution": dict(item_resolution)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
