#!/usr/bin/env python3
"""Apply/rollback Firebase formulas and BOMs as non-operational HML review data."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import (
    PLAN_ID,
    SOURCE_SHA,
    assert_homologation,
    document_hash,
    load_env,
    stable_id,
)


COLLECTION = "legacy_formula_bom_reviews"
RULE = "formula_bom_legacy_review_option_a_v1"
EXPECTED_FORMULAS = 197
EXPECTED_BOMS = 246
EXPECTED_TOTAL = EXPECTED_FORMULAS + EXPECTED_BOMS


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def blocking_reasons(record: dict[str, Any]) -> list[str]:
    reasons = ["legacy_review_not_operational"]
    if record.get("status") != "APROVADA":
        reasons.append("source_not_approved")
    classification = record.get("classification")
    if classification != "safe_full":
        reasons.append(f"classification:{classification}")
    for state, count in sorted((record.get("item_states") or {}).items()):
        if state != "mapped" and count:
            reasons.append(f"items:{state}:{count}")
    if not record.get("target_sku_id"):
        reasons.append("target_sku_unresolved")
    return reasons


def build_documents(source: dict[str, Any], preflight: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    documents: list[dict[str, Any]] = []
    definitions = (("formula", "formulas"), ("bom", "boms"))
    for kind, report_node in definitions:
        source_node = "formulas" if kind == "formula" else "bom"
        source_records = source.get(source_node) or {}
        for record in preflight[report_node]["records"]:
            source_key = record["source_key"]
            if source_key not in source_records:
                raise RuntimeError(f"Preflight/source divergence: {source_node}/{source_key}")
            raw = source_records[source_key]
            operation_id = stable_id(PLAN_ID, RULE, kind, source_key)
            documents.append({
                "id": stable_id("firebase-current", tenant_id, COLLECTION, kind, source_key),
                "tenant_id": tenant_id,
                "record_type": kind,
                "source_node": source_node,
                "source_key": source_key,
                "legacy_sku": record.get("legacy_sku"),
                "legacy_sku_origin": record.get("legacy_sku_origin"),
                "canonical_legacy_sku": record.get("canonical_legacy_sku"),
                "target_sku_id": record.get("target_sku_id"),
                "target_sku_code": record.get("target_sku_code"),
                "cliente_id": record.get("cliente_id"),
                "legacy_status": record.get("status"),
                "legacy_version": record.get("version"),
                "legacy_version_origin": record.get("version_origin"),
                "reconciliation_classification": record.get("classification"),
                "item_states": record.get("item_states") or {},
                "mapped_item_count": record.get("mapped_item_count", 0),
                "source_total": record.get("source_total"),
                "mapped_total": record.get("mapped_total"),
                "resolved_items": record.get("mapped_items") or [],
                "review_status": "pendente_revisao",
                "activation_status": "bloqueado",
                "operational_eligible": False,
                "blocking_reasons": blocking_reasons(record),
                "source_payload": raw,
                "source_payload_sha256": payload_hash(raw),
                "created_at": now,
                "updated_at": now,
                "_migration": {
                    "source": "firebase-current",
                    "source_sha256": SOURCE_SHA,
                    "plan_id": PLAN_ID,
                    "operation_id": operation_id,
                    "approved_rule": RULE,
                    "applied_at": now,
                },
            })
    counts = {
        kind: sum(document["record_type"] == kind for document in documents)
        for kind in ("formula", "bom")
    }
    if counts != {"formula": EXPECTED_FORMULAS, "bom": EXPECTED_BOMS}:
        raise RuntimeError(f"Expected 197 formulas/246 BOMs, found {counts}")
    if len({document["id"] for document in documents}) != EXPECTED_TOTAL:
        raise RuntimeError("Deterministic review IDs are not unique")
    return documents


def create_indexes(collection) -> list[str]:
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
            [("tenant_id", ASCENDING), ("target_sku_id", ASCENDING), ("legacy_version", DESCENDING)],
            name="tenant_target_sku_version",
        ),
    ]


def rollback(db, tenant_id: str, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("policy") != "A_LEGACY_REVIEW":
        raise RuntimeError("Valid formula/BOM review apply report required")
    if COLLECTION not in db.list_collection_names():
        raise RuntimeError("Review collection is absent; rollback refused")
    query = {"tenant_id": tenant_id, "_migration.approved_rule": RULE}
    current = list(db[COLLECTION].find(query, {"_id": 0}))
    if len(current) != EXPECTED_TOTAL or db[COLLECTION].count_documents({}) != EXPECTED_TOTAL:
        raise RuntimeError("Review collection count or ownership changed; rollback refused")
    expected = {operation["target_id"]: operation["after_hash"] for operation in report["operations"]}
    for document in current:
        if expected.get(document["id"]) != document_hash(document):
            raise RuntimeError(f"Review document edited after migration: {document['id']}")
    # The collection did not exist in the verified pre-wave snapshot. Dropping it
    # restores both documents and migration-created indexes exactly.
    db.drop_collection(COLLECTION)
    return {"collection_dropped": COLLECTION, "documents_removed": len(current)}


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
    uri = env["ERP_HML_MONGO_URI"]
    database_name = env["ERP_HML_DB_NAME"]
    tenant_id = env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)

    source_path = Path(args.source)
    preflight_path = Path(args.preflight)
    snapshot_path = Path(args.snapshot)
    if sha256_file(source_path) != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    if sha256_file(snapshot_path) != args.snapshot_sha256:
        raise RuntimeError("Formula/BOM-wave snapshot hash mismatch")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        result = {
            "status": "ROLLED_BACK",
            "plan_id": PLAN_ID,
            "policy": "A_LEGACY_REVIEW",
            "result": rollback(db, tenant_id, Path(args.apply_report)),
        }
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        client.close()
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("mode") != "READ_ONLY_LOCAL_RECONCILIATION":
        raise RuntimeError("Unexpected preflight document")
    documents = build_documents(source, preflight, tenant_id)

    if COLLECTION in db.list_collection_names():
        raise RuntimeError(f"Target review collection already exists: {COLLECTION}")
    operational_before = {
        "produtos_pai": db.produtos_pai.count_documents({"tenant_id": tenant_id}),
        "bom_items": db.bom_items.count_documents({"tenant_id": tenant_id}),
        "skus_with_parent": db.skus.count_documents({"tenant_id": tenant_id, "produto_pai_id": {"$nin": [None, ""]}}),
    }
    operations = [{
        "target_id": document["id"],
        "source_node": document["source_node"],
        "source_key": document["source_key"],
        "after_hash": document_hash(document),
    } for document in documents]
    planned = {
        "formula": sum(document["record_type"] == "formula" for document in documents),
        "bom": sum(document["record_type"] == "bom" for document in documents),
        "total": len(documents),
        "operational_writes": 0,
    }
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID,
        "policy": "A_LEGACY_REVIEW",
        "approved_rule": RULE,
        "target": {"database": database_name, "tenant_id": tenant_id, "collection": COLLECTION},
        "source_sha256": SOURCE_SHA,
        "preflight_sha256": sha256_file(preflight_path),
        "snapshot_sha256": args.snapshot_sha256,
        "operational_before": operational_before,
        "planned": planned,
        "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
        client.close()
        return 0

    try:
        db.create_collection(COLLECTION)
        create_indexes(db[COLLECTION])
        with client.start_session() as session:
            session.with_transaction(
                lambda active: db[COLLECTION].insert_many(documents, ordered=True, session=active),
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )
        by_type = {
            kind: db[COLLECTION].count_documents({"tenant_id": tenant_id, "record_type": kind})
            for kind in ("formula", "bom")
        }
        operational_after = {
            "produtos_pai": db.produtos_pai.count_documents({"tenant_id": tenant_id}),
            "bom_items": db.bom_items.count_documents({"tenant_id": tenant_id}),
            "skus_with_parent": db.skus.count_documents({"tenant_id": tenant_id, "produto_pai_id": {"$nin": [None, ""]}}),
        }
        if by_type != {"formula": EXPECTED_FORMULAS, "bom": EXPECTED_BOMS}:
            raise RuntimeError(f"Review post-check failed: {by_type}")
        if operational_after != operational_before:
            raise RuntimeError(f"Operational collections changed: {operational_before} -> {operational_after}")
        if db[COLLECTION].count_documents({"operational_eligible": {"$ne": False}}):
            raise RuntimeError("At least one review document became operationally eligible")
    except Exception:
        if COLLECTION in db.list_collection_names():
            db.drop_collection(COLLECTION)
        raise

    result.update({
        "status": "APPLIED_HOMOLOGATION",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "inserted": by_type,
        "operational_after": operational_after,
        "indexes": sorted(index["name"] for index in db[COLLECTION].list_indexes()),
    })
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
