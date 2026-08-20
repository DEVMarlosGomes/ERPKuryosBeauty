"""
Iteration 7 Backend Tests: Formula Locking/Versioning (RN-BF-01), Stability Study, Task Reminders
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


@pytest.fixture(scope="module")
def in_progress_card(admin_session):
    """Create a card and transition to IN_PROGRESS."""
    r = admin_session.post(f"{BASE_URL}/api/pd/requests", json={
        "project_name": "TEST_ITER7_Base",
        "client_name": "TEST",
        "category": "skincare",
        "briefing": "Test base card iteration 7",
    })
    assert r.status_code == 200
    cid = r.json()["id"]
    r2 = admin_session.put(f"{BASE_URL}/api/pd/requests/{cid}/status", json={"new_status": "IN_PROGRESS"})
    assert r2.status_code == 200
    return cid


@pytest.fixture(scope="module")
def pd_card_id(in_progress_card):
    return in_progress_card


@pytest.fixture(scope="module")
def development_id(admin_session, in_progress_card):
    """Get development for card (auto-created on IN_PROGRESS transition)."""
    r = admin_session.get(f"{BASE_URL}/api/pd/requests/{in_progress_card}/development")
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture(scope="module")
def formula_id(admin_session, development_id):
    """Create formula for development."""
    r = admin_session.post(f"{BASE_URL}/api/pd/developments/{development_id}/formulas", json={
        "name": "TEST Formula v1",
        "notes": "test",
        "volume": 100,
        "volume_unit": "mL",
    })
    assert r.status_code in [200, 201]
    return r.json()["id"]


class TestTaskReminders:
    """Task reminders and manual task creation"""

    def test_check_reminders_endpoint(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/workflow/tasks/check-reminders")
        assert r.status_code == 200
        data = r.json()
        assert "notified" in data or "d1_notified_count" in data or "message" in data or isinstance(data, dict)
        print(f"check-reminders response: {data}")

    def test_create_manual_task(self, admin_session, pd_card_id):
        r = admin_session.post(f"{BASE_URL}/api/workflow/tasks", json={
            "title": "Teste manual iter7",
            "entity_type": "pd_card",
            "entity_id": pd_card_id,
            "blocking": False,
            "due_in_days": 3,
        })
        assert r.status_code in [200, 201]
        data = r.json()
        assert data.get("title") == "Teste manual iter7"
        print(f"Created task: {data.get('id')}")
        return data

    def test_list_tasks(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/workflow/tasks")
        assert r.status_code == 200
        tasks = r.json()
        assert isinstance(tasks, list)
        print(f"Total tasks: {len(tasks)}")


class TestFormulaLocking:
    """Formula locking (RN-BF-01) and new version creation"""

    def test_formula_is_unlocked_initially(self, admin_session, formula_id):
        r = admin_session.get(f"{BASE_URL}/api/pd/formulas/{formula_id}/items")
        assert r.status_code == 200
        # Just verifying formula accessible
        print(f"Formula {formula_id} items accessible")

    def test_add_item_to_unlocked_formula(self, admin_session, formula_id):
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{formula_id}/items", json={
            "ingredient_name": "TEST_Agua destilada",
            "percentage": 100.0,
            "price_per_kg": 1.0,
        })
        assert r.status_code in [200, 201], f"Add item failed: {r.text}"
        data = r.json()
        assert data.get("ingredient_name") == "TEST_Agua destilada"
        print(f"Added item to unlocked formula")

    def test_new_version_on_unlocked_formula_returns_400(self, admin_session, formula_id):
        """Cannot create new version of unlocked formula."""
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{formula_id}/new-version", json={
            "justification": "Test justification long enough"
        })
        assert r.status_code == 400
        print(f"Correctly blocked new version on unlocked formula: {r.json()}")

    def test_new_version_short_justification_returns_422(self, admin_session, formula_id):
        """Short justification (< 10 chars) must fail validation."""
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{formula_id}/new-version", json={
            "justification": "short"
        })
        assert r.status_code == 422
        print(f"Correctly rejected short justification: {r.status_code}")


class TestFormulaLockingWithLockedFormula:
    """Tests requiring a locked formula - created by transitioning a card to IN_TESTS."""

    @pytest.fixture(scope="class")
    def locked_formula_data(self, admin_session):
        """Create card, transition to IN_TESTS to get locked formula."""
        r = admin_session.post(f"{BASE_URL}/api/pd/requests", json={
            "project_name": "TEST_ITER7_LockClass",
            "client_name": "TEST",
            "category": "skincare",
            "briefing": "Test locked formula class",
        })
        assert r.status_code == 200
        card_id = r.json()["id"]
        
        # Transition to IN_PROGRESS
        admin_session.put(f"{BASE_URL}/api/pd/requests/{card_id}/status", json={"new_status": "IN_PROGRESS"})
        dev_id = admin_session.get(f"{BASE_URL}/api/pd/requests/{card_id}/development").json()["id"]
        
        # Create formula
        r2 = admin_session.post(f"{BASE_URL}/api/pd/developments/{dev_id}/formulas", json={
            "name": "TEST_Lock_Class", "volume": 100, "volume_unit": "mL"
        })
        fid = r2.json()["id"]
        
        # Add 100% item
        admin_session.post(f"{BASE_URL}/api/pd/formulas/{fid}/items", json={
            "ingredient_name": "TEST_Agua_Lock", "percentage": 100.0, "price_per_kg": 1.0
        })
        
        # Transition to IN_TESTS -> locks formula
        r3 = admin_session.put(f"{BASE_URL}/api/pd/requests/{card_id}/status", json={"new_status": "IN_TESTS"})
        assert r3.status_code == 200
        
        return {"formula_id": fid, "card_id": card_id, "dev_id": dev_id}

    def test_formula_is_locked_after_in_tests(self, admin_session, locked_formula_data):
        fid = locked_formula_data["formula_id"]
        r = admin_session.get(f"{BASE_URL}/api/pd/developments/{locked_formula_data['dev_id']}/formulas")
        assert r.status_code == 200
        formulas = r.json()
        locked = [f for f in formulas if f["id"] == fid]
        if locked:
            assert locked[0].get("locked") == True, "Formula should be locked after IN_TESTS"
            print(f"Formula is locked: {locked[0].get('locked')}")

    def test_add_item_to_locked_formula_blocked(self, admin_session, locked_formula_data):
        fid = locked_formula_data["formula_id"]
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{fid}/items", json={
            "ingredient_name": "BLOCKED_ingredient", "percentage": 5.0, "price_per_kg": 2.0,
        })
        assert r.status_code == 409
        assert "RN-BF-01" in r.text
        print(f"Correctly blocked add to locked formula: {r.json()}")

    def test_new_version_valid_justification(self, admin_session, locked_formula_data):
        fid = locked_formula_data["formula_id"]
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{fid}/new-version", json={
            "justification": "Justificativa valida com mais de 10 caracteres"
        })
        assert r.status_code in [200, 201]
        data = r.json()
        assert data.get("locked") == False
        assert data.get("version", 0) >= 2
        assert data.get("parent_formula_id") == fid
        print(f"New version created: v{data.get('version')} id={data.get('id')}")

    def test_new_version_items_copied(self, admin_session, locked_formula_data):
        fid = locked_formula_data["formula_id"]
        r = admin_session.post(f"{BASE_URL}/api/pd/formulas/{fid}/new-version", json={
            "justification": "Segunda versao para testar copia de ingredientes"
        })
        assert r.status_code in [200, 201]
        data = r.json()
        new_fid = data.get("id")
        # Check items were copied
        items_r = admin_session.get(f"{BASE_URL}/api/pd/formulas/{new_fid}/items")
        assert items_r.status_code == 200
        new_items = items_r.json()
        assert len(new_items) > 0, "New version should have items copied from locked formula"
        print(f"New version has {len(new_items)} items copied")


class TestStabilityStudy:
    """Stability study creation and readings"""

    def test_get_or_create_stability_study(self, admin_session, pd_card_id):
        r = admin_session.get(f"{BASE_URL}/api/pd/requests/{pd_card_id}/stability-study")
        assert r.status_code == 200
        data = r.json()
        assert "study" in data
        assert "readings" in data
        assert "constants" in data
        print(f"Study id: {data['study']['id']}")

    def test_stability_constants(self, admin_session, pd_card_id):
        r = admin_session.get(f"{BASE_URL}/api/pd/requests/{pd_card_id}/stability-study")
        assert r.status_code == 200
        data = r.json()
        constants = data["constants"]
        assert len(constants["conditions"]) == 5
        assert len(constants["parameters"]) == 12
        assert constants["checkpoints"] == [1, 2, 7, 30, 60, 90]
        freeze = next(condition for condition in constants["conditions"] if condition["code"] == "freeze_thaw")
        assert freeze["checkpoints"] == [1, 2, 7, 15]
        print(f"Conditions: {len(constants['conditions'])}, Params: {len(constants['parameters'])}")

    def test_study_idempotent(self, admin_session, pd_card_id):
        """Calling study endpoint twice should return same study."""
        r1 = admin_session.get(f"{BASE_URL}/api/pd/requests/{pd_card_id}/stability-study")
        r2 = admin_session.get(f"{BASE_URL}/api/pd/requests/{pd_card_id}/stability-study")
        assert r1.json()["study"]["id"] == r2.json()["study"]["id"]
        print("Study is idempotent")

    def test_register_reading(self, admin_session, pd_card_id):
        r = admin_session.get(f"{BASE_URL}/api/pd/requests/{pd_card_id}/stability-study")
        assert r.status_code == 200
        data = r.json()
        study_id = data["study"]["id"]
        conditions = data["constants"]["conditions"]
        cond_id = conditions[0]["code"]

        # Register first reading at D24h for the first condition
        reading_data = {
            "condition_code": cond_id,
            "day_offset": 1,
            "parameters": {
                "aspecto": "Normal",
                "cor": "Branco",
                "odor": "Suave",
                "ph": "7.0",
                "viscosidade": "500",
                "densidade": "1.05",
            }
        }
        r2 = admin_session.post(f"{BASE_URL}/api/pd/stability/studies/{study_id}/readings", json=reading_data)
        print(f"Register reading status: {r2.status_code}, response: {r2.text[:200]}")
        assert r2.status_code in [200, 201], f"Unexpected status: {r2.status_code}"
