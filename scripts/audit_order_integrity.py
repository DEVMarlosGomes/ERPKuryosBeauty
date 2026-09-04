"""
Dry-run audit for order governance.

Usage:
    python scripts/audit_order_integrity.py --report reports/audit_v2/order_integrity.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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


def _safe(doc: Dict[str, Any]) -> Dict[str, Any]:
    copy = dict(doc)
    copy.pop("_id", None)
    return copy


async def run_audit(db, tenant_id: str = "", limit: int = 10000) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    orders = await db.orders.find(query, {"_id": 0}).to_list(limit)
    clients = await db.crm_clients.find({"tenant_id": tenant_id} if tenant_id else {}, {"_id": 0, "id": 1}).to_list(limit)
    skus = await db.skus.find({"tenant_id": tenant_id} if tenant_id else {}, {"_id": 0, "id": 1, "codigo_interno": 1}).to_list(limit)

    client_ids = {doc.get("id") for doc in clients}
    sku_ids = {doc.get("id") for doc in skus}
    sku_codes = {doc.get("codigo_interno") for doc in skus}
    by_fingerprint = defaultdict(list)
    findings = []

    for order in orders:
        fingerprint = order.get("duplicate_fingerprint")
        if fingerprint and order.get("status") not in {"cancelado", "concluido"}:
            by_fingerprint[(order.get("tenant_id"), fingerprint)].append(order)

        if (order.get("origem") == "gerador" or order.get("gerador_origem")) and not order.get("cliente_id"):
            findings.append({"type": "generator_order_without_cliente_id", "order": _safe(order)})
        if order.get("cliente_id") and order.get("cliente_id") not in client_ids:
            findings.append({"type": "order_client_reference_missing", "order": _safe(order)})

        for item in order.get("items") or []:
            sku_id = item.get("sku_id")
            code = item.get("codigo_kuryos")
            if sku_id and sku_id not in sku_ids:
                findings.append({"type": "order_item_sku_id_missing", "order_id": order.get("id"), "item": item})
            if code and code not in {"A definir", "NA", "N/A"} and code not in sku_codes:
                findings.append({"type": "order_item_sku_code_missing", "order_id": order.get("id"), "item": item})
            if not sku_id and str(code or "").strip().lower() in {"", "a definir", "na", "n/a"} and not order.get("cadastro_pendente"):
                findings.append({"type": "manual_item_without_cadastro_pendente_flag", "order_id": order.get("id"), "item": item})

        if order.get("status") in {"confirmado", "em_producao", "concluido"} and order.get("cgi_status") != "assinado":
            findings.append({"type": "confirmed_order_without_signed_cgi", "order": _safe(order)})
        if order.get("status") in {"confirmado", "em_producao", "concluido"} and order.get("aprovacao_cliente") != "aprovado":
            findings.append({"type": "confirmed_order_without_client_approval", "order": _safe(order)})

    for key, docs in by_fingerprint.items():
        if len(docs) > 1:
            findings.append({"type": "duplicate_active_order_fingerprint", "tenant_id": key[0], "fingerprint": key[1], "orders": [_safe(doc) for doc in docs]})

    return {
        "script": "audit_order_integrity",
        "mode": "dry-run",
        "generated_at": _now_iso(),
        "summary": {
            "orders_scanned": len(orders),
            "clients_scanned": len(clients),
            "skus_scanned": len(skus),
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
