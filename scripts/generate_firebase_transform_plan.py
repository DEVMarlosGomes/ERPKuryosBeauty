"""Generate a versioned, reversible transformation plan without Mongo writes."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_SHA = "7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4"
PLAN_NAMESPACE = uuid.UUID("44a35553-7319-49f5-8e77-5ae3e78099f1")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(PLAN_NAMESPACE, ":".join(parts)))


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_firebase_transform_plan.py REPORT_DIR OUTPUT_DIR")
    report_dir = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)

    reconciliation = read_json(report_dir / "RECONCILIATION_CURRENT_MONGO.json")
    if reconciliation.get("status") != "COMPLETED_READ_ONLY_AWAITING_HUMAN_APPROVAL":
        raise RuntimeError("Read-only reconciliation checkpoint is not complete")
    if reconciliation.get("write_operations_performed"):
        raise RuntimeError("Reconciliation unexpectedly reports Mongo writes")

    tenant_id = reconciliation["mongo"]["tenant_id"]
    db_name = reconciliation["mongo"]["db_name"]
    generated_at = datetime.now(timezone.utc).isoformat()
    plan_id = stable_id("firebase-current-plan", SOURCE_SHA, tenant_id, db_name)

    map_files = {
        "clients": "CLIENT_ID_MAP.json",
        "suppliers": "SUPPLIER_ID_MAP.json",
        "materials": "MATERIAL_ID_MAP.json",
        "skus": "SKU_ID_MAP.json",
        "orders": "ORDER_ID_MAP.json",
        "ops": "OP_ID_MAP.json",
        "addresses": "ADDRESS_ID_MAP.json",
        "lots": "LOT_ID_MAP.json",
    }
    maps = {domain: read_json(report_dir / filename)["entries"] for domain, filename in map_files.items()}
    input_hashes = {filename: sha256(report_dir / filename) for filename in [
        "RECONCILIATION_CURRENT_MONGO.json", "MIGRATION_COUNTS.json", "CONFLICTS.json",
        "MANUAL_REVIEW.json", "STOCK_RECONCILIATION.json", *map_files.values(),
    ]}

    records: list[dict[str, Any]] = []
    for domain, entries in maps.items():
        for entry in entries:
            node = str(entry.get("source_node") or domain)
            legacy_id = str(entry.get("legacy_id"))
            classification = entry["classification"]
            if classification == "MATCH":
                disposition = "NO_OP_MAP_ONLY"
                target_id = (
                    entry.get("current_client_id") or entry.get("current_supplier_id")
                    or entry.get("target_id") or entry.get("current_sku_id")
                    or entry.get("current_order_id") or entry.get("current_op_id")
                    or entry.get("current_address_id") or entry.get("current_lot_balance_id")
                )
            elif classification == "INSERT_CANDIDATE" and domain in {"clients", "suppliers"}:
                disposition = "PROPOSED_INSERT_REVIEW_REQUIRED"
                target_id = stable_id("firebase-current", tenant_id, domain, node, legacy_id)
            elif classification == "INSERT_CANDIDATE":
                disposition = "BLOCKED_DEPENDENCIES"
                target_id = stable_id("firebase-current", tenant_id, domain, node, legacy_id)
            else:
                disposition = "BLOCKED_CONFLICT_OR_MANUAL_REVIEW"
                target_id = None
            records.append({
                "operation_id": stable_id(plan_id, domain, node, legacy_id),
                "domain": domain,
                "source_node": node,
                "legacy_id": legacy_id,
                "classification": classification,
                "disposition": disposition,
                "proposed_target_id": target_id,
                "mongo_action_authorized": False,
            })

    disposition_counts: dict[str, int] = {}
    for record in records:
        disposition_counts[record["disposition"]] = disposition_counts.get(record["disposition"], 0) + 1

    def record_count(domain: str, *, disposition: str | None = None, classification: str | None = None) -> int:
        return sum(
            record["domain"] == domain
            and (disposition is None or record["disposition"] == disposition)
            and (classification is None or record["classification"] == classification)
            for record in records
        )

    waves = [
        {
            "wave": 0,
            "name": "baseline_and_journal",
            "status": "PLANNED_NOT_AUTHORIZED",
            "scope": "Create retained pre-apply snapshot, immutable manifest and migration journal in homologation.",
            "required_gates": ["fresh database fingerprint", "snapshot SHA-256", "restore drill", "homologation-only URI assertion"],
        },
        {
            "wave": 1,
            "name": "clients",
            "status": "REVIEW_REQUIRED",
            "counts": {
                "map_only": record_count("clients", disposition="NO_OP_MAP_ONLY"),
                "proposed_insert": record_count("clients", disposition="PROPOSED_INSERT_REVIEW_REQUIRED"),
                "blocked_review": record_count("clients", disposition="BLOCKED_CONFLICT_OR_MANUAL_REVIEW"),
            },
            "rules": [
                "Exact CNPJ/name matches are map-only and never update existing clients.",
                "New IDs are UUIDv5 deterministic by tenant/domain/source id.",
                "cli4 is resolved with the current ERP collision rules; frozen cli4 is never overwritten.",
                "Imported lifecycle stage requires explicit business approval before apply.",
            ],
        },
        {
            "wave": 2,
            "name": "suppliers",
            "status": "REVIEW_REQUIRED",
            "counts": {
                "proposed_insert": record_count("suppliers", disposition="PROPOSED_INSERT_REVIEW_REQUIRED"),
                "conflict_records": record_count("suppliers", classification="CONFLICT"),
                "blocked_review": record_count("suppliers", classification="MANUAL_REVIEW"),
            },
            "rules": [
                "Only unique normalized CNPJ can become an insert.",
                "Name similarity is not an automatic match.",
                "Internal supplier codes are allocated by the current ERP sequence during apply.",
                "Counter before-image is mandatory for exact rollback.",
            ],
        },
        {
            "wave": 3,
            "name": "materials_and_fragrances",
            "status": "BLOCKED",
            "counts": {"manual_review": 939},
            "blocker": "Human domain classification and governed internal-code decision required.",
        },
        {
            "wave": 4,
            "name": "skus_formulas_bom",
            "status": "BLOCKED",
            "counts": {"sku_alias_review": 392, "formulas_pending": 197, "bom_pending": 246},
            "blocker": "Historical SKU lookup, contractual validity and material dependencies unresolved; no SKU auto-generation.",
        },
        {
            "wave": 5,
            "name": "orders_and_ops",
            "status": "BLOCKED",
            "counts": {"order_candidates": 453, "ops_review": 1388},
            "blocker": "Client, SKU, CGI and order dependencies unresolved; production postings will not be replayed.",
        },
        {
            "wave": 6,
            "name": "physical_stock_wms_cq",
            "status": "BLOCKED",
            "counts": {"addresses_review": 250, "lots_review": 39},
            "blocker": "Physical cutoff, addresses and CQ/WMS approval required; saldoAtual and legacy movements are history only.",
        },
    ]

    transformation = {
        "status": "PLAN_ONLY_NOT_APPLIED",
        "plan_id": plan_id,
        "generated_at": generated_at,
        "source_sha256": SOURCE_SHA,
        "target": {"database": db_name, "tenant_id": tenant_id, "environment": "homologation"},
        "production_writes_allowed": False,
        "homologation_writes_authorized": False,
        "functional_erp_code_changes": False,
        "input_report_sha256": input_hashes,
        "disposition_counts": disposition_counts,
        "transformation_contracts": {
            "clients": {
                "target_collection": "crm_clients",
                "field_map": {
                    "nome": "nome_empresa", "cnpj": "cnpj", "condicaoPagamento": "condicao_pagamento",
                    "cidade": "cidade", "uf": "uf", "site": "site", "contatoComNome": "responsavel",
                    "contatoComEmail": "email", "contatoComTelefone": "telefone",
                },
                "generated_fields": ["id", "tenant_id", "cnpj_normalized", "cli4", "status_cadastro", "created_at", "updated_at"],
                "decision_required": "stage for imported legacy master clients",
            },
            "suppliers": {
                "target_collection": "compras_fornecedores",
                "field_map": {
                    "razaoSocial": "razao_social", "nomeFantasia": "nome_fantasia", "cnpj": "cnpj",
                    "contatoNome": "contatos[0].nome", "contatoEmail": "contatos[0].email",
                    "contatoTelefone": "contatos[0].telefone", "cidade": "endereco.cidade", "uf": "endereco.uf",
                    "cep": "endereco.cep", "logradouro": "endereco.logradouro", "numero": "endereco.numero",
                    "bairro": "endereco.bairro", "complemento": "endereco.complemento",
                },
                "generated_fields": ["id", "tenant_id", "codigo_interno", "cnpj_normalizado", "homologacao", "status_cadastro", "created_at", "updated_at"],
            },
        },
        "waves": waves,
        "records": records,
        "apply_gate": "A separate explicit authorization is required after reviewing this plan and resolving wave decisions.",
    }
    write_json(output / "TRANSFORMATION_PLAN_CURRENT.json", transformation)

    rollback = {
        "status": "PLAN_ONLY_NOT_APPLIED",
        "plan_id": plan_id,
        "target": {"database": db_name, "tenant_id": tenant_id, "environment": "homologation"},
        "recovery_objective": "Return homologation data and indexes to the exact pre-apply fingerprint.",
        "mandatory_before_apply": [
            "Create a fresh compressed mongodump of the complete homologation database.",
            "Calculate and record SHA-256 and archive size; retain the archive until final homologation approval.",
            "Record exact per-collection document hashes, counts and index definitions.",
            "Record before-images for counters and every document that could be updated.",
            "Create a migration run manifest with plan_id, operation_id, target id and before/after hashes.",
            "Verify a restore drill into a disposable database before starting Wave 1.",
        ],
        "apply_safety": {
            "batching": "One domain wave at a time; bounded transaction batches where supported.",
            "idempotency": "Deterministic UUIDv5 IDs plus plan_id/operation_id precondition checks.",
            "existing_documents": "No automatic updates in the initial plan; MATCH records are map-only.",
            "migration_marker": "Every inserted document must carry source, source_id, plan_id and operation_id metadata.",
            "stop_conditions": ["count drift", "hash drift", "new conflict", "index failure", "dependency unresolved", "target is not homologation"],
        },
        "inverse_operations": [
            "Stop the homologation application and background workers.",
            "Verify inserted documents still match their recorded after-hash; stop on operator/user edits.",
            "Delete only inserted documents whose tenant_id, plan_id and operation_id all match the manifest.",
            "Restore any future updates from immutable before-images.",
            "Restore counter before-images after dependent inserts are removed.",
            "Restore index definitions if a future approved wave changes indexes.",
            "Recalculate collection counts/hashes/index fingerprints and compare with the baseline.",
            "If any inverse check fails, restore the retained full snapshot to a new clean homologation database and switch the homologation connection only after validation.",
        ],
        "production_actions": [],
        "current_rollback_required": False,
        "reason": "This turn generated files only; no Mongo transformation was applied.",
    }
    write_json(output / "ROLLBACK_PLAN_CURRENT.json", rollback)

    manifest = {
        "status": "TEMPLATE_NOT_APPLIED",
        "plan_id": plan_id,
        "baseline": {
            "database": db_name,
            "tenant_id": tenant_id,
            "expected_collections": 101,
            "expected_documents": 9041,
            "snapshot_archive": None,
            "snapshot_sha256": None,
            "collection_fingerprints": None,
        },
        "runs": [],
        "operations": [
            {**record, "status": "NOT_APPLIED", "before_hash": None, "after_hash": None, "applied_at": None, "rolled_back_at": None}
            for record in records
        ],
    }
    write_json(output / "APPLY_MANIFEST_TEMPLATE.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
