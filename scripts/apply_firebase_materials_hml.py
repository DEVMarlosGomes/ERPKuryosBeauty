"""Apply or roll back the explicitly approved 846-record material wave in HML."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from apply_firebase_clients_hml import (
    PLAN_ID,
    SOURCE_SHA,
    assert_homologation,
    clean,
    document_hash,
    load_env,
    stable_id,
)


EXPECTED_MATERIALS = 647
EXPECTED_FRAGRANCES = 199
EXPECTED_BLOCKED = 93


def ascii_upper(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    return "".join(char for char in text if not unicodedata.combining(char)).upper()


def normalized_unit(value: Any) -> str:
    unit = clean(value).lower()
    return {"lt": "l", "litro": "l", "litros": "l", "unidade": "un"}.get(unit, unit)


def approved_target(entry: dict[str, Any], payload: dict[str, Any]) -> str | None:
    domain = entry.get("target_domain")
    unit = normalized_unit(payload.get("unidade"))
    if domain == "materiais:EP" and unit == "un":
        return "EP"
    if domain == "materiais:ES" and unit == "un":
        return "ES"
    if domain == "materiais:MP" and unit in {"kg", "l"}:
        return "MP"
    if domain == "fragrancias" and unit == "kg":
        return "FR"
    return None


def subtype(tipo2: str, payload: dict[str, Any]) -> str:
    text = ascii_upper(" ".join([
        clean(payload.get("mpNome")), clean(payload.get("formato")),
        clean(payload.get("especificacoesTecnicas")),
    ]))
    if tipo2 == "MP":
        return "Geral"
    if tipo2 == "EP":
        for needle, label in (
            ("FRASCO", "Frasco"), ("POTE", "Frasco"), ("BISNAGA", "Frasco"),
            ("SOBRETAMPA", "Sobretampa"), ("TAMPA", "Tampa"),
            ("VALVULA", "Válvula"), ("BOMBA", "Bomba"),
        ):
            if needle in text:
                return label
        return "Outro"
    if tipo2 == "ES":
        for needle, label in (
            ("CARTUCHO", "Cartucho"), ("CELOFANE", "Celofane"),
            ("SLEEVE", "Sleeve"), ("CAIXA", "Caixa de embarque"),
        ):
            if needle in text:
                return label
        return "Outro"
    raise RuntimeError(f"Unexpected material type: {tipo2}")


def build_documents(source: dict[str, Any], mapping: list[dict[str, Any]], db, tenant_id: str):
    selected: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {key: [] for key in ("MP", "EP", "ES", "FR")}
    blocked = []
    for entry in mapping:
        payload = source.get("materiais", {}).get(entry["legacy_id"])
        if not isinstance(payload, dict):
            raise RuntimeError(f"Missing material payload: {entry['legacy_id']}")
        target = approved_target(entry, payload)
        if target:
            selected[target].append((entry, payload))
        else:
            blocked.append(entry["legacy_id"])
    if sum(len(items) for items in selected.values()) != EXPECTED_MATERIALS + EXPECTED_FRAGRANCES:
        raise RuntimeError("Approved material rule no longer selects exactly 846 records")
    if len(blocked) != EXPECTED_BLOCKED:
        raise RuntimeError("Blocked material count changed")

    actor = db.users.find_one({"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}}) \
        or db.users.find_one({"tenant_id": tenant_id})
    if not actor:
        raise RuntimeError("No migration actor found")
    actor_id = str(actor.get("id") or actor.get("_id"))
    actor_name = clean(actor.get("name") or actor.get("nome") or "Migracao Firebase")
    now = datetime.now(timezone.utc).isoformat()
    materials, fragrances, map_entries = [], [], []

    assigned_codes: set[str] = set()
    for tipo2 in ("EP", "ES", "MP"):
        rows = sorted(selected[tipo2], key=lambda pair: pair[0]["legacy_id"])
        for sequence, (entry, payload) in enumerate(rows, 1):
            legacy_id = entry["legacy_id"]
            if tipo2 in {"EP", "ES"} and re.fullmatch(fr"{tipo2}-\d{{5}}", legacy_id):
                code = legacy_id
            else:
                code = f"{tipo2}-{sequence:05d}"
            if code in assigned_codes:
                raise RuntimeError(f"Generated duplicate material code: {code}")
            assigned_codes.add(code)
            operation_id = stable_id(PLAN_ID, "materials", legacy_id)
            migration = {
                "source": "firebase-current", "source_node": "materiais", "source_id": legacy_id,
                "source_sha256": SOURCE_SHA, "plan_id": PLAN_ID, "operation_id": operation_id,
                "applied_at": now, "approved_rule": "material_wave_846_v1",
            }
            stock_unit = normalized_unit(payload.get("unidade"))
            purchase_unit = normalized_unit(payload.get("unidadeCompra")) or stock_unit
            raw_attributes = {
                key: value for key, value in payload.items()
                if key not in {"fornecedores", "mpCodigo", "mpNome", "tipo", "unidade", "unidadeCompra", "fatorConversao", "ativo", "especificacoesTecnicas"}
                and value not in (None, "", [], {})
            }
            document = {
                "id": stable_id("firebase-current", tenant_id, "materials", legacy_id),
                "tenant_id": tenant_id,
                "codigo_interno": code,
                "tipo2": tipo2,
                "subtipo": subtype(tipo2, payload),
                "nome": clean(payload.get("mpNome")),
                "descricao": clean(payload.get("especificacoesTecnicas")),
                "unidade_estoque": stock_unit,
                "unidade_compra": purchase_unit,
                "fator_conversao": float(payload.get("fatorConversao") or 1),
                "atributos": raw_attributes,
                "fornecedores": [],
                "status": "ativo" if payload.get("ativo", True) is not False else "inativo",
                "legacy_material_code": legacy_id,
                "legacy_type": clean(payload.get("tipo")),
                "_legacy_supplier_refs": payload.get("fornecedores") or {},
                "created_by": actor_id,
                "created_by_name": actor_name,
                "created_at": now,
                "updated_at": now,
                "_migration": migration,
            }
            materials.append(document)
            map_entries.append({
                "legacy_id": legacy_id, "target_domain": "materiais", "target_id": document["id"],
                "target_codigo_interno": code, "target_tipo2": tipo2,
            })

    for sequence, (entry, payload) in enumerate(sorted(selected["FR"], key=lambda pair: pair[0]["legacy_id"]), 1):
        legacy_id = entry["legacy_id"]
        code = f"FR-{sequence:05d}"
        operation_id = stable_id(PLAN_ID, "fragrances", legacy_id)
        migration = {
            "source": "firebase-current", "source_node": "materiais", "source_id": legacy_id,
            "source_sha256": SOURCE_SHA, "plan_id": PLAN_ID, "operation_id": operation_id,
            "applied_at": now, "approved_rule": "material_wave_846_v1",
        }
        document = {
            "id": stable_id("firebase-current", tenant_id, "fragrances", legacy_id),
            "tenant_id": tenant_id,
            "codigo_interno": code,
            "inspiracao": clean(payload.get("mpNome")),
            "descricao": clean(payload.get("especificacoesTecnicas")),
            "status": "ativa" if payload.get("ativo", True) is not False else "inativa",
            "fornecedores": [],
            "legacy_material_code": legacy_id,
            "legacy_type": clean(payload.get("tipo")),
            "unidade_estoque_legacy": normalized_unit(payload.get("unidade")),
            "_legacy_supplier_refs": payload.get("fornecedores") or {},
            "created_by": actor_id,
            "created_by_name": actor_name,
            "created_at": now,
            "updated_at": now,
            "_migration": migration,
        }
        fragrances.append(document)
        map_entries.append({
            "legacy_id": legacy_id, "target_domain": "fragrancias", "target_id": document["id"],
            "target_codigo_interno": code, "target_tipo2": "FR",
        })

    if len(materials) != EXPECTED_MATERIALS or len(fragrances) != EXPECTED_FRAGRANCES:
        raise RuntimeError(f"Unexpected split: {len(materials)} materials, {len(fragrances)} fragrances")
    counter_values = {
        "EP": max(int(doc["codigo_interno"].split("-")[1]) for doc in materials if doc["tipo2"] == "EP"),
        "ES": max(int(doc["codigo_interno"].split("-")[1]) for doc in materials if doc["tipo2"] == "ES"),
        "MP": max(int(doc["codigo_interno"].split("-")[1]) for doc in materials if doc["tipo2"] == "MP"),
        "FR": len(fragrances),
    }
    counters = []
    for family, value in counter_values.items():
        name = "fr_seq" if family == "FR" else f"mat_{family}_seq"
        counters.append({
            "_id": f"{name}:{tenant_id}", "seq": value, "start": 0,
            "_migration": {"plan_id": PLAN_ID, "operation_id": stable_id(PLAN_ID, "counter", family), "applied_at": now},
        })
    return materials, fragrances, counters, map_entries, blocked


def comparable(document: dict[str, Any], keep_id: bool = False) -> dict[str, Any]:
    result = dict(document)
    if not keep_id:
        result.pop("_id", None)
    return result


def rollback(db, tenant_id: str, report_path: Path) -> dict[str, int]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("plan_id") != PLAN_ID:
        raise RuntimeError("Valid material apply report required")
    hashes = {(item["collection"], item["target_id"]): item["after_hash"] for item in report["operations"]}
    collection_queries = {
        "materiais": {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID, "_migration.approved_rule": "material_wave_846_v1"},
        "fragrancias": {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID, "_migration.approved_rule": "material_wave_846_v1"},
        "counters": {"_migration.plan_id": PLAN_ID},
    }
    current_by_collection = {name: list(db[name].find(query)) for name, query in collection_queries.items()}
    expected = {"materiais": EXPECTED_MATERIALS, "fragrancias": EXPECTED_FRAGRANCES, "counters": 4}
    for name, documents in current_by_collection.items():
        if len(documents) != expected[name]:
            raise RuntimeError(f"{name} count changed; rollback refused")
        for document in documents:
            target_id = document.get("id") if name != "counters" else document.get("_id")
            if hashes.get((name, target_id)) != document_hash(comparable(document, keep_id=name == "counters")):
                raise RuntimeError(f"{name} document edited; rollback refused: {target_id}")
    deleted: dict[str, int] = {}
    with db.client.start_session() as session:
        def callback(active_session):
            for name in ("counters", "fragrancias", "materiais"):
                deleted[name] = db[name].delete_many(collection_queries[name], session=active_session).deleted_count
        session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--material-map", required=True)
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
        raise RuntimeError("Material-wave snapshot hash mismatch")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[database_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        result = {"status": "ROLLED_BACK", "plan_id": PLAN_ID, "deleted": rollback(db, tenant_id, Path(args.apply_report))}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    mapping = json.loads(Path(args.material_map).read_text(encoding="utf-8"))["entries"]
    materials, fragrances, counters, applied_map, blocked = build_documents(source, mapping, db, tenant_id)
    marker = {"_migration.plan_id": PLAN_ID, "_migration.approved_rule": "material_wave_846_v1"}
    if db.materiais.count_documents(marker) or db.fragrancias.count_documents(marker):
        raise RuntimeError("Material wave is already applied")
    for counter in counters:
        if db.counters.count_documents({"_id": counter["_id"]}):
            raise RuntimeError(f"Required counter already exists: {counter['_id']}")
    baseline = {
        "materiais": db.materiais.count_documents({"tenant_id": tenant_id}),
        "fragrancias": db.fragrancias.count_documents({"tenant_id": tenant_id}),
    }
    operations = []
    for name, documents in (("materiais", materials), ("fragrancias", fragrances)):
        operations.extend({
            "collection": name, "operation_id": doc["_migration"]["operation_id"],
            "legacy_id": doc["_migration"]["source_id"], "target_id": doc["id"],
            "target_codigo_interno": doc["codigo_interno"], "before_hash": None, "after_hash": document_hash(doc),
        } for doc in documents)
    operations.extend({
        "collection": "counters", "operation_id": doc["_migration"]["operation_id"],
        "legacy_id": None, "target_id": doc["_id"], "target_codigo_interno": None,
        "before_hash": None, "after_hash": document_hash(doc),
    } for doc in counters)
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID, "target": {"database": database_name, "tenant_id": tenant_id},
        "baseline": baseline,
        "planned": {"materiais": len(materials), "fragrancias": len(fragrances), "counters": 4, "blocked": len(blocked)},
        "operations": operations, "applied_material_map": applied_map, "blocked_legacy_ids": blocked,
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key not in {"operations", "applied_material_map", "blocked_legacy_ids"}}, ensure_ascii=False))
        return 0

    queries = {
        "materiais": {"tenant_id": tenant_id, **marker},
        "fragrancias": {"tenant_id": tenant_id, **marker},
        "counters": {"_migration.plan_id": PLAN_ID},
    }
    try:
        combined = [("materiais", doc) for doc in materials] + [("fragrancias", doc) for doc in fragrances]
        for start in range(0, len(combined), 20):
            batch = combined[start:start + 20]
            with client.start_session() as session:
                def callback(active_session):
                    by_collection: dict[str, list[dict[str, Any]]] = {}
                    for name, document in batch:
                        by_collection.setdefault(name, []).append(document)
                    for name, documents in by_collection.items():
                        db[name].insert_many(documents, ordered=True, session=active_session)
                session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        with client.start_session() as session:
            session.with_transaction(lambda active: db.counters.insert_many(counters, ordered=True, session=active), read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
        post = {name: db[name].count_documents(query) for name, query in queries.items()}
        if post != {"materiais": EXPECTED_MATERIALS, "fragrancias": EXPECTED_FRAGRANCES, "counters": 4}:
            raise RuntimeError(f"Material post-check failed: {post}")
    except Exception:
        for name in ("counters", "fragrancias", "materiais"):
            db[name].delete_many(queries[name])
        raise
    result.update({
        "status": "APPLIED_HOMOLOGATION",
        "after": {"materiais": baseline["materiais"] + len(materials), "fragrancias": baseline["fragrancias"] + len(fragrances)},
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"operations", "applied_material_map", "blocked_legacy_ids"}}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
