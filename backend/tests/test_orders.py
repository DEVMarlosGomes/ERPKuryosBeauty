"""
Backend tests for Orders (Pedidos) module.
Covers CRUD, PDF generation, RBAC, and PD->Order auto-creation idempotency.
Auth: cookie-based session (POST /api/auth/login sets cookies).
"""
import pytest
import requests
import uuid
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)

PD_TEST_ID = "c04daf64-da3a-4e86-b6d9-04e917209adc"


def _orders_for_pd_request(session, pd_request_id):
    r = session.get(f"{BASE_URL}/api/orders", timeout=15)
    assert r.status_code == 200
    return [o for o in r.json() if o.get("pd_request_id") == pd_request_id]


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="session")
def admin():
    return _login("admin@kuryos.com", "admin123")


@pytest.fixture(scope="session")
def vendedor():
    return _login("vendedor@kuryos.com", "kuryos123")


@pytest.fixture(scope="session")
def formulador():
    return _login("formulador@kuryos.com", "kuryos123")


# ===== List & RBAC =====
class TestListOrdersRBAC:
    def test_admin_can_list(self, admin):
        r = admin.get(f"{BASE_URL}/api/orders", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_vendedor_can_list(self, vendedor):
        r = vendedor.get(f"{BASE_URL}/api/orders", timeout=15)
        assert r.status_code == 200

    def test_formulador_can_list(self, formulador):
        r = formulador.get(f"{BASE_URL}/api/orders", timeout=15)
        assert r.status_code == 200

    def test_unauthenticated_blocked(self):
        r = requests.get(f"{BASE_URL}/api/orders", timeout=15)
        assert r.status_code in (401, 403)


# ===== Auto-create from PD APPROVED =====
class TestAutoCreatedOrder:
    def test_auto_created_order_exists(self, admin):
        matches = _orders_for_pd_request(admin, PD_TEST_ID)
        if not matches:
            pytest.skip(f"historical PD fixture not present in this database: {PD_TEST_ID}")
        assert len(matches) >= 1, f"Expected auto-created order for PD {PD_TEST_ID}"
        order = matches[0]
        assert order.get("client_card_id"), "client_card_id should be populated"
        assert order.get("auto_created") is True
        assert order.get("numero_pedido"), "numero_pedido should be set"
        assert len(order.get("items", [])) >= 1
        cliente = order.get("cliente", {})
        assert cliente.get("nome") or cliente.get("razao_social")

    def test_idempotency_no_duplicates(self, admin):
        matches = _orders_for_pd_request(admin, PD_TEST_ID)
        if not matches:
            pytest.skip(f"historical PD fixture not present in this database: {PD_TEST_ID}")
        assert len(matches) == 1, f"Idempotency violated: {len(matches)} orders for PD {PD_TEST_ID}"


# ===== Get single order =====
class TestGetOrder:
    def test_get_existing_order(self, admin):
        r = admin.get(f"{BASE_URL}/api/orders", timeout=15)
        orders = r.json()
        if not orders:
            pytest.skip("No orders to test GET")
        oid = orders[0]["id"]
        r2 = admin.get(f"{BASE_URL}/api/orders/{oid}", timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        assert d["id"] == oid
        for key in ("cliente", "frete", "items", "condicoes", "insumos", "status"):
            assert key in d

    def test_get_nonexistent(self, admin):
        r = admin.get(f"{BASE_URL}/api/orders/does-not-exist-xyz", timeout=15)
        assert r.status_code == 404


# ===== CRUD =====
class TestOrderCRUD:
    created_id = None
    numero_pedido = None

    def test_create_order(self, admin):
        numero_pedido = f"TEST_99_99_{uuid.uuid4().hex[:8]}"
        unique_cnpj_suffix = uuid.uuid4().hex[:12]
        payload = {
            "numero_pedido": numero_pedido,
            "cliente": {
                "nome": f"TEST Client {numero_pedido}",
                "razao_social": f"TEST LTDA {numero_pedido}",
                "cnpj": f"{unique_cnpj_suffix[:2]}.{unique_cnpj_suffix[2:5]}.{unique_cnpj_suffix[5:8]}/{unique_cnpj_suffix[8:12]}-00",
            },
            "items": [
                {"item": "Produto A", "valor_unitario": 10.5, "qtd": 3},
                {"item": "Produto B", "valor_unitario": 20.0, "qtd": 2},
            ],
        }
        r = admin.post(f"{BASE_URL}/api/orders", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cliente"]["nome"] == payload["cliente"]["nome"]
        assert data["total_pedido"] == 71.5
        assert data["status"] == "rascunho"
        assert data["origem"] == "pipeline", "A12: pedidos do fluxo normal devem ter origem=pipeline"
        TestOrderCRUD.created_id = data["id"]
        TestOrderCRUD.numero_pedido = numero_pedido

    def test_get_created(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        r = admin.get(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}", timeout=15)
        assert r.status_code == 200
        assert r.json()["numero_pedido"] == TestOrderCRUD.numero_pedido

    def test_update_status(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        r = admin.put(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}",
                      json={"status": "confirmado"}, timeout=15)
        if r.status_code == 422 and "CGI" in r.text:
            pytest.skip("order confirmation requires signed CGI in this database")
        assert r.status_code == 200
        assert r.json()["status"] == "confirmado"

    def test_update_invalid_status(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        r = admin.put(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}",
                      json={"status": "INVALID_XYZ"}, timeout=15)
        assert r.status_code == 400

    def test_update_items_recalculates_total(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        new_items = [{"item": "X", "valor_unitario": 5.0, "qtd": 4}]
        r = admin.put(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}",
                      json={"items": new_items}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["total_pedido"] == 20.0
        assert len(d["items"]) == 1

    def test_pdf_generation(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        r = admin.get(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}/pdf", timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000

    def test_pdf_for_auto_created(self, admin):
        r = admin.get(f"{BASE_URL}/api/orders", timeout=15)
        orders = r.json()
        matches = [o for o in orders if o.get("pd_request_id") == PD_TEST_ID]
        if not matches:
            pytest.skip("Auto-created order not present")
        oid = matches[0]["id"]
        r2 = admin.get(f"{BASE_URL}/api/orders/{oid}/pdf", timeout=30)
        assert r2.status_code == 200
        assert r2.content[:4] == b"%PDF"

    def test_delete_order(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        r = admin.delete(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}", timeout=15)
        assert r.status_code == 200

    def test_get_after_delete_404(self, admin):
        if not TestOrderCRUD.created_id:
            pytest.skip("Create failed")
        r = admin.get(f"{BASE_URL}/api/orders/{TestOrderCRUD.created_id}", timeout=15)
        assert r.status_code == 404


# ===== Filters / search =====
class TestFilters:
    def test_status_filter(self, admin):
        r = admin.get(f"{BASE_URL}/api/orders?status=rascunho", timeout=15)
        assert r.status_code == 200
        for o in r.json():
            assert o.get("status") == "rascunho"

    def test_search_filter(self, admin):
        r = admin.get(f"{BASE_URL}/api/orders?q=05", timeout=15)
        assert r.status_code == 200


# ===== A12: Pedido Direto (cliente + SKU existentes, sem lead->projeto->amostra) =====
class TestDirectOrder:
    created_id = None

    def test_unknown_cliente_404(self, admin):
        r = admin.post(f"{BASE_URL}/api/orders/direct", json={
            "cliente_id": "does-not-exist-xyz",
            "sku_id": "does-not-exist-xyz",
            "qtd": 10,
        }, timeout=15)
        assert r.status_code == 404

    def test_unknown_sku_404(self, admin):
        r = admin.get(f"{BASE_URL}/api/crm/clients", timeout=15)
        assert r.status_code == 200
        clientes = r.json()
        if not clientes:
            pytest.skip("No client available in this environment")
        r2 = admin.post(f"{BASE_URL}/api/orders/direct", json={
            "cliente_id": clientes[0]["id"],
            "sku_id": "does-not-exist-xyz",
            "qtd": 10,
        }, timeout=15)
        assert r2.status_code == 404

    def test_invalid_qtd_rejected(self, admin):
        r = admin.get(f"{BASE_URL}/api/crm/skus", params={"status": "ativo"}, timeout=15)
        assert r.status_code == 200
        skus = r.json()
        if not skus:
            pytest.skip("No active SKU available in this environment to test the happy path")
        sku = skus[0]
        r2 = admin.post(f"{BASE_URL}/api/orders/direct", json={
            "cliente_id": sku["cliente_id"],
            "sku_id": sku["id"],
            "qtd": 0,
        }, timeout=15)
        assert r2.status_code == 400

    def test_happy_path_creates_order_with_origem_direto(self, admin):
        r = admin.get(f"{BASE_URL}/api/crm/skus", params={"status": "ativo"}, timeout=15)
        skus = [s for s in r.json() if (s.get("preco_unitario") or 0) > 0]
        if not skus:
            pytest.skip("No active SKU with preco_unitario available in this environment")
        sku = skus[0]
        r2 = admin.post(f"{BASE_URL}/api/orders/direct", json={
            "cliente_id": sku["cliente_id"],
            "sku_id": sku["id"],
            "qtd": 5,
            "prazo_entrega": "15 dias",
        }, timeout=15)
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["origem"] == "direto"
        assert data["pd_request_id"] is None
        assert data["client_card_id"] is None
        assert len(data["items"]) == 1
        assert data["items"][0]["codigo_kuryos"] == sku["codigo_interno"]
        assert data["items"][0]["qtd"] == 5
        assert data["status"] == "rascunho"
        TestDirectOrder.created_id = data["id"]

    def test_happy_path_cleanup(self, admin):
        if not TestDirectOrder.created_id:
            pytest.skip("Happy path did not run")
        r = admin.delete(f"{BASE_URL}/api/orders/{TestDirectOrder.created_id}", timeout=15)
        assert r.status_code == 200
