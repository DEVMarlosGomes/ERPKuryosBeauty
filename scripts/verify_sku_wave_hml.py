"""Verify the legacy-authorized SKU wave and unrelated HML collections."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import PLAN_ID, assert_homologation, document_hash, load_env
from apply_firebase_legacy_skus_hml import SKU_RULE
from create_hml_snapshot import canonical, digest_docs, digest_indexes


def docs_digest(documents: list[dict]) -> tuple[int, str]:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: str(item.get("_id"))):
        digest.update(canonical(document)); digest.update(b"\n")
    return len(documents), digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-report", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--applied-map", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    snapshot = json.loads(Path(args.snapshot_report).read_text(encoding="utf-8"))
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION":
        raise RuntimeError("Verified snapshot and applied SKU result required")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    database = client[database_name]
    failures = []
    for name, before in snapshot["inventory"].items():
        collection = database[name]
        if name not in {"skus", "counters"}:
            count, content_hash = digest_docs(collection)
            if count != before["count"] or content_hash != before["documents_sha256"] or digest_indexes(collection) != before["indexes_sha256"]:
                failures.append({"collection": name, "reason": "unexpected_change"})
            continue
        if digest_indexes(collection) != before["indexes_sha256"]:
            failures.append({"collection": name, "reason": "index_drift"})
        if name == "counters":
            baseline = list(collection.find({
                "$or": [{"_migration.approved_rule": {"$ne": SKU_RULE}}, {"_migration": {"$exists": False}}]
            }))
            count, content_hash = docs_digest(baseline)
            if count != before["count"] or content_hash != before["documents_sha256"]:
                failures.append({"collection": name, "reason": "baseline_counter_drift"})
        elif before["count"] != 0:
            failures.append({"collection": name, "reason": "expected_empty_sku_baseline"})

    skus = list(database.skus.find({"tenant_id": tenant_id, "_migration.approved_rule": SKU_RULE}))
    counters = list(database.counters.find({"_migration.approved_rule": SKU_RULE}))
    expected_hashes = {(item["collection"], item["target_id"]): item["after_hash"] for item in applied["operations"]}
    mismatches = []
    for name, documents in (("skus", skus), ("counters", counters)):
        for document in documents:
            target_id = document.get("_id") if name == "counters" else document.get("id")
            comparable = dict(document)
            if name != "counters":
                comparable.pop("_id", None)
            if expected_hashes.get((name, target_id)) != document_hash(comparable):
                mismatches.append({"collection": name, "target_id": target_id})
    client_ids = {doc["id"] for doc in database.crm_clients.find({"tenant_id": tenant_id}, {"id": 1})}
    checks = {
        "skus": len(skus), "counters": len(counters),
        "unique_codes": len({doc.get("codigo_interno") for doc in skus}) == len(skus),
        "resolved_clients": all(doc.get("cliente_id") in client_ids for doc in skus),
        "legacy_authorized": all(doc.get("origem_contratual_status") == "legado_autorizado" and doc.get("legado_sem_cgi") is True and doc.get("bloqueado_por_cgi") is False for doc in skus),
        "active": sum(doc.get("status") == "ativo" for doc in skus),
        "inactive": sum(doc.get("status") == "inativo" for doc in skus),
        "aliases": sum(len(doc.get("legacy_aliases") or []) for doc in skus),
        "hash_mismatches": mismatches,
    }
    valid = (
        not failures and not mismatches and checks["skus"] == 382 and checks["counters"] == 13
        and checks["unique_codes"] and checks["resolved_clients"] and checks["legacy_authorized"]
        and checks["active"] == 328 and checks["inactive"] == 54 and checks["aliases"] == 7
    )
    report = {
        "status": "VERIFIED" if valid else "FAILED", "plan_id": PLAN_ID, "policy": "A_LEGACY_AUTHORIZED",
        "checks": checks, "unrelated_collection_failures": failures,
        "unrelated_collections_verified": len(snapshot["inventory"]) - 2 - len(failures),
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.applied_map).write_text(json.dumps({
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED", "plan_id": PLAN_ID,
        "policy": "A_LEGACY_AUTHORIZED", "entries": applied["applied_sku_map"], "blocked": applied["blocked"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
