#!/usr/bin/env python3
"""Exercise formula/BOM selective rollback on a disposable local MongoDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, load_env
from apply_firebase_formula_bom_review_hml import COLLECTION, RULE, rollback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--local-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not args.local_db.startswith("kuryos_rollback_verify_formula_bom_"):
        raise RuntimeError("Unsafe disposable local database name")

    env = load_env(Path(args.env))
    assert_homologation(env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"])
    tenant_id = env["ERP_HML_TENANT_ID"]
    remote_client = MongoClient(env["ERP_HML_MONGO_URI"], serverSelectionTimeoutMS=15000)
    local_client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    if args.local_db in local_client.list_database_names():
        raise RuntimeError("Disposable rollback database already exists")

    remote_collection = remote_client[env["ERP_HML_DB_NAME"]][COLLECTION]
    documents = list(remote_collection.find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}))
    local_db = local_client[args.local_db]
    local_db[COLLECTION].insert_many(documents, ordered=True)
    copied = local_db[COLLECTION].count_documents({})
    result = rollback(local_db, tenant_id, Path(args.apply_report))
    collection_absent = COLLECTION not in local_db.list_collection_names()
    valid = copied == 443 and result.get("documents_removed") == 443 and collection_absent
    if collection_absent:
        local_client.drop_database(args.local_db)
    report = {
        "status": "VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED",
        "source_mode": "HML_READ_ONLY",
        "rollback_target": "LOCAL_DISPOSABLE_DATABASE",
        "copied_documents": copied,
        "rollback_result": result,
        "collection_absent_after_rollback": collection_absent,
        "local_database_removed": valid,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    remote_client.close()
    local_client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
