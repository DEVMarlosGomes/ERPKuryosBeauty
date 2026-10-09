#!/usr/bin/env python3
"""Read-only reconciliation for legacy HR roles and users."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from apply_firebase_clients_hml import SOURCE_SHA, assert_homologation, load_env


EXPECTED = {"job_role": 3, "legacy_user": 13}
SENSITIVE_FIELDS = {"password", "password_hash", "senha", "token", "refresh_token", "access_token"}


def clean(value: Any) -> str:
    return str(value or "").strip()


def sanitized(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key.lower() not in SENSITIVE_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--env", required=True); parser.add_argument("--source", type=Path, required=True); parser.add_argument("--json-output", type=Path, required=True); parser.add_argument("--markdown-output", type=Path, required=True); args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA: raise RuntimeError("Firebase source hash mismatch")
    source = json.loads(source_bytes.decode("utf-8")); env = load_env(Path(args.env)); uri, database_name, tenant_id = env["ERP_HML_MONGO_URI"], env["ERP_HML_DB_NAME"], env["ERP_HML_TENANT_ID"]
    assert_homologation(uri, database_name, tenant_id)
    client = MongoClient(uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=15000)
    target_by_email = {clean(row.get("email")).lower(): row.get("id") for row in client[database_name].users.find({"tenant_id": tenant_id}, {"_id": 0, "id": 1, "email": 1}) if clean(row.get("email"))}
    roles = [{"source_key": key, "legacy_name": raw.get("nome"), "legacy_sector": raw.get("setor"), "legacy_level": raw.get("nivelTrilha"), "legacy_active": raw.get("ativo"), "classification": "manual_review", "blockers": ["target_role_mapping_required"], "sanitized_payload": sanitized(raw)} for key, raw in sorted((source.get("rh_cargos") or {}).items())]
    users, classifications = [], Counter()
    for key, raw in sorted((source.get("usuarios") or {}).items()):
        email = clean(raw.get("email")).lower(); target_id = target_by_email.get(email)
        classification = "match_existing" if target_id else "manual_review"
        blockers = ["account_creation_prohibited", "role_mapping_required"] if not target_id else ["existing_account_preserved"]
        classifications[classification] += 1
        users.append({"source_key": key, "legacy_name": raw.get("nome"), "legacy_email": email or None, "legacy_role": raw.get("role"), "target_user_id": target_id, "classification": classification, "blockers": blockers, "sanitized_payload": sanitized(raw)})
    counts = {"job_role": len(roles), "legacy_user": len(users)}
    if counts != EXPECTED: raise RuntimeError(f"Unexpected HR counts: {counts}")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "READ_ONLY_HML_RECONCILIATION", "source_sha256": SOURCE_SHA, "production_written": False, "homologation_written": False, "counts": counts, "user_classifications": dict(classifications), "job_roles": roles, "legacy_users": users, "decision_gate": {"status": "READY_FOR_ISOLATED_HML_REVIEW", "account_creation_allowed": False, "permission_replay_allowed": False}}
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text("\n".join(["# RH legado - preflight HML", "", f"Gerado em: {report['generated_at']}", "", "Modo somente leitura.", "", f"- Cargos: {len(roles)}", f"- Usuários: {len(users)}", f"- Contas existentes por e-mail: {classifications['match_existing']}", f"- Usuários sem conta correspondente: {classifications['manual_review']}", "", "Nenhuma conta, senha, sessão, papel ou permissão será criada nesta onda."]) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PREFLIGHT_VALID", "counts": counts, "user_classifications": dict(classifications)}, ensure_ascii=False)); client.close(); return 0


if __name__ == "__main__": raise SystemExit(main())
