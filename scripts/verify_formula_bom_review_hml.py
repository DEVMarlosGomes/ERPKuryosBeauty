#!/usr/bin/env python3
"""Verify the isolated formula/BOM review wave in homologation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import PLAN_ID, assert_homologation, document_hash, load_env
from apply_firebase_formula_bom_review_hml import COLLECTION, EXPECTED_TOTAL, RULE, payload_hash
from create_hml_snapshot import digest_docs, digest_indexes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-report", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    env = load_env(Path(args.env))
    uri = env["ERP_HML_MONGO_URI"]
    database_name = env["ERP_HML_DB_NAME"]
    tenant_id = env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    snapshot = json.loads(Path(args.snapshot_report).read_text(encoding="utf-8"))
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION":
        raise RuntimeError("Verified snapshot and applied report are required")
    if applied.get("plan_id") != PLAN_ID or applied.get("approved_rule") != RULE:
        raise RuntimeError("Unexpected formula/BOM apply report")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    failures: dict[str, object] = {}
    for name, before in snapshot["inventory"].items():
        count, docs_hash = digest_docs(db[name])
        indexes_hash = digest_indexes(db[name])
        current = {"count": count, "documents_sha256": docs_hash, "indexes_sha256": indexes_hash}
        if current != before:
            failures[name] = {"before": before, "after": current}

    current_docs = list(db[COLLECTION].find(
        {"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}
    ))
    expected_hashes = {operation["target_id"]: operation["after_hash"] for operation in applied["operations"]}
    hash_failures = [
        document["id"] for document in current_docs
        if expected_hashes.get(document["id"]) != document_hash(document)
    ]
    payload_hash_failures = [
        document["id"] for document in current_docs
        if document.get("source_payload_sha256") != payload_hash(document.get("source_payload"))
    ]
    review_checks = {
        "total": len(current_docs),
        "formula": sum(doc.get("record_type") == "formula" for doc in current_docs),
        "bom": sum(doc.get("record_type") == "bom" for doc in current_docs),
        "operational_eligible_true": sum(doc.get("operational_eligible") is not False for doc in current_docs),
        "activation_not_blocked": sum(doc.get("activation_status") != "bloqueado" for doc in current_docs),
        "hash_failures": hash_failures,
        "payload_hash_failures": payload_hash_failures,
    }
    operational = {
        "produtos_pai": db.produtos_pai.count_documents({"tenant_id": tenant_id}),
        "bom_items": db.bom_items.count_documents({"tenant_id": tenant_id}),
        "skus_with_parent": db.skus.count_documents({"tenant_id": tenant_id, "produto_pai_id": {"$nin": [None, ""]}}),
    }
    review_valid = (
        review_checks["total"] == EXPECTED_TOTAL
        and review_checks["formula"] == 197
        and review_checks["bom"] == 246
        and review_checks["operational_eligible_true"] == 0
        and review_checks["activation_not_blocked"] == 0
        and not hash_failures
        and not payload_hash_failures
    )
    operational_valid = operational == applied["operational_before"] == applied["operational_after"]
    valid = not failures and review_valid and operational_valid
    result = {
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED",
        "plan_id": PLAN_ID,
        "collection": COLLECTION,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(failures),
        "unrelated_collection_failures": failures,
        "review_checks": review_checks,
        "operational_collections": operational,
        "operational_unchanged": operational_valid,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        **result,
        "unrelated_collection_failures": list(failures),
        "review_checks": {**review_checks, "hash_failures": len(hash_failures), "payload_hash_failures": len(payload_hash_failures)},
    }, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
