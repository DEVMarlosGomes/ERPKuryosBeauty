import asyncio
import os
import sys
from types import SimpleNamespace
from itertools import count

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

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    self._set_path(doc, key, value)
                for key, value in update.get("$push", {}).items():
                    current = self._get_path(doc, key) or []
                    if isinstance(value, dict) and "$each" in value:
                        current.extend(value["$each"])
                    else:
                        current.append(value)
                    self._set_path(doc, key, current)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def _matches(self, doc, query):
        for key, value in query.items():
            current = self._get_path(doc, key)
            if isinstance(value, dict):
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$nin" in value and current in value["$nin"]:
                    return False
                if "$gte" in value and current < value["$gte"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    def _get_path(self, doc, key):
        current = doc
        for part in str(key).split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _set_path(self, doc, key, value):
        current = doc
        parts = str(key).split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value


class FakeUploadFile:
    def __init__(self, filename, data=b"conteudo", content_type="application/pdf"):
        self.filename = filename
        self._data = data
        self.content_type = content_type

    async def read(self):
        return self._data


async def _current_user(_request):
    return {"id": "user-1", "tenant_id": "tenant-1", "role": "admin", "name": "Admin"}


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


def test_cadastro_pendente_items_flags_manual_products_only():
    pending = orders_routes._cadastro_pendente_items([
        {"item": "Produto Manual", "codigo_kuryos": "A definir"},
        {"item": "Produto Sem Codigo", "codigo_kuryos": ""},
        {"item": "Produto Cadastrado", "codigo_kuryos": "BSP-MISS-0001", "sku_id": "sku-1"},
    ])

    assert [item["item"] for item in pending] == ["Produto Manual", "Produto Sem Codigo"]
    assert all(item["motivo"] == "Produto sem SKU cadastrado no pedido gerado" for item in pending)


def test_safe_attachment_filename_blocks_path_traversal():
    filename = orders_routes._safe_attachment_filename("../Pedido Cliente 01.pdf")

    assert filename == "Pedido Cliente 01.pdf"


def test_upload_order_attachment_writes_unified_metadata_with_object_storage():
    stored = {}

    def fake_put(path, data, content_type):
        stored["path"] = path
        stored["data"] = data
        stored["content_type"] = content_type
        return {"path": path, "size": len(data)}

    seq = count(1)
    orders_routes.db = SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {orders_routes.UNIFIED_ATTACHMENTS_FLAG: True},
        }]),
        orders=FakeCollection([{"id": "order-1", "tenant_id": "tenant-1", "attachments": []}]),
        attachments=FakeCollection([]),
        files=FakeCollection([]),
    )
    orders_routes.get_current_user = _current_user
    orders_routes.new_id_func = lambda: f"id-{next(seq)}"
    orders_routes.now_iso_func = lambda: "2026-09-12T10:00:00-03:00"
    orders_routes.put_object_func = fake_put

    attachment = asyncio.run(orders_routes.upload_order_attachment(
        "order-1",
        SimpleNamespace(),
        FakeUploadFile("pedido.pdf", b"pdf-data", "application/pdf"),
    ))

    assert attachment["id"] == "id-1"
    assert attachment["storage_backend"] == "object"
    assert attachment["file_id"] == "id-2"
    assert attachment["unified_attachment_v2"] is True
    assert stored["path"].endswith("/tenant-1/order-1/id-1.pdf")
    assert orders_routes.db.orders.docs[0]["attachments"][0]["id"] == "id-1"
    assert orders_routes.db.files.docs[0]["id"] == "id-2"
    assert orders_routes.db.attachments.docs[0]["entity_type"] == "order"
    assert orders_routes.db.attachments.docs[0]["owner_type"] == "order"
    assert orders_routes.db.attachments.docs[0]["owner_id"] == "order-1"
    assert orders_routes.db.attachments.docs[0]["file_id"] == "id-2"


