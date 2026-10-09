#!/usr/bin/env python3
"""Stage legacy expedition history in an isolated HML review queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import PLAN_ID, SOURCE_SHA, assert_homologation, document_hash, load_env, stable_id


COLLECTION = "legacy_expedition_reviews"
RULE = "expedition_legacy_history_review_v1"
EXPECTED = 338
OPERATIONAL_COLLECTIONS = (
    "expedicao_ordens", "expedicao_transacoes", "orders", "ops", "estoque_saldos_lote",
    "inventory_ledger", "wms_paletes", "faturamento_notas", "faturamento_duplicatas",
    "devolucoes_cliente", "retrabalho_ordens",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_documents(source: dict[str, Any], preflight: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    raw_records = source.get("expedicoes_comerciais") or {}
    now = datetime.now(timezone.utc).isoformat()
    documents = []
    for record in preflight.get("records", []):
        source_key = record["source_key"]
        raw = raw_records.get(source_key)
        if raw is None: raise RuntimeError(f"Preflight/source divergence: {source_key}")
        documents.append({
            "id": stable_id("firebase-current", tenant_id, RULE, source_key), "tenant_id": tenant_id,
            "record_type": "commercial_expedition", "source_node": "expedicoes_comerciais", "source_key": source_key,
            "legacy_number": record.get("legacy_number"), "legacy_status": record.get("legacy_status"),
            "legacy_type": record.get("legacy_type"), "legacy_client": record.get("legacy_client"),
            "target_client_id": record.get("target_client_id"), "reconciliation_classification": record.get("classification"),
            "blockers": list(record.get("blockers") or []), "reconciliation": record,
            "review_status": "pendente_revisao", "activation_status": "bloqueado",
            "operational_eligible": False, "historical_only": True, "stock_replay_allowed": False,
            "source_payload": raw, "source_payload_sha256": payload_hash(raw), "created_at": now, "updated_at": now,
            "_migration": {"source": "firebase-current", "source_sha256": SOURCE_SHA, "plan_id": PLAN_ID,
                           "approved_rule": RULE, "operation_id": stable_id(PLAN_ID, RULE, source_key), "applied_at": now},
        })
    if len(documents) != EXPECTED or len({doc["id"] for doc in documents}) != EXPECTED:
        raise RuntimeError("Unexpected or duplicate expedition review documents")
    return documents


def owned_query(tenant_id: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "_migration.approved_rule": RULE}


def rollback(db, tenant_id: str, apply_report: Path) -> int:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("approved_rule") != RULE:
        raise RuntimeError("Valid apply report required")
    expected = {op["target_id"]: op["after_hash"] for op in report["operations"]}
    if COLLECTION not in db.list_collection_names(): raise RuntimeError("Review collection absent")
    current = list(db[COLLECTION].find(owned_query(tenant_id), {"_id": 0}))
    if len(current) != EXPECTED or db[COLLECTION].count_documents({}) != EXPECTED:
        raise RuntimeError("Review collection ownership changed")
    for doc in current:
        if expected.get(doc["id"]) != document_hash(doc): raise RuntimeError(f"Review document edited: {doc['id']}")
    db.drop_collection(COLLECTION); return len(current)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True); parser.add_argument("--source", required=True)
    parser.add_argument("--preflight", required=True); parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True); parser.add_argument("--apply-report")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env)); uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    source_path, preflight_path, snapshot_path = Path(args.source), Path(args.preflight), Path(args.snapshot)
    if sha256_file(source_path) != SOURCE_SHA: raise RuntimeError("Firebase source hash mismatch")
    if sha256_file(snapshot_path) != args.snapshot_sha256: raise RuntimeError("Snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000); db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report: raise RuntimeError("--apply-report is required")
        result = {"status": "ROLLED_BACK", "approved_rule": RULE, "removed": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(json.dumps(result)); return 0
    source = json.loads(source_path.read_text(encoding="utf-8")); preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("mode") != "READ_ONLY_HML_RECONCILIATION": raise RuntimeError("Unexpected preflight")
    documents = build_documents(source, preflight, tenant_id)
    if COLLECTION in db.list_collection_names(): raise RuntimeError("Target review collection already exists")
    operational_before = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in OPERATIONAL_COLLECTIONS}
    operations = [{"collection": COLLECTION, "target_id": doc["id"], "source_key": doc["source_key"], "after_hash": document_hash(doc)} for doc in documents]
    result = {"status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED", "plan_id": PLAN_ID,
              "approved_rule": RULE, "policy": "ISOLATED_HISTORICAL_REVIEW", "target": {"database": database_name, "tenant_id": tenant_id},
              "source_sha256": SOURCE_SHA, "preflight_sha256": sha256_file(preflight_path), "snapshot_sha256": args.snapshot_sha256,
              "planned": EXPECTED, "operational_before": operational_before, "operations": operations}
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k != "operations"})); return 0
    try:
        db.create_collection(COLLECTION)
        db[COLLECTION].create_index([("tenant_id", ASCENDING), ("source_key", ASCENDING)], unique=True, name="tenant_source_key_unique")
        db[COLLECTION].create_index([("tenant_id", ASCENDING), ("review_status", ASCENDING), ("legacy_type", ASCENDING)], name="tenant_review_type")
        with client.start_session() as session:
            session.with_transaction(lambda active: db[COLLECTION].insert_many(documents, ordered=True, session=active), read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        operational_after = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in OPERATIONAL_COLLECTIONS}
        count = db[COLLECTION].count_documents(owned_query(tenant_id))
        unsafe = db[COLLECTION].count_documents({"$or": [{"operational_eligible": {"$ne": False}}, {"stock_replay_allowed": {"$ne": False}}, {"activation_status": {"$ne": "bloqueado"}}]})
        if count != EXPECTED or unsafe or operational_after != operational_before: raise RuntimeError("Post-check failed")
    except Exception:
        if COLLECTION in db.list_collection_names(): db.drop_collection(COLLECTION)
        raise
    result.update({"status": "APPLIED_HOMOLOGATION", "completed_at": datetime.now(timezone.utc).isoformat(), "inserted": count, "operational_after": operational_after, "collection": COLLECTION})
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k != "operations"})); client.close(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
