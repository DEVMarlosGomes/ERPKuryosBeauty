#!/usr/bin/env python3
"""Promote the three reviewed Firebase HR roles to operational HML cargos."""

from __future__ import annotations

import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import PLAN_ID, assert_homologation, document_hash, load_env, stable_id
from apply_hr_legacy_review_hml import COLLECTION as REVIEW_COLLECTION, RULE as REVIEW_RULE

RULE = "hr_cargo_exact_firebase_promotion_v1"
EXPECTED = 3

def sha256_file(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def review_query(tenant_id: str): return {"tenant_id":tenant_id,"record_type":"job_role","_migration.approved_rule":REVIEW_RULE}

def build_cargo(review: dict, now: str) -> dict:
    row=review["reconciliation"]
    return {"id":stable_id("firebase-current",review["tenant_id"],RULE,review["source_key"]),"tenant_id":review["tenant_id"],
        "nome":row.get("legacy_name") or "","setor":row.get("legacy_sector") or "","nivel":str(row.get("legacy_level") or ""),
        "descricao":"","ativo":bool(row.get("legacy_active",True)),"created_at":now,"updated_at":now,"created_by":"migration:firebase-current",
        "legacy_source_key":review["source_key"],"_migration":{"source":"firebase-current","plan_id":PLAN_ID,"approved_rule":RULE,"operation_id":stable_id(PLAN_ID,RULE,review["source_key"]),"applied_at":now}}

def rollback(db, tenant_id: str, apply_report: Path) -> dict:
    report=json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status")!="APPLIED_HOMOLOGATION" or report.get("approved_rule")!=RULE: raise RuntimeError("Valid cargo promotion report required")
    for op in report["operations"]:
        cargo=db.rh_cargos.find_one({"id":op["cargo_id"],"tenant_id":tenant_id},{"_id":0}); review=db[REVIEW_COLLECTION].find_one({"id":op["review_id"],"tenant_id":tenant_id},{"_id":0})
        if not cargo or document_hash(cargo)!=op["cargo_after_hash"]: raise RuntimeError(f"Cargo edited after promotion: {op['cargo_id']}")
        if not review or document_hash(review)!=op["review_after_hash"]: raise RuntimeError(f"Review edited after promotion: {op['review_id']}")
    for op in report["operations"]:
        db.rh_cargos.delete_one({"id":op["cargo_id"],"tenant_id":tenant_id})
        db[REVIEW_COLLECTION].replace_one({"id":op["review_id"],"tenant_id":tenant_id},op["review_before_document"])
    return {"cargos_removed":len(report["operations"]),"reviews_restored":len(report["operations"])}

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("mode",choices=["dry-run","apply","rollback"]); p.add_argument("--env",required=True); p.add_argument("--snapshot",required=True); p.add_argument("--snapshot-sha256",required=True); p.add_argument("--apply-report"); p.add_argument("--report",required=True); a=p.parse_args()
    e=load_env(Path(a.env)); u,d,t=e["ERP_HML_MONGO_URI"],e["ERP_HML_DB_NAME"],e["ERP_HML_TENANT_ID"]; assert_homologation(u,d,t)
    if sha256_file(Path(a.snapshot))!=a.snapshot_sha256: raise RuntimeError("Snapshot hash mismatch")
    client=MongoClient(u,serverSelectionTimeoutMS=15000,connectTimeoutMS=15000); db=client[d]
    if a.mode=="rollback":
        if not a.apply_report: raise RuntimeError("--apply-report is required")
        result={"status":"ROLLED_BACK","approved_rule":RULE,**rollback(db,t,Path(a.apply_report))}; Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(result)); return 0
    reviews=list(db[REVIEW_COLLECTION].find(review_query(t),{"_id":0}).sort("source_key",1))
    if len(reviews)!=EXPECTED: raise RuntimeError(f"Expected {EXPECTED} reviewed cargos, found {len(reviews)}")
    if any(x.get("review_status")!="pendente_revisao" or x.get("operational_eligible") is not False for x in reviews): raise RuntimeError("Cargo reviews are not in the expected blocked state")
    if db.rh_cargos.count_documents({"tenant_id":t}): raise RuntimeError("Operational HML cargos already exist; manual merge required")
    now=datetime.now(timezone.utc).isoformat(); cargos=[build_cargo(x,now) for x in reviews]
    if any(not x["nome"] for x in cargos) or len({(x["nome"],x["setor"]) for x in cargos})!=EXPECTED: raise RuntimeError("Invalid or duplicate cargo source")
    review_after=[]; operations=[]
    for before,cargo in zip(reviews,cargos):
        after={**before,"review_status":"promovido","activation_status":"promovido","operational_eligible":True,"promoted_at":now,"promoted_target_collection":"rh_cargos","promoted_target_id":cargo["id"],"updated_at":now}
        review_after.append(after); operations.append({"review_id":before["id"],"cargo_id":cargo["id"],"source_key":before["source_key"],"cargo_after_hash":document_hash(cargo),"review_before_hash":document_hash(before),"review_after_hash":document_hash(after),"review_before_document":before})
    protected=("users","rh_colaboradores","rh_avaliacoes","rh_ferias"); protected_before={n:db[n].count_documents({"tenant_id":t}) for n in protected}
    result={"status":"DRY_RUN_VALID" if a.mode=="dry-run" else "APPLY_STARTED","approved_rule":RULE,"target":{"database":d,"tenant_id":t},"snapshot_sha256":a.snapshot_sha256,"planned":EXPECTED,"protected_before":protected_before,"operations":operations}
    if a.mode=="dry-run": Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k!="operations"})); return 0
    with client.start_session() as session:
        def tx(active):
            db.rh_cargos.insert_many(cargos,ordered=True,session=active)
            for before,after in zip(reviews,review_after): db[REVIEW_COLLECTION].replace_one({"id":before["id"],"tenant_id":t},after,session=active)
        session.with_transaction(tx,read_concern=ReadConcern("snapshot"),write_concern=WriteConcern("majority"))
    protected_after={n:db[n].count_documents({"tenant_id":t}) for n in protected}
    if db.rh_cargos.count_documents({"tenant_id":t,"_migration.approved_rule":RULE})!=EXPECTED or protected_after!=protected_before: raise RuntimeError("Promotion post-check failed")
    result.update({"status":"APPLIED_HOMOLOGATION","completed_at":datetime.now(timezone.utc).isoformat(),"inserted_cargos":EXPECTED,"promoted_reviews":EXPECTED,"protected_after":protected_after}); Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k!="operations"})); client.close(); return 0
if __name__=="__main__": raise SystemExit(main())
