#!/usr/bin/env python3
"""Verify the isolated procurement, receipt and quality review wave in HML."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, document_hash, load_env
from apply_procurement_receipt_quality_review_hml import COLLECTIONS, EXPECTED, RULE, payload_hash
from create_hml_snapshot import digest_docs, digest_indexes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-report", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    snapshot = json.loads(Path(args.snapshot_report).read_text(encoding="utf-8"))
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION" or applied.get("approved_rule") != RULE:
        raise RuntimeError("Verified snapshot and applied report are required")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    unrelated_failures = {}
    for name, before in snapshot["inventory"].items():
        count, documents_sha256 = digest_docs(db[name])
        current = {"count": count, "documents_sha256": documents_sha256, "indexes_sha256": digest_indexes(db[name])}
        if current != before:
            unrelated_failures[name] = {"before": before, "after": current}
    expected_hashes = {(op["collection"], op["target_id"]): op["after_hash"] for op in applied["operations"]}
    hash_failures, payload_failures, review_checks = [], [], {}
    for name in COLLECTIONS:
        docs = list(db[name].find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}))
        review_checks[name] = {
            "total": len(docs),
            "operational_eligible_true": sum(doc.get("operational_eligible") is not False for doc in docs),
            "activation_not_blocked": sum(doc.get("activation_status") != "bloqueado" for doc in docs),
            "historical_only_false": sum(doc.get("historical_only") is not True for doc in docs),
        }
        for doc in docs:
            if expected_hashes.get((name, doc["id"])) != document_hash(doc): hash_failures.append(doc["id"])
            if doc.get("source_payload_sha256") != payload_hash(doc.get("source_payload")): payload_failures.append(doc["id"])
    type_to_collection = {
        "purchase_request": COLLECTIONS[0], "purchase_order": COLLECTIONS[0], "receipt": COLLECTIONS[1],
        "finished_goods_check": COLLECTIONS[2], "nonconformity": COLLECTIONS[2],
    }
    counts = {kind: db[name].count_documents({"tenant_id": tenant_id, "record_type": kind}) for kind, name in type_to_collection.items()}
    operational_valid = applied["operational_before"] == applied["operational_after"]
    valid = not unrelated_failures and counts == EXPECTED and operational_valid and not hash_failures and not payload_failures and all(not any(item[key] for key in ("operational_eligible_true", "activation_not_blocked", "historical_only_false")) for item in review_checks.values())
    result = {
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED", "approved_rule": RULE,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(unrelated_failures),
        "unrelated_collection_failures": unrelated_failures, "counts": counts, "review_checks": review_checks,
        "hash_failures": hash_failures, "payload_hash_failures": payload_failures, "operational_unchanged": operational_valid,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "unrelated_collection_failures": list(unrelated_failures), "hash_failures": len(hash_failures), "payload_hash_failures": len(payload_failures)}, ensure_ascii=False))
    client.close(); return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
