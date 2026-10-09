#!/usr/bin/env python3
"""Verify isolated order/OP review queues and prove operational data unchanged."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, document_hash, load_env
from apply_firebase_order_op_review_hml import EXPECTED, OP_COLLECTION, ORDER_COLLECTION, RULE, payload_hash
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
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION":
        raise RuntimeError("Verified snapshot and applied report are required")
    if applied.get("approved_rule") != RULE:
        raise RuntimeError("Unexpected order/OP apply report")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    failures = {}
    for name, before in snapshot["inventory"].items():
        count, docs_hash = digest_docs(db[name])
        current = {"count": count, "documents_sha256": docs_hash, "indexes_sha256": digest_indexes(db[name])}
        if current != before:
            failures[name] = {"before": before, "after": current}

    expected_hashes = {
        (op["collection"], op["target_id"]): op["after_hash"] for op in applied["operations"]
    }
    checks = {}
    hash_failures = []
    payload_failures = []
    for name in (ORDER_COLLECTION, OP_COLLECTION):
        docs = list(db[name].find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}))
        checks[name] = {
            "total": len(docs),
            "operational_eligible_true": sum(doc.get("operational_eligible") is not False for doc in docs),
            "activation_not_blocked": sum(doc.get("activation_status") != "bloqueado" for doc in docs),
        }
        for doc in docs:
            if expected_hashes.get((name, doc["id"])) != document_hash(doc):
                hash_failures.append(doc["id"])
            if doc.get("source_payload_sha256") != payload_hash(doc.get("source_payload")):
                payload_failures.append(doc["id"])
    counts = {
        "commercial_order": db[ORDER_COLLECTION].count_documents({"record_type": "commercial_order"}),
        "order_line": db[ORDER_COLLECTION].count_documents({"record_type": "order_line"}),
        "production_order": db[OP_COLLECTION].count_documents({"record_type": "production_order"}),
    }
    operational_valid = applied["operational_before"] == applied["operational_after"]
    valid = (
        not failures and counts == EXPECTED and operational_valid and not hash_failures and not payload_failures
        and all(item["operational_eligible_true"] == 0 and item["activation_not_blocked"] == 0 for item in checks.values())
    )
    result = {
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED",
        "approved_rule": RULE,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(failures),
        "unrelated_collection_failures": failures,
        "counts": counts,
        "review_checks": checks,
        "hash_failures": hash_failures,
        "payload_hash_failures": payload_failures,
        "operational_unchanged": operational_valid,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "unrelated_collection_failures": list(failures), "hash_failures": len(hash_failures), "payload_hash_failures": len(payload_failures)}, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
