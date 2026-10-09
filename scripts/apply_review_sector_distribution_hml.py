#!/usr/bin/env python3
"""Atomically add one sector destination to each unassigned legacy review in HML."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient, UpdateOne
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import assert_homologation, load_env
from review_sector_routing import DISPATCH_RULE, ROUTING_FIELDS, canonical_hash


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update_fields(row: dict, now: str) -> dict:
    desired = row["desired"]
    return {
        **desired,
        "dispatched_at": now,
        "dispatch_rule": DISPATCH_RULE,
        "sector_history": [{
            "sector": desired["assigned_sector"],
            "stage": desired["review_stage"],
            "status": desired["sector_status"],
            "at": now,
            "reason": "Distribuicao controlada da auditoria Firebase para o setor responsavel.",
        }],
        "updated_at": now,
    }


def rollback(database, tenant_id: str, apply_report: Path, *, use_transaction: bool = True) -> dict:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("dispatch_rule") != DISPATCH_RULE:
        raise RuntimeError("Valid distribution apply report required")
    operations = report["operations"]
    by_collection: dict[str, list[dict]] = {}
    for operation in operations:
        by_collection.setdefault(operation["collection"], []).append(operation)
    for collection_name, rows in by_collection.items():
        current = list(database[collection_name].find({
            "tenant_id": tenant_id,
            "dispatch_rule": DISPATCH_RULE,
            "id": {"$in": [row["id"] for row in rows]},
        }, {"_id": 0}))
        expected = {row["id"]: row["after_hash"] for row in rows}
        if len(current) != len(rows):
            raise RuntimeError(f"Distribution ownership changed: {collection_name}")
        for document in current:
            if expected.get(document["id"]) != canonical_hash(document):
                raise RuntimeError(f"Distributed review edited after apply: {collection_name}/{document['id']}")

    def callback(session=None):
        kwargs = {"session": session} if session is not None else {}
        for operation in operations:
            result = database[operation["collection"]].update_one(
                {"tenant_id": tenant_id, "id": operation["id"], "dispatch_rule": DISPATCH_RULE},
                {
                    "$unset": {field: "" for field in ROUTING_FIELDS},
                    "$set": {"updated_at": operation["original_updated_at"]},
                },
                **kwargs,
            )
            if result.modified_count != 1:
                raise RuntimeError(f"Rollback count mismatch: {operation['collection']}/{operation['id']}")
    if use_transaction:
        with database.client.start_session() as session:
            session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
    else:
        callback()
    return {"reviews_restored": len(operations)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--apply-report")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    if sha256_file(Path(args.snapshot)) != args.snapshot_sha256:
        raise RuntimeError("Distribution snapshot hash mismatch")
    preflight = json.loads(Path(args.preflight).read_text(encoding="utf-8"))
    if preflight.get("decision_gate", {}).get("status") != "READY_FOR_ATOMIC_SECTOR_DISTRIBUTION":
        raise RuntimeError("Approved preflight required")
    if preflight["target"] != {"database": database_name, "tenant_id": tenant_id}:
        raise RuntimeError("Preflight target mismatch")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    database = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required")
        result = {"status": "ROLLED_BACK", "dispatch_rule": DISPATCH_RULE, "result": rollback(database, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    rows = [row for row in preflight["records"] if row["needs_update"]]
    if len(rows) != preflight["planned_updates"]:
        raise RuntimeError("Preflight update count mismatch")
    now = datetime.now(timezone.utc).isoformat()
    rows_by_collection: dict[str, list[dict]] = {}
    for row in rows:
        rows_by_collection.setdefault(row["collection"], []).append(row)
    operations = []
    for collection_name, collection_rows in rows_by_collection.items():
        documents = list(database[collection_name].find({
            "tenant_id": tenant_id,
            "id": {"$in": [row["id"] for row in collection_rows]},
        }, {"_id": 0}))
        documents_by_id = {document["id"]: document for document in documents}
        for row in collection_rows:
            document = documents_by_id.get(row["id"])
            if not document or document.get("assigned_sector") or canonical_hash(document) != row["before_hash"]:
                raise RuntimeError(f"Review changed after preflight: {row['collection']}/{row['id']}")
            after = {**document, **update_fields(row, now)}
            operations.append({
                "collection": row["collection"],
                "id": row["id"],
                "sector": row["desired"]["assigned_sector"],
                "before_hash": row["before_hash"],
                "after_hash": canonical_hash(after),
                "original_updated_at": row["original_updated_at"],
            })
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "dispatch_rule": DISPATCH_RULE,
        "target": {"database": database_name, "tenant_id": tenant_id},
        "preflight_sha256": sha256_file(Path(args.preflight)),
        "snapshot_sha256": args.snapshot_sha256,
        "total_reviews": preflight["total_reviews"],
        "already_dispatched": preflight["already_dispatched"],
        "planned_updates": len(operations),
        "planned_sector_counts": preflight["planned_sector_counts"],
        "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
        return 0

    with client.start_session() as session:
        def callback(active):
            for collection_name, collection_rows in rows_by_collection.items():
                requests = [UpdateOne(
                    {
                        "tenant_id": tenant_id,
                        "id": row["id"],
                        "assigned_sector": {"$exists": False},
                        "activation_status": {"$in": ["bloqueado", "promovido"]},
                    },
                    {"$set": update_fields(row, now)},
                ) for row in collection_rows]
                result_update = database[collection_name].bulk_write(requests, ordered=True, session=active)
                if result_update.modified_count != len(collection_rows):
                    raise RuntimeError(f"Atomic distribution mismatch: {collection_name}/{result_update.modified_count}")
        session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))

    failures = []
    operations_by_collection: dict[str, list[dict]] = {}
    for operation in operations:
        operations_by_collection.setdefault(operation["collection"], []).append(operation)
    for collection_name, collection_operations in operations_by_collection.items():
        documents = list(database[collection_name].find({
            "tenant_id": tenant_id,
            "id": {"$in": [operation["id"] for operation in collection_operations]},
        }, {"_id": 0}))
        expected = {operation["id"]: operation["after_hash"] for operation in collection_operations}
        failures.extend(
            f"{collection_name}/{document['id']}"
            for document in documents
            if expected.get(document["id"]) != canonical_hash(document)
        )
        if len(documents) != len(collection_operations):
            failures.append(f"{collection_name}/missing_documents")
    if failures:
        raise RuntimeError(f"Post-distribution hash failures: {len(failures)}")
    result.update({"status": "APPLIED_HOMOLOGATION", "completed_at": datetime.now(timezone.utc).isoformat(), "hash_failures": failures})
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
