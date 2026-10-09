"""Apply/rollback the user-approved legacy-authorized SKU wave in HML."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import (
    PLAN_ID, SOURCE_SHA, assert_homologation, clean, document_hash, load_env, stable_id,
)


EXPECTED_SKUS = 382
EXPECTED_BLOCKED = 3
SKU_RULE = "legacy_authorized_sku_wave_382_v1"
NEW_CODE_RE = re.compile(r"^([A-Z]{3})-([A-Z]{4})-(\d{4})$")


def client_crosswalk(source: dict[str, Any], client_map: list[dict[str, Any]], client_apply: dict[str, Any]) -> dict[str, str]:
    inserted = {item["legacy_id"]: item["target_id"] for item in client_apply["operations"]}
    by_legacy = {}
    for entry in client_map:
        target = entry.get("current_client_id") or inserted.get(entry["legacy_id"])
        if not target:
            raise RuntimeError(f"Client has no target mapping: {entry['legacy_id']}")
        by_legacy[entry["legacy_id"]] = target
    if len(by_legacy) != 59:
        raise RuntimeError(f"Expected 59 reconciled clients, found {len(by_legacy)}")
    by_code = {}
    for legacy_id, payload in source["clientes"].items():
        if not isinstance(payload, dict):
            continue
        for key in (legacy_id, payload.get("codigo")):
            normalized = clean(key).upper()
            if normalized:
                if normalized in by_code and by_code[normalized] != by_legacy[legacy_id]:
                    raise RuntimeError(f"Ambiguous legacy client code: {normalized}")
                by_code[normalized] = by_legacy[legacy_id]
    return by_code


def build_documents(source, client_map, client_apply, db, tenant_id):
    crosswalk = client_crosswalk(source, client_map, client_apply)
    target_clients = {
        document["id"]: document
        for document in db.crm_clients.find({"tenant_id": tenant_id}, {"_id": 0})
    }
    alias_by_target: dict[str, list[str]] = defaultdict(list)
    for alias, target in source.get("sku_historico", {}).items():
        alias = clean(alias).upper()
        target = clean(target).upper()
        if alias and alias not in alias_by_target[target]:
            alias_by_target[target].append(alias)

    now = datetime.now(timezone.utc).isoformat()
    documents, blocked, seen_codes = [], [], set()
    for legacy_id, payload in sorted(source["produtos"].items()):
        if not isinstance(payload, dict):
            blocked.append({"legacy_id": legacy_id, "reason": "payload_not_object"})
            continue
        client_key = clean(payload.get("clienteKey")).upper()
        target_client_id = crosswalk.get(client_key)
        code = clean(payload.get("sku") or legacy_id).upper()
        if not target_client_id:
            blocked.append({"legacy_id": legacy_id, "codigo": code, "reason": "client_not_resolved"})
            continue
        if code in seen_codes:
            blocked.append({"legacy_id": legacy_id, "codigo": code, "reason": "duplicate_legacy_code"})
            continue
        seen_codes.add(code)
        client = target_clients.get(target_client_id)
        if not client:
            raise RuntimeError(f"Mapped client is absent from HML: {target_client_id}")
        operation_id = stable_id(PLAN_ID, "legacy-skus", legacy_id)
        match = NEW_CODE_RE.fullmatch(code)
        active = clean(payload.get("ativo")).lower() != "inativo"
        migration = {
            "source": "firebase-current", "source_node": "produtos", "source_id": legacy_id,
            "source_sha256": SOURCE_SHA, "plan_id": PLAN_ID, "operation_id": operation_id,
            "applied_at": now, "approved_rule": SKU_RULE,
        }
        document = {
            "id": stable_id("firebase-current", tenant_id, "legacy-skus", legacy_id),
            "tenant_id": tenant_id,
            "codigo_interno": code,
            "codigo_legado": code,
            "cat3": match.group(1) if match else "",
            "cli4": clean(client.get("cli4")).upper(),
            "cat2": "",
            "cli3": clean(client.get("cli3")).upper(),
            "nome_produto": clean(payload.get("descricao")),
            "categoria": clean(payload.get("categoria")),
            "subcategoria": clean(payload.get("subcategoria")),
            "formula_vinculada": "",
            "cliente_id": target_client_id,
            "cliente_nome": clean(client.get("nome_empresa")),
            "projeto_id": None,
            "projeto_nome": "",
            "amostra_id": None,
            "produto_pai_id": None,
            "preco_unitario": 0.0,
            "moq": 0,
            "anvisa": {"numero": clean(payload.get("msAnvisa")), "validade": None},
            "status": "ativo" if active else "inativo",
            "pd_concluido": True,
            "pd_concluido_em": now,
            "pd_concluido_origem": "migracao_legado_autorizado",
            "origem_contratual_status": "legado_autorizado",
            "cgi_contrato_id": None,
            "cgi_numero": None,
            "cgi_assinado_em": None,
            "legado_sem_cgi": True,
            "bloqueado_por_cgi": False,
            "legacy_authorized": True,
            "legacy_aliases": sorted(alias_by_target.get(code, [])),
            "legacy_skus_anteriores": payload.get("skusAnteriores") or [],
            "legacy_product_data": payload,
            "descontinuado_motivo": None,
            "descontinuado_em": None,
            "descontinuado_por": None,
            "historico_pedidos": [],
            "data_ultimo_pedido": None,
            "frequencia_media_recompra_dias": 0,
            "medias_producao": {
                "media_geral_unh": None, "media_12m_unh": None, "media_3m_unh": None,
                "media_1m_unh": None, "meta_unh": None, "ajuste_percentual": 0,
                "meta_set_by": None, "meta_set_at": None, "historico_producao": [],
            },
            "created_at": now,
            "updated_at": now,
            "_migration": migration,
        }
        documents.append(document)

    if len(documents) != EXPECTED_SKUS or len(blocked) != EXPECTED_BLOCKED:
        raise RuntimeError(f"Expected 382/3 SKU split, found {len(documents)}/{len(blocked)}")

    max_by_pair: dict[tuple[str, str], int] = {}
    for document in documents:
        match = NEW_CODE_RE.fullmatch(document["codigo_interno"])
        if match:
            cat3, code_cli4, sequence = match.groups()
            max_by_pair[(cat3, code_cli4)] = max(max_by_pair.get((cat3, code_cli4), 0), int(sequence))
    counters = []
    for (cat3, code_cli4), sequence in sorted(max_by_pair.items()):
        counter_id = f"skuv2_{cat3}_{code_cli4}:{tenant_id}"
        counters.append({
            "_id": counter_id, "seq": sequence, "start": 0,
            "_migration": {"plan_id": PLAN_ID, "operation_id": stable_id(PLAN_ID, "sku-counter", cat3, code_cli4), "applied_at": now, "approved_rule": SKU_RULE},
        })
    if len(counters) != 13:
        raise RuntimeError(f"Expected 13 SKU counters, found {len(counters)}")
    return documents, counters, blocked


def comparable(document: dict[str, Any], keep_id: bool = False) -> dict[str, Any]:
    result = dict(document)
    if not keep_id:
        result.pop("_id", None)
    return result


def rollback(db, tenant_id: str, report_path: Path) -> dict[str, int]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("plan_id") != PLAN_ID:
        raise RuntimeError("Valid SKU apply report required")
    hashes = {(item["collection"], item["target_id"]): item["after_hash"] for item in report["operations"]}
    queries = {
        "skus": {"tenant_id": tenant_id, "_migration.approved_rule": SKU_RULE},
        "counters": {"_migration.approved_rule": SKU_RULE},
    }
    current = {name: list(db[name].find(query)) for name, query in queries.items()}
    if len(current["skus"]) != EXPECTED_SKUS or len(current["counters"]) != 13:
        raise RuntimeError("SKU wave count changed; rollback refused")
    for name, documents in current.items():
        for document in documents:
            target_id = document.get("_id") if name == "counters" else document.get("id")
            if hashes.get((name, target_id)) != document_hash(comparable(document, keep_id=name == "counters")):
                raise RuntimeError(f"{name} document edited; rollback refused: {target_id}")
    deleted = {}
    with db.client.start_session() as session:
        def callback(active):
            deleted["counters"] = db.counters.delete_many(queries["counters"], session=active).deleted_count
            deleted["skus"] = db.skus.delete_many(queries["skus"], session=active).deleted_count
        session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--client-map", required=True)
    parser.add_argument("--client-apply", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--apply-report")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    env = load_env(Path(args.env))
    uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    source_path, snapshot_path = Path(args.source), Path(args.snapshot)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != args.snapshot_sha256:
        raise RuntimeError("SKU-wave snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required")
        result = {"status": "ROLLED_BACK", "plan_id": PLAN_ID, "deleted": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    client_map = json.loads(Path(args.client_map).read_text(encoding="utf-8"))["entries"]
    client_apply = json.loads(Path(args.client_apply).read_text(encoding="utf-8"))
    documents, counters, blocked = build_documents(source, client_map, client_apply, db, tenant_id)
    if db.skus.count_documents({"tenant_id": tenant_id, "_migration.approved_rule": SKU_RULE}):
        raise RuntimeError("SKU wave already applied")
    existing_codes = {doc["codigo_interno"] for doc in db.skus.find({"tenant_id": tenant_id}, {"codigo_interno": 1})}
    conflicts = existing_codes & {doc["codigo_interno"] for doc in documents}
    if conflicts:
        raise RuntimeError(f"Target SKU code conflicts: {sorted(conflicts)[:5]}")
    for counter in counters:
        if db.counters.count_documents({"_id": counter["_id"]}):
            raise RuntimeError(f"SKU counter already exists: {counter['_id']}")
    baseline = db.skus.count_documents({"tenant_id": tenant_id})
    operations = [{
        "collection": "skus", "operation_id": doc["_migration"]["operation_id"],
        "legacy_id": doc["_migration"]["source_id"], "target_id": doc["id"],
        "target_codigo_interno": doc["codigo_interno"], "before_hash": None, "after_hash": document_hash(doc),
    } for doc in documents]
    operations.extend({
        "collection": "counters", "operation_id": doc["_migration"]["operation_id"],
        "legacy_id": None, "target_id": doc["_id"], "target_codigo_interno": None,
        "before_hash": None, "after_hash": document_hash(doc),
    } for doc in counters)
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID, "policy": "A_LEGACY_AUTHORIZED",
        "target": {"database": database_name, "tenant_id": tenant_id},
        "baseline": {"skus": baseline},
        "planned": {"skus": len(documents), "counters": len(counters), "blocked": len(blocked)},
        "operations": operations,
        "applied_sku_map": [{
            "legacy_id": doc["_migration"]["source_id"], "legacy_sku": doc["codigo_interno"],
            "target_id": doc["id"], "target_codigo_interno": doc["codigo_interno"], "cliente_id": doc["cliente_id"],
        } for doc in documents],
        "blocked": blocked,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key not in {"operations", "applied_sku_map", "blocked"}}, ensure_ascii=False))
        return 0
    queries = {
        "skus": {"tenant_id": tenant_id, "_migration.approved_rule": SKU_RULE},
        "counters": {"_migration.approved_rule": SKU_RULE},
    }
    try:
        for start in range(0, len(documents), 20):
            batch = documents[start:start + 20]
            with client.start_session() as session:
                session.with_transaction(lambda active: db.skus.insert_many(batch, ordered=True, session=active), read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        with client.start_session() as session:
            session.with_transaction(lambda active: db.counters.insert_many(counters, ordered=True, session=active), read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        post = {name: db[name].count_documents(query) for name, query in queries.items()}
        if post != {"skus": EXPECTED_SKUS, "counters": 13} or db.skus.count_documents({"tenant_id": tenant_id}) != baseline + EXPECTED_SKUS:
            raise RuntimeError(f"SKU post-check failed: {post}")
    except Exception:
        db.counters.delete_many(queries["counters"])
        db.skus.delete_many(queries["skus"])
        raise
    result.update({"status": "APPLIED_HOMOLOGATION", "after": {"skus": baseline + EXPECTED_SKUS}, "completed_at": datetime.now(timezone.utc).isoformat()})
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"operations", "applied_sku_map", "blocked"}}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
