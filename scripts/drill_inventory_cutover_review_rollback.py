#!/usr/bin/env python3
"""Exercise inventory cutover review rollback on a disposable local MongoDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, load_env
from apply_inventory_cutover_review_hml import COLLECTION, EXPECTED_TOTAL, RULE, rollback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--local-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not args.local_db.startswith("kuryos_rollback_verify_inventory_cutover_"):
        raise RuntimeError("Unsafe disposable database name")
    env = load_env(Path(args.env))
    assert_homologation(env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"])
    remote = MongoClient(env["ERP_HML_MONGO_URI"], serverSelectionTimeoutMS=15000)
    local = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    if args.local_db in local.list_database_names():
        raise RuntimeError("Disposable rollback database already exists")
    query = {"tenant_id": env["ERP_HML_TENANT_ID"], "_migration.approved_rule": RULE}
    documents = list(remote[env["ERP_HML_DB_NAME"]][COLLECTION].find(query))
    local_db = local[args.local_db]
    local_db[COLLECTION].insert_many(documents, ordered=True)
    result = rollback(local_db, env["ERP_HML_TENANT_ID"], Path(args.apply_report))
    absent = COLLECTION not in local_db.list_collection_names()
    valid = len(documents) == EXPECTED_TOTAL and result.get("documents_removed") == EXPECTED_TOTAL and absent
    if valid:
        local.drop_database(args.local_db)
    report = {"status": "VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED", "source_mode": "HML_READ_ONLY",
              "rollback_target": "LOCAL_DISPOSABLE_DATABASE", "copied_documents": len(documents),
              "rollback_result": result, "collection_absent_after_rollback": absent, "local_database_removed": valid}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    remote.close(); local.close(); return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
