import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import faturamento_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return {key: value for key, value in doc.items() if key != "_id"}
        return None

    async def update_one(self, query, update):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


async def fake_user(_request):
    return {"id": "u1", "tenant_id": "t1", "name": "Fiscal", "role": "faturamento"}


def setup_function():
    faturamento_routes.get_current_user = fake_user
    faturamento_routes.now_iso_func = lambda: "2026-09-23T10:00:00-03:00"


def test_update_manual_cannot_mark_invoice_as_issued():
    faturamento_routes.db = SimpleNamespace(faturamento_notas=FakeCollection([{
        "id": "nf-1", "tenant_id": "t1", "status": "rascunho", "historico": [],
    }]))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(faturamento_routes.update_nota(
            "nf-1", faturamento_routes.NFUpdate(status="emitida", numero_nfe="123"), SimpleNamespace()
        ))

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "status_fiscal_controlado_pelo_provedor"
    assert faturamento_routes.db.faturamento_notas.docs[0]["status"] == "rascunho"


def test_authorized_provider_response_is_the_only_path_that_sets_fiscal_keys():
    nf = {"id": "nf-1", "tenant_id": "t1", "status": "processando", "historico": []}
    faturamento_routes.db = SimpleNamespace(faturamento_notas=FakeCollection([nf]))

    updated = asyncio.run(faturamento_routes._persist_focus_result(
        nf,
        {"status": "autorizado", "numero": "456", "chave_nfe": "3" * 44, "protocolo": "135"},
        {"id": "u1", "tenant_id": "t1", "name": "Fiscal"},
        "homologacao",
    ))

    assert updated["status"] == "emitida"
    assert updated["fiscal_status"] == "autorizada"
    assert updated["numero_nfe"] == "456"
    assert updated["chave_acesso"] == "3" * 44
    assert updated["fiscal_provider"] == "focus_nfe"


def test_missing_provider_token_keeps_emission_blocked(monkeypatch):
    monkeypatch.delenv("FOCUS_NFE_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        faturamento_routes._focus_config()
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "provedor_fiscal_nao_configurado"
