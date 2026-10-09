#!/usr/bin/env python3
"""Verify the isolated blocked master-data queue in homologation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, document_hash, load_env
from apply_master_data_review_hml import COLLECTION, EXPECTED, EXPECTED_TOTAL, RULE, payload_hash
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
        raise RuntimeError("Verified snapshot and valid apply report are required")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    unrelated_failures = {}
    for name, before in snapshot["inventory"].items():
        count, docs_hash = digest_docs(db[name])
        current = {"count": count, "documents_sha256": docs_hash, "indexes_sha256": digest_indexes(db[name])}
        if current != before:
            unrelated_failures[name] = {"before": before, "after": current}
    documents = list(db[COLLECTION].find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}))
    hashes = {item["target_id"]: item["after_hash"] for item in applied["operations"]}
    hash_failures = [doc["id"] for doc in documents if hashes.get(doc["id"]) != document_hash(doc)]
    payload_failures = [doc["id"] for doc in documents if doc.get("source_payload_sha256") != payload_hash(doc.get("source_payload"))]
    counts = {kind: sum(doc.get("record_type") == kind for doc in documents) for kind in EXPECTED}
    blocked = sum(doc.get("activation_status") == "bloqueado" and doc.get("operational_eligible") is False for doc in documents)
    operational_valid = applied["operational_before"] == applied["operational_after"]
    valid = not unrelated_failures and len(documents) == EXPECTED_TOTAL and counts == EXPECTED and blocked == EXPECTED_TOTAL and not hash_failures and not payload_failures and operational_valid
    result = {
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED", "approved_rule": RULE,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(unrelated_failures),
        "unrelated_collection_failures": unrelated_failures, "counts": counts,
        "blocked_non_operational": blocked, "hash_failures": hash_failures,
        "payload_hash_failures": payload_failures, "operational_unchanged": operational_valid,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "unrelated_collection_failures": list(unrelated_failures), "hash_failures": len(hash_failures), "payload_hash_failures": len(payload_failures)}, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
