"""
RBAC - Role Based Access Control for Kuryos ERP
================================================

Defines the user profiles per Section 10 of PRD and provides
helpers to enforce role restrictions on routes.
"""

from typing import Iterable, Set
from fastapi import HTTPException

# All canonical roles supported by the system.
ROLES = {
    "admin",                # Total access.
    "vendedor",             # Comercial: pipeline clientes/projetos/amostras (read+write); sem P&D.
    "sales_ops",            # Comercial: total CRM, KPIs, configuracao; sem formulas.
    "formulador",           # P&D: pipeline P&D, banco de formulas, estoque lab, estabilidades.
    "qa",                   # CQ: aprovacoes P&D, FT, EPA. Nao cria formulas.
    "lider_pd",             # Lider P&D: total P&D + dashboards de equipe.
    "engenharia_produto",   # Operacional: kickoff, BOM/embalagem, EPA.
    "sucesso_cliente",      # Pos-venda: clientes fechados, recompra/cross-sell.
    "compras",              # Compras: recebe custos v1 do P&D, define custos finais (v2).
}

# Legacy role aliases -> canonical roles (for backwards compatibility)
LEGACY_ALIASES = {
    "gestor": "lider_pd",
}

# Profile capability matrix (allowed_role_set per scope).
COMERCIAL_FULL = {"admin", "vendedor", "sales_ops", "sucesso_cliente"}
COMERCIAL_LEAD = {"admin", "sales_ops", "sucesso_cliente"}
PD_FULL = {"admin", "lider_pd", "formulador", "qa", "engenharia_produto"}
PD_WRITE = {"admin", "lider_pd", "formulador"}
PD_READ = PD_FULL | {"sales_ops", "compras"}   # compras pode visualizar solicitacoes P&D
QA_APPROVERS = {"admin", "qa", "lider_pd"}
ENG_PRODUTO = {"admin", "engenharia_produto", "lider_pd"}
HOMOLOGACAO_WRITE = {"admin", "lider_pd", "qa", "formulador"}
HOMOLOGACAO_APPROVE = {"admin", "lider_pd", "qa"}
DOC_REVIEWERS = {"admin", "lider_pd", "qa", "engenharia_produto", "formulador"}
ADMIN_ONLY = {"admin"}
COMPRAS_FULL = {"admin", "compras"}             # acesso total ao modulo de custos comerciais


def normalize_role(role: str) -> str:
    if not role:
        return ""
    role = role.strip().lower()
    return LEGACY_ALIASES.get(role, role)


def has_role(user: dict, allowed: Iterable[str]) -> bool:
    """Return True if the user's normalized role is in the allowed set."""
    if not user:
        return False
    role = normalize_role(user.get("role", ""))
    if role == "admin":
        return True
    return role in {normalize_role(r) for r in allowed}


def require_roles(user: dict, allowed: Iterable[str]):
    """Raise 403 when the user role is outside the allowed set. Admin always passes."""
    if has_role(user, allowed):
        return
    raise HTTPException(
        status_code=403,
        detail="Sua funcao nao tem permissao para esta acao.",
    )


def can_view_formula_composition(user: dict) -> bool:
    """CRM-only profiles see Banco de Formulas in aggregate but never composition."""
    return has_role(user, PD_READ | DOC_REVIEWERS)


def can_view_live_document_revisions(user: dict) -> bool:
    """Roles allowed to see versions in 'em_revisao' (production line is restricted)."""
    return has_role(user, DOC_REVIEWERS)


def can_view_commercial_costs(user: dict) -> bool:
    """Commercial and compras roles see the full commercial cost breakdown (v2).
    P&D roles see only the final total, never the line-item detail."""
    return has_role(user, COMPRAS_FULL | COMERCIAL_FULL)
