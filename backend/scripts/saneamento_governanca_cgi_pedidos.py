"""Saneia governanca CGI de SKUs e integridade historica de pedidos.

Dry-run por padrao; use ``--apply`` para persistir. A aplicacao salva snapshots
integrais em ``data_governance_reconciliation_runs`` antes de cada alteracao.
O script nunca inventa assinatura, aprovacao ou cliente: vinculos ambiguos ficam
explicitamente pendentes de revisao.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env", override=False)
ORIGIN = "saneamento_governanca_cgi_pedidos_2026_09"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", clean(value).lower())


def digits(value: Any) -> str:
    return re.sub(r"\D", "", clean(value))


def order_fingerprint(order: dict, cliente_id: Optional[str]) -> str:
    cliente = order.get("cliente") or {}
    client_key = f"id:{cliente_id}" if cliente_id else digits(cliente.get("cnpj")) or norm(
        cliente.get("razao_social") or cliente.get("nome")
    )
    ref_key = norm(order.get("pedido_cliente_ref")) or clean(order.get("data_pedido"))[:10]
    item_keys = []
    for item in order.get("items") or []:
        code = norm(item.get("codigo_kuryos") or item.get("sku_id"))
        name = norm(item.get("item"))
        qty = round(float(item.get("qtd") or 0), 4)
        unit = round(float(item.get("valor_unitario") or 0), 4)
        item_keys.append(f"{code}:{name}:{qty}:{unit}")
    basis = "|".join([client_key, ref_key, *sorted(item_keys)])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _unique_index(items: Iterable[dict], value_getter) -> Dict[str, Optional[dict]]:
    grouped: Dict[str, list] = {}
    for item in items:
        value = value_getter(item)
        if value:
            grouped.setdefault(value, []).append(item)
    return {key: values[0] if len(values) == 1 else None for key, values in grouped.items()}


def build_plan(
    *,
    skus: list,
    orders: list,
    contracts: list,
    kickoffs: list,
    projects: list,
    pd_requests: list,
    clients: list,
    at: str,
) -> dict:
    signed = [c for c in contracts if c.get("status") in {"assinado", "vigente"}]
    kickoff_by_id = {clean(k.get("id")): k for k in kickoffs if k.get("id")}
    project_by_id = {clean(p.get("id")): p for p in projects if p.get("id")}
    pd_by_id = {clean(p.get("id")): p for p in pd_requests if p.get("id")}
    client_by_id = {clean(c.get("id")): c for c in clients if c.get("id")}
    sku_by_id = {clean(s.get("id")): s for s in skus if s.get("id")}
    sku_by_code = {norm(s.get("codigo_interno")): s for s in skus if s.get("codigo_interno")}
    client_by_cnpj = _unique_index(clients, lambda c: digits(c.get("cnpj")))
    client_by_email = _unique_index(clients, lambda c: norm(c.get("email")))
    client_by_name = _unique_index(clients, lambda c: norm(c.get("nome_empresa") or c.get("nome")))

    signed_by_project: Dict[str, dict] = {}
    signed_by_kickoff: Dict[str, dict] = {}
    for contract in signed:
        if contract.get("projeto_id"):
            signed_by_project[clean(contract["projeto_id"])] = contract
        if contract.get("kickoff_id"):
            kickoff_id = clean(contract["kickoff_id"])
            signed_by_kickoff[kickoff_id] = contract
            project_id = clean((kickoff_by_id.get(kickoff_id) or {}).get("projeto_id"))
            if project_id:
                signed_by_project.setdefault(project_id, contract)

    sku_updates = []
    sku_status_counts = {"cgi_assinado": 0, "legado_autorizado": 0}
    for sku in skus:
        project_id = clean(sku.get("projeto_id"))
        contract = signed_by_project.get(project_id)
        if contract:
            sku_status_counts["cgi_assinado"] += 1
            governance = {
                "origem_contratual_status": "cgi_assinado",
                "cgi_contrato_id": contract.get("id"),
                "cgi_numero": contract.get("numero_contrato") or contract.get("numero"),
                "cgi_assinado_em": contract.get("signed_at") or (contract.get("assinatura") or {}).get("assinado_em"),
                "legado_sem_cgi": False,
                "bloqueado_por_cgi": False,
            }
        else:
            sku_status_counts["legado_autorizado"] += 1
            governance = {
                "origem_contratual_status": "legado_autorizado",
                "legado_sem_cgi": True,
                "legado_autorizado_em": sku.get("legado_autorizado_em") or at,
                "legado_autorizado_motivo": "SKU anterior a exigencia operacional de assinatura do CGI",
                "bloqueado_por_cgi": False,
            }
        if any(sku.get(key) != value for key, value in governance.items()):
            sku_updates.append({"id": sku["id"], "set": {**governance, "governanca_atualizada_em": at}})

    order_updates = []
    stats = {
        "clientes_derivados": 0,
        "clientes_pendentes": 0,
        "pd_orfaos": 0,
        "itens_cadastro_pendente": 0,
        "fingerprints_criados": 0,
        "cgi_pendente_preenchido": 0,
        "aprovacao_pendente_preenchida": 0,
    }
    for order in orders:
        patch: Dict[str, Any] = {}
        client_id = clean(order.get("cliente_id"))
        pd_id = clean(order.get("pd_request_id"))
        pd_request = pd_by_id.get(pd_id) if pd_id else None
        kickoff = kickoff_by_id.get(clean(order.get("kickoff_id")))
        project_id = clean(order.get("projeto_id") or (pd_request or {}).get("linked_projeto_id") or (kickoff or {}).get("projeto_id"))
        project = project_by_id.get(project_id)

        candidates = []
        for candidate in [
            (pd_request or {}).get("linked_cliente_id"),
            (project or {}).get("cliente_id"),
            (project or {}).get("client_id"),
        ]:
            if clean(candidate) in client_by_id:
                candidates.append(client_by_id[clean(candidate)])
        embedded = order.get("cliente") or {}
        for candidate in [
            client_by_cnpj.get(digits(embedded.get("cnpj"))),
            client_by_email.get(norm(embedded.get("email"))),
            client_by_name.get(norm(embedded.get("razao_social") or embedded.get("nome"))),
            client_by_name.get(norm((pd_request or {}).get("client_name"))),
        ]:
            if candidate:
                candidates.append(candidate)
        unique_candidates = {c["id"]: c for c in candidates if c and c.get("id")}
        if not client_id and len(unique_candidates) == 1:
            client = next(iter(unique_candidates.values()))
            client_id = client["id"]
            patch.update({
                "cliente_id": client_id,
                "cliente_vinculo_status": "reconciliado",
                "cliente_vinculo_origem": "pd_projeto_ou_identificador_unico",
            })
            if not any(clean(value) for value in embedded.values()):
                patch["cliente"] = {
                    "nome": client.get("nome_empresa", ""),
                    "razao_social": client.get("razao_social") or client.get("nome_empresa", ""),
                    "cnpj": client.get("cnpj", ""),
                    "cidade_uf": client.get("cidade_uf", ""),
                    "responsavel": client.get("contato_nome", ""),
                    "telefone": client.get("telefone", ""),
                    "email": client.get("email", ""),
                }
            stats["clientes_derivados"] += 1
        elif not client_id:
            patch.update({
                "cliente_vinculo_status": "pendente_revisao",
                "cliente_vinculo_motivo": "sem evidencia unica para vinculo automatico",
            })
            stats["clientes_pendentes"] += 1
        else:
            patch.setdefault("cliente_vinculo_status", order.get("cliente_vinculo_status") or "valido")

        if pd_id and not pd_request:
            patch.update({
                "pd_reference_status": "orfao_historico",
                "pd_reference_review_required": True,
            })
            stats["pd_orfaos"] += 1
        elif pd_id:
            patch.update({"pd_reference_status": "valido", "pd_reference_review_required": False})

        if not order.get("cgi_status"):
            contract = signed_by_project.get(project_id) or signed_by_kickoff.get(clean(order.get("kickoff_id")))
            patch["cgi_status"] = "assinado" if contract else "pendente"
            if contract:
                patch["cgi_assinado_em"] = contract.get("signed_at") or (contract.get("assinatura") or {}).get("assinado_em")
            stats["cgi_pendente_preenchido"] += 1
        if not order.get("aprovacao_cliente"):
            patch["aprovacao_cliente"] = "pendente"
            stats["aprovacao_pendente_preenchida"] += 1

        new_items = deepcopy(order.get("items") or [])
        items_changed = False
        for item in new_items:
            sku = sku_by_id.get(clean(item.get("sku_id"))) or sku_by_code.get(norm(item.get("codigo_kuryos")))
            if sku:
                expected = {"sku_id": sku.get("id"), "cadastro_pendente": False, "cadastro_status": "cadastrado"}
            else:
                expected = {
                    "cadastro_pendente": True,
                    "cadastro_status": "pendente",
                    "cadastro_motivo": "sku_nao_encontrado" if clean(item.get("codigo_kuryos")) else "item_manual_sem_codigo",
                }
                stats["itens_cadastro_pendente"] += 1
            for key, value in expected.items():
                if item.get(key) != value:
                    item[key] = value
                    items_changed = True
        if items_changed:
            patch["items"] = new_items

        if not order.get("duplicate_fingerprint"):
            source = {**order, **patch}
            patch["duplicate_fingerprint"] = order_fingerprint(source, client_id or None)
            stats["fingerprints_criados"] += 1
        patch = {key: value for key, value in patch.items() if order.get(key) != value}
        if patch:
            patch.update({"governanca_reconciliada_em": at, "governanca_reconciliada_origem": ORIGIN, "updated_at": at})
            order_updates.append({"id": order["id"], "set": patch})

    updates_by_order = {item["id"]: item for item in order_updates}
    duplicate_groups: Dict[tuple, list] = {}
    for order in orders:
        planned = (updates_by_order.get(order["id"]) or {}).get("set") or {}
        fingerprint = planned.get("duplicate_fingerprint") or order.get("duplicate_fingerprint")
        if fingerprint and order.get("status") not in {"cancelado", "concluido"}:
            duplicate_groups.setdefault((order.get("tenant_id"), fingerprint), []).append(order)
    duplicate_orders = 0
    for (_tenant, fingerprint), grouped_orders in duplicate_groups.items():
        if len(grouped_orders) < 2:
            continue
        for order in grouped_orders:
            desired = {
                "duplicidade_status": "pendente_revisao",
                "duplicidade_grupo": fingerprint,
                "duplicidade_motivo": "pedidos ativos com a mesma assinatura de cliente, data e itens",
            }
            delta = {key: value for key, value in desired.items() if order.get(key) != value}
            if not delta:
                continue
            update = updates_by_order.get(order["id"])
            if not update:
                update = {"id": order["id"], "set": {}}
                order_updates.append(update)
                updates_by_order[order["id"]] = update
            update["set"].update(delta)
            update["set"].update({
                "governanca_reconciliada_em": at,
                "governanca_reconciliada_origem": ORIGIN,
                "updated_at": at,
            })
            duplicate_orders += 1

    return {
        "generated_at": at,
        "summary": {
            "skus_analisados": len(skus),
            "skus_cgi_assinado": sku_status_counts["cgi_assinado"],
            "skus_legado_autorizado": sku_status_counts["legado_autorizado"],
            "skus_atualizados": len(sku_updates),
            "pedidos_analisados": len(orders),
            "pedidos_atualizados": len(order_updates),
            "pedidos_duplicados_marcados": duplicate_orders,
            **stats,
        },
        "sku_updates": sku_updates,
        "order_updates": order_updates,
    }


async def load_plan(db, tenant_id: str = "") -> dict:
    query = {"tenant_id": tenant_id} if tenant_id else {}
    names = ["skus", "orders", "contratos", "kickoffs", "crm_projects", "pd_requests", "crm_clients"]
    docs = {name: await db[name].find(query, {"_id": 0}).to_list(10000) for name in names}
    return build_plan(
        skus=docs["skus"], orders=docs["orders"], contracts=docs["contratos"],
        kickoffs=docs["kickoffs"], projects=docs["crm_projects"],
        pd_requests=docs["pd_requests"], clients=docs["crm_clients"], at=now_iso(),
    )


async def apply_plan(db, plan: dict, tenant_id: str) -> dict:
    run_id = str(uuid.uuid4())
    sku_ids = [item["id"] for item in plan["sku_updates"]]
    order_ids = [item["id"] for item in plan["order_updates"]]
    snapshots = {
        "skus": await db.skus.find({"id": {"$in": sku_ids}}, {"_id": 0}).to_list(len(sku_ids) + 1),
        "orders": await db.orders.find({"id": {"$in": order_ids}}, {"_id": 0}).to_list(len(order_ids) + 1),
    }
    await db.data_governance_reconciliation_runs.insert_one({
        "id": run_id, "tenant_id": tenant_id or "__all__", "executed_at": now_iso(),
        "origin": ORIGIN, "status": "running", "summary": plan["summary"], "snapshots": snapshots,
    })
    modified = {"skus": 0, "orders": 0}
    try:
        for item in plan["sku_updates"]:
            result = await db.skus.update_one({"id": item["id"]}, {"$set": item["set"]})
            modified["skus"] += result.modified_count
        for item in plan["order_updates"]:
            result = await db.orders.update_one({"id": item["id"]}, {"$set": item["set"]})
            modified["orders"] += result.modified_count
        await db.data_governance_reconciliation_runs.update_one(
            {"id": run_id}, {"$set": {"status": "completed", "completed_at": now_iso(), "modified": modified}}
        )
    except Exception as exc:
        await db.data_governance_reconciliation_runs.update_one(
            {"id": run_id}, {"$set": {"status": "failed", "failed_at": now_iso(), "error": str(exc)}}
        )
        raise
    return {"run_id": run_id, "modified": modified}


async def main_async(args) -> int:
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    try:
        db = client[os.environ.get("DB_NAME", "kuryos_crm")]
        plan = await load_plan(db, args.tenant_id)
        payload = {"mode": "apply" if args.apply else "dry-run", **plan}
        if args.apply:
            payload["apply_result"] = await apply_plan(db, plan, args.tenant_id)
        if args.report:
            Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"mode": payload["mode"], **plan["summary"], "apply_result": payload.get("apply_result")}, ensure_ascii=False))
        return 0
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--report", default="")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
