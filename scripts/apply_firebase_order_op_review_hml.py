#!/usr/bin/env python3
"""Stage Firebase orders and production orders in isolated HML review queues."""

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


ORDER_COLLECTION = "legacy_order_reviews"
OP_COLLECTION = "legacy_op_reviews"
RULE = "order_op_legacy_review_option_a_v1"
EXPECTED = {"commercial_order": 76, "order_line": 377, "production_order": 1388}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_document(*, tenant_id: str, record_type: str, source_node: str, record: dict[str, Any], raw: Any) -> dict[str, Any]:
    source_key = record["source_key"]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": stable_id("firebase-current", tenant_id, RULE, record_type, source_key),
        "tenant_id": tenant_id,
        "record_type": record_type,
        "source_node": source_node,
        "source_key": source_key,
        "reconciliation_classification": record.get("classification"),
        "legacy_status": record.get("legacy_status"),
        "target_client_id": record.get("target_client_id"),
        "target_sku_id": record.get("target_sku_id"),
        "target_sku_code": record.get("target_sku_code"),
        "blockers": list(record.get("blockers") or []),
        "reconciliation": record,
        "review_status": "pendente_revisao",
        "activation_status": "bloqueado",
        "operational_eligible": False,
        "source_payload": raw,
        "source_payload_sha256": payload_hash(raw),
        "created_at": now,
        "updated_at": now,
        "_migration": {
            "source": "firebase-current",
            "source_sha256": SOURCE_SHA,
            "plan_id": PLAN_ID,
            "approved_rule": RULE,
            "operation_id": stable_id(PLAN_ID, RULE, record_type, source_key),
            "applied_at": now,
        },
    }


def build_documents(source: dict[str, Any], preflight: dict[str, Any], tenant_id: str):
    definitions = (
        ("commercial_order", "pedidos_comerciais", preflight["commercial_orders"]["records"], ORDER_COLLECTION),
        ("order_line", "pedidos", preflight["order_lines"]["records"], ORDER_COLLECTION),
        ("production_order", "ops", preflight["ops"]["records"], OP_COLLECTION),
    )
    by_collection = {ORDER_COLLECTION: [], OP_COLLECTION: []}
    counts: dict[str, int] = {}
    for record_type, source_node, records, collection in definitions:
        source_records = source.get(source_node) or {}
        counts[record_type] = len(records)
        for record in records:
            source_key = record["source_key"]
            if source_key not in source_records:
                raise RuntimeError(f"Preflight/source divergence: {source_node}/{source_key}")
            by_collection[collection].append(build_document(
                tenant_id=tenant_id,
                record_type=record_type,
                source_node=source_node,
                record=record,
                raw=source_records[source_key],
            ))
    if counts != EXPECTED:
        raise RuntimeError(f"Unexpected preflight counts: {counts}")
    all_ids = [doc["id"] for docs in by_collection.values() for doc in docs]
    if len(all_ids) != len(set(all_ids)):
        raise RuntimeError("Deterministic review IDs are not unique")
    return by_collection


def create_indexes(collection):
    return [
        collection.create_index(
            [("tenant_id", ASCENDING), ("source_node", ASCENDING), ("source_key", ASCENDING)],
            unique=True,
            name="tenant_source_key_unique",
        ),
        collection.create_index(
            [("tenant_id", ASCENDING), ("review_status", ASCENDING), ("record_type", ASCENDING)],
            name="tenant_review_type",
        ),
        collection.create_index(
            [("tenant_id", ASCENDING), ("reconciliation_classification", ASCENDING)],
            name="tenant_classification",
        ),
    ]


def owned_query(tenant_id: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "_migration.approved_rule": RULE}


def rollback(db, tenant_id: str, apply_report: Path) -> dict[str, Any]:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("approved_rule") != RULE:
        raise RuntimeError("Valid order/OP apply report required")
    removed = {}
    expected_by_collection: dict[str, dict[str, str]] = {ORDER_COLLECTION: {}, OP_COLLECTION: {}}
    for operation in report["operations"]:
        expected_by_collection[operation["collection"]][operation["target_id"]] = operation["after_hash"]
    for name in (ORDER_COLLECTION, OP_COLLECTION):
        if name not in db.list_collection_names():
            raise RuntimeError(f"Review collection is absent: {name}")
        current = list(db[name].find(owned_query(tenant_id), {"_id": 0}))
        if len(current) != len(expected_by_collection[name]) or db[name].count_documents({}) != len(current):
            raise RuntimeError(f"Review collection ownership changed: {name}")
        for document in current:
            if expected_by_collection[name].get(document["id"]) != document_hash(document):
                raise RuntimeError(f"Review document edited after migration: {document['id']}")
    for name in (ORDER_COLLECTION, OP_COLLECTION):
        removed[name] = db[name].count_documents({})
        db.drop_collection(name)
    return removed


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
        raise RuntimeError("Order/OP-wave snapshot hash mismatch")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        result = {"status": "ROLLED_BACK", "approved_rule": RULE, "removed": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("mode") != "READ_ONLY_HML_RECONCILIATION":
        raise RuntimeError("Unexpected preflight document")
    documents = build_documents(source, preflight, tenant_id)
    for name in documents:
        if name in db.list_collection_names():
            raise RuntimeError(f"Target review collection already exists: {name}")

    operational_names = ("orders", "ops", "estoque_saldos_lote", "inventory_ledger", "reservas_lote")
    operational_before = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in operational_names}
    operations = [{
        "collection": name,
        "target_id": document["id"],
        "source_node": document["source_node"],
        "source_key": document["source_key"],
        "after_hash": document_hash(document),
    } for name, docs in documents.items() for document in docs]
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID,
        "policy": "A_LEGACY_REVIEW",
        "approved_rule": RULE,
        "target": {"database": database_name, "tenant_id": tenant_id},
        "source_sha256": SOURCE_SHA,
        "preflight_sha256": sha256_file(preflight_path),
        "snapshot_sha256": args.snapshot_sha256,
        "planned": EXPECTED,
        "operational_before": operational_before,
        "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
        return 0

    try:
        for name in documents:
            db.create_collection(name)
            create_indexes(db[name])
        with client.start_session() as session:
            def transaction(active):
                for name, docs in documents.items():
                    db[name].insert_many(docs, ordered=True, session=active)
            session.with_transaction(transaction, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        actual = {
            "commercial_order": db[ORDER_COLLECTION].count_documents({"record_type": "commercial_order"}),
            "order_line": db[ORDER_COLLECTION].count_documents({"record_type": "order_line"}),
            "production_order": db[OP_COLLECTION].count_documents({"record_type": "production_order"}),
        }
        operational_after = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in operational_names}
        if actual != EXPECTED or operational_after != operational_before:
            raise RuntimeError(f"Post-check failed: counts={actual}, operational={operational_before}->{operational_after}")
        for name in documents:
            if db[name].count_documents({"operational_eligible": {"$ne": False}}):
                raise RuntimeError(f"Operationally eligible review found in {name}")
    except Exception:
        for name in documents:
            if name in db.list_collection_names():
                db.drop_collection(name)
        raise

    result.update({
        "status": "APPLIED_HOMOLOGATION",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "inserted": actual,
        "operational_after": operational_after,
        "collections": list(documents),
    })
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
