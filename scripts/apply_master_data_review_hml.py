#!/usr/bin/env python3
"""Apply or roll back the isolated blocked master-data review queue in HML."""

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


COLLECTION = "legacy_master_data_reviews"
RULE = "blocked_master_data_review_v1"
EXPECTED = {"supplier": 20, "material": 93, "sku": 3}
EXPECTED_TOTAL = 116


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_documents(source: dict[str, Any], preflight: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    documents = []
    for record in preflight["records"]:
        source_node, source_key = record["source_node"], record["source_key"]
        raw = (source.get(source_node) or {}).get(source_key)
        if not isinstance(raw, dict):
            raise RuntimeError(f"Preflight/source divergence: {source_node}/{source_key}")
        documents.append({
            "id": stable_id("firebase-current", tenant_id, COLLECTION, source_node, source_key),
            "tenant_id": tenant_id,
            **record,
            "review_status": "pendente_revisao",
            "activation_status": "bloqueado",
            "operational_eligible": False,
            "source_payload": raw,
            "source_payload_sha256": payload_hash(raw),
            "created_at": now,
            "updated_at": now,
            "_migration": {
                "source": "firebase-current", "source_sha256": SOURCE_SHA,
                "plan_id": PLAN_ID, "approved_rule": RULE,
                "operation_id": stable_id(PLAN_ID, RULE, source_node, source_key),
                "applied_at": now,
            },
        })
    counts = {kind: sum(doc["record_type"] == kind for doc in documents) for kind in EXPECTED}
    if counts != EXPECTED or len(documents) != EXPECTED_TOTAL:
        raise RuntimeError(f"Unexpected review counts: {counts}")
    if len({doc["id"] for doc in documents}) != EXPECTED_TOTAL:
        raise RuntimeError("Deterministic IDs are not unique")
    return documents


def rollback(db, tenant_id: str, apply_report: Path) -> dict[str, Any]:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("approved_rule") != RULE:
        raise RuntimeError("Valid master-data review apply report required")
    if COLLECTION not in db.list_collection_names():
        raise RuntimeError("Review collection is absent")
    documents = list(db[COLLECTION].find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}))
    expected = {operation["target_id"]: operation["after_hash"] for operation in report["operations"]}
    if len(documents) != EXPECTED_TOTAL or db[COLLECTION].count_documents({}) != EXPECTED_TOTAL:
        raise RuntimeError("Review collection ownership changed; rollback refused")
    for document in documents:
        if expected.get(document["id"]) != document_hash(document):
            raise RuntimeError(f"Review document edited after migration: {document['id']}")
    db.drop_collection(COLLECTION)
    return {"collection_dropped": COLLECTION, "documents_removed": len(documents)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--apply-report")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    source_path, preflight_path, snapshot_path = Path(args.source), Path(args.preflight), Path(args.snapshot)
    if sha256_file(source_path) != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    if sha256_file(snapshot_path) != args.snapshot_sha256:
        raise RuntimeError("Master-data-wave snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]

    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        result = {"status": "ROLLED_BACK", "approved_rule": RULE, "result": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("mode") != "READ_ONLY_LOCAL_RECONCILIATION":
        raise RuntimeError("Unexpected preflight document")
    documents = build_documents(source, preflight, tenant_id)
    if COLLECTION in db.list_collection_names():
        raise RuntimeError(f"Target review collection already exists: {COLLECTION}")
    operational_names = ("compras_fornecedores", "materiais", "fragrancias", "skus")
    operational_before = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in operational_names}
    operations = [{"target_id": doc["id"], "after_hash": document_hash(doc), "source_node": doc["source_node"], "source_key": doc["source_key"]} for doc in documents]
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID, "policy": "BLOCKED_REVIEW_ONLY", "approved_rule": RULE,
        "target": {"database": database_name, "tenant_id": tenant_id, "collection": COLLECTION},
        "source_sha256": SOURCE_SHA, "preflight_sha256": sha256_file(preflight_path),
        "snapshot_sha256": args.snapshot_sha256, "planned": EXPECTED,
        "operational_before": operational_before, "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
        return 0

    try:
        db.create_collection(COLLECTION)
        collection = db[COLLECTION]
        collection.create_index([("tenant_id", ASCENDING), ("source_node", ASCENDING), ("source_key", ASCENDING)], unique=True, name="tenant_source_key_unique")
        collection.create_index([("tenant_id", ASCENDING), ("review_status", ASCENDING), ("record_type", ASCENDING)], name="tenant_review_type")
        with client.start_session() as session:
            session.with_transaction(
                lambda active: collection.insert_many(documents, ordered=True, session=active),
                read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"),
            )
        actual = {kind: collection.count_documents({"tenant_id": tenant_id, "record_type": kind}) for kind in EXPECTED}
        operational_after = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in operational_names}
        if actual != EXPECTED or operational_after != operational_before:
            raise RuntimeError(f"Post-check failed: {actual}; operational {operational_before}->{operational_after}")
        if collection.count_documents({"operational_eligible": {"$ne": False}}):
            raise RuntimeError("An operationally eligible review was created")
    except Exception:
        if COLLECTION in db.list_collection_names():
            db.drop_collection(COLLECTION)
        raise
    result.update({"status": "APPLIED_HOMOLOGATION", "completed_at": datetime.now(timezone.utc).isoformat(), "inserted": actual, "operational_after": operational_after})
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
