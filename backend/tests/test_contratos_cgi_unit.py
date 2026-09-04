import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import contratos_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                for key, value in update.get("$push", {}).items():
                    doc.setdefault(key, []).append(value)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def _matches(self, doc, query):
        return all(doc.get(key) == value for key, value in query.items())

    def _project(self, doc, projection):
        if projection and all(value == 0 for value in projection.values()):
            return {key: value for key, value in doc.items() if key not in projection}
        return dict(doc)


def test_assinar_contrato_transiciona_por_api_oficial(monkeypatch):
    audit_entries = []

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Admin", "tenant_id": "tenant-1", "role": "admin"}

    async def fake_audit_log(**kwargs):
        audit_entries.append(kwargs)

    monkeypatch.setattr(contratos_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(contratos_routes, "now_iso", lambda: "2026-08-25T10:00:00+00:00")
    monkeypatch.setattr(contratos_routes, "audit_log", fake_audit_log)
    contratos_routes.db = SimpleNamespace(
        contratos=FakeCollection([{
            "id": "contrato-1",
            "tenant_id": "tenant-1",
            "status": "gerado",
            "kickoff_id": "kickoff-1",
            "projeto_id": "proj-1",
            "client_id": "cli-1",
            "pdf_data": b"%PDF",
        }])
    )

    result = asyncio.run(contratos_routes.assinar_contrato(
        "contrato-1",
        contratos_routes.ContratoAssinarInput(observacoes="Assinado pelo comercial"),
        SimpleNamespace(),
    ))

    assert result["status"] == "assinado"
    assert result["signed_by"] == "user-1"
    assert result["assinatura"]["assinado_em"] == "2026-08-25T10:00:00+00:00"
    assert result["status_history"][-1]["to"] == "assinado"
    assert "pdf_data" not in result
    assert audit_entries[0]["action"] == "contrato_assinado"
    assert audit_entries[0]["metadata"]["projeto_id"] == "proj-1"
