"""Reconcilia OPs legadas, cadastros de material e duplicidades de CGI.

Dry-run por padrao. ``--apply`` persiste com snapshots em
``industrial_governance_reconciliation_runs``. Nenhuma reserva/lote, anexo ou
homologacao e inventada durante o saneamento.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env", override=False)
ORIGIN = "saneamento_ops_bom_contratos_2026_09"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", clean(value).lower())


def build_plan(docs: dict, at: str) -> dict:
    ops = docs["ops"]
    kickoffs = docs["kickoffs"]
    projects = docs["crm_projects"]
    clients = docs["crm_clients"]
    contracts = docs["contratos"]
    bom_requests = docs["cadastro_bom_solicitacoes"]
    purchase_items = docs["compras_itens"]
    stock_items = docs["pd_stock_items"]
    materials = docs["materiais"]
    catalogs = docs["pd_catalog"]

    kickoff_by_id = {k["id"]: k for k in kickoffs if k.get("id")}
    project_by_id = {p["id"]: p for p in projects if p.get("id")}
    client_by_id = {c["id"]: c for c in clients if c.get("id")}
    existing_material_by_purchase = {
        m.get("compras_item_id"): m for m in materials if m.get("compras_item_id")
    }
    existing_material_by_lab_key = {
        m.get("origem_ref_key"): m for m in materials if m.get("origem_ref_key")
    }

    op_updates = []
    for op in ops:
        if op.get("empenho_status"):
            continue
        concluded = op.get("status") in {"concluida", "cancelada"}
        patch = {
            "empenho_status": "legado_encerrado_sem_rastreabilidade" if concluded else "bloqueado_migracao_sem_lotes",
            "empenho_migracao_status": "nao_conciliavel_sem_lotes",
            "empenho_migracao_motivo": "OP anterior ao ledger por lote; nenhuma reserva retroativa foi criada",
            "requer_replanejamento_material": not concluded,
            "governanca_atualizada_em": at,
        }
        op_updates.append({"id": op["id"], "set": patch})

    contract_updates = []
    groups: Dict[tuple, list] = defaultdict(list)
    for contract in contracts:
        groups[(contract.get("tenant_id"), contract.get("kickoff_id"), int(contract.get("version") or 1))].append(contract)
    duplicate_contracts = 0
    for (_tenant, kickoff_id, version), grouped in groups.items():
        canonical = sorted(
            grouped,
            key=lambda c: (0 if c.get("status") in {"assinado", "vigente"} else 1, clean(c.get("created_at")), clean(c.get("id"))),
        )[0]
        kickoff = kickoff_by_id.get(kickoff_id) or {}
        project = project_by_id.get(kickoff.get("projeto_id") or canonical.get("projeto_id")) or {}
        client_id = clean(kickoff.get("cliente_id") or project.get("cliente_id") or project.get("client_id"))
        for contract in grouped:
            is_canonical = contract.get("id") == canonical.get("id")
            patch = {
                "version": version,
                "ativo": is_canonical,
                "projeto_id": contract.get("projeto_id") or kickoff.get("projeto_id") or project.get("id"),
                "client_id": contract.get("client_id") or client_id or None,
                "cliente_id": contract.get("cliente_id") or contract.get("client_id") or client_id or None,
            }
            if not is_canonical:
                duplicate_contracts += 1
                patch.update({
                    "governanca_duplicidade_status": "substituido",
                    "substituido_por": canonical.get("id"),
                    "substituido_em": contract.get("substituido_em") or at,
                })
                if contract.get("status") in {"gerado", "enviado"}:
                    patch["status"] = "substituido"
            delta = {key: value for key, value in patch.items() if contract.get(key) != value}
            if delta:
                delta["governanca_atualizada_em"] = at
                contract_updates.append({"id": contract["id"], "set": delta})

    request_updates = []
    pending_by_kickoff: Dict[str, int] = defaultdict(int)
    for request in bom_requests:
        if request.get("status") != "cadastrado":
            pending_by_kickoff[request.get("kickoff_id")] += 1
            patch = {
                "mrp_bloqueado": True,
                "pendencia_documental": not bool(request.get("anexo_file_ids")),
                "mrp_bloqueio_motivo": "cadastro e documento tecnico pendentes",
            }
            delta = {key: value for key, value in patch.items() if request.get(key) != value}
            if delta:
                delta["governanca_atualizada_em"] = at
                request_updates.append({"id": request["id"], "set": delta})

    kickoff_updates = []
    for kickoff in kickoffs:
        if kickoff.get("status") != "aprovado":
            continue
        pending = pending_by_kickoff.get(kickoff.get("id"), 0)
        desired = "bloqueado_cadastro_bom" if pending else "liberado"
        patch = {"mrp_status": desired, "mrp_pendencias_bom": pending}
        delta = {key: value for key, value in patch.items() if kickoff.get(key) != value}
        if delta:
            delta["governanca_atualizada_em"] = at
            kickoff_updates.append({"id": kickoff["id"], "set": delta})

    material_creates = []
    purchase_links = []
    material_ref_by_purchase: Dict[str, str] = {}
    material_ref_by_name: Dict[str, str] = {}
    for item in purchase_items:
        material = existing_material_by_purchase.get(item.get("id"))
        material_id = (material or {}).get("id") or str(uuid.uuid4())
        material_ref_by_purchase[item["id"]] = material_id
        material_ref_by_name.setdefault(norm(item.get("descricao")), material_id)
        if not material:
            material_creates.append({
                "id": material_id,
                "tenant_id": item.get("tenant_id"),
                "tipo2": "MP",
                "subtipo": item.get("sub_categoria") or item.get("categoria") or "Geral",
                "nome": item.get("descricao") or item.get("codigo_interno"),
                "descricao": "Cadastro mestre reconciliado a partir de item de Compras existente",
                "unidade_estoque": item.get("unidade_compra") or "kg",
                "unidade_compra": item.get("unidade_compra") or "kg",
                "fator_conversao": item.get("fator_conversao_producao") or 1.0,
                "status": "ativo",
                "mrp_liberado": True,
                "compras_item_id": item.get("id"),
                "origem": "reconciliacao_compras",
                "created_at": at,
                "updated_at": at,
            })
        if item.get("material_id") != material_id:
            purchase_links.append({"id": item["id"], "material_id": material_id})

    stock_groups: Dict[tuple, list] = defaultdict(list)
    for stock in stock_items:
        stock_groups[(stock.get("tenant_id"), norm(stock.get("nome")))].append(stock)
    stock_links = []
    provisional_created = 0
    catalog_by_name: Dict[str, list] = defaultdict(list)
    for catalog in catalogs:
        catalog_by_name[norm(catalog.get("nome"))].append(catalog)
    for (tenant_id, name_key), grouped in stock_groups.items():
        material_id = material_ref_by_name.get(name_key)
        material = existing_material_by_lab_key.get(f"pd_stock:{name_key}")
        if not material_id:
            material_id = (material or {}).get("id") or str(uuid.uuid4())
            if not material:
                sample = grouped[0]
                provisional_created += 1
                material_creates.append({
                    "id": material_id,
                    "tenant_id": tenant_id,
                    "tipo2": "MP",
                    "subtipo": sample.get("categoria") or "Geral",
                    "nome": sample.get("nome") or "Material laboratorio sem nome",
                    "descricao": "Cadastro provisório reconciliado do estoque de laboratório",
                    "unidade_estoque": sample.get("unidade_medida") or "kg",
                    "unidade_compra": sample.get("unidade_medida") or "kg",
                    "fator_conversao": 1.0,
                    "status": "pendente_homologacao",
                    "mrp_liberado": False,
                    "origem": "reconciliacao_estoque_laboratorio",
                    "origem_ref_key": f"pd_stock:{name_key}",
                    "created_at": at,
                    "updated_at": at,
                })
        catalogs_for_name = catalog_by_name.get(name_key) or []
        catalog_id = catalogs_for_name[0].get("id") if len(catalogs_for_name) == 1 else None
        material_is_active = material_id in set(material_ref_by_purchase.values())
        for stock in grouped:
            patch = {
                "material_id": material_id,
                "material_vinculo_status": "validado_compras" if material_is_active else "provisorio_pendente_homologacao",
                "mrp_liberado": material_is_active,
            }
            if catalog_id:
                patch["catalog_id"] = catalog_id
            delta = {key: value for key, value in patch.items() if stock.get(key) != value}
            if delta:
                delta["governanca_atualizada_em"] = at
                stock_links.append({"id": stock["id"], "set": delta})

    return {
        "generated_at": at,
        "summary": {
            "ops_analisadas": len(ops), "ops_legadas_marcadas": len(op_updates),
            "contratos_analisados": len(contracts), "contratos_atualizados": len(contract_updates),
            "contratos_duplicados_desativados": duplicate_contracts,
            "solicitacoes_bom_pendentes": sum(pending_by_kickoff.values()),
            "solicitacoes_bom_atualizadas": len(request_updates),
            "kickoffs_mrp_atualizados": len(kickoff_updates),
            "materiais_mestre_criados": len(material_creates),
            "materiais_provisorios_laboratorio": provisional_created,
            "itens_compras_vinculados": len(purchase_links),
            "itens_laboratorio_vinculados": len(stock_links),
        },
        "op_updates": op_updates,
        "contract_updates": contract_updates,
        "request_updates": request_updates,
        "kickoff_updates": kickoff_updates,
        "material_creates": material_creates,
        "purchase_links": purchase_links,
        "stock_links": stock_links,
    }


async def load_plan(db) -> dict:
    names = ["ops", "kickoffs", "crm_projects", "crm_clients", "contratos", "cadastro_bom_solicitacoes", "compras_itens", "pd_stock_items", "materiais", "pd_catalog"]
    docs = {name: await db[name].find({}, {"_id": 0}).to_list(10000) for name in names}
    return build_plan(docs, now_iso())


async def _next_material_code(db, tenant_id: str, tipo2: str) -> str:
    counter = await db.counters.find_one_and_update(
        {"_id": f"mat_{tipo2}:{tenant_id}"},
        {"$inc": {"seq": 1}, "$setOnInsert": {"start": 0}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"{tipo2}-{int((counter or {}).get('seq') or 1):05d}"


async def apply_plan(db, plan: dict) -> dict:
    run_id = str(uuid.uuid4())
    snapshots = {}
    mappings = {
        "ops": plan["op_updates"], "contratos": plan["contract_updates"],
        "cadastro_bom_solicitacoes": plan["request_updates"], "kickoffs": plan["kickoff_updates"],
        "compras_itens": plan["purchase_links"], "pd_stock_items": plan["stock_links"],
    }
    for collection, updates in mappings.items():
        ids = [item["id"] for item in updates]
        snapshots[collection] = await db[collection].find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 1)
    await db.industrial_governance_reconciliation_runs.insert_one({
        "id": run_id, "origin": ORIGIN, "status": "running", "executed_at": now_iso(),
        "summary": plan["summary"], "snapshots": snapshots,
    })
    modified = defaultdict(int)
    try:
        material_codes = {}
        for material in plan["material_creates"]:
            document = dict(material)
            document["codigo_interno"] = await _next_material_code(db, document["tenant_id"], document["tipo2"])
            await db.materiais.insert_one(document)
            material_codes[document["id"]] = document["codigo_interno"]
            modified["materiais"] += 1
        for collection, updates in mappings.items():
            for item in updates:
                patch = item.get("set") or {"material_id": item.get("material_id"), "updated_at": now_iso()}
                result = await db[collection].update_one({"id": item["id"]}, {"$set": patch})
                modified[collection] += result.modified_count
        for kickoff in await db.kickoffs.find({}, {"_id": 0, "id": 1, "bom": 1}).to_list(1000):
            bom = list(kickoff.get("bom") or [])
            changed = False
            for line in bom:
                material_id = next((p["material_id"] for p in plan["purchase_links"] if p["id"] == line.get("compras_item_id")), None)
                if material_id and line.get("material_id") != material_id:
                    line["material_id"] = material_id
                    line["codigo_material_mestre"] = material_codes.get(material_id)
                    changed = True
            if changed:
                await db.kickoffs.update_one({"id": kickoff["id"]}, {"$set": {"bom": bom, "updated_at": now_iso()}})
                modified["kickoffs_bom"] += 1
        await db.industrial_governance_reconciliation_runs.update_one(
            {"id": run_id}, {"$set": {"status": "completed", "completed_at": now_iso(), "modified": dict(modified)}}
        )
    except Exception as exc:
        await db.industrial_governance_reconciliation_runs.update_one(
            {"id": run_id}, {"$set": {"status": "failed", "failed_at": now_iso(), "error": str(exc)}}
        )
        raise
    return {"run_id": run_id, "modified": dict(modified)}


async def main_async(args) -> int:
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    try:
        db = client[os.environ.get("DB_NAME", "kuryos_crm")]
        plan = await load_plan(db)
        result = {"mode": "apply" if args.apply else "dry-run", **plan["summary"]}
        if args.apply:
            result["apply_result"] = await apply_plan(db, plan)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
