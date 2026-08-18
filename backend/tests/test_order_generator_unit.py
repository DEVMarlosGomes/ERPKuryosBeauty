import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import orders_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, key, direction):
        reverse = direction < 0
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=reverse)
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    def _matches(self, doc, query):
        for key, value in query.items():
            current = doc.get(key)
            if isinstance(value, dict):
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$nin" in value and current in value["$nin"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


def test_order_duplicate_fingerprint_is_stable_for_same_items_in_any_order():
    cliente = {"cnpj": "12.345.678/0001-90", "nome": "Cliente Teste"}
    items_a = [
        {"codigo_kuryos": "SKU-2", "item": "B", "qtd": 2, "valor_unitario": 10},
        {"codigo_kuryos": "SKU-1", "item": "A", "qtd": 1, "valor_unitario": 20},
    ]
    items_b = list(reversed(items_a))

    first = orders_routes._order_duplicate_fingerprint(cliente, items_a, "2026-08-17", "PC-123")
    second = orders_routes._order_duplicate_fingerprint(cliente, items_b, "2026-08-17", "PC-123")

    assert first == second


def test_enrich_items_from_skus_links_approved_pd_request():
    orders_routes.db = SimpleNamespace(
        skus=FakeCollection([
            {
                "id": "sku-1",
                "tenant_id": "tenant-1",
                "codigo_interno": "SKU-001",
                "status": "ativo",
                "nome_produto": "Body Splash Teste",
                "preco_unitario": 12.5,
                "preco_unitario_currency": "BRL",
                "amostra_id": "sample-1",
                "amostra_variacao_id": "var-1",
                "cliente_id": "cli-1",
            }
        ]),
        pd_requests=FakeCollection([
            {
                "id": "pd-1",
                "tenant_id": "tenant-1",
                "status": "APPROVED",
                "linked_amostra_id": "sample-1",
                "linked_variacao_id": "var-1",
                "updated_at": "2026-08-17T10:00:00+00:00",
            }
        ]),
    )

    enriched = asyncio.run(orders_routes._enrich_items_from_skus(
        [{"codigo_kuryos": "SKU-001", "item": "", "qtd": 10, "valor_unitario": 0}],
        "tenant-1",
        require_known_sku=True,
    ))

    assert enriched[0]["sku_id"] == "sku-1"
    assert enriched[0]["pd_request_id"] == "pd-1"
    assert enriched[0]["pd_concluido"] is True
    assert enriched[0]["item"] == "Body Splash Teste"
    assert enriched[0]["valor_unitario"] == 12.5


def test_enrich_items_from_skus_can_require_completed_pd():
    orders_routes.db = SimpleNamespace(
        skus=FakeCollection([
            {
                "id": "sku-1",
                "tenant_id": "tenant-1",
                "codigo_interno": "SKU-001",
                "status": "ativo",
                "amostra_id": "sample-1",
                "amostra_variacao_id": "var-1",
            }
        ]),
        pd_requests=FakeCollection([]),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orders_routes._enrich_items_from_skus(
            [{"codigo_kuryos": "SKU-001", "item": "Produto", "qtd": 10}],
            "tenant-1",
            require_known_sku=True,
            require_pd_completed=True,
        ))

    assert exc.value.status_code == 422


def test_order_generator_status_tracks_attachment_pdf_and_approvals():
    status = orders_routes._order_generator_status({
        "id": "order-1",
        "numero_pedido": "08_01",
        "status": "rascunho",
        "origem": "gerador",
        "cliente": {"razao_social": "Cliente Teste"},
        "attachments": [{"id": "att-1", "original_filename": "pedido.pdf"}],
        "pdf": {"generated_at": "2026-08-17T10:00:00+00:00", "filename": "ordem.pdf"},
        "aprovacao_cliente": "pendente",
        "aprovacao_comercial": "nao_necessaria",
        "op_id": None,
    })

    assert status["completed_steps"] == 3
    assert status["progress_pct"] == 60.0
    assert status["pending"] == ["aprovacao_cliente", "op"]


def test_safe_attachment_filename_blocks_path_traversal():
    filename = orders_routes._safe_attachment_filename("../Pedido Cliente 01.pdf")

    assert filename == "Pedido Cliente 01.pdf"
