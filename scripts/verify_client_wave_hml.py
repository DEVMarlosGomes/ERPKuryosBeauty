"""Verify the homologation client wave against a locally restored snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bson import BSON, json_util
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri


PLAN_ID = "e5669507-b321-5187-96fa-7246cc909085"
EXPECTED_DB = "kuryos_erp_homologacao"
EXPECTED_TENANT = "a1534e89-bbfa-483f-ac0b-8d6dbf6bab22"
HML_HOST_FRAGMENT = "yxj58uo"
PRODUCTION_HOST_FRAGMENT = "h2hedhh"
PD_COLLECTIONS = ("crm_samples", "pd_requests", "pd_developments")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def assert_homologation(uri: str, db_name: str, tenant_id: str) -> None:
    hosts = [host for host, _ in parse_uri(uri).get("nodelist", [])]
    if db_name != EXPECTED_DB or tenant_id != EXPECTED_TENANT:
        raise RuntimeError("Target database/tenant is not the approved homologation target")
    if any(PRODUCTION_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Production host detected; verification refused")
    if not any(HML_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Approved homologation host not detected")


def canonical(value: Any) -> bytes:
    return json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS, sort_keys=True).encode()


def collection_digest(documents: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: str(item.get("_id"))):
        digest.update(canonical(document))
        digest.update(b"\n")
    return digest.hexdigest()


def index_digest(collection) -> str:
    indexes = []
    for index in collection.list_indexes():
        payload = dict(index)
        payload.pop("ns", None)
        indexes.append(payload)
    indexes.sort(key=lambda item: item.get("name", ""))
    return hashlib.sha256(canonical(indexes)).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    if not args.snapshot_db.startswith("kuryos_apply_verify_"):
        raise RuntimeError("Unexpected local snapshot database name")

    env = load_env(Path(args.env))
    uri = env["ERP_HML_MONGO_URI"]
    db_name = env["ERP_HML_DB_NAME"]
    tenant_id = env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, db_name, tenant_id)

    remote_client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    local_client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    remote = remote_client[db_name]
    snapshot = local_client[args.snapshot_db]

    baseline_clients = list(snapshot.crm_clients.find({"tenant_id": tenant_id}))
    old_clients = list(remote.crm_clients.find({
        "tenant_id": tenant_id,
        "$or": [{"_migration.plan_id": {"$ne": PLAN_ID}}, {"_migration": {"$exists": False}}],
    }))
    checks: dict[str, Any] = {
        "existing_clients": {
            "snapshot_count": len(baseline_clients),
            "homologation_unmarked_count": len(old_clients),
            "snapshot_sha256": collection_digest(baseline_clients),
            "homologation_sha256": collection_digest(old_clients),
        },
        "pd_collections": {},
    }
    checks["existing_clients"]["unchanged"] = (
        checks["existing_clients"]["snapshot_count"] == checks["existing_clients"]["homologation_unmarked_count"]
        and checks["existing_clients"]["snapshot_sha256"] == checks["existing_clients"]["homologation_sha256"]
    )

    for name in PD_COLLECTIONS:
        baseline_docs = list(snapshot[name].find({"tenant_id": tenant_id}))
        remote_docs = list(remote[name].find({"tenant_id": tenant_id}))
        details = {
            "snapshot_count": len(baseline_docs),
            "homologation_count": len(remote_docs),
            "snapshot_sha256": collection_digest(baseline_docs),
            "homologation_sha256": collection_digest(remote_docs),
            "snapshot_indexes_sha256": index_digest(snapshot[name]),
            "homologation_indexes_sha256": index_digest(remote[name]),
            "migration_marked_count": remote[name].count_documents({"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}),
        }
        details["unchanged"] = (
            details["snapshot_count"] == details["homologation_count"]
            and details["snapshot_sha256"] == details["homologation_sha256"]
            and details["snapshot_indexes_sha256"] == details["homologation_indexes_sha256"]
            and details["migration_marked_count"] == 0
        )
        checks["pd_collections"][name] = details

    query = {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}
    marked_clients = list(remote.crm_clients.find(query))
    client_ids = [doc.get("id") for doc in marked_clients]
    cli4_values = [doc.get("cli4") for doc in marked_clients]
    related_tasks = remote.workflow_tasks.count_documents({**query, "entity_id": {"$in": client_ids}})
    related_audits = remote.audit_logs.count_documents({**query, "entity_id": {"$in": client_ids}})
    checks["new_wave"] = {
        "clients": len(marked_clients),
        "all_in_prospeccao": all(doc.get("stage") == "prospeccao" for doc in marked_clients),
        "unique_ids": len(set(client_ids)) == len(client_ids),
        "unique_cli4": len(set(cli4_values)) == len(cli4_values),
        "workflow_tasks": related_tasks,
        "audit_logs": related_audits,
    }
    checks["new_wave"]["valid"] = (
        checks["new_wave"]["clients"] == 56
        and checks["new_wave"]["all_in_prospeccao"]
        and checks["new_wave"]["unique_ids"]
        and checks["new_wave"]["unique_cli4"]
        and related_tasks == 56
        and related_audits == 56
    )

    ok = checks["existing_clients"]["unchanged"] and checks["new_wave"]["valid"]
    ok = ok and all(item["unchanged"] for item in checks["pd_collections"].values())
    report = {"status": "VERIFIED" if ok else "FAILED", "plan_id": PLAN_ID, "checks": checks}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    remote_client.close()
    local_client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
