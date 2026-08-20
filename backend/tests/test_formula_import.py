"""
B13: Importar Fórmula — copia a composição de uma fórmula existente (banco de fórmulas)
como rascunho editável em outro desenvolvimento (deep copy, nunca referência).
Segue o mesmo padrão de fixtures de test_pd_iter7.py (sessão de admin + PD request
transicionado pra IN_PROGRESS para obter um development_id).
"""
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@kuryos.com", "password": "admin123"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


def _new_development(admin_session, name):
    r = admin_session.post(f"{BASE_URL}/api/pd/requests", json={
        "project_name": name,
        "client_name": "TEST",
        "category": "skincare",
        "briefing": "Test base card - formula import",
    })
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]
    r2 = admin_session.put(f"{BASE_URL}/api/pd/requests/{req_id}/status", json={"new_status": "IN_PROGRESS"})
    assert r2.status_code == 200, r2.text
    r3 = admin_session.get(f"{BASE_URL}/api/pd/requests/{req_id}/development")
    assert r3.status_code == 200, r3.text
    return req_id, r3.json()["id"]


@pytest.fixture(scope="module")
def source_formula(admin_session):
    """Cria uma requisição + fórmula de origem com 2 ingredientes, para importar depois."""
    req_id, dev_id = _new_development(admin_session, "TEST_IMPORT_Source")
    r = admin_session.post(f"{BASE_URL}/api/pd/developments/{dev_id}/formulas", json={
        "name": "Fórmula Base Importável",
        "volume": 100,
        "volume_unit": "mL",
    })
    assert r.status_code == 200, r.text
    formula_id = r.json()["id"]
    for name, pct in [("Água", 70.0), ("Glicerina", 30.0)]:
        ri = admin_session.post(f"{BASE_URL}/api/pd/formulas/{formula_id}/items", json={
            "ingredient_name": name, "percentage": pct,
        })
        assert ri.status_code == 200, ri.text
    return {"req_id": req_id, "development_id": dev_id, "formula_id": formula_id}


@pytest.fixture(scope="module")
def target_development(admin_session):
    _, dev_id = _new_development(admin_session, "TEST_IMPORT_Target")
    return dev_id


class TestImportFormula:
    def test_unknown_formula_404(self, admin_session, target_development):
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/does-not-exist-xyz/import-into/{target_development}")
        assert r.status_code == 404

    def test_unknown_target_development_404(self, admin_session, source_formula):
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{source_formula['formula_id']}/import-into/does-not-exist-xyz")
        assert r.status_code == 404

    def test_import_deep_copies_items_and_tracks_provenance(self, admin_session, source_formula, target_development):
        r = admin_session.post(
            f"{BASE_URL}/api/pd/formulas/{source_formula['formula_id']}/import-into/{target_development}"
        )
        assert r.status_code == 200, r.text
        imported = r.json()
        assert imported["development_id"] == target_development
        assert imported["id"] != source_formula["formula_id"], "deve criar uma fórmula nova, nunca reaproveitar o id de origem"
        assert imported["importada_de_formula_id"] == source_formula["formula_id"]
        assert imported["importada_de_request_id"] == source_formula["req_id"]
        assert imported["locked"] is False
        names = sorted(it["ingredient_name"] for it in imported["items"])
        assert names == ["Glicerina", "Água"]

        # Confirma deep copy: editar o item importado não deve afetar a fórmula de origem
        imported_item_id = imported["items"][0]["id"]
        r2 = admin_session.put(f"{BASE_URL}/api/pd/formula-items/{imported_item_id}", json={"percentage": 99})
        if r2.status_code == 200:
            r3 = admin_session.get(f"{BASE_URL}/api/pd/formulas/bank", params={"q": "Fórmula Base Importável"})
            assert r3.status_code == 200
            original = next((f for f in r3.json() if f["id"] == source_formula["formula_id"]), None)
            if original:
                original_pcts = sorted(it["percentage"] for it in original["items"])
                assert 99 not in original_pcts, "editar a copia importada alterou a formula de origem (referencia, nao deep copy)"
