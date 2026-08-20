"""
Backend tests for P&D Module improvements - Iteration 6
Tests: Fornecedor field, RN-PD-02, Ficha Técnica UI endpoints
Auth: Cookie-based (HttpOnly)
"""
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)

def make_session(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return s
    return None

@pytest.fixture(scope="module")
def sess():
    """Formulador session (cookie-based)"""
    s = make_session("formulador@kuryos.com", "kuryos123")
    assert s, "Login failed for formulador@kuryos.com with kuryos123"
    return s

@pytest.fixture(scope="module")
def pd_request_id(sess):
    r = sess.get(f"{BASE_URL}/api/pd/requests")
    assert r.status_code == 200
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", items.get("results", []))
    if items:
        return items[0]["id"]
    r2 = sess.post(f"{BASE_URL}/api/pd/requests", json={
        "product_type": "Cosmetico",
        "project_name": "TEST_PD_Iter6",
        "priority": "Normal",
        "client_name": "TEST Cliente",
    })
    assert r2.status_code in (200, 201), f"Failed to create PD request: {r2.text}"
    return r2.json()["id"]

@pytest.fixture(scope="module")
def in_progress_pd_id(sess):
    r = sess.get(f"{BASE_URL}/api/pd/requests")
    assert r.status_code == 200
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", items.get("results", []))
    for it in items:
        if it.get("status") == "IN_PROGRESS":
            return it["id"]
    if items:
        req_id = items[0]["id"]
        if items[0]["status"] == "NEW":
            sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_PROGRESS"})
            return req_id
    pytest.skip("No IN_PROGRESS PD card available")


# ---- Tests ----

class TestAuth:
    def test_login_formulador(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "formulador@kuryos.com", "password": "kuryos123"})
        assert r.status_code == 200, f"Login failed: {r.text}"
        assert r.json().get("email") == "formulador@kuryos.com"

    def test_login_admin(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@kuryos.com", "password": "admin123"})
        assert r.status_code == 200

    def test_formulador_wrong_password(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "formulador@kuryos.com", "password": "admin123"})
        assert r.status_code == 401


class TestPDRequests:
    def test_list_pd_requests(self, sess):
        r = sess.get(f"{BASE_URL}/api/pd/requests")
        assert r.status_code == 200

    def test_pd_request_detail(self, sess, pd_request_id):
        r = sess.get(f"{BASE_URL}/api/pd/requests/{pd_request_id}/full")
        assert r.status_code == 200
        data = r.json()
        assert "request" in data
        assert "formulas" in data


class TestFormulaItemFornecedor:
    def test_add_formula_item_with_fornecedor(self, sess, in_progress_pd_id):
        r_detail = sess.get(f"{BASE_URL}/api/pd/requests/{in_progress_pd_id}/full")
        data = r_detail.json()
        dev = data.get("development")

        if not dev:
            r_dev = sess.post(f"{BASE_URL}/api/pd/developments",
                              json={"pd_request_id": in_progress_pd_id, "developer_name": "Test Dev"})
            if r_dev.status_code not in (200, 201):
                pytest.skip(f"Could not create development: {r_dev.text}")
            dev = r_dev.json()

        dev_id = dev["id"]
        formulas = data.get("formulas", [])
        if not formulas:
            r_f = sess.post(f"{BASE_URL}/api/pd/developments/{dev_id}/formulas",
                            json={"name": "TEST Formula Iter6", "volume": 1000, "volume_unit": "mL"})
            if r_f.status_code not in (200, 201):
                pytest.skip(f"Could not create formula: {r_f.text}")
            formula_id = r_f.json()["id"]
        else:
            formula_id = formulas[0]["id"]

        r_item = sess.post(f"{BASE_URL}/api/pd/formulas/{formula_id}/items",
                           json={
                               "ingredient_name": "TEST_Agua Deionizada",
                               "percentage": 70.0,
                               "price_per_kg": 0.5,
                               "fornecedor": "TEST_Fornecedor ABC"
                           })
        assert r_item.status_code in (200, 201), f"Failed to add item: {r_item.text}"
        item_data = r_item.json()
        assert item_data.get("fornecedor") == "TEST_Fornecedor ABC", f"Fornecedor not saved: {item_data}"

        # Verify persistence via GET
        r_items = sess.get(f"{BASE_URL}/api/pd/formulas/{formula_id}/items")
        assert r_items.status_code == 200
        items_list = r_items.json()
        found = next((it for it in items_list if it.get("ingredient_name") == "TEST_Agua Deionizada"), None)
        assert found is not None, "Item not found after creation"
        assert found.get("fornecedor") == "TEST_Fornecedor ABC", f"Fornecedor not persisted: {found}"
        print(f"Fornecedor field saved and persisted correctly: {found.get('fornecedor')}")


