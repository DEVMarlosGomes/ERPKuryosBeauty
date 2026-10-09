#!/usr/bin/env python3
"""Stage legacy HR records in an isolated, non-authenticating HML queue."""

from __future__ import annotations

import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import PLAN_ID, SOURCE_SHA, assert_homologation, document_hash, load_env, stable_id

COLLECTION = "legacy_hr_reviews"
RULE = "hr_legacy_review_no_account_creation_v1"
EXPECTED = {"job_role": 3, "legacy_user": 13}
OPERATIONAL_COLLECTIONS = ("users", "rh_cargos", "rh_colaboradores", "rh_avaliacoes", "rh_ferias")

def sha256_file(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def payload_hash(value: Any) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def build_documents(preflight: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat(); documents = []
    for record_type, key in (("job_role", "job_roles"), ("legacy_user", "legacy_users")):
        for row in preflight[key]:
            source_key = row["source_key"]; payload = row["sanitized_payload"]
            documents.append({"id": stable_id("firebase-current", tenant_id, RULE, record_type, source_key), "tenant_id": tenant_id,
                "record_type": record_type, "source_node": "rh_cargos" if record_type == "job_role" else "usuarios", "source_key": source_key,
                "legacy_name": row.get("legacy_name"), "legacy_email": row.get("legacy_email"), "legacy_role": row.get("legacy_role"),
                "legacy_sector": row.get("legacy_sector"), "target_user_id": row.get("target_user_id"),
                "reconciliation_classification": row.get("classification"), "blockers": list(row.get("blockers") or []), "reconciliation": row,
                "review_status": "pendente_revisao", "activation_status": "bloqueado", "operational_eligible": False,
                "historical_only": True, "account_creation_allowed": False, "permission_replay_allowed": False,
                "source_payload": payload, "source_payload_sha256": payload_hash(payload), "created_at": now, "updated_at": now,
                "_migration": {"source": "firebase-current", "source_sha256": SOURCE_SHA, "plan_id": PLAN_ID, "approved_rule": RULE,
                               "operation_id": stable_id(PLAN_ID, RULE, record_type, source_key), "applied_at": now}})
    counts = {kind: sum(doc["record_type"] == kind for doc in documents) for kind in EXPECTED}
    if counts != EXPECTED or len({doc["id"] for doc in documents}) != sum(EXPECTED.values()): raise RuntimeError("Unexpected HR review documents")
    return documents

def owned_query(tenant_id: str): return {"tenant_id": tenant_id, "_migration.approved_rule": RULE}

def rollback(db, tenant_id: str, apply_report: Path) -> int:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("approved_rule") != RULE: raise RuntimeError("Valid apply report required")
    expected = {op["target_id"]: op["after_hash"] for op in report["operations"]}; current = list(db[COLLECTION].find(owned_query(tenant_id), {"_id": 0}))
    if len(current) != sum(EXPECTED.values()) or db[COLLECTION].count_documents({}) != len(current): raise RuntimeError("Review collection ownership changed")
    for doc in current:
        if expected.get(doc["id"]) != document_hash(doc): raise RuntimeError(f"Review document edited: {doc['id']}")
    db.drop_collection(COLLECTION); return len(current)

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=["dry-run", "apply", "rollback"]); parser.add_argument("--env", required=True); parser.add_argument("--source", required=True); parser.add_argument("--preflight", required=True); parser.add_argument("--snapshot", required=True); parser.add_argument("--snapshot-sha256", required=True); parser.add_argument("--apply-report"); parser.add_argument("--report", required=True); args = parser.parse_args()
    env = load_env(Path(args.env)); uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]; assert_homologation(uri, database_name, tenant_id)
    source_path, preflight_path, snapshot_path = Path(args.source), Path(args.preflight), Path(args.snapshot)
    if sha256_file(source_path) != SOURCE_SHA: raise RuntimeError("Firebase source hash mismatch")
    if sha256_file(snapshot_path) != args.snapshot_sha256: raise RuntimeError("Snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000); db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report: raise RuntimeError("--apply-report is required")
        result = {"status": "ROLLED_BACK", "approved_rule": RULE, "removed": rollback(db, tenant_id, Path(args.apply_report))}; Path(args.report).write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8"); print(json.dumps(result)); return 0
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("mode") != "READ_ONLY_HML_RECONCILIATION": raise RuntimeError("Unexpected preflight")
    documents = build_documents(preflight, tenant_id)
    if COLLECTION in db.list_collection_names(): raise RuntimeError("Target review collection already exists")
    operational_before = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in OPERATIONAL_COLLECTIONS}
    operations = [{"target_id": doc["id"], "source_key": doc["source_key"], "after_hash": document_hash(doc)} for doc in documents]
    result = {"status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED", "plan_id": PLAN_ID, "approved_rule": RULE,
              "policy": "ISOLATED_HR_REVIEW_NO_ACCOUNT_CREATION", "target": {"database": database_name, "tenant_id": tenant_id},
              "source_sha256": SOURCE_SHA, "preflight_sha256": sha256_file(preflight_path), "snapshot_sha256": args.snapshot_sha256,
              "planned": EXPECTED, "operational_before": operational_before, "operations": operations}
    if args.mode == "dry-run": Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k != "operations"})); return 0
    try:
        db.create_collection(COLLECTION); db[COLLECTION].create_index([("tenant_id", ASCENDING), ("source_node", ASCENDING), ("source_key", ASCENDING)], unique=True, name="tenant_source_key_unique"); db[COLLECTION].create_index([("tenant_id", ASCENDING), ("review_status", ASCENDING), ("record_type", ASCENDING)], name="tenant_review_type")
        with client.start_session() as session: session.with_transaction(lambda active: db[COLLECTION].insert_many(documents, ordered=True, session=active), read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        operational_after = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in OPERATIONAL_COLLECTIONS}; counts = {kind: db[COLLECTION].count_documents({"tenant_id": tenant_id, "record_type": kind}) for kind in EXPECTED}
        unsafe = db[COLLECTION].count_documents({"$or": [{"operational_eligible":{"$ne":False}}, {"account_creation_allowed":{"$ne":False}}, {"permission_replay_allowed":{"$ne":False}}, {"activation_status":{"$ne":"bloqueado"}}]})
        if counts != EXPECTED or unsafe or operational_after != operational_before: raise RuntimeError("Post-check failed")
    except Exception:
        if COLLECTION in db.list_collection_names(): db.drop_collection(COLLECTION)
        raise
    result.update({"status":"APPLIED_HOMOLOGATION", "completed_at":datetime.now(timezone.utc).isoformat(), "inserted":counts, "operational_after":operational_after, "collection":COLLECTION}); Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k != "operations"})); client.close(); return 0

if __name__ == "__main__": raise SystemExit(main())
