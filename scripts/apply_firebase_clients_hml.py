"""Apply or roll back the approved Firebase client wave in homologation only.

The script refuses production hosts/databases, never updates existing clients,
uses deterministic identifiers, and tags every inserted document so rollback
can target only this migration plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bson import BSON
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.uri_parser import parse_uri
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


PLAN_ID = "e5669507-b321-5187-96fa-7246cc909085"
SOURCE_SHA = "7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4"
EXPECTED_DB = "kuryos_erp_homologacao"
EXPECTED_TENANT = "a1534e89-bbfa-483f-ac0b-8d6dbf6bab22"
PRODUCTION_HOST_FRAGMENT = "h2hedhh"
ID_NAMESPACE = uuid.UUID("44a35553-7319-49f5-8e77-5ae3e78099f1")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, ":".join(parts)))


def clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def norm_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", clean(value))
    return " ".join("".join(c for c in raw if not unicodedata.combining(c)).upper().split())


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def valid_email(value: Any) -> str:
    email = clean(value).lower()
    return email if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else ""


def valid_phone(value: Any) -> str:
    phone = digits(value)
    return phone if 10 <= len(phone) <= 13 else ""


def cli4_candidates(name: str) -> list[str]:
    words = ["".join(c for c in word.upper() if c.isalpha()) for word in name.split()]
    words = [word for word in words if word]
    all_letters = "".join(words)
    candidates: list[str] = []
    if len(words) >= 2 and len(words[0]) >= 3:
        candidates.append((words[0][:3] + words[1][0]).ljust(4, "X"))
    if all_letters:
        candidates.append(all_letters[:4].ljust(4, "X"))
    if len(words) >= 2:
        candidates.append((words[0][:2] + words[1][:2]).ljust(4, "X"))
    initials = "".join(word[0] for word in words)
    if len(initials) >= 2:
        candidates.append(initials[:4].ljust(4, "X"))
    for start in range(1, max(0, len(all_letters) - 3)):
        candidates.append(all_letters[start:start + 4].ljust(4, "X"))
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if candidate not in seen and len(candidate) == 4 and candidate.isalpha():
            seen.add(candidate)
            result.append(candidate)
    return result


def allocate_cli4(name: str, legacy_id: str, occupied: set[str]) -> str:
    for candidate in cli4_candidates(name):
        if candidate not in occupied:
            occupied.add(candidate)
            return candidate
    digest = hashlib.sha256(f"{name}:{legacy_id}".encode()).digest()
    for offset in range(0, 256):
        value = int.from_bytes(digest[:4], "big") + offset
        letters = ""
        for _ in range(4):
            letters = chr(ord("A") + value % 26) + letters
            value //= 26
        if letters not in occupied:
            occupied.add(letters)
            return letters
    raise RuntimeError(f"Unable to allocate unique CLI4 for legacy client {legacy_id}")


def document_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(BSON.encode(document)).hexdigest()


def assert_homologation(uri: str, db_name: str, tenant_id: str) -> None:
    parsed = parse_uri(uri)
    hosts = [host for host, _ in parsed.get("nodelist", [])]
    if db_name != EXPECTED_DB or tenant_id != EXPECTED_TENANT:
        raise RuntimeError("Target database/tenant is not the approved homologation target")
    if any(PRODUCTION_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Production host detected; operation refused")
    if not any("yxj58uo" in host for host in hosts):
        raise RuntimeError("Approved homologation host not detected; operation refused")


def build_documents(source: dict[str, Any], map_entries: list[dict[str, Any]], db, tenant_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = {entry["legacy_id"]: entry for entry in map_entries if entry["classification"] == "INSERT_CANDIDATE"}
    if len(candidates) != 56:
        raise RuntimeError(f"Expected 56 client candidates, found {len(candidates)}")

    existing = list(db.crm_clients.find({"tenant_id": tenant_id}))
    existing_cnpj = {digits(doc.get("cnpj_normalized") or doc.get("cnpj")) for doc in existing if digits(doc.get("cnpj_normalized") or doc.get("cnpj"))}
    existing_names = {norm_text(doc.get("nome_empresa")) for doc in existing if norm_text(doc.get("nome_empresa"))}
    occupied_cli4 = {clean(doc.get("cli4")).upper() for doc in existing if clean(doc.get("cli4"))}

    actor = db.users.find_one(
        {"tenant_id": tenant_id, "$or": [{"role": {"$in": ["admin", "super_admin"]}}, {"roles": {"$in": ["admin", "super_admin"]}}]},
        sort=[("created_at", 1)],
    ) or db.users.find_one({"tenant_id": tenant_id}, sort=[("created_at", 1)])
    if not actor:
        raise RuntimeError("No homologation user available as migration actor/responsible")
    actor_id = str(actor.get("id") or actor.get("_id"))
    actor_name = clean(actor.get("name") or actor.get("nome") or "Migração Firebase")

    now = datetime.now(timezone.utc).isoformat()
    due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    clients: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    invalid_contact_values = 0
    seen_cnpj = set(existing_cnpj)
    seen_names = set(existing_names)

    for legacy_id in sorted(candidates):
        payload = source["clientes"].get(legacy_id)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Missing source payload for client {legacy_id}")
        name = clean(payload.get("nome"))
        cnpj = clean(payload.get("cnpj"))
        cnpj_norm = digits(cnpj)
        name_norm = norm_text(name)
        if not name:
            raise RuntimeError(f"Client {legacy_id} has no name")
        if cnpj_norm and cnpj_norm in seen_cnpj:
            raise RuntimeError(f"CNPJ conflict appeared after reconciliation for client {legacy_id}")
        if name_norm in seen_names:
            raise RuntimeError(f"Name conflict appeared after reconciliation for client {legacy_id}")
        if cnpj_norm:
            seen_cnpj.add(cnpj_norm)
        seen_names.add(name_norm)

        client_id = stable_id("firebase-current", tenant_id, "clients", "clientes", legacy_id)
        operation_id = stable_id(PLAN_ID, "clients", "clientes", legacy_id)
        cli4 = allocate_cli4(name, legacy_id, occupied_cli4)
        main_email = valid_email(payload.get("contatoComEmail"))
        main_phone = valid_phone(payload.get("contatoComTelefone"))
        if clean(payload.get("contatoComEmail")) and not main_email:
            invalid_contact_values += 1
        if clean(payload.get("contatoComTelefone")) and not main_phone:
            invalid_contact_values += 1
        additional = []
        tech_name = clean(payload.get("contatoTecNome"))
        tech_email = valid_email(payload.get("contatoTecEmail"))
        tech_phone = valid_phone(payload.get("contatoTecTelefone"))
        if clean(payload.get("contatoTecEmail")) and not tech_email:
            invalid_contact_values += 1
        if clean(payload.get("contatoTecTelefone")) and not tech_phone:
            invalid_contact_values += 1
        if tech_name or tech_email or tech_phone:
            additional.append({"nome": tech_name, "cargo": "", "whatsapp": tech_phone, "email": tech_email})

        migration = {
            "source": "firebase-current",
            "source_node": "clientes",
            "source_id": legacy_id,
            "source_sha256": SOURCE_SHA,
            "plan_id": PLAN_ID,
            "operation_id": operation_id,
            "applied_at": now,
        }
        client = {
            "id": client_id,
            "tenant_id": tenant_id,
            "stage": "prospeccao",
            "nome_empresa": name,
            "cnpj": cnpj,
            "cnpj_normalized": cnpj_norm,
            "contato_principal": {"nome": clean(payload.get("contatoComNome")), "whatsapp": main_phone, "email": main_email},
            "contatos_adicionais": additional,
            "canal_origem": "",
            "categoria_interesse": [],
            "origem_lead": "",
            "temperatura_lead": "morno",
            "responsavel_comercial": actor_id,
            "segmento": "outro",
            "porte": "",
            "regiao": clean(payload.get("uf")).upper(),
            "cidade": clean(payload.get("cidade")),
            "uf": clean(payload.get("uf")).upper(),
            "site": clean(payload.get("site")),
            "instagram": "",
            "observacoes": "",
            "cli3": "GEN",
            "cli4": cli4,
            "cli4_congelado": False,
            "has_grau2_anvisa": False,
            "ultima_atualizacao_temperatura": now,
            "decisores": [],
            "tem_marca_propria": None,
            "tem_anvisa": "",
            "volume_estimado_mensal": "",
            "fornecedor_atual": {"tem": False, "motivo_troca": ""},
            "prazo_urgencia": None,
            "amostras_aprovadas": [],
            "valor_estimado_projeto": None,
            "moq_negociado": "",
            "condicao_pagamento": clean(payload.get("condicaoPagamento")),
            "anvisa_necessario": {"necessario": False, "status": ""},
            "concorrentes_envolvidos": [],
            "data_pedido": None,
            "skus_confirmados": [],
            "valor_primeiro_pedido": None,
            "previsao_segundo_pedido": None,
            "motivo_perda": "",
            "historico_movimentacoes": [],
            "status_cadastro": "ativo" if payload.get("ativo", True) is not False else "inativo",
            "created_by": actor_id,
            "created_by_name": actor_name,
            "created_at": now,
            "updated_at": now,
            "_migration": migration,
        }
        task_id = stable_id(PLAN_ID, "workflow_task", legacy_id)
        task = {
            "id": task_id,
            "display_code": f"MIG-{operation_id[:8].upper()}",
            "tenant_id": tenant_id,
            "entity_type": "client",
            "entity_id": client_id,
            "module_origin": "client",
            "title": "Realizar primeiro contato comercial",
            "description": "Tarefa gerada na importação controlada do cliente para Prospecção.",
            "category": "comercial",
            "task_type": "standard",
            "priority": "normal",
            "blocking": False,
            "blocks_stages": [],
            "responsible_id": actor_id,
            "responsible_name": actor_name,
            "assignment_history": [{"responsible_id": actor_id, "responsible_name": actor_name, "assigned_by": actor_id, "assigned_by_name": actor_name, "assigned_at": now, "reason": "initial_assignment"}],
            "due_date": due,
            "status": "pendente",
            "decision": None,
            "decision_comment": "",
            "decision_at": None,
            "decision_by": None,
            "decision_by_name": None,
            "completed_at": None,
            "completed_by": None,
            "completed_by_name": None,
            "created_by": actor_id,
            "created_by_name": actor_name,
            "created_at": now,
            "updated_at": now,
            "metadata": {"trigger": "client_created", "stage": "prospeccao", "migration_plan_id": PLAN_ID},
            "notification_flags": {"assigned_at": None, "due_1d_at": None, "overdue_at": None, "completed_at": None},
            "_migration": migration,
        }
        audit = {
            "id": stable_id(PLAN_ID, "audit_log", legacy_id),
            "tenant_id": tenant_id,
            "user_id": actor_id,
            "user_name": actor_name,
            "action": "client_created_firebase_migration",
            "entity_type": "client",
            "entity_id": client_id,
            "before": None,
            "after": {"nome_empresa": name, "stage": "prospeccao", "cli4": cli4},
            "metadata": {"source": "firebase-current", "source_id": legacy_id, "plan_id": PLAN_ID},
            "timestamp": now,
            "_migration": migration,
        }
        clients.append(client); tasks.append(task); audits.append(audit)

    return clients, {"tasks": tasks, "audits": audits, "actor_id": actor_id, "invalid_contact_values_omitted": invalid_contact_values}


def rollback(db, tenant_id: str) -> dict[str, int]:
    query = {"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID}
    result = {}
    with db.client.start_session() as session:
        def callback(s):
            result["audit_logs"] = db.audit_logs.delete_many(query, session=s).deleted_count
            result["workflow_tasks"] = db.workflow_tasks.delete_many(query, session=s).deleted_count
            result["crm_clients"] = db.crm_clients.delete_many(query, session=s).deleted_count
        session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dry-run", "apply", "rollback"])
    parser.add_argument("--env", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--client-map", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    env = load_env(Path(args.env))
    uri = env["ERP_HML_MONGO_URI"]
    db_name = env["ERP_HML_DB_NAME"]
    tenant_id = env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, db_name, tenant_id)

    source_path = Path(args.source)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    snapshot_path = Path(args.snapshot)
    if not snapshot_path.is_file() or hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != args.snapshot_sha256:
        raise RuntimeError("Retained pre-apply snapshot is missing or has a different hash")

    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    db = client[db_name]
    if db.tenants.count_documents({"id": tenant_id}) != 1:
        raise RuntimeError("Approved tenant not found exactly once")

    if args.mode == "rollback":
        deleted = rollback(db, tenant_id)
        report = {"status": "ROLLED_BACK", "plan_id": PLAN_ID, "deleted": deleted, "at": datetime.now(timezone.utc).isoformat()}
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        client.close()
        return 0

    source = json.loads(source_path.read_text(encoding="utf-8"))
    client_map = json.loads(Path(args.client_map).read_text(encoding="utf-8"))["entries"]
    clients, related = build_documents(source, client_map, db, tenant_id)
    existing_marked = db.crm_clients.count_documents({"tenant_id": tenant_id, "_migration.plan_id": PLAN_ID})
    if existing_marked:
        raise RuntimeError("This migration plan already has inserted clients; refusing to reapply")
    baseline = {
        "crm_clients": db.crm_clients.count_documents({"tenant_id": tenant_id}),
        "workflow_tasks": db.workflow_tasks.count_documents({"tenant_id": tenant_id}),
        "audit_logs": db.audit_logs.count_documents({"tenant_id": tenant_id}),
        "crm_samples": db.crm_samples.count_documents({"tenant_id": tenant_id}),
        "pd_requests": db.pd_requests.count_documents({"tenant_id": tenant_id}),
        "pd_developments": db.pd_developments.count_documents({"tenant_id": tenant_id}),
    }
    preview = {
        "status": "DRY_RUN_VALID" if args.mode == "dry-run" else "APPLY_STARTED",
        "plan_id": PLAN_ID,
        "target": {"database": db_name, "tenant_id": tenant_id},
        "baseline": baseline,
        "planned": {"clients": len(clients), "workflow_tasks": len(related["tasks"]), "audit_logs": len(related["audits"]), "pd_writes": 0},
        "invalid_contact_values_omitted": related["invalid_contact_values_omitted"],
        "operations": [{"operation_id": doc["_migration"]["operation_id"], "legacy_id": doc["_migration"]["source_id"], "target_id": doc["id"], "before_hash": None, "after_hash": document_hash(doc)} for doc in clients],
    }
    if args.mode == "dry-run":
        Path(args.report).write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in preview.items() if k != "operations"}, ensure_ascii=False))
        client.close()
        return 0

    batch_size = 10
    applied_batches = 0
    try:
        for start in range(0, len(clients), batch_size):
            batch_clients = clients[start:start + batch_size]
            batch_ids = {doc["id"] for doc in batch_clients}
            batch_tasks = [doc for doc in related["tasks"] if doc["entity_id"] in batch_ids]
            batch_audits = [doc for doc in related["audits"] if doc["entity_id"] in batch_ids]
            with client.start_session() as session:
                def callback(s):
                    if db.crm_clients.count_documents({"tenant_id": tenant_id, "id": {"$in": list(batch_ids)}}, session=s):
                        raise RuntimeError("Deterministic client ID appeared before batch insert")
                    db.crm_clients.insert_many(batch_clients, ordered=True, session=s)
                    db.workflow_tasks.insert_many(batch_tasks, ordered=True, session=s)
                    db.audit_logs.insert_many(batch_audits, ordered=True, session=s)
                session.with_transaction(callback, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"))
            applied_batches += 1
    except Exception:
        rollback_result = rollback(db, tenant_id)
        preview.update({"status": "APPLY_FAILED_AUTO_ROLLED_BACK", "applied_batches_before_failure": applied_batches, "rollback": rollback_result})
        Path(args.report).write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise

    after = {
        "crm_clients": db.crm_clients.count_documents({"tenant_id": tenant_id}),
        "workflow_tasks": db.workflow_tasks.count_documents({"tenant_id": tenant_id}),
        "audit_logs": db.audit_logs.count_documents({"tenant_id": tenant_id}),
        "crm_samples": db.crm_samples.count_documents({"tenant_id": tenant_id}),
        "pd_requests": db.pd_requests.count_documents({"tenant_id": tenant_id}),
        "pd_developments": db.pd_developments.count_documents({"tenant_id": tenant_id}),
    }
    expected = {
        **baseline,
        "crm_clients": baseline["crm_clients"] + len(clients),
        "workflow_tasks": baseline["workflow_tasks"] + len(related["tasks"]),
        "audit_logs": baseline["audit_logs"] + len(related["audits"]),
    }
    if after != expected:
        rollback_result = rollback(db, tenant_id)
        preview.update({"status": "POSTCHECK_FAILED_AUTO_ROLLED_BACK", "after": after, "expected": expected, "rollback": rollback_result})
        Path(args.report).write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("Post-apply counts diverged; automatic rollback executed")

    preview.update({"status": "APPLIED_HOMOLOGATION", "applied_batches": applied_batches, "after": after, "expected": expected, "completed_at": datetime.now(timezone.utc).isoformat()})
    Path(args.report).write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in preview.items() if k != "operations"}, ensure_ascii=False))
    client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, PyMongoError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
