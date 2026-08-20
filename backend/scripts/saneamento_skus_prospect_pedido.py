"""
Auditoria e saneamento seguro de SKUs antigos do fluxo Prospecto -> Pedido.

Dry-run por padrao:
    python backend/scripts/saneamento_skus_prospect_pedido.py --report saneamento_skus.json

Aplicacao explicita:
    python backend/scripts/saneamento_skus_prospect_pedido.py --apply --report saneamento_skus_apply.json

O script nao cria SKU, nao cria Produto-Pai e nao apaga documentos. Ele apenas
prepara/aplica updates idempotentes quando existe evidencia inequivoca nos dados.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=False)

PD_PROJECT_APPROVED_STAGES = {"pedido_aprovado", "cliente_fechado"}
APPROVED_STATES = {"aprovada", "aprovado"}
SCRIPT_ORIGIN = "saneamento_prospect_pedido_2026_08"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _norm_text(value: Any) -> str:
    cleaned = _clean(value).lower()
    return re.sub(r"\s+", " ", cleaned)


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _key(tenant_id: Any, item_id: Any) -> Tuple[str, str]:
    return (_clean(tenant_id), _clean(item_id))


def _safe_doc(doc: dict) -> dict:
    safe = deepcopy(doc)
    safe.pop("_id", None)
    return safe


def _variation_is_approved(variation: Optional[dict]) -> bool:
    if not variation:
        return False
    return (
        _clean(variation.get("status")).lower() in APPROVED_STATES
        or _clean(variation.get("resultado")).lower() in APPROVED_STATES
    )


def _sample_is_approved(sample: Optional[dict]) -> bool:
    return bool(sample and _clean(sample.get("stage")).lower() in APPROVED_STATES)


def _project_is_commercially_approved(project: Optional[dict]) -> bool:
    return bool(project and _clean(project.get("stage")).lower() in PD_PROJECT_APPROVED_STAGES)


def _find_variation(sample: Optional[dict], variation_id: str) -> Optional[dict]:
    if not sample:
        return None
    for variation in sample.get("variacoes") or []:
        if _clean(variation.get("id")) == variation_id:
            return variation
    return None


def _derive_nome_base(sku: dict, sample: Optional[dict], variation: Optional[dict]) -> str:
    if sample:
        name = sample.get("nome_amostra") or sample.get("nome_produto")
        if name:
            return _clean(name)

    name = _clean(sku.get("nome_produto"))
    variation_code = _clean((variation or {}).get("codigo"))
    if variation_code and name.lower().endswith(f" - {variation_code}".lower()):
        return name[: -(len(variation_code) + 3)].strip()
    return name


def _merge_update(
    updates_by_key: Dict[Tuple[str, str, str], dict],
    collection: str,
    query: dict,
    fields: dict,
    reason: str,
) -> None:
    update_key = (collection, json.dumps(query, sort_keys=True, ensure_ascii=True), "$set")
    current = updates_by_key.setdefault(
        update_key,
        {
            "collection": collection,
            "query": query,
            "set": {},
            "reasons": [],
        },
    )
    current["set"].update(fields)
    if reason not in current["reasons"]:
        current["reasons"].append(reason)


def build_sku_saneamento_plan(
    *,
    skus: Iterable[dict],
    samples: Iterable[dict],
    projects: Iterable[dict],
    produtos_pai: Iterable[dict],
    now: Optional[str] = None,
) -> dict:
    """Monta plano idempotente de saneamento sem acessar banco.

    Regras de seguranca:
    - amostra_variacao_id so e preenchido quando existe uma unica evidencia.
    - produto_pai_id so e preenchido quando existe um unico Produto-Pai candidato.
    - pd_concluido so e marcado quando ha variacao/amostra aprovada e projeto aprovado.
    """

    now = now or _now_iso()
    sku_docs = [_safe_doc(doc) for doc in skus]
    sample_docs = [_safe_doc(doc) for doc in samples]
    project_docs = [_safe_doc(doc) for doc in projects]
    pai_docs = [_safe_doc(doc) for doc in produtos_pai]

    sample_by_id = {
        _key(sample.get("tenant_id"), sample.get("id")): sample
        for sample in sample_docs
        if sample.get("tenant_id") and sample.get("id")
    }
    project_by_id = {
        _key(project.get("tenant_id"), project.get("id")): project
        for project in project_docs
        if project.get("tenant_id") and project.get("id")
    }

    sku_by_variation: Dict[Tuple[str, str, str], List[dict]] = {}
    sku_by_sample: Dict[Tuple[str, str], List[dict]] = {}
    for sku in sku_docs:
        tenant_id = _clean(sku.get("tenant_id"))
        sample_id = _clean(sku.get("amostra_id"))
        variation_id = _clean(sku.get("amostra_variacao_id"))
        if sample_id:
            sku_by_sample.setdefault((tenant_id, sample_id), []).append(sku)
        if sample_id and variation_id:
            sku_by_variation.setdefault((tenant_id, sample_id, variation_id), []).append(sku)

    produto_pai_by_name: Dict[Tuple[str, str, str], List[dict]] = {}
    for pai in pai_docs:
        lookup = (_clean(pai.get("tenant_id")), _clean(pai.get("cliente_id")), _norm_text(pai.get("nome")))
        produto_pai_by_name.setdefault(lookup, []).append(pai)

    updates_by_key: Dict[Tuple[str, str, str], dict] = {}
    issues: List[dict] = []

    for sku in sku_docs:
        sku_id = _clean(sku.get("id"))
        tenant_id = _clean(sku.get("tenant_id"))
        sample_id = _clean(sku.get("amostra_id"))

        if not sku_id or not tenant_id:
            issues.append(
                {
                    "type": "sku_sem_identificador_confiavel",
                    "sku_id": sku.get("id"),
                    "tenant_id": sku.get("tenant_id"),
                    "severity": "alta",
                    "detail": "SKU sem id ou tenant_id nao pode ser saneado automaticamente.",
                }
            )
            continue

        sample = sample_by_id.get((tenant_id, sample_id)) if sample_id else None
        project_id = _clean(sku.get("projeto_id") or (sample or {}).get("projeto_id"))
        project = project_by_id.get((tenant_id, project_id)) if project_id else None
        variation_id = _clean(sku.get("amostra_variacao_id"))
        variation = _find_variation(sample, variation_id) if variation_id else None

        if sample_id and not sample:
            issues.append(
                {
                    "type": "amostra_nao_encontrada",
                    "sku_id": sku_id,
                    "tenant_id": tenant_id,
                    "amostra_id": sample_id,
                    "severity": "media",
                    "detail": "SKU referencia amostra inexistente ou fora do tenant carregado.",
                }
            )

        if _is_missing(variation_id) and sample:
            linked_by_sku_id = [
                variation_candidate
                for variation_candidate in sample.get("variacoes") or []
                if _clean(variation_candidate.get("sku_id")) == sku_id
            ]
            if len(linked_by_sku_id) == 1:
                variation = linked_by_sku_id[0]
                variation_id = _clean(variation.get("id"))
                _merge_update(
                    updates_by_key,
                    "skus",
                    {"tenant_id": tenant_id, "id": sku_id},
                    {"amostra_variacao_id": variation_id, "updated_at": now},
                    "amostra_variacao_id recuperado a partir de variacoes[].sku_id",
                )
            elif not linked_by_sku_id:
                approved_variations = [
                    variation_candidate
                    for variation_candidate in sample.get("variacoes") or []
                    if _variation_is_approved(variation_candidate)
                ]
                same_sample_skus = sku_by_sample.get((tenant_id, sample_id), [])
                unclaimed = [
                    variation_candidate
                    for variation_candidate in approved_variations
                    if not sku_by_variation.get((tenant_id, sample_id, _clean(variation_candidate.get("id"))))
                ]
                if len(approved_variations) == 1 and len(unclaimed) == 1 and len(same_sample_skus) == 1:
                    variation = unclaimed[0]
                    variation_id = _clean(variation.get("id"))
                    _merge_update(
                        updates_by_key,
                        "skus",
                        {"tenant_id": tenant_id, "id": sku_id},
                        {"amostra_variacao_id": variation_id, "updated_at": now},
                        "amostra_variacao_id inferido por unica variacao aprovada e unico SKU da amostra",
                    )
                elif approved_variations:
                    issues.append(
                        {
                            "type": "amostra_variacao_ambigua",
                            "sku_id": sku_id,
                            "tenant_id": tenant_id,
                            "amostra_id": sample_id,
                            "severity": "media",
                            "detail": "Mais de uma variacao aprovada/SKU na amostra; exige decisao manual.",
                        }
                    )

        if variation_id and sample:
            variation = variation or _find_variation(sample, variation_id)
            if variation:
                existing_variation_sku_id = _clean(variation.get("sku_id"))
                if not existing_variation_sku_id:
                    _merge_update(
                        updates_by_key,
                        "crm_samples",
                        {"tenant_id": tenant_id, "id": sample_id, "variacoes.id": variation_id},
                        {
                            "variacoes.$.sku_id": sku_id,
                            "variacoes.$.gera_sku": True,
                            "updated_at": now,
                        },
                        "variacao atualizada com sku_id reverso ausente",
                    )
                elif existing_variation_sku_id != sku_id:
                    issues.append(
                        {
                            "type": "variacao_aponta_para_outro_sku",
                            "sku_id": sku_id,
                            "tenant_id": tenant_id,
                            "amostra_id": sample_id,
                            "amostra_variacao_id": variation_id,
                            "sku_id_na_variacao": existing_variation_sku_id,
                            "severity": "alta",
                            "detail": "Conflito de vinculo; nao aplicar automaticamente.",
                        }
                    )
            else:
                issues.append(
                    {
                        "type": "variacao_nao_encontrada",
                        "sku_id": sku_id,
                        "tenant_id": tenant_id,
                        "amostra_id": sample_id,
                        "amostra_variacao_id": variation_id,
                        "severity": "media",
                        "detail": "SKU referencia variacao inexistente na amostra.",
                    }
                )

        if not bool(sku.get("pd_concluido")):
            has_approved_origin = _variation_is_approved(variation) or _sample_is_approved(sample)
            has_approved_project = _project_is_commercially_approved(project)
            if has_approved_origin and has_approved_project:
                _merge_update(
                    updates_by_key,
                    "skus",
                    {"tenant_id": tenant_id, "id": sku_id},
                    {
                        "pd_concluido": True,
                        "pd_concluido_em": now,
                        "pd_concluido_origem": SCRIPT_ORIGIN,
                        "updated_at": now,
                    },
                    "pd_concluido recuperado por amostra/variacao aprovada e projeto aprovado",
                )
            else:
                issues.append(
                    {
                        "type": "pd_concluido_sem_evidencia_suficiente",
                        "sku_id": sku_id,
                        "tenant_id": tenant_id,
                        "severity": "baixa",
                        "detail": "Nao ha evidencia suficiente para marcar P&D concluido automaticamente.",
                    }
                )

        if _is_missing(sku.get("produto_pai_id")):
            nome_base = _derive_nome_base(sku, sample, variation)
            lookup = (tenant_id, _clean(sku.get("cliente_id") or (sample or {}).get("cliente_id")), _norm_text(nome_base))
            candidates = produto_pai_by_name.get(lookup, [])
            if len(candidates) == 1:
                _merge_update(
                    updates_by_key,
                    "skus",
                    {"tenant_id": tenant_id, "id": sku_id},
                    {"produto_pai_id": candidates[0]["id"], "updated_at": now},
                    "produto_pai_id recuperado por Produto-Pai unico do mesmo cliente e nome base",
                )
            elif len(candidates) > 1:
                issues.append(
                    {
                        "type": "produto_pai_ambiguidade",
                        "sku_id": sku_id,
                        "tenant_id": tenant_id,
                        "cliente_id": lookup[1],
                        "nome_base": nome_base,
                        "candidatos": [candidate.get("id") for candidate in candidates],
                        "severity": "alta",
                        "detail": "Mais de um Produto-Pai candidato; exige saneamento manual.",
                    }
                )
            elif nome_base:
                issues.append(
                    {
                        "type": "produto_pai_nao_encontrado",
                        "sku_id": sku_id,
                        "tenant_id": tenant_id,
                        "cliente_id": lookup[1],
                        "nome_base": nome_base,
                        "severity": "baixa",
                        "detail": "Nao existe Produto-Pai candidato; o script nao cria produto-pai.",
                    }
                )

    updates = list(updates_by_key.values())
    return {
        "generated_at": now,
        "mode": "plan",
        "summary": {
            "skus_analisados": len(sku_docs),
            "updates_planejados": len(updates),
            "issues": len(issues),
            "updates_por_colecao": {
                collection: sum(1 for update in updates if update["collection"] == collection)
                for collection in sorted({update["collection"] for update in updates})
            },
            "issues_por_tipo": {
                issue_type: sum(1 for issue in issues if issue["type"] == issue_type)
                for issue_type in sorted({issue["type"] for issue in issues})
            },
        },
        "updates": updates,
        "issues": issues,
    }


async def _load_docs(db, *, tenant_id: str = "", limit: int = 5000, include_descontinuados: bool = False) -> dict:
    sku_query: dict = {}
    if tenant_id:
        sku_query["tenant_id"] = tenant_id
    if not include_descontinuados:
        sku_query["status"] = {"$ne": "descontinuado"}

    skus = await db.skus.find(sku_query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    tenant_ids = sorted({_clean(sku.get("tenant_id")) for sku in skus if sku.get("tenant_id")})
    sample_ids = sorted({_clean(sku.get("amostra_id")) for sku in skus if sku.get("amostra_id")})
    project_ids = sorted({_clean(sku.get("projeto_id")) for sku in skus if sku.get("projeto_id")})
    client_ids = sorted({_clean(sku.get("cliente_id")) for sku in skus if sku.get("cliente_id")})

    tenant_filter = {"$in": tenant_ids} if len(tenant_ids) > 1 else (tenant_ids[0] if tenant_ids else "__none__")

    samples = []
    if sample_ids:
        samples = await db.crm_samples.find(
            {"tenant_id": tenant_filter, "id": {"$in": sample_ids}},
            {"_id": 0},
        ).to_list(len(sample_ids) + 100)
        project_ids = sorted(set(project_ids) | {_clean(sample.get("projeto_id")) for sample in samples if sample.get("projeto_id")})
        client_ids = sorted(set(client_ids) | {_clean(sample.get("cliente_id")) for sample in samples if sample.get("cliente_id")})

    projects = []
    if project_ids:
        projects = await db.crm_projects.find(
            {"tenant_id": tenant_filter, "id": {"$in": project_ids}},
            {"_id": 0},
        ).to_list(len(project_ids) + 100)

    produtos_pai = []
    if client_ids:
        produtos_pai = await db.produtos_pai.find(
            {"tenant_id": tenant_filter, "cliente_id": {"$in": client_ids}},
            {"_id": 0},
        ).to_list(10000)

    return {
        "skus": skus,
        "samples": samples,
        "projects": projects,
        "produtos_pai": produtos_pai,
    }


async def apply_saneamento_plan(db, plan: dict) -> dict:
    result = {"matched": 0, "modified": 0, "errors": []}
    for update in plan.get("updates", []):
        collection_name = update["collection"]
        try:
            write_result = await db[collection_name].update_one(
                update["query"],
                {"$set": update["set"]},
            )
            result["matched"] += getattr(write_result, "matched_count", 0)
            result["modified"] += getattr(write_result, "modified_count", 0)
        except Exception as exc:  # pragma: no cover - protegido para relatorio operacional
            result["errors"].append(
                {
                    "collection": collection_name,
                    "query": update["query"],
                    "error": str(exc),
                }
            )
    return result


def _write_report(path: str, payload: dict) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audita/saneia SKUs antigos do fluxo Prospecto -> Pedido.")
    parser.add_argument("--apply", action="store_true", help="Aplica os updates planejados. Sem esta flag, roda dry-run.")
    parser.add_argument("--tenant-id", default="", help="Filtra um tenant especifico.")
    parser.add_argument("--limit", type=int, default=5000, help="Limite de SKUs analisados.")
    parser.add_argument("--report", default="", help="Caminho para gravar relatorio JSON.")
    parser.add_argument(
        "--include-descontinuados",
        action="store_true",
        help="Inclui SKUs descontinuados na auditoria.",
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    db_name = os.environ.get("DB_NAME", "kuryos_crm")

    client = AsyncIOMotorClient(mongo_url)
    try:
        db = client[db_name]
        docs = await _load_docs(
            db,
            tenant_id=args.tenant_id,
            limit=args.limit,
            include_descontinuados=args.include_descontinuados,
        )
        plan = build_sku_saneamento_plan(**docs)
        plan["mode"] = "apply" if args.apply else "dry-run"
        plan["database"] = db_name

        if args.apply:
            plan["apply_result"] = await apply_saneamento_plan(db, plan)

        if args.report:
            _write_report(args.report, plan)

        print(json.dumps({"mode": plan["mode"], **plan["summary"], "report": args.report or None}, ensure_ascii=False))
        if args.apply and plan.get("apply_result", {}).get("errors"):
            return 2
        return 0
    finally:
        client.close()


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
