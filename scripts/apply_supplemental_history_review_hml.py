#!/usr/bin/env python3
"""Stage supplemental Firebase history in one isolated HML review queue."""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from pymongo import ASCENDING,MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from apply_firebase_clients_hml import PLAN_ID,SOURCE_SHA,assert_homologation,document_hash,load_env,stable_id
from reconcile_supplemental_history_wave import EXPECTED

COLLECTION="legacy_supplemental_history_reviews";RULE="supplemental_legacy_history_review_v1";TOTAL=sum(EXPECTED.values())
PROTECTED=("skus","pcp_programacao","production_order_events","estoque_movimentos","inventory_ledger","compras_demandas","compras_pos")
def sha256_file(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def payload_hash(v:Any)->str:return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def owned(t:str):return {"tenant_id":t,"_migration.approved_rule":RULE}

def build(source:dict,preflight:dict,t:str)->list[dict]:
 now=datetime.now(timezone.utc).isoformat();docs=[]
 for row in preflight["records"]:
  raw=(source.get(row["source_node"]) or {}).get(row["source_key"])
  if raw is None:raise RuntimeError(f"Preflight/source divergence: {row['source_node']}/{row['source_key']}")
  docs.append({"id":stable_id("firebase-current",t,RULE,row["source_node"],row["source_key"]),"tenant_id":t,"record_type":row["record_type"],"source_node":row["source_node"],"source_key":row["source_key"],"legacy_status":row.get("legacy_status"),"reconciliation_classification":row["classification"],"blockers":row["blockers"],"reconciliation":row,"review_status":"pendente_revisao","activation_status":"bloqueado","operational_eligible":False,"historical_only":True,"operational_replay_allowed":False,"source_payload":raw,"source_payload_sha256":payload_hash(raw),"created_at":now,"updated_at":now,"_migration":{"source":"firebase-current","source_sha256":SOURCE_SHA,"plan_id":PLAN_ID,"approved_rule":RULE,"operation_id":stable_id(PLAN_ID,RULE,row["source_node"],row["source_key"]),"applied_at":now}})
 counts={kind:sum(x["record_type"]==kind for x in docs) for kind in EXPECTED}
 if counts!=EXPECTED or len({x["id"] for x in docs})!=TOTAL:raise RuntimeError("Unexpected supplemental documents")
 return docs

def rollback(db,t:str,report_path:Path)->int:
 report=json.loads(report_path.read_text(encoding="utf-8"))
 if report.get("status")!="APPLIED_HOMOLOGATION" or report.get("approved_rule")!=RULE:raise RuntimeError("Valid apply report required")
 expected={x["target_id"]:x["after_hash"] for x in report["operations"]};current=list(db[COLLECTION].find(owned(t),{"_id":0}))
 if len(current)!=TOTAL or db[COLLECTION].count_documents({})!=TOTAL:raise RuntimeError("Review collection ownership changed")
 for doc in current:
  if expected.get(doc["id"])!=document_hash(doc):raise RuntimeError(f"Review edited: {doc['id']}")
 db.drop_collection(COLLECTION);return len(current)

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["dry-run","apply","rollback"]);p.add_argument("--env",required=True);p.add_argument("--source",required=True);p.add_argument("--preflight",required=True);p.add_argument("--snapshot",required=True);p.add_argument("--snapshot-sha256",required=True);p.add_argument("--apply-report");p.add_argument("--report",required=True);a=p.parse_args()
 e=load_env(Path(a.env));u,d,t=e["ERP_HML_MONGO_URI"],e["ERP_HML_DB_NAME"],e["ERP_HML_TENANT_ID"];assert_homologation(u,d,t);sp,pp,snap=Path(a.source),Path(a.preflight),Path(a.snapshot)
 if sha256_file(sp)!=SOURCE_SHA:raise RuntimeError("Firebase source hash mismatch")
 if sha256_file(snap)!=a.snapshot_sha256:raise RuntimeError("Snapshot hash mismatch")
 client=MongoClient(u,serverSelectionTimeoutMS=15000,connectTimeoutMS=15000);db=client[d]
 if a.mode=="rollback":
  if not a.apply_report:raise RuntimeError("--apply-report is required")
  result={"status":"ROLLED_BACK","approved_rule":RULE,"removed":rollback(db,t,Path(a.apply_report))};Path(a.report).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps(result));return 0
 source=json.loads(sp.read_text(encoding="utf-8"));preflight=json.loads(pp.read_text(encoding="utf-8"));docs=build(source,preflight,t)
 if COLLECTION in db.list_collection_names():raise RuntimeError("Target review collection already exists")
 protected_before={n:db[n].count_documents({"tenant_id":t}) for n in PROTECTED};operations=[{"target_id":x["id"],"source_node":x["source_node"],"source_key":x["source_key"],"after_hash":document_hash(x)} for x in docs]
 result={"status":"DRY_RUN_VALID" if a.mode=="dry-run" else "APPLY_STARTED","approved_rule":RULE,"target":{"database":d,"tenant_id":t},"source_sha256":SOURCE_SHA,"preflight_sha256":sha256_file(pp),"snapshot_sha256":a.snapshot_sha256,"planned":EXPECTED,"total":TOTAL,"protected_before":protected_before,"operations":operations}
 if a.mode=="dry-run":Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({k:v for k,v in result.items() if k!="operations"}));return 0
 try:
  db.create_collection(COLLECTION);db[COLLECTION].create_index([("tenant_id",ASCENDING),("source_node",ASCENDING),("source_key",ASCENDING)],unique=True,name="tenant_source_key_unique");db[COLLECTION].create_index([("tenant_id",ASCENDING),("review_status",ASCENDING),("record_type",ASCENDING)],name="tenant_review_type")
  with client.start_session() as session:session.with_transaction(lambda active:db[COLLECTION].insert_many(docs,ordered=True,session=active),read_concern=ReadConcern("snapshot"),write_concern=WriteConcern("majority"))
  protected_after={n:db[n].count_documents({"tenant_id":t}) for n in PROTECTED};counts={kind:db[COLLECTION].count_documents({"tenant_id":t,"record_type":kind}) for kind in EXPECTED};unsafe=db[COLLECTION].count_documents({"$or":[{"operational_eligible":{"$ne":False}},{"operational_replay_allowed":{"$ne":False}},{"activation_status":{"$ne":"bloqueado"}}]})
  if counts!=EXPECTED or protected_after!=protected_before or unsafe:raise RuntimeError("Post-check failed")
 except Exception:
  if COLLECTION in db.list_collection_names():db.drop_collection(COLLECTION)
  raise
 result.update({"status":"APPLIED_HOMOLOGATION","completed_at":datetime.now(timezone.utc).isoformat(),"inserted":counts,"protected_after":protected_after,"collection":COLLECTION});Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps({k:v for k,v in result.items() if k!="operations"}));client.close();return 0
if __name__=="__main__":raise SystemExit(main())
