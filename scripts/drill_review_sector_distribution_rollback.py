#!/usr/bin/env python3
"""Exercise sector-distribution rollback using local disposable collections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, load_env
from apply_review_sector_distribution_hml import rollback
from review_sector_routing import DISPATCH_RULE, canonical_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--local-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not args.local_db.startswith("kuryos_rollback_verify_review_distribution_"):
        raise RuntimeError("Unsafe disposable local database name")
    env = load_env(Path(args.env))
    assert_homologation(env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"])
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    expected_before = {(row["collection"], row["id"]): row["before_hash"] for row in applied["operations"]}
    remote = MongoClient(env["ERP_HML_MONGO_URI"], serverSelectionTimeoutMS=15000)
    local = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    if args.local_db in local.list_database_names():
        raise RuntimeError("Disposable rollback database already exists")
    tenant_id = env["ERP_HML_TENANT_ID"]
    remote_db, local_db = remote[env["ERP_HML_DB_NAME"]], local[args.local_db]
    by_collection = {}
    for operation in applied["operations"]:
        by_collection.setdefault(operation["collection"], []).append(operation["id"])
    copied = 0
    for collection_name, ids in by_collection.items():
        documents = list(remote_db[collection_name].find({"tenant_id": tenant_id, "id": {"$in": ids}, "dispatch_rule": DISPATCH_RULE}))
        if documents:
            local_db[collection_name].insert_many(documents, ordered=True)
        copied += len(documents)
    rollback_result = rollback(local_db, tenant_id, Path(args.apply_report), use_transaction=False)
    failures = []
    remaining = 0
    restored = 0
    for collection_name, ids in by_collection.items():
        documents = list(local_db[collection_name].find({"tenant_id": tenant_id, "id": {"$in": ids}}, {"_id": 0}))
        restored += len(documents)
        remaining += local_db[collection_name].count_documents({"tenant_id": tenant_id, "dispatch_rule": DISPATCH_RULE})
        failures.extend(f"{collection_name}/{doc['id']}" for doc in documents if expected_before.get((collection_name, doc["id"])) != canonical_hash(doc))
    valid = copied == applied["planned_updates"] and restored == copied and not failures and remaining == 0
    if valid:
        local.drop_database(args.local_db)
    result = {
        "status": "VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED",
        "copied_documents": copied,
        "restored_documents": restored,
        "rollback_result": rollback_result,
        "hash_failures": failures,
        "distributed_records_remaining": remaining,
        "local_database_removed": valid,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "hash_failures": len(failures)}, ensure_ascii=False))
    remote.close()
    local.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
