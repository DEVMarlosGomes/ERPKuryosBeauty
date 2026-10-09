"""Verify the approved material/fragrance wave and unrelated HML collections."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import PLAN_ID, assert_homologation, document_hash, load_env
from create_hml_snapshot import canonical, digest_docs, digest_indexes


def docs_digest(documents: list[dict]) -> tuple[int, str]:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: str(item.get("_id"))):
        digest.update(canonical(document))
        digest.update(b"\n")
    return len(documents), digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-report", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--applied-map", required=True)
    args = parser.parse_args()
    values = load_env(Path(args.env))
    uri, database_name, tenant_id = values["ERP_HML_MONGO_URI"], values["ERP_HML_DB_NAME"], values["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    snapshot = json.loads(Path(args.snapshot_report).read_text(encoding="utf-8"))
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION":
        raise RuntimeError("Verified snapshot and applied result required")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    database = client[database_name]
    failures = []
    allowed = {"materiais", "fragrancias", "counters"}
    for name, before in snapshot["inventory"].items():
        collection = database[name]
        if name not in allowed:
            count, content_hash = digest_docs(collection)
            if count != before["count"] or content_hash != before["documents_sha256"] or digest_indexes(collection) != before["indexes_sha256"]:
                failures.append({"collection": name, "reason": "unexpected_change"})
            continue
        if digest_indexes(collection) != before["indexes_sha256"]:
            failures.append({"collection": name, "reason": "index_drift"})
        if name == "counters":
            baseline_docs = list(collection.find({
                "$or": [{"_migration.plan_id": {"$ne": PLAN_ID}}, {"_migration": {"$exists": False}}]
            }))
            count, content_hash = docs_digest(baseline_docs)
            if count != before["count"] or content_hash != before["documents_sha256"]:
                failures.append({"collection": name, "reason": "baseline_counter_drift"})
        elif before["count"] != 0:
            failures.append({"collection": name, "reason": "expected_empty_baseline"})

    marker = {"_migration.plan_id": PLAN_ID, "_migration.approved_rule": "material_wave_846_v1"}
    materials = list(database.materiais.find({"tenant_id": tenant_id, **marker}))
    fragrances = list(database.fragrancias.find({"tenant_id": tenant_id, **marker}))
    counters = list(database.counters.find({"_migration.plan_id": PLAN_ID}))
    expected_hashes = {(item["collection"], item["target_id"]): item["after_hash"] for item in applied["operations"]}
    mismatches = []
    for name, documents in (("materiais", materials), ("fragrancias", fragrances), ("counters", counters)):
        for document in documents:
            target_id = document.get("_id") if name == "counters" else document.get("id")
            comparable = dict(document)
            if name != "counters":
                comparable.pop("_id", None)
            if expected_hashes.get((name, target_id)) != document_hash(comparable):
                mismatches.append({"collection": name, "target_id": target_id})

    checks = {
        "materials": len(materials), "fragrances": len(fragrances), "counters": len(counters),
        "material_codes_unique": len({doc.get("codigo_interno") for doc in materials}) == len(materials),
        "fragrance_codes_unique": len({doc.get("codigo_interno") for doc in fragrances}) == len(fragrances),
        "operational_supplier_links_created": sum(len(doc.get("fornecedores") or []) for doc in materials + fragrances),
        "document_hash_mismatches": mismatches,
    }
    valid = (
        not failures and not mismatches and checks["materials"] == 647 and checks["fragrances"] == 199
        and checks["counters"] == 4 and checks["material_codes_unique"] and checks["fragrance_codes_unique"]
        and checks["operational_supplier_links_created"] == 0
    )
    report = {
        "status": "VERIFIED" if valid else "FAILED", "plan_id": PLAN_ID, "checks": checks,
        "unrelated_collection_failures": failures,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(allowed) - len(failures),
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.applied_map).write_text(json.dumps({
        "plan_id": PLAN_ID, "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED",
        "entries": applied["applied_material_map"], "blocked_legacy_ids": applied["blocked_legacy_ids"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
