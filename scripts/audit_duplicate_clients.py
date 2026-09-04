"""
Dry-run audit for duplicate CRM clients.

Usage:
    python scripts/audit_duplicate_clients.py --report reports/audit_v2/duplicate_clients.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env", override=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _safe(doc: Dict[str, Any]) -> Dict[str, Any]:
    copy = dict(doc)
    copy.pop("_id", None)
    return copy


async def run_audit(db, tenant_id: str = "", limit: int = 10000) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id

    clients = await db.crm_clients.find(query, {"_id": 0}).to_list(limit)
    by_cnpj = defaultdict(list)
    by_name = defaultdict(list)
    by_cli4 = defaultdict(list)

    for client in clients:
        cnpj = _digits(client.get("cnpj_normalized") or client.get("cnpj"))
        name = _norm(client.get("nome_empresa") or client.get("razao_social") or client.get("nome"))
        cli4 = str(client.get("cli4") or "").strip().upper()
        tenant = str(client.get("tenant_id") or "")
        if cnpj:
            by_cnpj[(tenant, cnpj)].append(client)
        if name:
            by_name[(tenant, name)].append(client)
        if cli4:
            by_cli4[(tenant, cli4)].append(client)

    findings = []
    for kind, grouped in (("cnpj", by_cnpj), ("nome", by_name), ("cli4", by_cli4)):
        for key, docs in grouped.items():
            if len(docs) > 1:
                findings.append({
                    "type": f"duplicate_{kind}",
                    "tenant_id": key[0],
                    "key": key[1],
                    "count": len(docs),
                    "clients": [_safe(doc) for doc in docs],
                })

    return {
        "script": "audit_duplicate_clients",
        "mode": "dry-run",
        "generated_at": _now_iso(),
        "summary": {
            "clients_scanned": len(clients),
            "findings": len(findings),
        },
        "findings": findings,
    }


def _write_report(path: str, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--report", default="")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    db_name = os.environ.get("DB_NAME", "kuryos_crm")
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    try:
        result = await run_audit(client[db_name], args.tenant_id, args.limit)
        if args.report:
            _write_report(args.report, result)
        print(json.dumps({"summary": result["summary"], "report": args.report or None}, ensure_ascii=False))
        return 1 if result["findings"] else 0
    finally:
        client.close()


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
