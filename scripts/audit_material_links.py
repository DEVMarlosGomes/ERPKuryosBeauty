"""
Dry-run audit for material/supplier links across homologation, cadastros and lab stock.

Usage:
    python scripts/audit_material_links.py --report reports/audit_v2/material_links.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
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


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _safe(doc: Dict[str, Any]) -> Dict[str, Any]:
    copy = dict(doc)
    copy.pop("_id", None)
    return copy


async def _load(collection, tenant_id: str, limit: int) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    return await collection.find(query, {"_id": 0}).to_list(limit)


async def run_audit(db, tenant_id: str = "", limit: int = 10000) -> Dict[str, Any]:
    homolog_mps = await _load(db.homologacao_mps, tenant_id, limit)
    homolog_suppliers = await _load(db.homologacao_fornecedores, tenant_id, limit)
    materiais = await _load(db.materiais, tenant_id, limit)
    stock_items = await _load(db.pd_stock_items, tenant_id, limit)
    compras_suppliers = await _load(db.compras_fornecedores, tenant_id, limit)

    supplier_ids = {doc.get("id") for doc in homolog_suppliers + compras_suppliers if doc.get("id")}
    supplier_names = {_norm(doc.get("razao_social") or doc.get("nome_fantasia") or doc.get("fornecedor_nome")) for doc in homolog_suppliers + compras_suppliers}
    material_names = {_norm(doc.get("nome") or doc.get("nome_material") or doc.get("descricao")) for doc in materiais}
    homolog_mp_names = {_norm(doc.get("nome") or doc.get("nome_material") or doc.get("descricao")) for doc in homolog_mps}

    findings = []
    for mp in homolog_mps:
        fornecedor_id = mp.get("fornecedor_id")
        fornecedor_nome = _norm(mp.get("fornecedor_nome") or mp.get("fornecedor") or "")
        if fornecedor_id and fornecedor_id not in supplier_ids:
            findings.append({"type": "homolog_mp_supplier_id_missing", "mp": _safe(mp)})
        if fornecedor_nome and fornecedor_nome not in supplier_names:
            findings.append({"type": "homolog_mp_supplier_name_missing", "mp": _safe(mp)})
        mp_name = _norm(mp.get("nome") or mp.get("nome_material") or mp.get("descricao"))
        if mp_name and mp_name not in material_names:
            findings.append({"type": "homolog_mp_not_in_cadastros_materiais", "mp": _safe(mp)})

    for material in materiais:
        material_name = _norm(material.get("nome") or material.get("nome_material") or material.get("descricao"))
        if material_name and material_name not in homolog_mp_names:
            findings.append({"type": "material_without_homologacao_mp", "material": _safe(material)})

    for stock in stock_items:
        stock_name = _norm(stock.get("nome") or stock.get("descricao"))
        if stock_name and stock_name not in material_names and stock_name not in homolog_mp_names:
            findings.append({"type": "lab_stock_without_material_master", "stock_item": _safe(stock)})

    return {
        "script": "audit_material_links",
        "mode": "dry-run",
        "generated_at": _now_iso(),
        "summary": {
            "homolog_mps": len(homolog_mps),
            "homolog_suppliers": len(homolog_suppliers),
            "materiais": len(materiais),
            "lab_stock_items": len(stock_items),
            "compras_suppliers": len(compras_suppliers),
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
