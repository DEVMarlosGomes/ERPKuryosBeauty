#!/usr/bin/env python3
"""Exercise selective expedition-review rollback in a disposable local database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_expedition_history_review_hml import COLLECTION, EXPECTED, RULE, rollback
from apply_firebase_clients_hml import assert_homologation, load_env


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--env", required=True); parser.add_argument("--apply-report", required=True); parser.add_argument("--local-db", required=True); parser.add_argument("--report", required=True); args = parser.parse_args()
    if not args.local_db.startswith("kuryos_rollback_verify_expedition_"): raise RuntimeError("Unsafe disposable local database name")
    env = load_env(Path(args.env)); assert_homologation(env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"])
    remote = MongoClient(env["ERP_HML_MONGO_URI"], serverSelectionTimeoutMS=15000); local = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    if args.local_db in local.list_database_names(): raise RuntimeError("Disposable rollback database already exists")
    docs = list(remote[env["ERP_HML_DB_NAME"]][COLLECTION].find({"tenant_id": env["ERP_HML_TENANT_ID"], "_migration.approved_rule": RULE}))
    local[args.local_db][COLLECTION].insert_many(docs, ordered=True)
    removed = rollback(local[args.local_db], env["ERP_HML_TENANT_ID"], Path(args.apply_report)); absent = COLLECTION not in local[args.local_db].list_collection_names(); valid = len(docs) == EXPECTED and removed == EXPECTED and absent
    if valid: local.drop_database(args.local_db)
    result = {"status": "VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED", "source_mode": "HML_READ_ONLY", "rollback_target": "LOCAL_DISPOSABLE_DATABASE", "copied_documents": len(docs), "removed": removed, "collection_absent_after_rollback": absent, "local_database_removed": valid}
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(json.dumps(result)); remote.close(); local.close(); return 0 if valid else 1


if __name__ == "__main__": raise SystemExit(main())
