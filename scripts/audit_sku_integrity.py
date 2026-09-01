"""
Dry-run audit for SKU governance.

Usage:
    python scripts/audit_sku_integrity.py --report reports/audit_v2/sku_integrity.json
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

SKU_RE = re.compile(r"^[A-Z]{3}-[A-Z]{4}-\d{4}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(doc: Dict[str, Any]) -> Dict[str, Any]:
    copy = dict(doc)
    copy.pop("_id", None)
    return copy


async def run_audit(db, tenant_id: str = "", limit: int = 10000) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    skus = await db.skus.find(query, {"_id": 0}).to_list(limit)
    clients = await db.crm_clients.find({"tenant_id": tenant_id} if tenant_id else {}, {"_id": 0, "id": 1}).to_list(limit)
    product_parents = await db.produtos_pai.find({"tenant_id": tenant_id} if tenant_id else {}, {"_id": 0, "id": 1}).to_list(limit)
    legacy_product_parents = await db.produto_pais.find({"tenant_id": tenant_id} if tenant_id else {}, {"_id": 0, "id": 1}).to_list(limit)
    parent_ids_seen = {doc.get("id") for doc in product_parents}
    product_parents.extend([doc for doc in legacy_product_parents if doc.get("id") not in parent_ids_seen])

    client_ids = {doc.get("id") for doc in clients}
    parent_ids = {doc.get("id") for doc in product_parents}
    by_code = defaultdict(list)
    by_variation = defaultdict(list)
    findings = []

    for sku in skus:
        code = str(sku.get("codigo_interno") or "").strip().upper()
        if code:
            by_code[(sku.get("tenant_id"), code)].append(sku)
        if sku.get("status") == "ativo" and sku.get("amostra_id") and sku.get("amostra_variacao_id"):
            by_variation[(sku.get("tenant_id"), sku.get("amostra_id"), sku.get("amostra_variacao_id"))].append(sku)
        if not SKU_RE.match(code):
            findings.append({"type": "invalid_sku_format", "sku": _safe(sku)})
        if not sku.get("cat3") or not sku.get("cli4"):
            findings.append({"type": "missing_cat3_or_cli4", "sku": _safe(sku)})
        if sku.get("cliente_id") and sku.get("cliente_id") not in client_ids:
            findings.append({"type": "missing_client_reference", "sku": _safe(sku)})
        if sku.get("produto_pai_id") and sku.get("produto_pai_id") not in parent_ids:
            findings.append({"type": "missing_product_parent_reference", "sku": _safe(sku)})
        if not sku.get("produto_pai_id"):
            findings.append({"type": "missing_product_parent", "sku": _safe(sku)})

    for key, docs in by_code.items():
        if len(docs) > 1:
            findings.append({"type": "duplicate_codigo_interno", "tenant_id": key[0], "codigo_interno": key[1], "skus": [_safe(doc) for doc in docs]})
    for key, docs in by_variation.items():
        if len(docs) > 1:
            findings.append({"type": "duplicate_active_sample_variation", "tenant_id": key[0], "amostra_id": key[1], "amostra_variacao_id": key[2], "skus": [_safe(doc) for doc in docs]})

    return {
        "script": "audit_sku_integrity",
        "mode": "dry-run",
        "generated_at": _now_iso(),
        "summary": {
            "skus_scanned": len(skus),
            "clients_scanned": len(clients),
            "product_parents_scanned": len(product_parents),
            "legacy_product_parents_scanned": len(legacy_product_parents),
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
