#!/usr/bin/env python3
"""Archive remaining Firebase source nodes in an isolated HML collection."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import PLAN_ID, SOURCE_SHA, assert_homologation, document_hash, load_env, stable_id
from reconcile_final_source_archive_wave import EXPECTED


COLLECTION = "legacy_source_archive_reviews"
RULE = "firebase_final_source_archive_v1"
TOTAL = sum(EXPECTED.values())
SENSITIVE_KEY = re.compile(r"(pass(word)?|senha|token|secret|credential|api.?key|private.?key|smtp)", re.IGNORECASE)
PROTECTED = (
    "crm_clients", "crm_projects", "pd_requests", "pd_samples", "skus", "materiais",
    "fragrancias", "estoque", "estoque_movimentos", "estoque_movimentos_lote",
    "inventory_ledger", "pcp_programacao", "ops", "orders", "production_orders",
    "compras_demandas", "compras_pos", "recebimentos", "expedicoes", "users", "rh_cargos",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sanitize(value: Any, parent_key: str = "") -> tuple[Any, int]:
    if SENSITIVE_KEY.search(parent_key):
        return "[REDACTED]", 1
    if isinstance(value, dict):
        result = {}
        redacted = 0
        for key, child in value.items():
            clean, count = sanitize(child, str(key))
            result[str(key)] = clean
            redacted += count
        return result, redacted
    if isinstance(value, list):
        result = []
        redacted = 0
        for child in value:
            clean, count = sanitize(child)
            result.append(clean)
            redacted += count
        return result, redacted
    return value, 0


def payload_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def owned(tenant_id: str) -> dict:
    return {"tenant_id": tenant_id, "_migration.approved_rule": RULE}


def build(source: dict, preflight: dict, tenant_id: str) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    documents = []
    for row in preflight["records"]:
        raw = source[row["source_node"]][row["source_key"]]
        clean_payload, redacted_fields = sanitize(raw, row["source_key"] if row["source_node"] == "config" else "")
        target_id = stable_id("firebase-current", tenant_id, RULE, row["source_node"], row["source_key"])
        documents.append({
            "id": target_id,
            "tenant_id": tenant_id,
            "record_type": f"source_archive:{row['source_node']}",
            "source_node": row["source_node"],
            "source_key": row["source_key"],
            "source_value_type": row["source_value_type"],
            "disposition": row["disposition"],
            "disposition_reason": row["disposition_reason"],
            "review_status": "pendente_revisao",
            "activation_status": "bloqueado",
            "operational_eligible": False,
            "historical_only": True,
            "operational_replay_allowed": False,
            "source_payload": clean_payload,
            "source_payload_sha256": payload_hash(clean_payload),
            "redacted_fields": redacted_fields,
            "created_at": now,
            "updated_at": now,
            "_migration": {
                "source": "firebase-current",
                "source_sha256": SOURCE_SHA,
                "plan_id": PLAN_ID,
                "approved_rule": RULE,
                "operation_id": stable_id(PLAN_ID, RULE, row["source_node"], row["source_key"]),
                "applied_at": now,
            },
        })
    counts = {node: sum(doc["source_node"] == node for doc in documents) for node in EXPECTED}
    if counts != EXPECTED or len(documents) != TOTAL or len({doc["id"] for doc in documents}) != TOTAL:
        raise RuntimeError("Unexpected final archive documents")
    return documents


def rollback(database, tenant_id: str, report_path: Path) -> int:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("approved_rule") != RULE:
        raise RuntimeError("Valid apply report required")
    expected = {row["target_id"]: row["after_hash"] for row in report["operations"]}
    current = list(database[COLLECTION].find(owned(tenant_id), {"_id": 0}))
    if len(current) != TOTAL or database[COLLECTION].count_documents({}) != TOTAL:
        raise RuntimeError("Archive collection ownership changed")
    for document in current:
        if expected.get(document["id"]) != document_hash(document):
            raise RuntimeError(f"Archive document edited: {document['id']}")
    database.drop_collection(COLLECTION)
    return len(current)


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
    database = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required")
        result = {"status": "ROLLED_BACK", "approved_rule": RULE, "removed": rollback(database, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    documents = build(source, preflight, tenant_id)
    if COLLECTION in database.list_collection_names():
        raise RuntimeError("Target archive collection already exists")
    protected_before = {name: database[name].count_documents({"tenant_id": tenant_id}) for name in PROTECTED}
    operations = [
        {"target_id": doc["id"], "source_node": doc["source_node"], "source_key": doc["source_key"], "after_hash": document_hash(doc)}
        for doc in documents
    ]
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "approved_rule": RULE,
        "target": {"database": database_name, "tenant_id": tenant_id},
        "source_sha256": SOURCE_SHA,
        "preflight_sha256": sha256_file(preflight_path),
        "snapshot_sha256": args.snapshot_sha256,
        "planned": EXPECTED,
        "total": TOTAL,
        "protected_before": protected_before,
        "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
        return 0

    try:
        database.create_collection(COLLECTION)
        database[COLLECTION].create_index([("tenant_id", ASCENDING), ("source_node", ASCENDING), ("source_key", ASCENDING)], unique=True, name="tenant_source_key_unique")
        database[COLLECTION].create_index([("tenant_id", ASCENDING), ("disposition", ASCENDING), ("source_node", ASCENDING)], name="tenant_disposition_node")
        with client.start_session() as session:
            session.with_transaction(
                lambda active: database[COLLECTION].insert_many(documents, ordered=True, session=active),
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )
        protected_after = {name: database[name].count_documents({"tenant_id": tenant_id}) for name in PROTECTED}
        counts = {node: database[COLLECTION].count_documents({"tenant_id": tenant_id, "source_node": node}) for node in EXPECTED}
        unsafe = database[COLLECTION].count_documents({"$or": [
            {"operational_eligible": {"$ne": False}},
            {"operational_replay_allowed": {"$ne": False}},
            {"activation_status": {"$ne": "bloqueado"}},
        ]})
        if counts != EXPECTED or protected_after != protected_before or unsafe:
            raise RuntimeError("Post-check failed")
    except Exception:
        if COLLECTION in database.list_collection_names():
            database.drop_collection(COLLECTION)
        raise

    result.update({
        "status": "APPLIED_HOMOLOGATION",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "inserted": counts,
        "protected_after": protected_after,
        "collection": COLLECTION,
        "redacted_fields": sum(doc["redacted_fields"] for doc in documents),
    })
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
