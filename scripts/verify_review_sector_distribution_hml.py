#!/usr/bin/env python3
"""Verify sector routing, uniqueness and isolation after HML distribution."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import assert_homologation, load_env
from create_hml_snapshot import digest_docs, digest_indexes
from review_sector_routing import COLLECTIONS, DISPATCH_RULE, canonical_hash, route, source_identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-report", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    snapshot = json.loads(Path(args.snapshot_report).read_text(encoding="utf-8"))
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION" or applied.get("dispatch_rule") != DISPATCH_RULE:
        raise RuntimeError("Verified inputs required")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    database = client[database_name]
    unrelated_failures = {}
    for name, before in snapshot["inventory"].items():
        if name in COLLECTIONS:
            continue
        count, content_hash = digest_docs(database[name])
        current = {"count": count, "documents_sha256": content_hash, "indexes_sha256": digest_indexes(database[name])}
        if current != before:
            unrelated_failures[name] = {"before": before, "after": current}

    expected_hashes = {(row["collection"], row["id"]): row["after_hash"] for row in applied["operations"]}
    ids = defaultdict(list)
    identities = defaultdict(list)
    sectors = Counter()
    hash_failures = []
    route_failures = []
    unsafe = 0
    total = 0
    distributed_by_rule = 0
    for collection_name in COLLECTIONS:
        documents = list(database[collection_name].find({"tenant_id": tenant_id}, {"_id": 0}))
        total += len(documents)
        for document in documents:
            ids[str(document.get("id"))].append(collection_name)
            identities[source_identity(document)].append(f"{collection_name}/{document.get('id')}")
            desired = route(collection_name, document)
            sectors[str(document.get("assigned_sector"))] += 1
            if any(document.get(key) != value for key, value in desired.items()):
                route_failures.append(f"{collection_name}/{document.get('id')}")
            if document.get("dispatch_rule") == DISPATCH_RULE:
                distributed_by_rule += 1
                if expected_hashes.get((collection_name, document.get("id"))) != canonical_hash(document):
                    hash_failures.append(f"{collection_name}/{document.get('id')}")
            if document.get("review_status") != "promovido" and document.get("operational_eligible") is not False:
                unsafe += 1
    duplicate_ids = {key: value for key, value in ids.items() if len(value) > 1}
    duplicate_identities = {key: value for key, value in identities.items() if len(value) > 1}
    valid = (
        total == applied["total_reviews"]
        and distributed_by_rule == applied["planned_updates"]
        and dict(sorted(sectors.items())) == applied["planned_sector_counts"]
        and not duplicate_ids and not duplicate_identities and not hash_failures
        and not route_failures and not unrelated_failures and unsafe == 0
    )
    result = {
        "status": "APPLIED_HOMOLOGATION_VERIFIED" if valid else "FAILED",
        "dispatch_rule": DISPATCH_RULE,
        "total_reviews": total,
        "distributed_by_rule": distributed_by_rule,
        "sector_counts": dict(sorted(sectors.items())),
        "duplicate_ids": duplicate_ids,
        "duplicate_source_identities": duplicate_identities,
        "hash_failures": hash_failures,
        "route_failures": route_failures,
        "unsafe_reviews": unsafe,
        "unrelated_collections_verified": len(snapshot["inventory"]) - len(COLLECTIONS) - len(unrelated_failures),
        "unrelated_collection_failures": unrelated_failures,
    }
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "hash_failures": len(hash_failures), "route_failures": len(route_failures), "unrelated_collection_failures": list(unrelated_failures)}, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
