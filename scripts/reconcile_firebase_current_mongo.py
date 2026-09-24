"""Read-only Firebase -> current ERP reconciliation for an approved tenant.

The script reads an immutable Firebase JSON export and an explicitly configured
homologation Mongo database.  It never mutates MongoDB.  Its only writes are
JSON reports in the requested local output directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pymongo import MongoClient


EXPECTED_SHA = "7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c for c in raw if not unicodedata.combining(c)).upper().split())


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def source_records(source: dict[str, Any], node: str) -> Iterable[tuple[str, Any]]:
    value = source.get(node, {})
    if isinstance(value, dict):
        return ((str(key), payload) for key, payload in value.items())
    return (("__root__", value),)


def flatten_nested(source: dict[str, Any], node: str) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    outer = source.get(node, {})
    if not isinstance(outer, dict):
        return flattened
    for parent_id, children in outer.items():
        if not isinstance(children, dict):
            continue
        for legacy_id, payload in children.items():
            if isinstance(payload, dict):
                flattened.append({"parent_id": str(parent_id), "legacy_id": str(legacy_id), "payload": payload})
    return flattened


def target_id(document: dict[str, Any]) -> str:
    return str(document.get("id") or document.get("_id"))


def grouped(documents: Iterable[dict[str, Any]], getter) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        key = getter(document)
        if key:
            result[str(key)].append(document)
    return result


def classify_exact(matches: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    if len(matches) == 1:
        return "MATCH", matches[0]
    if len(matches) > 1:
        return "CONFLICT", None
    return "INSERT_CANDIDATE", None


def material_domain(payload: dict[str, Any]) -> tuple[str | None, str, str]:
    legacy_type = norm_text(payload.get("tipo"))
    if legacy_type == "MPGR":
        return "materiais:MP", "medium", "Tipo legado MPGR sugere materia-prima; exige validacao humana."
    if legacy_type == "MPES" or payload.get("casaFragrancia") or payload.get("inspiracao"):
        return "fragrancias", "medium", "Campos semanticos indicam essencia/fragrancia; confirmar dominio separado."
    if legacy_type == "EP":
        return "materiais:EP", "medium", "Tipo legado EP sugere embalagem primaria."
    if legacy_type == "ES":
        return "materiais:ES", "medium", "Tipo legado ES sugere embalagem secundaria."
    if legacy_type == "ET":
        return "materiais:RT|ES", "low", "ET mistura rotulos, etiquetas e caixas; exige classificacao item a item."
    return None, "low", "Familia legada sem correspondencia governada segura."


def safe_index_names(db, collections: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name in collections:
        try:
            result[name] = [str(index.get("name")) for index in db[name].list_indexes()]
        except Exception:
            result[name] = []
    return result


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: reconcile_firebase_current_mongo.py SOURCE_JSON ENV_FILE OUTPUT_DIR EXISTING_REPORT_DIR")

    source_path = Path(sys.argv[1]).resolve()
    env_path = Path(sys.argv[2]).resolve()
    output = Path(sys.argv[3]).resolve()
    existing = Path(sys.argv[4]).resolve()
    output.mkdir(parents=True, exist_ok=True)

    actual_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_sha != EXPECTED_SHA:
        raise RuntimeError(f"Firebase source SHA mismatch: {actual_sha}")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    env = load_env(env_path)
    required = ("ERP_HML_MONGO_URI", "ERP_HML_DB_NAME", "ERP_HML_TENANT_ID")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise RuntimeError(f"Missing required configuration keys: {', '.join(missing)}")

    uri = env["ERP_HML_MONGO_URI"]
    db_name = env["ERP_HML_DB_NAME"]
    tenant_id = env["ERP_HML_TENANT_ID"]
    generated_at = datetime.now(timezone.utc).isoformat()

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[db_name]
    tenant = db.tenants.find_one({"id": tenant_id}, {"_id": 1, "id": 1, "name": 1})
    if not tenant:
        raise RuntimeError("Approved tenant_id was not found in the homologation database")

    target_collections = [
        "crm_clients", "compras_fornecedores", "materiais", "fragrancias", "skus",
        "orders", "ops", "wms_enderecos", "estoque_saldos_lote", "produtos_pai",
        "bom_items", "estoque_movimentos_lote", "wms_paletes", "cq_status_lote",
    ]
    target_docs = {
        name: list(db[name].find({"tenant_id": tenant_id}))
        for name in target_collections
    }
    target_counts = {name: db[name].count_documents({"tenant_id": tenant_id}) for name in target_collections}
    target_indexes = safe_index_names(db, target_collections)

    # Clients: exact normalized CNPJ, then exact normalized name. Multiple hits are conflicts.
    clients_target = target_docs["crm_clients"]
    clients_by_cnpj = grouped(clients_target, lambda d: digits(d.get("cnpj_normalized") or d.get("cnpj")))
    clients_by_name = grouped(clients_target, lambda d: norm_text(d.get("nome_empresa") or d.get("nome")))
    client_entries: list[dict[str, Any]] = []
    for legacy_id, raw in source_records(source, "clientes"):
        payload = raw if isinstance(raw, dict) else {}
        cnpj = digits(payload.get("cnpj"))
        name = norm_text(payload.get("nome"))
        basis = None
        matches: list[dict[str, Any]] = []
        if cnpj:
            matches = clients_by_cnpj.get(cnpj, [])
            basis = "CNPJ_EXACT" if matches else None
        if not matches and name:
            matches = clients_by_name.get(name, [])
            basis = "NAME_EXACT" if matches else None
        classification, match = classify_exact(matches)
        reason = {
            "MATCH": f"Correspondencia unica por {basis} dentro do tenant aprovado.",
            "CONFLICT": f"Mais de um cliente alvo corresponde por {basis}; nenhuma decisao automatica.",
            "INSERT_CANDIDATE": "Nenhum cliente alvo corresponde por CNPJ ou nome normalizado.",
        }[classification]
        client_entries.append({
            "legacy_id": legacy_id,
            "normalized_cnpj": cnpj,
            "normalized_name": name,
            "current_client_id": target_id(match) if match else None,
            "current_cli4": match.get("cli4") if match else None,
            "current_cli4_frozen": bool(match.get("cli4_congelado")) if match else None,
            "classification": classification,
            "match_basis": basis,
            "reason": reason,
            "preserve_frozen_cli4": True,
        })
    write_json(output / "CLIENT_ID_MAP.json", {"source_node": "clientes", "tenant_id": tenant_id, "entries": client_entries})

    # Suppliers: CNPJ is authoritative; name is only a suggestion.
    suppliers_target = target_docs["compras_fornecedores"]
    suppliers_by_cnpj = grouped(suppliers_target, lambda d: digits(d.get("cnpj_normalizado") or d.get("cnpj")))
    suppliers_by_name = grouped(suppliers_target, lambda d: norm_text(d.get("razao_social") or d.get("nome_fantasia") or d.get("nome")))
    source_supplier_cnpj = Counter(
        digits(raw.get("cnpj"))
        for _, raw in source_records(source, "fornecedores")
        if isinstance(raw, dict) and digits(raw.get("cnpj"))
    )
    supplier_entries: list[dict[str, Any]] = []
    for legacy_id, raw in source_records(source, "fornecedores"):
        payload = raw if isinstance(raw, dict) else {}
        cnpj = digits(payload.get("cnpj"))
        name = norm_text(payload.get("razaoSocial") or payload.get("nomeFantasia"))
        matches = suppliers_by_cnpj.get(cnpj, []) if cnpj else []
        duplicate_source = bool(cnpj and source_supplier_cnpj[cnpj] > 1)
        if duplicate_source:
            classification, match = "CONFLICT", None
            reason = "CNPJ aparece em mais de um fornecedor na fonte; exige consolidacao humana."
        else:
            classification, match = classify_exact(matches)
            if classification == "MATCH":
                reason = "Correspondencia unica por CNPJ normalizado."
            elif classification == "CONFLICT":
                reason = "CNPJ corresponde a mais de um fornecedor alvo."
            else:
                reason = "Nenhum CNPJ alvo correspondente; nome e apenas sugestao de revisao."
        name_suggestions = [target_id(doc) for doc in suppliers_by_name.get(name, [])] if name else []
        supplier_entries.append({
            "legacy_id": legacy_id,
            "normalized_cnpj": cnpj,
            "normalized_name": name,
            "current_supplier_id": target_id(match) if match else None,
            "name_suggestion_target_ids": name_suggestions,
            "classification": classification,
            "reason": reason,
        })
    write_json(output / "SUPPLIER_ID_MAP.json", {"source_node": "fornecedores", "tenant_id": tenant_id, "entries": supplier_entries})

    # Materials: exact historical internal code only; no prefix or Firebase suggestion matching.
    materials_by_code = grouped(target_docs["materiais"], lambda d: norm_text(d.get("codigo_interno")))
    fragrances_by_code = grouped(target_docs["fragrancias"], lambda d: norm_text(d.get("codigo_interno")))
    material_entries: list[dict[str, Any]] = []
    for legacy_id, raw in source_records(source, "materiais"):
        payload = raw if isinstance(raw, dict) else {}
        legacy_code = str(payload.get("mpCodigo") or legacy_id)
        domain, confidence, domain_reason = material_domain(payload)
        code_key = norm_text(legacy_code)
        matches: list[tuple[str, dict[str, Any]]] = []
        matches.extend(("materiais", doc) for doc in materials_by_code.get(code_key, []))
        matches.extend(("fragrancias", doc) for doc in fragrances_by_code.get(code_key, []))
        if len(matches) == 1:
            classification = "MATCH"
            target_domain, match = matches[0]
            reason = "Codigo interno historico corresponde exatamente a um cadastro alvo."
        elif len(matches) > 1:
            classification, target_domain, match = "CONFLICT", None, None
            reason = "Codigo historico corresponde a mais de um dominio/cadastro alvo."
        else:
            classification, target_domain, match = "MANUAL_REVIEW", domain, None
            reason = domain_reason + " Cadastro alvo inexistente; criacao requer aprovacao."
        material_entries.append({
            "legacy_id": legacy_id,
            "legacy_material_code": legacy_code,
            "legacy_type": payload.get("tipo"),
            "target_domain": target_domain,
            "target_id": target_id(match) if match else None,
            "target_codigo_interno": match.get("codigo_interno") if match else None,
            "confidence": "high" if match else confidence,
            "classification": classification,
            "reason": reason,
            "firebase_sugestaoMatch_used": False,
        })
    write_json(output / "MATERIAL_ID_MAP.json", {"source_node": "materiais", "tenant_id": tenant_id, "entries": material_entries})

    # SKU history is lookup-only. Missing targets never trigger automatic SKU generation.
    skus_by_code = grouped(target_docs["skus"], lambda d: norm_text(d.get("codigo_interno") or d.get("codigo") or d.get("sku")))
    sku_entries: list[dict[str, Any]] = []
    for node in ("produtos", "sku_historico"):
        for legacy_id, raw in source_records(source, node):
            payload = raw if isinstance(raw, dict) else {}
            legacy_sku = str(payload.get("sku") or legacy_id)
            matches = skus_by_code.get(norm_text(legacy_sku), [])
            if len(matches) == 1:
                classification, match, reason = "MATCH", matches[0], "SKU historico localizado exatamente no cadastro atual."
            elif len(matches) > 1:
                classification, match, reason = "CONFLICT", None, "SKU historico corresponde a mais de um cadastro alvo."
            else:
                classification, match, reason = "MANUAL_REVIEW", None, "SKU historico ausente; geracao automatica proibida."
            sku_entries.append({
                "source_node": node,
                "legacy_id": legacy_id,
                "legacy_sku": legacy_sku,
                "firebase_alias_value": raw if node == "sku_historico" and not isinstance(raw, dict) else None,
                "current_sku_id": target_id(match) if match else None,
                "current_codigo": (match.get("codigo_interno") or match.get("codigo")) if match else None,
                "classification": classification,
                "reason": reason,
            })
    write_json(output / "SKU_ID_MAP.json", {"tenant_id": tenant_id, "entries": sku_entries, "automatic_generation_allowed": False})

    # Orders and OPs use exact historical identifiers/numbers only.
    orders_target = target_docs["orders"]
    orders_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in orders_target:
        for value in (doc.get("id"), doc.get("numero_pedido")):
            if value is not None and str(value).strip():
                orders_by_key[norm_text(value)].append(doc)
    order_entries: list[dict[str, Any]] = []
    for node in ("pedidos", "pedidos_comerciais"):
        for legacy_id, raw in source_records(source, node):
            payload = raw if isinstance(raw, dict) else {}
            candidates = [legacy_id, payload.get("id"), payload.get("numero"), payload.get("numeroFormatado"), payload.get("numeroPedidoCliente")]
            matches_by_id: dict[str, dict[str, Any]] = {}
            basis = []
            for value in candidates:
                if value is None or not str(value).strip():
                    continue
                for doc in orders_by_key.get(norm_text(value), []):
                    matches_by_id[target_id(doc)] = doc
                    basis.append(str(value))
            matches = list(matches_by_id.values())
            classification, match = classify_exact(matches)
            reason = "Correspondencia exata por identificador/numero historico." if classification == "MATCH" else (
                "Mais de um pedido alvo corresponde aos identificadores historicos." if classification == "CONFLICT" else
                "Nenhum pedido alvo corresponde; depende de cliente, SKU e CGI reconciliados."
            )
            order_entries.append({
                "source_node": node,
                "legacy_id": legacy_id,
                "legacy_number": payload.get("numeroFormatado") or payload.get("id") or legacy_id,
                "current_order_id": target_id(match) if match else None,
                "classification": classification,
                "matched_values": sorted(set(basis)) if match else [],
                "reason": reason,
            })
    write_json(output / "ORDER_ID_MAP.json", {"tenant_id": tenant_id, "entries": order_entries})

    ops_target = target_docs["ops"]
    ops_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in ops_target:
        for value in (doc.get("id"), doc.get("numero_op")):
            if value is not None and str(value).strip():
                ops_by_key[norm_text(value)].append(doc)
    op_entries: list[dict[str, Any]] = []
    for legacy_id, raw in source_records(source, "ops"):
        payload = raw if isinstance(raw, dict) else {}
        candidates = [legacy_id, payload.get("id"), payload.get("numero_op"), payload.get("numeroOP")]
        matches_by_id: dict[str, dict[str, Any]] = {}
        for value in candidates:
            if value is not None and str(value).strip():
                for doc in ops_by_key.get(norm_text(value), []):
                    matches_by_id[target_id(doc)] = doc
        matches = list(matches_by_id.values())
        classification, match = classify_exact(matches)
        op_entries.append({
            "legacy_id": legacy_id,
            "legacy_lot": payload.get("lote"),
            "legacy_sku": payload.get("sku"),
            "current_op_id": target_id(match) if match else None,
            "classification": classification if classification != "INSERT_CANDIDATE" else "MANUAL_REVIEW",
            "reason": "OP historica localizada exatamente." if match else "OP depende de pedido, SKU e lote; apontamentos nao serao reproduzidos.",
        })
    write_json(output / "OP_ID_MAP.json", {"source_node": "ops", "tenant_id": tenant_id, "entries": op_entries})

    addresses_by_code = grouped(target_docs["wms_enderecos"], lambda d: norm_text(d.get("codigo")))
    address_entries: list[dict[str, Any]] = []
    for legacy_id, raw in source_records(source, "enderecos_estoque"):
        payload = raw if isinstance(raw, dict) else {}
        code = str(payload.get("codigo") or legacy_id)
        matches = addresses_by_code.get(norm_text(code), [])
        classification, match = classify_exact(matches)
        address_entries.append({
            "legacy_id": legacy_id,
            "legacy_code": code,
            "current_address_id": target_id(match) if match else None,
            "classification": classification if match or classification == "CONFLICT" else "MANUAL_REVIEW",
            "reason": "Endereco localizado por codigo exato." if match else "Endereco exige conferencia fisica antes de cadastro."
        })
    write_json(output / "ADDRESS_ID_MAP.json", {"source_node": "enderecos_estoque", "tenant_id": tenant_id, "entries": address_entries})

    lot_entries: list[dict[str, Any]] = []
    for row in flatten_nested(source, "estoque_lotes"):
        payload = row["payload"]
        lot_entries.append({
            "legacy_parent_material_code": row["parent_id"],
            "legacy_id": row["legacy_id"],
            "legacy_lot": payload.get("loteInterno") or payload.get("loteOrigem") or row["legacy_id"],
            "current_lot_balance_id": None,
            "classification": "MANUAL_REVIEW",
            "reason": "Lote exige material, endereco, CQ/WMS e corte fisico reconciliados; saldo agregado nao sera usado.",
        })
    write_json(output / "LOT_ID_MAP.json", {"source_node": "estoque_lotes", "tenant_id": tenant_id, "entries": lot_entries})

    map_entries = {
        "clients": client_entries,
        "suppliers": supplier_entries,
        "materials": material_entries,
        "skus": sku_entries,
        "orders": order_entries,
        "ops": op_entries,
        "addresses": address_entries,
        "lots": lot_entries,
    }
    classifications = Counter(entry["classification"] for entries in map_entries.values() for entry in entries)
    for label in ("MATCH", "INSERT_CANDIDATE", "MERGE_CANDIDATE", "CONFLICT", "MANUAL_REVIEW", "SKIP"):
        classifications.setdefault(label, 0)

    previous_stock = json.loads((existing / "STOCK_RECONCILIATION.json").read_text(encoding="utf-8"))
    previous_stock.update({
        "tenant_id": tenant_id,
        "target_evaluation_complete": True,
        "target_snapshot": {
            "wms_enderecos": target_counts["wms_enderecos"],
            "estoque_saldos_lote": target_counts["estoque_saldos_lote"],
            "estoque_movimentos_lote": target_counts["estoque_movimentos_lote"],
            "wms_paletes": target_counts["wms_paletes"],
            "cq_status_lote": target_counts["cq_status_lote"],
        },
        "classification": "MANUAL_REVIEW",
        "reason": "Estoque permanece bloqueado ate corte fisico e validacao CQ/WMS; saldoAtual e movimentos legados nao serao aplicados.",
    })
    write_json(output / "STOCK_RECONCILIATION.json", previous_stock)

    conflicts = {
        "tenant_id": tenant_id,
        "source_conflicts": {
            label: [entry for entry in entries if entry["classification"] == "CONFLICT"]
            for label, entries in map_entries.items()
        },
        "target_conflicts_status": "EVALUATED_READ_ONLY",
        "target_conflict_count": classifications["CONFLICT"],
    }
    write_json(output / "CONFLICTS.json", conflicts)

    manual = {
        "status": "TARGET_RECONCILED_AWAITING_HUMAN_APPROVAL",
        "tenant_id": tenant_id,
        "tenant_name": tenant.get("name"),
        "queues": {
            label: {
                "manual_review": sum(e["classification"] == "MANUAL_REVIEW" for e in entries),
                "conflict": sum(e["classification"] == "CONFLICT" for e in entries),
                "insert_candidate": sum(e["classification"] == "INSERT_CANDIDATE" for e in entries),
                "match": sum(e["classification"] == "MATCH" for e in entries),
            }
            for label, entries in map_entries.items()
        },
        "dependent_domains": {
            "formulas": {
                "count": len(source.get("formulas", {})),
                "status": "PENDING_DEPENDENCY_REVIEW",
                "reason": "Depende da reconciliacao e aprovacao dos materiais; itens nao resolvidos permanecem pendentes.",
            },
            "bom": {
                "count": len(source.get("bom", {})),
                "status": "PENDING_DEPENDENCY_REVIEW",
                "reason": "Depende de produto pai, SKU e materiais aprovados; camadas bulk e embalagem nao serao misturadas.",
            },
        },
        "blockers": [
            "Confirmacao humana dos conflitos e candidatos de cadastro.",
            "Validacao fisica de estoque, lotes, enderecos e CQ/WMS.",
            "Aprovacao separada para gerar transformacao e aplicar somente na homologacao.",
        ],
        "writes_to_mongo_performed": [],
    }
    write_json(output / "MANUAL_REVIEW.json", manual)

    old_counts = json.loads((existing / "MIGRATION_COUNTS.json").read_text(encoding="utf-8"))
    old_counts["generated_at"] = generated_at
    old_counts["target"] = {
        "database": db_name,
        "tenant_id": tenant_id,
        "tenant_name": tenant.get("name"),
        "collection_counts": target_counts,
    }
    old_counts["reconciliation"] = {
        **{key: classifications[key] for key in ("MATCH", "INSERT_CANDIDATE", "MERGE_CANDIDATE", "CONFLICT", "MANUAL_REVIEW", "SKIP")},
        "target_evaluation_complete": True,
    }
    write_json(output / "MIGRATION_COUNTS.json", old_counts)

    reconciliation = {
        "status": "COMPLETED_READ_ONLY_AWAITING_HUMAN_APPROVAL",
        "generated_at": generated_at,
        "source_sha256": EXPECTED_SHA,
        "mongo": {"uri": "REDACTED", "db_name": db_name, "tenant_id": tenant_id, "mode": "READ_ONLY"},
        "allowed_operations_used": ["find", "count", "list_indexes"],
        "write_operations_performed": [],
        "classifications": old_counts["reconciliation"],
        "target_collection_counts": target_counts,
        "target_index_names": target_indexes,
        "maps": {label: filename for label, filename in {
            "clients": "CLIENT_ID_MAP.json", "suppliers": "SUPPLIER_ID_MAP.json",
            "materials": "MATERIAL_ID_MAP.json", "skus": "SKU_ID_MAP.json",
            "orders": "ORDER_ID_MAP.json", "ops": "OP_ID_MAP.json",
            "addresses": "ADDRESS_ID_MAP.json", "lots": "LOT_ID_MAP.json",
        }.items()},
        "next_gate": "Human review is required before transformation generation or homologation apply.",
    }
    write_json(output / "RECONCILIATION_CURRENT_MONGO.json", reconciliation)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
