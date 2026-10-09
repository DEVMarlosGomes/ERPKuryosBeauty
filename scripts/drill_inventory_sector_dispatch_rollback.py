#!/usr/bin/env python3
"""Exercise sector-dispatch rollback on a disposable local MongoDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, load_env
from apply_inventory_cutover_review_hml import COLLECTION, EXPECTED_TOTAL
from dispatch_inventory_cutover_reviews_hml import DISPATCH_RULE, canonical_hash, rollback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--local-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not args.local_db.startswith("kuryos_rollback_verify_sector_dispatch_"):
        raise RuntimeError("Unsafe disposable database name")
    env = load_env(Path(args.env))
    assert_homologation(env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"])
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    expected_before = {item["target_id"]: item["before_hash"] for item in applied["operations"]}
    remote = MongoClient(env["ERP_HML_MONGO_URI"], serverSelectionTimeoutMS=15000)
    local = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    if args.local_db in local.list_database_names():
        raise RuntimeError("Disposable rollback database already exists")
    tenant_id = env["ERP_HML_TENANT_ID"]
    documents = list(remote[env["ERP_HML_DB_NAME"]][COLLECTION].find({"tenant_id": tenant_id, "dispatch_rule": DISPATCH_RULE}))
    local_db = local[args.local_db]
    local_db[COLLECTION].insert_many(documents, ordered=True)
    rollback_result = rollback(local_db, tenant_id, Path(args.apply_report), use_transaction=False)
    restored = list(local_db[COLLECTION].find({"tenant_id": tenant_id}, {"_id": 0}))
    hash_failures = [doc["id"] for doc in restored if expected_before.get(doc["id"]) != canonical_hash(doc)]
    dispatched_left = local_db[COLLECTION].count_documents({"tenant_id": tenant_id, "dispatch_rule": DISPATCH_RULE})
    valid = len(documents) == EXPECTED_TOTAL and len(restored) == EXPECTED_TOTAL and not hash_failures and dispatched_left == 0
    if valid:
        local.drop_database(args.local_db)
    report = {"status": "VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED", "source_mode": "HML_READ_ONLY",
              "rollback_target": "LOCAL_DISPOSABLE_DATABASE", "copied_documents": len(documents),
              "rollback_result": rollback_result, "hash_failures": hash_failures,
              "dispatched_records_remaining": dispatched_left, "local_database_removed": valid}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "hash_failures": len(hash_failures)}, ensure_ascii=False))
    remote.close(); local.close(); return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
