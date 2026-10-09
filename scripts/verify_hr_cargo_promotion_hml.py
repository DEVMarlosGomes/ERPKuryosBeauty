#!/usr/bin/env python3
"""Verify exact Firebase cargo promotion and preserve all unrelated HML data."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from pymongo import MongoClient
from apply_firebase_clients_hml import assert_homologation,document_hash,load_env
from create_hml_snapshot import digest_docs,digest_indexes
from promote_hr_cargos_hml import EXPECTED,REVIEW_COLLECTION,RULE

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--env",required=True);p.add_argument("--snapshot-report",required=True);p.add_argument("--apply-report",required=True);p.add_argument("--report",required=True);a=p.parse_args()
 e=load_env(Path(a.env));u,d,t=e["ERP_HML_MONGO_URI"],e["ERP_HML_DB_NAME"],e["ERP_HML_TENANT_ID"];assert_homologation(u,d,t);snapshot=json.loads(Path(a.snapshot_report).read_text(encoding="utf-8"));applied=json.loads(Path(a.apply_report).read_text(encoding="utf-8"))
 if snapshot.get("status")!="VERIFIED" or applied.get("status")!="APPLIED_HOMOLOGATION" or applied.get("approved_rule")!=RULE:raise RuntimeError("Verified inputs required")
 client=MongoClient(u,serverSelectionTimeoutMS=15000,connectTimeoutMS=15000);db=client[d];failures={}
 for name,before in snapshot["inventory"].items():
  if name in {"rh_cargos",REVIEW_COLLECTION}:continue
  count,h=digest_docs(db[name]);current={"count":count,"documents_sha256":h,"indexes_sha256":digest_indexes(db[name])}
  if current!=before:failures[name]={"before":before,"after":current}
 cargo_failures=[];review_failures=[];field_failures=[]
 for op in applied["operations"]:
  cargo=db.rh_cargos.find_one({"id":op["cargo_id"],"tenant_id":t},{"_id":0});review=db[REVIEW_COLLECTION].find_one({"id":op["review_id"],"tenant_id":t},{"_id":0});source=op["review_before_document"]["reconciliation"]
  if not cargo or document_hash(cargo)!=op["cargo_after_hash"]:cargo_failures.append(op["cargo_id"])
  if not review or document_hash(review)!=op["review_after_hash"]:review_failures.append(op["review_id"])
  if cargo and (cargo.get("nome")!=source.get("legacy_name") or cargo.get("setor")!=source.get("legacy_sector") or cargo.get("nivel")!=str(source.get("legacy_level") or "") or cargo.get("ativo") is not bool(source.get("legacy_active",True))):field_failures.append(op["cargo_id"])
 protected=applied["protected_before"]==applied["protected_after"];valid=not failures and not cargo_failures and not review_failures and not field_failures and protected and db.rh_cargos.count_documents({"tenant_id":t,"_migration.approved_rule":RULE})==EXPECTED
 result={"status":"APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED","approved_rule":RULE,"cargos":EXPECTED,"unrelated_collections_verified":len(snapshot["inventory"])-2-len(failures),"unrelated_collection_failures":failures,"cargo_hash_failures":cargo_failures,"review_hash_failures":review_failures,"exact_field_failures":field_failures,"protected_unchanged":protected};Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({**result,"unrelated_collection_failures":list(failures)}));client.close();return 0 if valid else 1
if __name__=="__main__":raise SystemExit(main())
