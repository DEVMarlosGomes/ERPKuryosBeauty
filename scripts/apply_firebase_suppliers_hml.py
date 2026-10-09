"""Apply or safely roll back the approved Firebase supplier wave in HML."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
    digits,
    document_hash,
    load_env,
    stable_id,
)


EXPECTED_COUNT = 383
CATEGORY_LABELS = {
    "mp": "Materia-prima",
    "embalagem": "Embalagem",
    "transportadora": "Transportadora",
    "tecnologia": "Tecnologia",
    "consumo": "Consumo",
    "servicos": "Servicos",
    "equipamentos": "Equipamentos",
    "publico": "Orgao publico",
    "outro": "Outro",
}


def valid_cnpj(value: str) -> bool:
    number = digits(value)
    if len(number) != 14 or len(set(number)) == 1:
        return False

    def check(part: str, weights: list[int]) -> int:
        remainder = sum(int(char) * weight for char, weight in zip(part, weights)) % 11
        return 0 if remainder < 2 else 11 - remainder

    return (
        int(number[12]) == check(number[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
        and int(number[13]) == check(number[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    )


def categories(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("tipos") or ([payload.get("tipo")] if payload.get("tipo") else [])
    values = []
    for item in raw:
        normalized = clean(item).lower()
        if normalized:
            label = CATEGORY_LABELS.get(normalized, clean(item))
            if label not in values:
                values.append(label)
    return values


def build_documents(source: dict[str, Any], mapping: list[dict[str, Any]], db, tenant_id: str) -> list[dict[str, Any]]:
    candidate_ids = sorted(entry["legacy_id"] for entry in mapping if entry["classification"] == "INSERT_CANDIDATE")
    if len(candidate_ids) != EXPECTED_COUNT:
        raise RuntimeError(f"Expected {EXPECTED_COUNT} supplier candidates, found {len(candidate_ids)}")

    existing_cnpjs = {
        digits(doc.get("cnpj_normalizado") or doc.get("cnpj"))
        for doc in db.compras_fornecedores.find({"tenant_id": tenant_id}, {"cnpj": 1, "cnpj_normalizado": 1})
        if digits(doc.get("cnpj_normalizado") or doc.get("cnpj"))
    }
    actor = db.users.find_one(
        {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
        sort=[("created_at", 1)],
    ) or db.users.find_one({"tenant_id": tenant_id}, sort=[("created_at", 1)])
    if not actor:
        raise RuntimeError("No homologation migration actor found")
    actor_id = str(actor.get("id") or actor.get("_id"))
    actor_name = clean(actor.get("name") or actor.get("nome") or "Migracao Firebase")
    now = datetime.now(timezone.utc).isoformat()
    seen = set(existing_cnpjs)
    documents = []

    for sequence, legacy_id in enumerate(candidate_ids, 1):
        payload = source.get("fornecedores", {}).get(legacy_id)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Missing Firebase supplier payload: {legacy_id}")
        cnpj = clean(payload.get("cnpj"))
        normalized_cnpj = digits(cnpj)
        if not valid_cnpj(cnpj):
            raise RuntimeError(f"Candidate contains invalid CNPJ: {legacy_id}")
        if normalized_cnpj in seen:
            raise RuntimeError(f"Supplier CNPJ conflict at apply time: {legacy_id}")
        seen.add(normalized_cnpj)
        supplier_id = stable_id("firebase-current", tenant_id, "suppliers", "fornecedores", legacy_id)
        operation_id = stable_id(PLAN_ID, "suppliers", "fornecedores", legacy_id)
        contact_name = clean(payload.get("contatoNome"))
        contact_phone = clean(payload.get("contatoTelefone"))
        contact_email = clean(payload.get("contatoEmail")).lower()
        contacts = []
        if contact_name or contact_phone or contact_email:
            contacts.append({
                "id": stable_id(operation_id, "contact", "primary"),
                "nome": contact_name,
                "cargo": "",
                "telefone": contact_phone,
                "email": contact_email,
                "whatsapp": contact_phone,
                "principal_compras": True,
            })
        migration = {
            "source": "firebase-current",
            "source_node": "fornecedores",
            "source_id": legacy_id,
            "source_sha256": SOURCE_SHA,
            "plan_id": PLAN_ID,
            "operation_id": operation_id,
            "applied_at": now,
        }
        documents.append({
            "id": supplier_id,
            "tenant_id": tenant_id,
            "codigo_interno": f"FOR-FB-{sequence:04d}",
            "razao_social": clean(payload.get("razaoSocial")) or clean(payload.get("nomeFantasia")),
            "nome_fantasia": clean(payload.get("nomeFantasia")),
            "cnpj": cnpj,
            "cnpj_normalizado": normalized_cnpj,
            "ie": "",
            "im": "",
            "endereco": {
                "cep": clean(payload.get("cep")),
                "logradouro": clean(payload.get("logradouro")),
                "numero": clean(payload.get("numero")),
                "complemento": clean(payload.get("complemento")),
                "bairro": clean(payload.get("bairro")),
                "cidade": clean(payload.get("cidade")),
                "uf": clean(payload.get("uf")).upper(),
            },
            "contatos": contacts,
            "categorias": categories(payload),
            "site": clean(payload.get("site")),
            "condicao_pagamento": clean(payload.get("condicaoPagamento")),
            "certificacoes": clean(payload.get("certificacoes")),
            "legacy_webmais_id": clean(payload.get("importadoWebmaisId")),
            "homologacao": {
                "status": "nao_iniciada",
                "data_homologacao": None,
                "proxima_reavaliacao": None,
                "documentos_file_ids": [],
                "historico_rncs_count": 0,
                "historico_rncs_criticas_12m": 0,
            },
            "status_cadastro": "ativo" if payload.get("ativo", True) is not False else "inativo",
            "created_at": now,
            "updated_at": now,
            "log_auditoria": [{
                "acao": "fornecedor_criado_migracao_firebase",
                "por_id": actor_id,
                "por_nome": actor_name,
                "em": now,
            }],
            "_migration": migration,
        })
    return documents


def rollback(db, tenant_id: str, apply_report: Path) -> dict[str, int]:
    report = json.loads(apply_report.read_text(encoding="utf-8"))
    if report.get("status") != "APPLIED_HOMOLOGATION" or report.get("plan_id") != PLAN_ID:
        raise RuntimeError("Valid applied supplier report is required for rollback")
    expected_hashes = {item["target_id"]: item["after_hash"] for item in report["operations"]}
    current = list(db.compras_fornecedores.find({"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}))
    if len(current) != EXPECTED_COUNT:
        raise RuntimeError("Marked supplier count changed; selective rollback refused")
    for document in current:
        comparable = dict(document)
        comparable.pop("_id", None)
        if expected_hashes.get(document.get("id")) != document_hash(comparable):
            raise RuntimeError(f"Supplier was edited after migration; rollback refused: {document.get('id')}")
    deleted = 0
    with db.client.start_session() as session:
        def callback(active_session):
            nonlocal deleted
            deleted = db.compras_fornecedores.delete_many(
                {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}, session=active_session
            ).deleted_count
        session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
    return {"compras_fornecedores": deleted}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--supplier-map", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--apply-report")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    env = load_env(Path(args.env))
    uri, db_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, db_name, tenant_id)
    source_path, snapshot_path = Path(args.source), Path(args.snapshot)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != args.snapshot_sha256:
        raise RuntimeError("Supplier-wave snapshot hash mismatch")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[db_name]
    if args.mode == "rollback":
        if not args.apply_report:
            raise RuntimeError("--apply-report is required for rollback")
        deleted = rollback(db, tenant_id, Path(args.apply_report))
        result = {"status": "ROLLED_BACK", "plan_id": PLAN_ID, "deleted": deleted}
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    mapping = json.loads(Path(args.supplier_map).read_text(encoding="utf-8"))["entries"]
    documents = build_documents(source, mapping, db, tenant_id)
    marker = {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}
    if db.compras_fornecedores.count_documents(marker):
        raise RuntimeError("Supplier wave is already applied")
    baseline = db.compras_fornecedores.count_documents({"tenant_id": tenant_id})
    result = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID,
        "target": {"database": db_name, "tenant_id": tenant_id},
        "baseline": {"compras_fornecedores": baseline},
        "planned": {"compras_fornecedores": len(documents), "blocked_suppliers": 20},
        "operations": [{
            "operation_id": document["_migration"]["operation_id"],
            "legacy_id": document["_migration"]["source_id"],
            "target_id": document["id"],
            "before_hash": None,
            "after_hash": document_hash(document),
        } for document in documents],
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
        return 0

    applied_batches = 0
    try:
        for start in range(0, len(documents), 20):
            batch = documents[start:start + 20]
            with client.start_session() as session:
                def callback(active_session):
                    db.compras_fornecedores.insert_many(batch, ordered=True, session=active_session)
                session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
            applied_batches += 1
        marked = list(db.compras_fornecedores.find(marker))
        valid = (
            len(marked) == EXPECTED_COUNT
            and db.compras_fornecedores.count_documents({"tenant_id": tenant_id}) == baseline + EXPECTED_COUNT
            and len({doc["cnpj_normalizado"] for doc in marked}) == EXPECTED_COUNT
            and len({doc["codigo_interno"] for doc in marked}) == EXPECTED_COUNT
            and all(doc.get("homologacao", {}).get("status") == "nao_iniciada" for doc in marked)
        )
        if not valid:
            db.compras_fornecedores.delete_many(marker)
            raise RuntimeError("Supplier post-check failed; inserted documents were removed")
    except Exception:
        db.compras_fornecedores.delete_many(marker)
        raise

    result.update({
        "status": "APPLIED_HOMOLOGATION",
        "applied_batches": applied_batches,
        "after": {"compras_fornecedores": baseline + EXPECTED_COUNT},
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
