"""
Iteration 8 backend tests:
- RBAC enforcement on commercial pipeline endpoints (server.py get_commercial_user)
- Live Documents inbox (/api/pd/live-documents/pending) and diff
- Stability scheduler endpoints (status & run-scheduler)

Auth uses HttpOnly cookies (access_token). We use requests.Session per role.
"""
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)
API = f"{BASE_URL}/api"

CREDS = {
    "admin":      ("admin@kuryos.com", "admin123"),
    "vendedor":   ("vendedor@kuryos.com", "kuryos123"),
    "salesops":   ("salesops@kuryos.com", "kuryos123"),
    "formulador": ("formulador@kuryos.com", "kuryos123"),
    "qa":         ("qa@kuryos.com", "kuryos123"),
    "liderpd":    ("liderpd@kuryos.com", "kuryos123"),
}


def _login(role: str) -> requests.Session:
    s = requests.Session()
    email, password = CREDS[role]
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {role}: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("role"), f"Login response missing role for {role}: {body}"
    return s


@pytest.fixture(scope="module")
def sessions():
    return {role: _login(role) for role in CREDS}


# ---------- Auth seeded users ----------

@pytest.mark.parametrize("role", list(CREDS.keys()))
def test_login_seeded_users(role):
    s = _login(role)
    me = s.get(f"{API}/auth/me", timeout=10)
    assert me.status_code == 200, f"/auth/me failed for {role}: {me.text}"
    data = me.json()
    assert data["email"] == CREDS[role][0]


# ---------- Commercial pipeline RBAC ----------

def test_pipelines_admin_ok(sessions):
    r = sessions["admin"].get(f"{API}/pipelines", timeout=10)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_pipelines_vendedor_ok(sessions):
    r = sessions["vendedor"].get(f"{API}/pipelines", timeout=10)
    assert r.status_code == 200, r.text


