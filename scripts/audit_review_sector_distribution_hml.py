#!/usr/bin/env python3
"""Read-only audit and routing plan for every legacy review document in HML."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, load_env
from review_sector_routing import COLLECTIONS, canonical_hash, route, source_identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    database = client[database_name]
    records = []
    ids = defaultdict(list)
    identities = defaultdict(list)
    collection_counts = Counter()
    sector_counts = Counter()
    current_sector_counts = Counter()
    updates = 0

    for collection_name in COLLECTIONS:
        documents = list(database[collection_name].find({"tenant_id": tenant_id}, {"_id": 0}))
        collection_counts[collection_name] = len(documents)
        for document in documents:
            desired = route(collection_name, document)
            current = document.get("assigned_sector")
            if current:
                current_sector_counts[str(current)] += 1
                if any(document.get(key) != value for key, value in desired.items()):
                    raise RuntimeError(f"Existing routing divergence: {collection_name}/{document.get('id')}")
            else:
                updates += 1
            sector_counts[desired["assigned_sector"]] += 1
            identity = source_identity(document)
            ids[str(document.get("id"))].append(collection_name)
            identities[identity].append(f"{collection_name}/{document.get('id')}")
            records.append({
                "collection": collection_name,
                "id": document.get("id"),
                "source_identity": identity,
                "source_node": document.get("source_node"),
                "source_key": document.get("source_key"),
                "record_type": document.get("record_type"),
                "review_status": document.get("review_status"),
                "current_sector": current,
                "needs_update": not bool(current),
                "before_hash": canonical_hash(document),
                "original_updated_at": document.get("updated_at"),
                "desired": desired,
            })

    duplicate_ids = {key: value for key, value in ids.items() if len(value) > 1}
    duplicate_identities = {key: value for key, value in identities.items() if len(value) > 1}
    if duplicate_ids or duplicate_identities:
        raise RuntimeError(f"Duplicate reviews found: ids={len(duplicate_ids)}, identities={len(duplicate_identities)}")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_HML_REVIEW_SECTOR_AUDIT",
        "production_written": False,
        "homologation_written": False,
        "target": {"database": database_name, "tenant_id": tenant_id},
        "total_reviews": len(records),
        "already_dispatched": len(records) - updates,
        "planned_updates": updates,
        "duplicate_ids": duplicate_ids,
        "duplicate_source_identities": duplicate_identities,
        "collection_counts": dict(collection_counts),
        "current_sector_counts": dict(current_sector_counts),
        "planned_sector_counts": dict(sorted(sector_counts.items())),
        "records": records,
        "decision_gate": {"status": "READY_FOR_ATOMIC_SECTOR_DISTRIBUTION", "create_copies": False},
    }
    Path(args.json_output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Auditoria das filas legadas por setor — HML",
        "",
        f"Gerado em: {report['generated_at']}",
        "",
        f"- Registros auditados: **{len(records)}**",
        f"- Já encaminhados: **{report['already_dispatched']}**",
        f"- Encaminhamentos pendentes: **{updates}**",
        "- IDs duplicados: **0**",
        "- Identidades de origem duplicadas: **0**",
        "",
        "## Destino final por setor",
        "",
        *[f"- `{sector}`: {count}" for sector, count in sorted(sector_counts.items())],
        "",
        "## Localização atual por coleção",
        "",
        *[f"- `{name}`: {count}" for name, count in collection_counts.items()],
        "",
        "O plano atualiza os próprios documentos. Nenhuma cópia, saldo, movimento, OP, pedido ou usuário será criado.",
    ]
    Path(args.markdown_output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