def test_list_order_attachment_metadata_falls_back_to_legacy_order_attachments():
    orders_routes.db = SimpleNamespace(
        tenant_settings=FakeCollection([{
            "tenant_id": "tenant-1",
            "features": {orders_routes.UNIFIED_ATTACHMENTS_FLAG: True},
        }]),
        orders=FakeCollection([{
            "id": "order-1",
            "tenant_id": "tenant-1",
            "attachments": [{
                "id": "att-1",
                "original_filename": "pedido-antigo.pdf",
                "storage_path": "tenant-1/order-1/att-1.pdf",
                "download_url": "/api/orders/order-1/attachments/att-1/download",
            }],
        }]),
        attachments=FakeCollection([]),
    )
    orders_routes.get_current_user = _current_user

    result = asyncio.run(orders_routes.list_order_attachment_metadata("order-1", SimpleNamespace()))

    assert result["source"] == "orders.attachments"
    assert result["count"] == 1
    assert result["attachments"][0]["storage_backend"] == "local"
    assert result["attachments"][0]["owner_type"] == "order"
    assert result["attachments"][0]["owner_id"] == "order-1"
    assert result["attachments"][0]["legacy_attachment_id"] == "att-1"


def test_queue_email_without_smtp_records_pending(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    orders_routes.new_id_func = lambda: "email-1"
    orders_routes.now_iso_func = lambda: "2026-08-19T10:00:00+00:00"
    orders_routes.db = SimpleNamespace(email_logs=FakeCollection())

    log = asyncio.run(orders_routes._queue_email(
        tenant_id="tenant-1",
        to_email="cliente@example.com",
        subject="Pedido",
        body="Resumo",
        source="client_confirmation_request",
        entity_type="order",
        entity_id="order-1",
        user={"id": "user-1", "name": "Admin"},
    ))

    assert log["status"] == "pendente"
    assert orders_routes.db.email_logs.docs[0]["to"] == "cliente@example.com"


def test_generator_order_requires_registered_client_id():
    orders_routes.db = SimpleNamespace()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(orders_routes._create_order_document(
            orders_routes.OrderCreate(
                cliente=orders_routes.ClienteData(nome="Cliente digitado"),
                items=[orders_routes.OrderItem(item="Produto", codigo_kuryos="A definir", qtd=10, valor_unitario=1)],
            ),
            {"id": "user-1", "tenant_id": "tenant-1", "name": "Admin"},
            origem="gerador",
        ))

    assert exc.value.status_code == 422
    assert "cliente cadastrado" in str(exc.value.detail).lower()


def test_generator_order_uses_registered_client_snapshot(monkeypatch):
    ids = count(1)
    orders_routes.new_id_func = lambda: f"id-{next(ids)}"
    orders_routes.now_iso_func = lambda: "2026-08-24T10:00:00+00:00"
    orders_routes.db = SimpleNamespace(
        crm_clients=FakeCollection([{
            "id": "cli-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Oficial",
            "razao_social": "Cliente Oficial LTDA",
            "cnpj": "12.345.678/0001-90",
            "cidade": "Sao Paulo",
            "uf": "SP",
            "responsavel": "Maria",
            "telefone": "11999990000",
            "email": "cliente@example.com",
        }]),
        skus=FakeCollection([]),
        orders=FakeCollection([]),
        email_logs=FakeCollection([]),
    )

    order = asyncio.run(orders_routes._create_order_document(
        orders_routes.OrderCreate(
            cliente_id="cli-1",
            cliente=orders_routes.ClienteData(
                nome="Texto divergente",
                razao_social="Texto divergente",
                cnpj="00.000.000/0000-00",
                email="errado@example.com",
            ),
            items=[orders_routes.OrderItem(item="Produto Manual", codigo_kuryos="A definir", qtd=10, valor_unitario=2)],
        ),
        {"id": "user-1", "tenant_id": "tenant-1", "name": "Admin"},
        origem="gerador",
    ))

    assert order["cliente_id"] == "cli-1"
    assert order["cliente"]["razao_social"] == "Cliente Oficial LTDA"
    assert order["cliente"]["cnpj"] == "12.345.678/0001-90"
    assert order["cliente"]["email"] == "cliente@example.com"
    assert order["cadastro_pendente"] is True
    assert len(orders_routes.db.orders.docs) == 1
    assert len(orders_routes.db.email_logs.docs) == 2


def test_direct_order_preserves_client_sku_and_currency(monkeypatch):
    ids = count(1)
    orders_routes.new_id_func = lambda: f"id-{next(ids)}"
    orders_routes.now_iso_func = lambda: "2026-08-25T21:00:00+00:00"
    orders_routes.db = SimpleNamespace(
        crm_clients=FakeCollection([{
            "id": "cli-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Oficial",
            "razao_social": "Cliente Oficial LTDA",
            "cnpj": "12.345.678/0001-90",
            "cidade": "Sao Paulo",
            "uf": "SP",
            "responsavel": "Maria",
            "telefone": "11999990000",
            "email": "cliente@example.com",
        }]),
        skus=FakeCollection([{
            "id": "sku-1",
            "tenant_id": "tenant-1",
            "cliente_id": "cli-1",
            "codigo_interno": "PER-MISS-0001",
            "status": "ativo",
            "nome_produto": "Body Splash Teste",
            "preco_unitario": 7.5,
            "preco_unitario_currency": "USD",
            "amostra_id": "sample-1",
            "amostra_variacao_id": "var-1",
        }]),
        pd_requests=FakeCollection([]),
        orders=FakeCollection([]),
        email_logs=FakeCollection([]),
    )

    async def fake_get_current_user(_request):
        return {"id": "user-1", "tenant_id": "tenant-1", "name": "Admin"}

    monkeypatch.setattr(orders_routes, "get_current_user", fake_get_current_user)

    order = asyncio.run(
        orders_routes.create_direct_order(
            orders_routes.DirectOrderCreate(
                cliente_id="cli-1",
                sku_id="sku-1",
                qtd=12,
                prazo_entrega="15 dias",
            ),
            SimpleNamespace(),
        )
    )

    assert order["origem"] == "direto"
    assert order["cliente_id"] == "cli-1"
    assert order["cliente"]["razao_social"] == "Cliente Oficial LTDA"
    assert order["items"][0]["sku_id"] == "sku-1"
    assert order["items"][0]["sku_cliente_id"] == "cli-1"
    assert order["items"][0]["codigo_kuryos"] == "PER-MISS-0001"
    assert order["items"][0]["valor_unitario"] == 7.5
    assert order["items"][0]["valor_unitario_currency"] == "USD"
    assert order["items"][0]["qtd"] == 12
    assert order["total_pedido"] == 90.0
    assert orders_routes.db.orders.docs[0]["items"][0]["valor_unitario_currency"] == "USD"


def test_direct_order_rejects_sku_from_another_client(monkeypatch):
    orders_routes.db = SimpleNamespace(
        crm_clients=FakeCollection([{
            "id": "cli-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Oficial",
        }]),
        skus=FakeCollection([{
            "id": "sku-1",
            "tenant_id": "tenant-1",
            "cliente_id": "cli-2",
            "codigo_interno": "PER-OUTR-0001",
            "status": "ativo",
            "preco_unitario": 7.5,
            "preco_unitario_currency": "USD",
        }]),
        orders=FakeCollection([]),
    )

    async def fake_get_current_user(_request):
        return {"id": "user-1", "tenant_id": "tenant-1", "name": "Admin"}

    monkeypatch.setattr(orders_routes, "get_current_user", fake_get_current_user)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            orders_routes.create_direct_order(
                orders_routes.DirectOrderCreate(cliente_id="cli-1", sku_id="sku-1", qtd=1),
                SimpleNamespace(),
            )
        )

    assert exc.value.status_code == 400
    assert "não pertence" in str(exc.value.detail).lower() or "nao pertence" in str(exc.value.detail).lower()
    assert orders_routes.db.orders.docs == []
