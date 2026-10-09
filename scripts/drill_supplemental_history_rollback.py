#!/usr/bin/env python3
"""Exercise selective supplemental-history rollback locally."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from pymongo import MongoClient
from apply_firebase_clients_hml import assert_homologation,load_env
from apply_supplemental_history_review_hml import COLLECTION,RULE,TOTAL,rollback

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--env",required=True);p.add_argument("--apply-report",required=True);p.add_argument("--local-db",required=True);p.add_argument("--report",required=True);a=p.parse_args()
 if not a.local_db.startswith("kuryos_rollback_verify_supplemental_"):raise RuntimeError("Unsafe disposable local database name")
 e=load_env(Path(a.env));assert_homologation(e["ERP_HML_MONGO_URI"],e["ERP_HML_DB_NAME"],e["ERP_HML_TENANT_ID"]);remote=MongoClient(e["ERP_HML_MONGO_URI"],serverSelectionTimeoutMS=15000);local=MongoClient("mongodb://127.0.0.1:27017",serverSelectionTimeoutMS=5000)
 if a.local_db in local.list_database_names():raise RuntimeError("Disposable rollback database already exists")
 docs=list(remote[e["ERP_HML_DB_NAME"]][COLLECTION].find({"tenant_id":e["ERP_HML_TENANT_ID"],"_migration.approved_rule":RULE}));local[a.local_db][COLLECTION].insert_many(docs,ordered=True);removed=rollback(local[a.local_db],e["ERP_HML_TENANT_ID"],Path(a.apply_report));absent=COLLECTION not in local[a.local_db].list_collection_names();valid=len(docs)==TOTAL and removed==TOTAL and absent
 if valid:local.drop_database(a.local_db)
 result={"status":"VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED","copied_documents":len(docs),"removed":removed,"collection_absent_after_rollback":absent,"local_database_removed":valid};Path(a.report).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps(result));remote.close();local.close();return 0 if valid else 1
if __name__=="__main__":raise SystemExit(main())
