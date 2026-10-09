#!/usr/bin/env python3
"""Verify isolated HR review records and unchanged operational identity data."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from pymongo import MongoClient
from apply_firebase_clients_hml import assert_homologation, document_hash, load_env
from apply_hr_legacy_review_hml import COLLECTION, EXPECTED, RULE, payload_hash
from create_hml_snapshot import digest_docs, digest_indexes

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--env",required=True); p.add_argument("--snapshot-report",required=True); p.add_argument("--apply-report",required=True); p.add_argument("--report",required=True); a=p.parse_args()
    e=load_env(Path(a.env)); u,d,t=e["ERP_HML_MONGO_URI"],e["ERP_HML_DB_NAME"],e["ERP_HML_TENANT_ID"]; assert_homologation(u,d,t)
    snapshot=json.loads(Path(a.snapshot_report).read_text(encoding="utf-8")); applied=json.loads(Path(a.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status")!="VERIFIED" or applied.get("status")!="APPLIED_HOMOLOGATION" or applied.get("approved_rule")!=RULE: raise RuntimeError("Verified inputs required")
    client=MongoClient(u,serverSelectionTimeoutMS=15000,connectTimeoutMS=15000); db=client[d]; failures={}
    for name,before in snapshot["inventory"].items():
        count,h=digest_docs(db[name]); current={"count":count,"documents_sha256":h,"indexes_sha256":digest_indexes(db[name])}
        if current!=before: failures[name]={"before":before,"after":current}
    expected={op["target_id"]:op["after_hash"] for op in applied["operations"]}; docs=list(db[COLLECTION].find({"tenant_id":t,"_migration.approved_rule":RULE},{"_id":0}))
    hashes=[x["id"] for x in docs if expected.get(x["id"])!=document_hash(x)]; payloads=[x["id"] for x in docs if x.get("source_payload_sha256")!=payload_hash(x.get("source_payload"))]
    sensitive={"password","password_hash","senha","token","refresh_token","access_token"}; leaked=[x["id"] for x in docs if any(str(k).lower() in sensitive for k in (x.get("source_payload") or {}))]
    unsafe=sum(x.get("operational_eligible") is not False or x.get("account_creation_allowed") is not False or x.get("permission_replay_allowed") is not False or x.get("activation_status")!="bloqueado" for x in docs)
    counts={kind:sum(x.get("record_type")==kind for x in docs) for kind in EXPECTED}; operational=applied["operational_before"]==applied["operational_after"]
    valid=counts==EXPECTED and not failures and not hashes and not payloads and not leaked and not unsafe and operational
    result={"status":"APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED","approved_rule":RULE,"counts":counts,"unsafe_reviews":unsafe,"sensitive_field_failures":leaked,"unrelated_collections_verified":len(snapshot["inventory"])-len(failures),"unrelated_collection_failures":failures,"hash_failures":hashes,"payload_hash_failures":payloads,"operational_unchanged":operational}
    Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({**result,"unrelated_collection_failures":list(failures),"hash_failures":len(hashes),"payload_hash_failures":len(payloads)})); client.close(); return 0 if valid else 1
if __name__=="__main__": raise SystemExit(main())
