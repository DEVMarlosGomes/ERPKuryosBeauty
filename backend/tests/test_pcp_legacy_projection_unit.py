from types import SimpleNamespace

import pytest

import pcp_routes


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, limit):
        return self.documents[:limit]


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    @staticmethod
    def _matches(document, query):
        for key, expected in query.items():
            value = document.get(key)
            if isinstance(expected, dict):
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$lte" in expected and value > expected["$lte"]:
                    return False
            elif value != expected:
                return False
        return True

    async def find_one(self, query, _projection=None):
        return next((doc for doc in self.documents if self._matches(doc, query)), None)

    def find(self, query, _projection=None):
        return FakeCursor([doc for doc in self.documents if self._matches(doc, query)])

    async def distinct(self, key, query):
        return list({doc.get(key) for doc in self.documents if self._matches(doc, query)})


class FakeDatabase:
    def __init__(self, **collections):
        self.collections = collections

    def __getitem__(self, name):
        return self.collections[name]

    def __getattr__(self, name):
        return self.collections[name]


@pytest.mark.asyncio
async def test_legacy_pcp_projection_is_read_only_and_uses_dashboard_shapes(monkeypatch):
    source = FakeCollection([
        {
            "tenant_id": "tenant-1",
            "source_node": "registros",
            "source_key": "2026-09-21",
            "source_payload": {
                "r1": {
                    "hora": "11:00",
                    "linha": "Linha 1",
                    "produto": "Produto A",
                    "quantidade": 1304,
                    "pedidoId": "0023",
                },
            },
        },
        {
            "tenant_id": "tenant-1",
            "source_node": "estado_linhas",
            "source_key": "Linha_1",
            "source_payload": {"status": "active", "produto": "Produto A", "opAtual": "OP1"},
        },
    ])
    supplemental = FakeCollection([
        {
            "tenant_id": "tenant-1",
            "source_node": "programacao",
            "source_key": "2026-09-21",
            "source_payload": {
                "07_00": {
                    "env1": {"produto": "Produto A", "sku": "A1", "pedidoKey": "P1", "mediaPorHora": 600},
                },
            },
        },
        {
            "tenant_id": "tenant-1",
            "source_node": "turnosEncerrados",
            "source_key": "2026-09-21",
            "source_payload": {"Padrao": {"itens": 1}},
        },
    ])
    production_orders = FakeCollection([
        {
            "tenant_id": "tenant-1",
            "record_type": "production_order",
            "id": "review-1",
            "source_key": "OP1",
            "source_payload": {
                "status": "Em Producao",
                "produto": "Produto A",
                "qtdPlanejada": 2000,
                "produzido": 100,
            },
        },
        {
            "tenant_id": "tenant-1",
            "record_type": "production_order",
            "id": "review-2",
            "source_key": "OP2",
            "source_payload": {"status": "Concluido", "produto": "Produto B"},
        },
    ])
    monkeypatch.setattr(
        pcp_routes,
        "db",
        FakeDatabase(
            legacy_source_archive_reviews=source,
            legacy_supplemental_history_reviews=supplemental,
            legacy_op_reviews=production_orders,
        ),
    )

    async def current_user(_request):
        return {"tenant_id": "tenant-1"}

    monkeypatch.setattr(pcp_routes, "get_current_user", current_user)

    dashboard = await pcp_routes.pcp_legacy_dashboard_view(SimpleNamespace(), "2026-09-21")
    active_ops = await pcp_routes.pcp_legacy_active_ops(SimpleNamespace())

    assert dashboard["operational_records_created"] is False
    assert dashboard["history"]["kpis"]["total_produzido"] == 1304
    assert dashboard["schedule_slots"][0]["qtd_planejada"] == 600
    assert dashboard["line_state_slots"][0]["legacy_read_only"] is True
    assert active_ops["operational_records_created"] is False
    assert active_ops["total"] == 1
    assert active_ops["rows"][0]["legacy_read_only"] is True
