import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import estoque_routes
import expedicao_routes
import faturamento_routes
import orders_routes
import pcp_routes
import recebimento_routes
import retrabalho_routes


def _request(method="POST", path="/api/test"):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def _auth(role):
    async def current_user(_request):
        return {"id": "u1", "tenant_id": "t1", "name": role, "role": role}
    return current_user


@pytest.mark.parametrize(
    "module,dependency,auth_attr,allowed_role",
    [
        (recebimento_routes, recebimento_routes._enforce_recebimento_write_rbac, "get_current_user", "logistica"),
        (estoque_routes, estoque_routes._enforce_estoque_write_rbac, "_get_current_user", "estoque"),
        (expedicao_routes, expedicao_routes._enforce_expedicao_write_rbac, "get_current_user", "logistica"),
        (faturamento_routes, faturamento_routes._enforce_faturamento_write_rbac, "get_current_user", "faturamento"),
        (retrabalho_routes, retrabalho_routes._enforce_retrabalho_write_rbac, "get_current_user", "producao"),
        (pcp_routes, pcp_routes._enforce_pcp_write_rbac, "get_current_user", "pcp"),
        (orders_routes, orders_routes._enforce_ops_write_rbac, "get_current_user", "producao"),
    ],
)
def test_operational_mutations_allow_sector_role_and_deny_sales(module, dependency, auth_attr, allowed_role, monkeypatch):
    monkeypatch.setattr(module, auth_attr, _auth(allowed_role))
    asyncio.run(dependency(_request()))

    monkeypatch.setattr(module, auth_attr, _auth("vendedor"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(_request()))
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "module,dependency,auth_attr",
    [
        (recebimento_routes, recebimento_routes._enforce_recebimento_write_rbac, "get_current_user"),
        (estoque_routes, estoque_routes._enforce_estoque_write_rbac, "_get_current_user"),
        (expedicao_routes, expedicao_routes._enforce_expedicao_write_rbac, "get_current_user"),
        (faturamento_routes, faturamento_routes._enforce_faturamento_write_rbac, "get_current_user"),
        (retrabalho_routes, retrabalho_routes._enforce_retrabalho_write_rbac, "get_current_user"),
        (pcp_routes, pcp_routes._enforce_pcp_write_rbac, "get_current_user"),
        (orders_routes, orders_routes._enforce_ops_write_rbac, "get_current_user"),
    ],
)
def test_operational_rbac_dependency_does_not_reauthenticate_safe_reads(module, dependency, auth_attr, monkeypatch):
    async def fail_if_called(_request):
        raise AssertionError("GET nao deve executar a verificacao adicional de escrita")

    monkeypatch.setattr(module, auth_attr, fail_if_called)
    asyncio.run(dependency(_request(method="GET")))


def test_pcp_timeline_accepts_production_but_planning_does_not(monkeypatch):
    monkeypatch.setattr(pcp_routes, "get_current_user", _auth("producao"))
    asyncio.run(pcp_routes._enforce_pcp_write_rbac(
        _request(path="/api/pcp/ops/op-1/timeline-events")
    ))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pcp_routes._enforce_pcp_write_rbac(
            _request(path="/api/pcp/programacao")
        ))
    assert exc.value.status_code == 403
