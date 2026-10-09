"""Create and restore-verify a full snapshot of the approved HML database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bson import json_util
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri


EXPECTED_DB = "kuryos_erp_homologacao"
HML_HOST_FRAGMENT = "yxj58uo"
PRODUCTION_HOST_FRAGMENT = "h2hedhh"


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def tool(name: str) -> str:
    located = shutil.which(name)
    if located:
        return located
    candidate = Path("C:/Program Files/MongoDB/Tools/100/bin") / f"{name}.exe"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError(f"MongoDB tool not found: {name}")


def canonical(value: Any) -> bytes:
    return json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS, sort_keys=True).encode()


def digest_docs(collection) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    documents = list(collection.find({}))
    for document in sorted(documents, key=lambda item: str(item.get("_id"))):
        digest.update(canonical(document))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def digest_indexes(collection) -> str:
    indexes = []
    for raw in collection.list_indexes():
        item = dict(raw)
        item.pop("ns", None)
        indexes.append(item)
    indexes.sort(key=lambda item: item.get("name", ""))
    return hashlib.sha256(canonical(indexes)).hexdigest()


def inventory(database) -> dict[str, dict[str, Any]]:
    result = {}
    for name in sorted(database.list_collection_names()):
        count, content_hash = digest_docs(database[name])
        result[name] = {
            "count": count,
            "documents_sha256": content_hash,
            "indexes_sha256": digest_indexes(database[name]),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--restore-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not args.restore_db.startswith("kuryos_snapshot_verify_"):
        raise RuntimeError("Unsafe disposable database name")

    values = load_env(Path(args.env))
    uri = values["ERP_HML_MONGO_URI"]
    database_name = values["ERP_HML_DB_NAME"]
    hosts = [host for host, _ in parse_uri(uri).get("nodelist", [])]
    if database_name != EXPECTED_DB or any(PRODUCTION_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Production or unexpected database target refused")
    if not any(HML_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Approved homologation host not detected")

    archive = Path(args.archive).resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise RuntimeError("Snapshot archive already exists; refusing overwrite")

    remote_client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    remote_inventory = inventory(remote_client[database_name])
    subprocess.run([
        tool("mongodump"), f"--uri={uri}", f"--db={database_name}",
        f"--archive={archive}", "--gzip",
    ], check=True, stdout=subprocess.DEVNULL)

    local_uri = "mongodb://127.0.0.1:27017"
    local_client = MongoClient(local_uri, serverSelectionTimeoutMS=5000)
    if args.restore_db in local_client.list_database_names():
        raise RuntimeError("Disposable restore database already exists")
    subprocess.run([
        tool("mongorestore"), f"--uri={local_uri}", f"--archive={archive}", "--gzip",
        f"--nsFrom={database_name}.*", f"--nsTo={args.restore_db}.*",
    ], check=True, stdout=subprocess.DEVNULL)
    restored_inventory = inventory(local_client[args.restore_db])
    verified = remote_inventory == restored_inventory
    if verified:
        local_client.drop_database(args.restore_db)
    report = {
        "status": "VERIFIED" if verified else "FAILED_RESTORE_RETAINED",
        "archive": str(archive),
        "archive_size": archive.stat().st_size,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "database": database_name,
        "collections": len(remote_inventory),
        "documents": sum(item["count"] for item in remote_inventory.values()),
        "restore_database_removed": verified,
        "inventory": remote_inventory,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "inventory"}, ensure_ascii=False))
    remote_client.close()
    local_client.close()
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
