#!/usr/bin/env python3
"""Exercise exact cargo-promotion rollback in a disposable local database."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from pymongo import MongoClient
from apply_firebase_clients_hml import assert_homologation,document_hash,load_env
from promote_hr_cargos_hml import EXPECTED,REVIEW_COLLECTION,RULE,rollback

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--env",required=True);p.add_argument("--apply-report",required=True);p.add_argument("--local-db",required=True);p.add_argument("--report",required=True);a=p.parse_args()
 if not a.local_db.startswith("kuryos_rollback_verify_hr_cargo_"):raise RuntimeError("Unsafe disposable local database name")
 e=load_env(Path(a.env));assert_homologation(e["ERP_HML_MONGO_URI"],e["ERP_HML_DB_NAME"],e["ERP_HML_TENANT_ID"]);remote=MongoClient(e["ERP_HML_MONGO_URI"],serverSelectionTimeoutMS=15000);local=MongoClient("mongodb://127.0.0.1:27017",serverSelectionTimeoutMS=5000)
 if a.local_db in local.list_database_names():raise RuntimeError("Disposable rollback database already exists")
 report=json.loads(Path(a.apply_report).read_text(encoding="utf-8"));ids=[x["review_id"] for x in report["operations"]];cargo_ids=[x["cargo_id"] for x in report["operations"]];rdb=remote[e["ERP_HML_DB_NAME"]];ldb=local[a.local_db]
 reviews=list(rdb[REVIEW_COLLECTION].find({"id":{"$in":ids},"tenant_id":e["ERP_HML_TENANT_ID"]}));cargos=list(rdb.rh_cargos.find({"id":{"$in":cargo_ids},"tenant_id":e["ERP_HML_TENANT_ID"]}));ldb[REVIEW_COLLECTION].insert_many(reviews);ldb.rh_cargos.insert_many(cargos);rolled=rollback(ldb,e["ERP_HML_TENANT_ID"],Path(a.apply_report))
 restored=list(ldb[REVIEW_COLLECTION].find({"id":{"$in":ids}},{"_id":0}));expected={x["review_id"]:x["review_before_hash"] for x in report["operations"]};valid=rolled=={"cargos_removed":EXPECTED,"reviews_restored":EXPECTED} and ldb.rh_cargos.count_documents({})==0 and len(restored)==EXPECTED and all(document_hash(x)==expected[x["id"]] for x in restored)
 if valid:local.drop_database(a.local_db)
 result={"status":"VERIFIED" if valid else "FAILED_LOCAL_DB_RETAINED","copied_cargos":len(cargos),"copied_reviews":len(reviews),"rollback_result":rolled,"local_database_removed":valid};Path(a.report).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps(result));remote.close();local.close();return 0 if valid else 1
if __name__=="__main__":raise SystemExit(main())