class TestRNPD02Block:
    def test_block_in_tests_no_formula(self, sess):
        """Create a new card, advance to IN_PROGRESS, then try IN_TESTS without formula"""
        r_create = sess.post(f"{BASE_URL}/api/pd/requests", json={
            "product_type": "Cosmetico",
            "project_name": "TEST_RN_PD_02_Block",
            "priority": "Normal",
            "client_name": "TEST",
        })
        if r_create.status_code not in (200, 201):
            pytest.skip(f"Could not create PD request: {r_create.text}")

        req_id = r_create.json()["id"]
        r_adv = sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_PROGRESS"})
        if r_adv.status_code != 200:
            pytest.skip(f"Could not advance to IN_PROGRESS: {r_adv.text}")

        r_block = sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_TESTS"})
        assert r_block.status_code == 400, f"Expected 400 (RN-PD-02) but got {r_block.status_code}: {r_block.text}"
        detail = r_block.json().get("detail", "")
        assert "RN-PD-02" in detail or "formula" in detail.lower() or "fórmula" in detail.lower(), \
            f"RN-PD-02 message not found in: {detail}"
        print(f"RN-PD-02 block confirmed: {detail}")

    def test_block_in_tests_formula_without_items(self, sess):
        """Formula exists but no items"""
        r_create = sess.post(f"{BASE_URL}/api/pd/requests", json={
            "product_type": "Cosmetico",
            "project_name": "TEST_RN_PD_02_NoItems",
            "priority": "Normal",
            "client_name": "TEST",
        })
        if r_create.status_code not in (200, 201):
            pytest.skip("Could not create request")
        req_id = r_create.json()["id"]

        # Advance to IN_PROGRESS - this auto-creates a development
        r_adv = sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_PROGRESS"})
        if r_adv.status_code != 200:
            pytest.skip(f"Could not advance to IN_PROGRESS: {r_adv.text}")

        # Get auto-created development
        full = sess.get(f"{BASE_URL}/api/pd/requests/{req_id}/full").json()
        dev = full.get("development")
        if not dev:
            pytest.skip("Development not auto-created")
        dev_id = dev["id"]

        r_f = sess.post(f"{BASE_URL}/api/pd/developments/{dev_id}/formulas",
                        json={"name": "TEST Empty Formula", "volume": 100, "volume_unit": "mL"})
        if r_f.status_code not in (200, 201):
            pytest.skip(f"Could not create formula: {r_f.text}")

        r_block = sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_TESTS"})
        assert r_block.status_code == 400, f"Expected 400 but got {r_block.status_code}: {r_block.text}"
        detail = r_block.json().get("detail", "")
        assert "RN-PD-02" in detail or "ingrediente" in detail.lower(), \
            f"Expected RN-PD-02 block, got: {detail}"
        print(f"RN-PD-02 (no items) block confirmed: {detail}")

    def test_block_total_pct_not_100(self, sess):
        """Formula with items but total != 100%"""
        r_create = sess.post(f"{BASE_URL}/api/pd/requests", json={
            "product_type": "Cosmetico",
            "project_name": "TEST_RN_PD_02_BadPct",
            "priority": "Normal",
            "client_name": "TEST",
        })
        if r_create.status_code not in (200, 201):
            pytest.skip("Could not create request")
        req_id = r_create.json()["id"]

        r_adv = sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_PROGRESS"})
        if r_adv.status_code != 200:
            pytest.skip(f"Could not advance: {r_adv.text}")

        full = sess.get(f"{BASE_URL}/api/pd/requests/{req_id}/full").json()
        dev = full.get("development")
        if not dev:
            pytest.skip("Development not auto-created")
        dev_id = dev["id"]

        r_f = sess.post(f"{BASE_URL}/api/pd/developments/{dev_id}/formulas",
                        json={"name": "TEST BadPct Formula", "volume": 100, "volume_unit": "mL"})
        if r_f.status_code not in (200, 201):
            pytest.skip(f"No formula: {r_f.text}")
        formula_id = r_f.json()["id"]

        # Add only 50%
        sess.post(f"{BASE_URL}/api/pd/formulas/{formula_id}/items",
                  json={"ingredient_name": "TEST_Half", "percentage": 50.0, "price_per_kg": 1.0})

        r_block = sess.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_TESTS"})
        assert r_block.status_code == 400, f"Expected 400 (total != 100%) but got {r_block.status_code}: {r_block.text}"
        detail = r_block.json().get("detail", "")
        assert "100" in detail or "RN-PD-02" in detail, f"Expected 100% or RN-PD-02, got: {detail}"
        print(f"RN-PD-02 (total != 100%) block confirmed: {detail}")