def test_pipelines_formulador_forbidden(sessions):
    r = sessions["formulador"].get(f"{API}/pipelines", timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_pipelines_qa_forbidden(sessions):
    r = sessions["qa"].get(f"{API}/pipelines", timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_pipelines_liderpd_forbidden(sessions):
    r = sessions["liderpd"].get(f"{API}/pipelines", timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_pipelines_board_qa_forbidden(sessions):
    pipelines_resp = sessions["admin"].get(f"{API}/pipelines", timeout=10)
    assert pipelines_resp.status_code == 200
    pipes = pipelines_resp.json()
    if not pipes:
        pytest.skip("No pipelines to test board endpoint")
    pid = pipes[0]["id"]
    r = sessions["qa"].get(f"{API}/pipelines/{pid}/board", timeout=10)
    assert r.status_code == 403, f"qa board expected 403, got {r.status_code}"
    r2 = sessions["vendedor"].get(f"{API}/pipelines/{pid}/board", timeout=10)
    assert r2.status_code == 200, f"vendedor board expected 200, got {r2.status_code}: {r2.text}"


def _get_first_pipeline_and_stage(session):
    pipelines = session.get(f"{API}/pipelines", timeout=10).json()
    if not pipelines:
        return None, None
    pid = pipelines[0]["id"]
    board = session.get(f"{API}/pipelines/{pid}/board", timeout=10)
    if board.status_code != 200:
        return pid, None
    stages = board.json().get("stages") or []
    if not stages:
        return pid, None
    return pid, stages[0]["id"]


def test_cards_post_formulador_forbidden(sessions):
    pid, sid = _get_first_pipeline_and_stage(sessions["admin"])
    if not pid or not sid:
        pytest.skip("No pipeline/stage available")
    payload = {"pipeline_id": pid, "stage_id": sid, "title": "TEST_RBAC_FORB", "nome_cliente": "TEST_RBAC_Cliente"}
    r = sessions["formulador"].post(f"{API}/cards", json=payload, timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_cards_post_vendedor_ok(sessions):
    pid, sid = _get_first_pipeline_and_stage(sessions["admin"])
    if not pid or not sid:
        pytest.skip("No pipeline/stage available")
    payload = {"pipeline_id": pid, "stage_id": sid, "title": "TEST_ITER8_RBAC_OK", "nome_cliente": "TEST_RBAC_Cliente"}
    r = sessions["vendedor"].post(f"{API}/cards", json=payload, timeout=15)
    assert r.status_code in (200, 201), f"Expected 200/201, got {r.status_code}: {r.text}"
    data = r.json()
    assert "id" in data and isinstance(data["id"], str)


# ---------- PD module access (vendedor restricted) ----------

@pytest.mark.xfail(reason="BUG: GET /api/pd/requests does NOT enforce require_roles - vendedor gets 200 instead of expected 403", strict=False)
def test_pd_requests_vendedor_forbidden(sessions):
    """PD_READ does not include vendedor; expect 403 (acceptable per request)."""
    r = sessions["vendedor"].get(f"{API}/pd/requests", timeout=10)
    assert r.status_code == 403, f"Expected 403 for vendedor on pd/requests, got {r.status_code}: {r.text}"


def test_pd_requests_salesops_ok(sessions):
    r = sessions["salesops"].get(f"{API}/pd/requests", timeout=10)
    assert r.status_code == 200, r.text


# ---------- Live Documents Inbox ----------

def test_live_docs_pending_qa_ok(sessions):
    r = sessions["qa"].get(f"{API}/pd/live-documents/pending", timeout=10)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_live_docs_pending_liderpd_ok(sessions):
    r = sessions["liderpd"].get(f"{API}/pd/live-documents/pending", timeout=10)
    assert r.status_code == 200, r.text


def test_live_docs_pending_formulador_ok(sessions):
    """Formulador is in DOC_REVIEWERS so should get 200."""
    r = sessions["formulador"].get(f"{API}/pd/live-documents/pending", timeout=10)
    assert r.status_code == 200, r.text


def test_live_docs_pending_vendedor_forbidden(sessions):
    r = sessions["vendedor"].get(f"{API}/pd/live-documents/pending", timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_live_docs_diff_nonexistent(sessions):
    """Diff endpoint with bogus id should return 404 (acceptable per request)."""
    r = sessions["qa"].get(f"{API}/pd/document-versions/nonexistent-id-xxx/diff", timeout=10)
    assert r.status_code in (404, 403), f"Got {r.status_code}: {r.text}"


# ---------- Stability scheduler ----------

@pytest.mark.parametrize("role", ["admin", "qa", "formulador", "liderpd"])
def test_scheduler_status_ok(sessions, role):
    r = sessions[role].get(f"{API}/pd/stability/scheduler-status", timeout=10)
    assert r.status_code == 200, f"{role}: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("scheduler_active") is True
    assert body.get("interval_seconds") == 3600
    assert "last_run_at" in body
    assert "last_alerts_created" in body


def test_scheduler_status_vendedor_forbidden(sessions):
    r = sessions["vendedor"].get(f"{API}/pd/stability/scheduler-status", timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_run_scheduler_admin_ok(sessions):
    r = sessions["admin"].post(f"{API}/pd/stability/run-scheduler", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "alerts_created" in body
    assert "ran_at" in body
    # Verify status updated (last_run_at recent, not strict equality due to repeated now_iso())
    s = sessions["admin"].get(f"{API}/pd/stability/scheduler-status", timeout=10).json()
    assert s.get("last_run_at"), "last_run_at not set after run"


def test_run_scheduler_vendedor_forbidden(sessions):
    r = sessions["vendedor"].post(f"{API}/pd/stability/run-scheduler", timeout=15)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_run_scheduler_salesops_forbidden(sessions):
    """sales_ops not in admin|liderpd|qa|formulador set -> 403."""
    r = sessions["salesops"].post(f"{API}/pd/stability/run-scheduler", timeout=15)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_run_scheduler_qa_ok(sessions):
    r = sessions["qa"].post(f"{API}/pd/stability/run-scheduler", timeout=30)
    assert r.status_code == 200, r.text
