"""Verify supplier-wave contents and prove unrelated HML collections unchanged."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient

from apply_firebase_clients_hml import PLAN_ID, assert_homologation, document_hash, load_env
from create_hml_snapshot import digest_docs, digest_indexes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--snapshot-report", required=True)
    parser.add_argument("--apply-report", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    values = load_env(Path(args.env))
    uri, database_name, tenant_id = values["ERP_HML_MONGO_URI"], values["ERP_HML_DB_NAME"], values["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    snapshot = json.loads(Path(args.snapshot_report).read_text(encoding="utf-8"))
    applied = json.loads(Path(args.apply_report).read_text(encoding="utf-8"))
    if snapshot.get("status") != "VERIFIED" or applied.get("status") != "APPLIED_HOMOLOGATION":
        raise RuntimeError("Verified snapshot and applied result are required")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    database = client[database_name]
    inventory_failures = []
    for name, before in snapshot["inventory"].items():
        collection = database[name]
        if name == "compras_fornecedores":
            if digest_indexes(collection) != before["indexes_sha256"]:
                inventory_failures.append({"collection": name, "reason": "index_drift"})
            continue
        count, content_hash = digest_docs(collection)
        index_hash = digest_indexes(collection)
        if count != before["count"] or content_hash != before["documents_sha256"] or index_hash != before["indexes_sha256"]:
            inventory_failures.append({"collection": name, "reason": "unexpected_change"})

    marker = {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}
    suppliers = list(database.compras_fornecedores.find(marker))
    expected_hashes = {item["target_id"]: item["after_hash"] for item in applied["operations"]}
    hash_mismatches = []
    for supplier in suppliers:
        comparable = dict(supplier)
        comparable.pop("_id", None)
        if expected_hashes.get(supplier.get("id")) != document_hash(comparable):
            hash_mismatches.append(supplier.get("id"))
    supplier_checks = {
        "marked_count": len(suppliers),
        "total_tenant_count": database.compras_fornecedores.count_documents({"tenant_id": tenant_id}),
        "unique_cnpj": len({item.get("cnpj_normalizado") for item in suppliers}) == len(suppliers),
        "unique_code": len({item.get("codigo_interno") for item in suppliers}) == len(suppliers),
        "all_not_started": all(item.get("homologacao", {}).get("status") == "nao_iniciada" for item in suppliers),
        "document_hash_mismatches": hash_mismatches,
    }
    valid = (
        not inventory_failures
        and supplier_checks["marked_count"] == 383
        and supplier_checks["total_tenant_count"] == 383
        and supplier_checks["unique_cnpj"]
        and supplier_checks["unique_code"]
        and supplier_checks["all_not_started"]
        and not hash_mismatches
    )
    report = {
        "status": "VERIFIED" if valid else "FAILED",
        "plan_id": PLAN_ID,
        "supplier_checks": supplier_checks,
        "unrelated_collection_failures": inventory_failures,
        "unrelated_collections_verified": len(snapshot["inventory"]) - 1 - len(inventory_failures),
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    client.close()
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