class TestFichaTecnicaUI:
    def test_get_ficha_tecnica_ui(self, sess, pd_request_id):
        r = sess.get(f"{BASE_URL}/api/pd/requests/{pd_request_id}/ficha-tecnica-ui")
        assert r.status_code == 200
        data = r.json()
        assert "request" in data
        assert "analise" in data
        assert "formula_items" in data
        print(f"GET ficha-tecnica-ui OK")

    def test_put_ficha_tecnica_ui(self, sess, pd_request_id):
        payload = {
            "produto": "TEST Produto Cosmetico",
            "lote": "L2025-001",
            "data_fabricacao": "2025-01-01",
            "validade": "2027-01-01",
            "quantidade": "1000 unidades",
            "aspecto": {"especificacao": "Liquido transparente", "resultado": "Conforme", "pa": "Conforme"},
            "cor": {"especificacao": "Incolor", "resultado": "Incolor", "pa": "Conforme"},
            "densidade": {"especificacao": "0.98-1.02", "resultado": "1.00", "pa": "Conforme"},
            "odor": {"especificacao": "Caracteristico", "resultado": "Caracteristico", "pa": "Conforme"},
            "ph": {"especificacao": "5.5-7.0", "resultado": "6.0", "pa": "Conforme"},
            "teor_alcool": {"especificacao": "N/A", "resultado": "N/A", "pa": "Conforme"},
            "elaboracao": "TEST Descricao da elaboracao",
            "resp_tecnico": "Dr. TEST Silva",
            "status_aprovacao": "aprovado"
        }
        r = sess.put(f"{BASE_URL}/api/pd/requests/{pd_request_id}/ficha-tecnica-ui", json=payload)
        assert r.status_code == 200, f"PUT failed: {r.text}"
        data = r.json()
        assert data.get("produto") == "TEST Produto Cosmetico"
        assert data.get("resp_tecnico") == "Dr. TEST Silva"
        assert data.get("status_aprovacao") == "aprovado"
        assert data.get("ph", {}).get("resultado") == "6.0"
        print(f"PUT ficha-tecnica-ui saved OK")

    def test_ficha_tecnica_persistence(self, sess, pd_request_id):
        r = sess.get(f"{BASE_URL}/api/pd/requests/{pd_request_id}/ficha-tecnica-ui")
        assert r.status_code == 200
        analise = r.json().get("analise", {})
        assert analise.get("produto") == "TEST Produto Cosmetico", f"Not persisted: {analise}"
        assert analise.get("resp_tecnico") == "Dr. TEST Silva"
        print("Ficha Tecnica data persisted correctly")

    def test_ficha_tecnica_put_empty_fails(self, sess, pd_request_id):
        r = sess.put(f"{BASE_URL}/api/pd/requests/{pd_request_id}/ficha-tecnica-ui", json={})
        assert r.status_code == 400, f"Expected 400 but got {r.status_code}: {r.text}"
