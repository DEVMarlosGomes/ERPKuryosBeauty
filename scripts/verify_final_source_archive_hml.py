#!/usr/bin/env python3
"""Verify final isolated Firebase source archive in HML."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, document_hash, load_env
from apply_final_source_archive_hml import COLLECTION, RULE, TOTAL, payload_hash
from create_hml_snapshot import digest_docs, digest_indexes
from reconcile_final_source_archive_wave import EXPECTED


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
        raise RuntimeError("Verified inputs required")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    database = client[database_name]
    failures = {}
    for name, before in snapshot["inventory"].items():
        count, content_hash = digest_docs(database[name])
        current = {"count": count, "documents_sha256": content_hash, "indexes_sha256": digest_indexes(database[name])}
        if current != before:
            failures[name] = {"before": before, "after": current}

    expected_hashes = {row["target_id"]: row["after_hash"] for row in applied["operations"]}
    documents = list(database[COLLECTION].find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}))
    hash_failures = [doc["id"] for doc in documents if expected_hashes.get(doc["id"]) != document_hash(doc)]
    payload_failures = [doc["id"] for doc in documents if doc.get("source_payload_sha256") != payload_hash(doc.get("source_payload"))]
    unsafe = sum(
        doc.get("operational_eligible") is not False
        or doc.get("operational_replay_allowed") is not False
        or doc.get("activation_status") != "bloqueado"
        for doc in documents
    )
    counts = {node: sum(doc.get("source_node") == node for doc in documents) for node in EXPECTED}
    protected = applied["protected_before"] == applied["protected_after"]
    valid = len(documents) == TOTAL and counts == EXPECTED and not failures and not hash_failures and not payload_failures and not unsafe and protected
    result = {
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED",
        "approved_rule": RULE,
        "total": len(documents),
        "counts": counts,
        "unsafe_archive_documents": unsafe,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(failures),
        "unrelated_collection_failures": failures,
        "hash_failures": hash_failures,
        "payload_hash_failures": payload_failures,
        "protected_unchanged": protected,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "unrelated_collection_failures": list(failures), "hash_failures": len(hash_failures), "payload_hash_failures": len(payload_failures)}))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
