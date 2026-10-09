#!/usr/bin/env python3
"""Stage procurement, receipt and quality history in isolated HML review queues."""

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


PROCUREMENT_COLLECTION = "legacy_procurement_reviews"
RECEIPT_COLLECTION = "legacy_receipt_reviews"
QUALITY_COLLECTION = "legacy_quality_reviews"
COLLECTIONS = (PROCUREMENT_COLLECTION, RECEIPT_COLLECTION, QUALITY_COLLECTION)
RULE = "procurement_receipt_quality_legacy_review_v1"
EXPECTED = {
    "purchase_request": 4,
    "purchase_order": 16,
    "receipt": 7,
    "finished_goods_check": 7,
    "nonconformity": 2,
}
OPERATIONAL_COLLECTIONS = (
    "compras_demandas", "compras_pos", "recebimentos", "estoque_saldos_lote",
    "inventory_ledger", "wms_paletes", "cq_rncs", "conferencias_pa",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_document(tenant_id: str, record_type: str, source_node: str, record: dict[str, Any], raw: Any) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    source_key = record["source_key"]
    return {
        "id": stable_id("firebase-current", tenant_id, RULE, record_type, source_key),
        "tenant_id": tenant_id,
        "record_type": record_type,
        "source_node": source_node,
        "source_key": source_key,
        "source_group_key": record.get("source_group_key"),
        "legacy_status": record.get("legacy_status"),
        "reconciliation_classification": record.get("classification"),
        "blockers": list(record.get("blockers") or []),
        "reconciliation": record,
        "review_status": "pendente_revisao",
        "activation_status": "bloqueado",
        "operational_eligible": False,
        "historical_only": True,
        "source_payload": raw,
        "source_payload_sha256": payload_hash(raw),
        "created_at": now,
        "updated_at": now,
        "_migration": {
            "source": "firebase-current", "source_sha256": SOURCE_SHA, "plan_id": PLAN_ID,
            "approved_rule": RULE, "operation_id": stable_id(PLAN_ID, RULE, record_type, source_key),
            "applied_at": now,
        },
    }


def build_documents(source: dict[str, Any], preflight: dict[str, Any], tenant_id: str) -> dict[str, list[dict[str, Any]]]:
    definitions = (
        ("purchase_request", "solicitacoes_compra", "purchase_requests", PROCUREMENT_COLLECTION),
        ("purchase_order", "pedidos_compra", "purchase_orders", PROCUREMENT_COLLECTION),
        ("receipt", "recebimentos_operacoes", "receipts", RECEIPT_COLLECTION),
        ("finished_goods_check", "conferencias_pa", "finished_goods_checks", QUALITY_COLLECTION),
        ("nonconformity", "nao_conformidades", "nonconformities", QUALITY_COLLECTION),
    )
    result = {name: [] for name in COLLECTIONS}
    counts: dict[str, int] = {}
    for record_type, source_node, report_key, collection in definitions:
        records = preflight[report_key]
        counts[record_type] = len(records)
        source_records = source.get(source_node) or {}
        for record in records:
            if record_type == "receipt":
                group = source_records.get(record.get("source_group_key")) or {}
                raw = group.get(record["source_key"])
            else:
                raw = source_records.get(record["source_key"])
            if raw is None:
                raise RuntimeError(f"Preflight/source divergence: {source_node}/{record['source_key']}")
            result[collection].append(build_document(tenant_id, record_type, source_node, record, raw))
    if counts != EXPECTED:
        raise RuntimeError(f"Unexpected preflight counts: {counts}")
    ids = [doc["id"] for docs in result.values() for doc in docs]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Deterministic review IDs are not unique")
    return result


def create_indexes(collection) -> None:
    collection.create_index([("tenant_id", ASCENDING), ("source_node", ASCENDING), ("source_group_key", ASCENDING), ("source_key", ASCENDING)], unique=True, name="tenant_source_key_unique")
    collection.create_index([("tenant_id", ASCENDING), ("review_status", ASCENDING), ("record_type", ASCENDING)], name="tenant_review_type")


def owned_query(tenant_id: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "_migration.approved_rule": RULE}


def rollback(db, tenant_id: str, apply_report: Path) -> dict[str, int]:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("approved_rule") != RULE:
        raise RuntimeError("Valid apply report required")
    expected = {name: {} for name in COLLECTIONS}
    for operation in report["operations"]:
        expected[operation["collection"]][operation["target_id"]] = operation["after_hash"]
    removed = {}
    for name in COLLECTIONS:
        if name not in db.list_collection_names():
            raise RuntimeError(f"Review collection is absent: {name}")
        current = list(db[name].find(owned_query(tenant_id), {"_id": 0}))
        if len(current) != len(expected[name]) or db[name].count_documents({}) != len(current):
            raise RuntimeError(f"Review collection ownership changed: {name}")
        for document in current:
            if expected[name].get(document["id"]) != document_hash(document):
                raise RuntimeError(f"Review document edited after migration: {document['id']}")
    for name in COLLECTIONS:
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
        raise RuntimeError("Snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        result = {"status": "ROLLED_BACK", "approved_rule": RULE, "removed": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False)); return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("mode") != "READ_ONLY_HML_RECONCILIATION":
        raise RuntimeError("Unexpected preflight document")
    documents = build_documents(source, preflight, tenant_id)
    for name in COLLECTIONS:
        if name in db.list_collection_names():
            raise RuntimeError(f"Target review collection already exists: {name}")
    operational_before = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in OPERATIONAL_COLLECTIONS}
    operations = [{"collection": name, "target_id": doc["id"], "source_node": doc["source_node"], "source_key": doc["source_key"], "after_hash": document_hash(doc)} for name, docs in documents.items() for doc in docs]
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID, "approved_rule": RULE, "policy": "ISOLATED_HISTORICAL_REVIEW",
        "target": {"database": database_name, "tenant_id": tenant_id}, "source_sha256": SOURCE_SHA,
        "preflight_sha256": sha256_file(preflight_path), "snapshot_sha256": args.snapshot_sha256,
        "planned": EXPECTED, "operational_before": operational_before, "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "operations"}, ensure_ascii=False)); return 0
    try:
        for name in COLLECTIONS:
            db.create_collection(name); create_indexes(db[name])
        with client.start_session() as session:
            def transaction(active):
                for name, docs in documents.items():
                    db[name].insert_many(docs, ordered=True, session=active)
            session.with_transaction(transaction, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        actual = {kind: db[name].count_documents({"record_type": kind}) for kind, name in {
            "purchase_request": PROCUREMENT_COLLECTION, "purchase_order": PROCUREMENT_COLLECTION,
            "receipt": RECEIPT_COLLECTION, "finished_goods_check": QUALITY_COLLECTION,
            "nonconformity": QUALITY_COLLECTION,
        }.items()}
        operational_after = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in OPERATIONAL_COLLECTIONS}
        if actual != EXPECTED or operational_after != operational_before:
            raise RuntimeError(f"Post-check failed: {actual}; {operational_before}->{operational_after}")
        if any(db[name].count_documents({"operational_eligible": {"$ne": False}}) for name in COLLECTIONS):
            raise RuntimeError("Operationally eligible review found")
    except Exception:
        for name in COLLECTIONS:
            if name in db.list_collection_names(): db.drop_collection(name)
        raise
    result.update({"status": "APPLIED_HOMOLOGATION", "completed_at": datetime.now(timezone.utc).isoformat(), "inserted": actual, "operational_after": operational_after, "collections": list(COLLECTIONS)})
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "operations"}, ensure_ascii=False))
    client.close(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
