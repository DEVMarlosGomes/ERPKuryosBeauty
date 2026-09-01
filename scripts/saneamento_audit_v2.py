"""
Safe data sanitation planner for Auditoria V2.

Default mode is dry-run. Apply mode is intentionally guarded and only executes
insert_one/update_one operations planned by deterministic rules.

Usage:
    python scripts/saneamento_audit_v2.py --report reports/audit_v2/saneamento_audit_v2.json
    python scripts/saneamento_audit_v2.py --apply --confirm APPLY_AUDIT_V2_SANITATION
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env", override=False)

SCRIPT_ORIGIN = "saneamento_audit_v2_2026_08"
APPLY_CONFIRMATION = "APPLY_AUDIT_V2_SANITATION"
MANUAL_SKU_CODES = {"", "a definir", "na", "n/a"}
VALID_MATERIAL_CODE_RE = re.compile(r"^(MP|EP|ES|RT)-\d{5}$", re.IGNORECASE)
SAMPLE_SUFFIX_RE = re.compile(r"\s+-\s+20\d{2}-\d{3,5}-[a-z]$", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _safe(doc: Dict[str, Any]) -> Dict[str, Any]:
    copy = deepcopy(doc)
    copy.pop("_id", None)
    return copy


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value).lower())


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _tenant_key(doc: Dict[str, Any]) -> str:
    return _clean(doc.get("tenant_id"))


def _client_name(client: Dict[str, Any]) -> str:
    return _clean(client.get("nome_empresa") or client.get("razao_social") or client.get("nome"))


def _order_client_name(order: Dict[str, Any]) -> str:
    cliente = order.get("cliente") or {}
    return _clean(cliente.get("razao_social") or cliente.get("nome"))


def _order_client_cnpj(order: Dict[str, Any]) -> str:
    return _digits((order.get("cliente") or {}).get("cnpj"))


def _is_generator_order(order: Dict[str, Any]) -> bool:
    return order.get("origem") == "gerador" or bool(order.get("gerador_origem"))


def _is_manual_item(item: Dict[str, Any]) -> bool:
    code = _norm(item.get("codigo_kuryos"))
    return not item.get("sku_id") and code in MANUAL_SKU_CODES


def _pending_key(item: Dict[str, Any]) -> Tuple[str, str]:
    return (_norm(item.get("item")), _norm(item.get("codigo_kuryos") or "A definir"))


def _base_product_name(sku: Dict[str, Any]) -> str:
    for field in ("projeto_nome", "nome_base", "produto_pai_nome"):
        value = _clean(sku.get(field))
        if value:
            return value
    name = _clean(sku.get("nome_produto"))
    return SAMPLE_SUFFIX_RE.sub("", name).strip() or name


def _op_update(collection: str, query: Dict[str, Any], set_fields: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "action": "update_one",
        "collection": collection,
        "query": query,
        "update": {"$set": set_fields},
        "reason": reason,
    }


def _op_insert(collection: str, document: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "action": "insert_one",
        "collection": collection,
        "document": document,
        "reason": reason,
    }


def _issue(issue_type: str, severity: str, detail: str, **extra: Any) -> Dict[str, Any]:
    return {"type": issue_type, "severity": severity, "detail": detail, **extra}


def _build_indexes(
    *,
    clients: Iterable[Dict[str, Any]],
    produtos_pai: Iterable[Dict[str, Any]],
    materiais: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    clients_by_id: Dict[Tuple[str, str], Dict[str, Any]] = {}
    clients_by_cnpj: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    clients_by_name: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    parents_by_id: Dict[Tuple[str, str], Dict[str, Any]] = {}
    parents_by_name: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    material_by_name: Dict[Tuple[str, str], Dict[str, Any]] = {}
    material_by_code: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for client in clients:
        tenant_id = _tenant_key(client)
        client_id = _clean(client.get("id"))
        if client_id:
            clients_by_id[(tenant_id, client_id)] = client
        cnpj = _digits(client.get("cnpj_normalized") or client.get("cnpj"))
        if cnpj:
            clients_by_cnpj.setdefault((tenant_id, cnpj), []).append(client)
        name = _norm(_client_name(client))
        if name:
            clients_by_name.setdefault((tenant_id, name), []).append(client)

    for parent in produtos_pai:
        tenant_id = _tenant_key(parent)
        parent_id = _clean(parent.get("id"))
        if parent_id:
            parents_by_id[(tenant_id, parent_id)] = parent
        name_key = (tenant_id, _clean(parent.get("cliente_id")), _norm(parent.get("nome")))
        if name_key[2]:
            parents_by_name.setdefault(name_key, []).append(parent)

    for material in materiais:
        tenant_id = _tenant_key(material)
        name = _norm(material.get("nome") or material.get("descricao"))
        code = _clean(material.get("codigo_interno")).upper()
        if name:
            material_by_name[(tenant_id, name)] = material
        if code:
            material_by_code[(tenant_id, code)] = material

    return {
        "clients_by_id": clients_by_id,
        "clients_by_cnpj": clients_by_cnpj,
        "clients_by_name": clients_by_name,
        "parents_by_id": parents_by_id,
        "parents_by_name": parents_by_name,
        "material_by_name": material_by_name,
        "material_by_code": material_by_code,
    }


def _next_reserved_material_code(tipo2: str, used_codes: set[str], planned_count: int) -> str:
    base = 90000
    candidate = f"{tipo2}-{base + planned_count:05d}"
    while candidate in used_codes:
        planned_count += 1
        candidate = f"{tipo2}-{base + planned_count:05d}"
    used_codes.add(candidate)
    return candidate


def _material_tipo_from_stock(stock: Dict[str, Any]) -> str:
    category = _norm(stock.get("categoria"))
    name = _norm(stock.get("nome") or stock.get("descricao"))
    if category in {"embalagem_primaria", "embalagem primaria", "ep"}:
        return "EP"
    if category in {"embalagem_secundaria", "embalagem secundaria", "es"}:
        return "ES"
    if category in {"rotulo", "etiqueta", "rt"}:
        return "RT"
    if "frasco" in name or "tampa" in name or "valvula" in name:
        return "EP"
    if "cartucho" in name or "caixa" in name or "sleeve" in name or "celofane" in name:
        return "ES"
    if "rotulo" in name or "etiqueta" in name:
        return "RT"
    return "MP"


def _material_document_from_stock(
    stock: Dict[str, Any],
    *,
    codigo_interno: str,
    now: str,
    material_id: str,
) -> Dict[str, Any]:
    tipo2 = codigo_interno.split("-", 1)[0].upper()
    fornecedor = _clean(stock.get("fornecedor"))
    fornecedores = []
    if fornecedor:
        fornecedores.append(
            {
                "fornecedor_id": "",
                "fornecedor_nome": fornecedor,
                "codigo_fornecedor": "",
                "status_homologacao": "pendente_identificacao",
                "adicionado_em": now,
            }
        )
    return {
        "id": material_id,
        "tenant_id": _tenant_key(stock),
        "codigo_interno": codigo_interno,
        "tipo2": tipo2,
        "subtipo": _clean(stock.get("categoria")) or "Geral",
        "nome": _clean(stock.get("nome") or stock.get("descricao")),
        "descricao": _clean(stock.get("observacoes")),
        "categoria_mp_id": "",
        "categoria_mp_codigo": "",
        "categoria_mp_nome": "",
        "unidade_estoque": _clean(stock.get("unidade_medida")) or "kg",
        "unidade_compra": _clean(stock.get("unidade_medida")) or "kg",
        "fator_conversao": 1.0,
        "fornecedores": fornecedores,
        "atributos": {
            "origem_saneamento": SCRIPT_ORIGIN,
            "pd_stock_item_id": stock.get("id"),
            "pd_stock_codigo_interno": stock.get("codigo_interno") or "",
            "custo_unitario_referencia": stock.get("custo_unitario"),
        },
        "status": "ativo",
        "created_by": "system",
        "created_by_name": "Saneamento Auditoria V2",
        "created_at": now,
        "updated_at": now,
    }


def build_saneamento_plan(
    *,
    skus: Iterable[Dict[str, Any]],
    orders: Iterable[Dict[str, Any]],
    clients: Iterable[Dict[str, Any]],
    produtos_pai: Iterable[Dict[str, Any]],
    materiais: Iterable[Dict[str, Any]],
    pd_stock_items: Iterable[Dict[str, Any]],
    now: Optional[str] = None,
) -> Dict[str, Any]:
    now = now or _now_iso()
    sku_docs = [_safe(doc) for doc in skus]
    order_docs = [_safe(doc) for doc in orders]
    client_docs = [_safe(doc) for doc in clients]
    parent_docs = [_safe(doc) for doc in produtos_pai]
    material_docs = [_safe(doc) for doc in materiais]
    stock_docs = [_safe(doc) for doc in pd_stock_items]

    indexes = _build_indexes(clients=client_docs, produtos_pai=parent_docs, materiais=material_docs)
    clients_by_id = indexes["clients_by_id"]
    clients_by_cnpj = indexes["clients_by_cnpj"]
    clients_by_name = indexes["clients_by_name"]
    parents_by_id = indexes["parents_by_id"]
    parents_by_name = indexes["parents_by_name"]
    material_by_name = indexes["material_by_name"]
    material_by_code = indexes["material_by_code"]

    operations: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    planned_parent_by_name: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for sku in sku_docs:
        sku_id = _clean(sku.get("id"))
        tenant_id = _tenant_key(sku)
        client_id = _clean(sku.get("cliente_id"))
        parent_id = _clean(sku.get("produto_pai_id"))
        if not sku_id or not tenant_id:
            issues.append(_issue("sku_sem_id_ou_tenant", "alta", "SKU sem id/tenant_id nao pode ser saneado.", sku=_safe(sku)))
            continue
        if parent_id and (tenant_id, parent_id) in parents_by_id:
            continue
        if client_id and (tenant_id, client_id) not in clients_by_id:
            issues.append(
                _issue(
                    "sku_cliente_inexistente",
                    "alta",
                    "Nao cria/vincula Produto-Pai porque cliente_id do SKU nao existe.",
                    sku_id=sku_id,
                    cliente_id=client_id,
                )
            )
            continue
        nome_base = _base_product_name(sku)
        lookup = (tenant_id, client_id, _norm(nome_base))
        candidates = parents_by_name.get(lookup, [])
        if len(candidates) == 1:
            operations.append(
                _op_update(
                    "skus",
                    {"tenant_id": tenant_id, "id": sku_id},
                    {
                        "produto_pai_id": candidates[0]["id"],
                        "updated_at": now,
                        "saneamento_audit_v2": {"origem": SCRIPT_ORIGIN, "campo": "produto_pai_id", "em": now},
                    },
                    "SKU vinculado a Produto-Pai existente por cliente e nome base unicos.",
                )
            )
            continue
        if len(candidates) > 1:
            issues.append(
                _issue(
                    "produto_pai_ambiguous",
                    "alta",
                    "Mais de um Produto-Pai candidato para o SKU.",
                    sku_id=sku_id,
                    cliente_id=client_id,
                    nome_base=nome_base,
                    candidatos=[candidate.get("id") for candidate in candidates],
                )
            )
            continue
        if not client_id or not nome_base:
            issues.append(
                _issue(
                    "produto_pai_sem_evidencia",
                    "media",
                    "Faltam cliente_id ou nome base para criar Produto-Pai.",
                    sku_id=sku_id,
                    cliente_id=client_id,
                    nome_base=nome_base,
                )
            )
            continue

        planned_parent = planned_parent_by_name.get(lookup)
        if not planned_parent:
            client = clients_by_id.get((tenant_id, client_id), {})
            planned_parent = {
                "id": _new_id(),
                "tenant_id": tenant_id,
                "nome": nome_base,
                "descricao": "Criado por saneamento seguro da Auditoria V2 para reparar SKU sem Produto-Pai.",
                "cliente_id": client_id,
                "cliente_nome": _client_name(client),
                "created_by": "system",
                "created_by_name": "Saneamento Auditoria V2",
                "created_at": now,
                "updated_at": now,
                "saneamento_audit_v2": {"origem": SCRIPT_ORIGIN, "em": now},
            }
            planned_parent_by_name[lookup] = planned_parent
            operations.append(_op_insert("produtos_pai", planned_parent, "Produto-Pai criado a partir de SKU ativo sem pai."))

        operations.append(
            _op_update(
                "skus",
                {"tenant_id": tenant_id, "id": sku_id},
                {
                    "produto_pai_id": planned_parent["id"],
                    "updated_at": now,
                    "saneamento_audit_v2": {"origem": SCRIPT_ORIGIN, "campo": "produto_pai_id", "em": now},
                },
                "SKU vinculado ao Produto-Pai planejado/criado pelo saneamento.",
            )
        )

    for order in order_docs:
        order_id = _clean(order.get("id"))
        tenant_id = _tenant_key(order)
        if not order_id or not tenant_id:
            issues.append(_issue("pedido_sem_id_ou_tenant", "alta", "Pedido sem id/tenant_id nao pode ser saneado.", order=_safe(order)))
            continue

        order_set: Dict[str, Any] = {}
        reasons: List[str] = []
        if _is_generator_order(order) and not order.get("cliente_id"):
            cnpj = _order_client_cnpj(order)
            name = _norm(_order_client_name(order))
            cnpj_candidates = clients_by_cnpj.get((tenant_id, cnpj), []) if cnpj else []
            name_candidates = clients_by_name.get((tenant_id, name), []) if name else []
            selected = cnpj_candidates[0] if len(cnpj_candidates) == 1 else None
            if not selected and len(name_candidates) == 1:
                selected = name_candidates[0]
            if selected:
                order_set["cliente_id"] = selected["id"]
                reasons.append("cliente_id recuperado por CNPJ/nome unico no CRM.")
            else:
                issues.append(
                    _issue(
                        "pedido_gerador_cliente_ambiguous",
                        "alta",
                        "Pedido do gerador sem cliente_id nao teve correspondencia unica no CRM.",
                        order_id=order_id,
                        cnpj=cnpj,
                        nome=_order_client_name(order),
                        candidatos_cnpj=len(cnpj_candidates),
                        candidatos_nome=len(name_candidates),
                    )
                )

        existing_pending = list(order.get("cadastro_pendente_items") or [])
        existing_keys = {_pending_key(item) for item in existing_pending}
        new_pending = []
        for item in order.get("items") or []:
            if _is_manual_item(item) and _pending_key(item) not in existing_keys:
                new_pending.append(
                    {
                        "item": item.get("item", ""),
                        "codigo_kuryos": item.get("codigo_kuryos") or "A definir",
                        "motivo": "Produto sem SKU cadastrado em pedido legado",
                        "origem": SCRIPT_ORIGIN,
                    }
                )
        if new_pending:
            order_set["cadastro_pendente"] = True
            order_set["cadastro_pendente_items"] = [*existing_pending, *new_pending]
            reasons.append("itens manuais antigos marcados para cadastro pendente.")

        if order_set:
            order_set["updated_at"] = now
            order_set["saneamento_audit_v2"] = {"origem": SCRIPT_ORIGIN, "em": now, "motivos": reasons}
            operations.append(
                _op_update(
                    "orders",
                    {"tenant_id": tenant_id, "id": order_id},
                    order_set,
                    " / ".join(reasons),
                )
            )

    used_material_codes = {_clean(mat.get("codigo_interno")).upper() for mat in material_docs if mat.get("codigo_interno")}
    planned_material_count = 1
    planned_material_by_name: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for stock in stock_docs:
        stock_id = _clean(stock.get("id"))
        tenant_id = _tenant_key(stock)
        name = _clean(stock.get("nome") or stock.get("descricao"))
        if not stock_id or not tenant_id:
            issues.append(_issue("estoque_lab_sem_id_ou_tenant", "alta", "Item de estoque lab sem id/tenant_id.", stock_item=_safe(stock)))
            continue
        if not name:
            issues.append(_issue("estoque_lab_sem_nome", "media", "Item de estoque lab sem nome/descricao.", stock_item_id=stock_id))
            continue

        stock_code = _clean(stock.get("codigo_interno")).upper()
        material = None
        if stock_code:
            material = material_by_code.get((tenant_id, stock_code))
        if not material:
            material = material_by_name.get((tenant_id, _norm(name)))
        if material:
            if stock.get("material_master_id") != material.get("id"):
                operations.append(
                    _op_update(
                        "pd_stock_items",
                        {"tenant_id": tenant_id, "id": stock_id},
                        {
                            "material_master_id": material.get("id"),
                            "material_master_codigo": material.get("codigo_interno"),
                            "updated_at": now,
                            "saneamento_audit_v2": {"origem": SCRIPT_ORIGIN, "campo": "material_master_id", "em": now},
                        },
                        "Estoque lab vinculado a material master existente por codigo/nome.",
                    )
                )
            continue

        lookup = (tenant_id, _norm(name))
        planned_material = planned_material_by_name.get(lookup)
        if not planned_material:
            tipo2 = _material_tipo_from_stock(stock)
            if VALID_MATERIAL_CODE_RE.match(stock_code) and stock_code not in used_material_codes:
                codigo = stock_code
                used_material_codes.add(codigo)
            else:
                codigo = _next_reserved_material_code(tipo2, used_material_codes, planned_material_count)
                planned_material_count += 1
            planned_material = _material_document_from_stock(stock, codigo_interno=codigo, now=now, material_id=_new_id())
            planned_material_by_name[lookup] = planned_material
            material_by_name[lookup] = planned_material
            operations.append(_op_insert("materiais", planned_material, "Material master criado a partir de item de estoque lab sem cadastro."))

        operations.append(
            _op_update(
                "pd_stock_items",
                {"tenant_id": tenant_id, "id": stock_id},
                {
                    "material_master_id": planned_material["id"],
                    "material_master_codigo": planned_material["codigo_interno"],
                    "updated_at": now,
                    "saneamento_audit_v2": {"origem": SCRIPT_ORIGIN, "campo": "material_master_id", "em": now},
                },
                "Estoque lab vinculado ao material master planejado/criado pelo saneamento.",
            )
        )

    collections = sorted({op["collection"] for op in operations})
    actions = sorted({op["action"] for op in operations})
    return {
        "script": "saneamento_audit_v2",
        "mode": "dry-run",
        "generated_at": now,
        "safety": {
            "default": "dry-run",
            "destructive_actions": False,
            "allowed_actions": ["insert_one", "update_one"],
            "apply_confirmation_required": APPLY_CONFIRMATION,
        },
        "summary": {
            "skus_scanned": len(sku_docs),
            "orders_scanned": len(order_docs),
            "clients_scanned": len(client_docs),
            "produtos_pai_scanned": len(parent_docs),
            "materiais_scanned": len(material_docs),
            "pd_stock_items_scanned": len(stock_docs),
            "operations": len(operations),
            "issues": len(issues),
            "operations_by_collection": {
                collection: sum(1 for op in operations if op["collection"] == collection)
                for collection in collections
            },
            "operations_by_action": {
                action: sum(1 for op in operations if op["action"] == action)
                for action in actions
            },
            "issues_by_type": {
                issue_type: sum(1 for issue in issues if issue["type"] == issue_type)
                for issue_type in sorted({issue["type"] for issue in issues})
            },
        },
        "operations": operations,
        "issues": issues,
    }


async def _load_docs(db, tenant_id: str, limit: int) -> Dict[str, List[Dict[str, Any]]]:
    query: Dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id

    skus = await db.skus.find(query, {"_id": 0}).to_list(limit)
    orders = await db.orders.find(query, {"_id": 0}).to_list(limit)
    clients = await db.crm_clients.find(query, {"_id": 0}).to_list(limit)
    produtos_pai = await db.produtos_pai.find(query, {"_id": 0}).to_list(limit)
    # Legacy typo collection, read-only fallback for environments that still have it.
    legacy_pais = await db.produto_pais.find(query, {"_id": 0}).to_list(limit)
    materiais = await db.materiais.find(query, {"_id": 0}).to_list(limit)
    pd_stock_items = await db.pd_stock_items.find(query, {"_id": 0}).to_list(limit)

    parent_ids = {_clean(parent.get("id")) for parent in produtos_pai}
    produtos_pai.extend([parent for parent in legacy_pais if _clean(parent.get("id")) not in parent_ids])

    return {
        "skus": skus,
        "orders": orders,
        "clients": clients,
        "produtos_pai": produtos_pai,
        "materiais": materiais,
        "pd_stock_items": pd_stock_items,
    }


async def apply_plan(db, plan: Dict[str, Any]) -> Dict[str, Any]:
    result = {"inserted": 0, "matched": 0, "modified": 0, "errors": []}
    for op in plan.get("operations", []):
        action = op.get("action")
        collection_name = op.get("collection")
        if action not in {"insert_one", "update_one"}:
            result["errors"].append({"operation": op, "error": f"Unsupported action {action}"})
            continue
        try:
            collection = db[collection_name]
            if action == "insert_one":
                await collection.insert_one(deepcopy(op["document"]))
                result["inserted"] += 1
            else:
                write_result = await collection.update_one(op["query"], op["update"])
                result["matched"] += getattr(write_result, "matched_count", 0)
                result["modified"] += getattr(write_result, "modified_count", 0)
        except Exception as exc:  # pragma: no cover - operational reporting guard
            result["errors"].append({"operation": op, "error": str(exc)})
    return result


def _write_report(path: str, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditoria V2 safe sanitation planner.")
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--report", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        print(json.dumps({"error": f"--apply exige --confirm {APPLY_CONFIRMATION}"}, ensure_ascii=False))
        return 2

    mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    db_name = os.environ.get("DB_NAME", "kuryos_crm")
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[db_name]
        docs = await _load_docs(db, args.tenant_id, args.limit)
        plan = build_saneamento_plan(**docs)
        plan["database"] = db_name
        plan["mode"] = "apply" if args.apply else "dry-run"
        if args.apply:
            plan["apply_result"] = await apply_plan(db, plan)
        if args.report:
            _write_report(args.report, plan)
        print(json.dumps({"mode": plan["mode"], **plan["summary"], "report": args.report or None}, ensure_ascii=False))
        if args.apply and plan.get("apply_result", {}).get("errors"):
            return 2
        return 0
    finally:
        client.close()


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
