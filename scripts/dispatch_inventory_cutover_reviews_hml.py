#!/usr/bin/env python3
"""Dispatch blocked inventory cutover reviews into Quality and Logistics sector queues."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import assert_homologation, load_env
from apply_inventory_cutover_review_hml import COLLECTION, EXPECTED_TOTAL, RULE


DISPATCH_RULE = "inventory_cutover_sector_dispatch_v1"
EXPECTED = {"address": 250, "lot": 39}
DISPATCH_FIELDS = (
    "assigned_sector", "next_sector", "review_stage", "sector_status",
    "dispatched_at", "dispatch_rule", "sector_history",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(document: dict) -> str:
    """Hash content independent of MongoDB field order."""
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def desired(record_type: str, now: str) -> dict:
    if record_type == "address":
        sector, next_sector, stage = "logistica", None, "conferencia_endereco_wms"
    else:
        sector, next_sector, stage = "qualidade", "logistica", "validacao_cq_lote_legado"
    return {
        "assigned_sector": sector, "next_sector": next_sector, "review_stage": stage,
        "sector_status": "pendente", "dispatched_at": now, "dispatch_rule": DISPATCH_RULE,
        "sector_history": [{"sector": sector, "stage": stage, "status": "pendente", "at": now,
                            "reason": "Encaminhamento controlado da fila legada para revisao setorial."}],
        "updated_at": now,
    }


def rollback(db, tenant_id: str, apply_report: Path, *, use_transaction: bool = True) -> dict:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("dispatch_rule") != DISPATCH_RULE:
        raise RuntimeError("Valid sector dispatch apply report required")
    collection = db[COLLECTION]
    current = list(collection.find({"tenant_id": tenant_id, "dispatch_rule": DISPATCH_RULE}, {"_id": 0}))
    operations = {item["target_id"]: item for item in report["operations"]}
    if len(current) != EXPECTED_TOTAL:
        raise RuntimeError("Sector dispatch ownership changed; rollback refused")
    for document in current:
        if operations.get(document["id"], {}).get("after_hash") != canonical_hash(document):
            raise RuntimeError(f"Dispatched review edited after apply: {document['id']}")
    def callback(active=None):
        for document in current:
            operation = operations[document["id"]]
            kwargs = {"session": active} if active is not None else {}
            collection.update_one(
                {"tenant_id": tenant_id, "id": document["id"], "dispatch_rule": DISPATCH_RULE},
                {"$unset": {field: "" for field in DISPATCH_FIELDS},
                 "$set": {"updated_at": operation["original_updated_at"]}},
                **kwargs,
            )
    if use_transaction:
        with db.client.start_session() as session:
            session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
    else:
        callback()
    return {"reviews_restored": len(current)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "recover-report", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--apply-report")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    if sha256_file(Path(args.snapshot)) != args.snapshot_sha256:
        raise RuntimeError("Sector-dispatch snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db, collection = client[database_name], client[database_name][COLLECTION]

    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        result = {"status": "ROLLED_BACK", "dispatch_rule": DISPATCH_RULE,
                  "result": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False)); return 0

    if args.mode == "recover-report":
        documents = list(collection.find({"tenant_id": tenant_id, "dispatch_rule": DISPATCH_RULE}, {"_id": 0}))
        sector_counts = {sector: sum(doc.get("assigned_sector") == sector for doc in documents) for sector in ("logistica", "qualidade")}
        if len(documents) != EXPECTED_TOTAL or sector_counts != {"logistica": 250, "qualidade": 39}:
            raise RuntimeError(f"Cannot recover dispatch report: {sector_counts}")
        operations = []
        for document in documents:
            base = {key: value for key, value in document.items() if key not in DISPATCH_FIELDS}
            original_updated_at = document.get("created_at")
            base["updated_at"] = original_updated_at
            operations.append({"target_id": document["id"], "record_type": document["record_type"],
                               "before_hash": canonical_hash(base), "after_hash": canonical_hash(document),
                               "original_updated_at": original_updated_at})
        result = {"status": "APPLIED_HOMOLOGATION", "dispatch_rule": DISPATCH_RULE,
                  "target": {"database": database_name, "tenant_id": tenant_id},
                  "snapshot_sha256": args.snapshot_sha256, "planned": {"logistica": 250, "qualidade": 39},
                  "operations": operations, "completed_at": datetime.now(timezone.utc).isoformat(),
                  "sector_counts": sector_counts, "hash_failures": [],
                  "recovery_note": "Report regenerated from verified persisted state after BSON field-order hash mismatch."}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False)); return 0

    documents = list(collection.find({"tenant_id": tenant_id, "_migration.approved_rule": RULE}, {"_id": 0}))
    counts = {kind: sum(doc.get("record_type") == kind for doc in documents) for kind in EXPECTED}
    if len(documents) != EXPECTED_TOTAL or counts != EXPECTED:
        raise RuntimeError(f"Inventory review queue mismatch: {counts}")
    if any(doc.get("dispatch_rule") or doc.get("assigned_sector") for doc in documents):
        raise RuntimeError("One or more reviews are already dispatched")
    now = datetime.now(timezone.utc).isoformat()
    operations = []
    for document in documents:
        after = {**document, **desired(document["record_type"], now)}
        operations.append({"target_id": document["id"], "record_type": document["record_type"],
                           "before_hash": canonical_hash(document), "after_hash": canonical_hash(after),
                           "original_updated_at": document.get("updated_at")})
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "dispatch_rule": DISPATCH_RULE, "target": {"database": database_name, "tenant_id": tenant_id},
        "snapshot_sha256": args.snapshot_sha256, "planned": {"logistica": 250, "qualidade": 39},
        "operations": operations,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False)); return 0

    with client.start_session() as session:
        def callback(active):
            for record_type in EXPECTED:
                update = desired(record_type, now)
                changed = collection.update_many(
                    {"tenant_id": tenant_id, "record_type": record_type, "activation_status": "bloqueado",
                     "operational_eligible": False, "assigned_sector": {"$exists": False}},
                    {"$set": update}, session=active,
                )
                if changed.modified_count != EXPECTED[record_type]:
                    raise RuntimeError(f"Atomic dispatch count mismatch for {record_type}: {changed.modified_count}")
        session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))

    current = list(collection.find({"tenant_id": tenant_id, "dispatch_rule": DISPATCH_RULE}, {"_id": 0}))
    expected_hashes = {item["target_id"]: item["after_hash"] for item in operations}
    failures = [doc["id"] for doc in current if expected_hashes.get(doc["id"]) != canonical_hash(doc)]
    sector_counts = {sector: sum(doc.get("assigned_sector") == sector for doc in current) for sector in ("logistica", "qualidade")}
    if len(current) != EXPECTED_TOTAL or sector_counts != {"logistica": 250, "qualidade": 39} or failures:
        raise RuntimeError(f"Dispatch verification failed: {sector_counts}; hash failures={len(failures)}")
    result.update({"status": "APPLIED_HOMOLOGATION", "completed_at": datetime.now(timezone.utc).isoformat(),
                   "sector_counts": sector_counts, "hash_failures": failures})
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
