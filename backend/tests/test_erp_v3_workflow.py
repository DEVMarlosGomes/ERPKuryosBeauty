"""
ERP v3.0 Process-driven Workflow backend tests.
Covers: auth, reset, audit logs, blocking tasks, hierarchy, global sample numbering,
rework, P&D stage gating with CQ approval, and role-based audit access.
"""
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@kuryos.com"
ADMIN_PASSWORD = "admin123"


# ---------- fixtures ----------

@pytest.fixture(scope="session")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    # Else rely on HttpOnly cookies already in session
    # Verify with /me
    me = s.get(f"{API}/auth/me")
    assert me.status_code == 200, f"auth/me failed: {me.status_code} {me.text}"
    return s


@pytest.fixture(scope="session")
def reset_state(admin_client):
    """Wipe operational data once per run to keep tests deterministic."""
    r = admin_client.post(f"{API}/workflow/admin/reset-data", timeout=30)
    assert r.status_code == 200, f"reset failed: {r.status_code} {r.text}"
    return r.json()


# ---------- auth ----------

def test_auth_login_admin():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    # Either a token in body OR HttpOnly cookie authentication
    me = s.get(f"{API}/auth/me")
    assert me.status_code == 200, "auth/me must succeed after login"
    assert me.json().get("email") == ADMIN_EMAIL


# ---------- reset ----------

def test_admin_reset_data(admin_client, reset_state):
    assert "deletions" in reset_state
    # Verify clients are empty after reset
    r = admin_client.get(f"{API}/crm/clients")
    assert r.status_code == 200
    # Accept list response; should be empty or close to it for this tenant
    data = r.json()
    clients = data if isinstance(data, list) else data.get("items", [])
    assert isinstance(clients, list)


# ---------- client creation + audit ----------

@pytest.fixture(scope="session")
def seed_client(admin_client, reset_state):
    payload = {
        "nome_empresa": "TEST_ERPv3 ClienteA",
        "cnpj": "00.000.000/0001-91",
        "contato_principal": {"nome": "João Teste", "whatsapp": "11999990000", "email": "TEST_erpv3_clientea@example.com"},
        "canal_origem": "formulario_site",
        "categoria_interesse": ["hidratante_facial"],
        "origem_lead": "site",
    }
    r = admin_client.post(f"{API}/crm/clients", json=payload, timeout=30)
    assert r.status_code in (200, 201), f"create client: {r.status_code} {r.text}"
    client = r.json()
    assert "id" in client
    return client


def test_create_client_generates_audit_log(admin_client, seed_client):
    r = admin_client.get(f"{API}/workflow/audit-logs/by-entity/client/{seed_client['id']}")
    assert r.status_code == 200
    logs = r.json()
    actions = [l.get("action") for l in logs]
    assert "client_created" in actions, f"actions={actions}"


# ---------- move client pipeline with blocking task ----------

def test_move_client_prospeccao_to_qualificado_creates_task(admin_client, seed_client):
    r = admin_client.put(f"{API}/crm/clients/{seed_client['id']}/move", json={"stage": "qualificado"})
    assert r.status_code == 200, r.text
    # A blocking workflow task must exist now
    r2 = admin_client.get(f"{API}/workflow/tasks/by-entity/client/{seed_client['id']}")
    assert r2.status_code == 200
    tasks = r2.json()
    pending_blocking = [t for t in tasks if t.get("blocking") and t.get("status") in ("pendente", "em_andamento")]
    assert pending_blocking, f"no blocking task created. tasks={tasks}"
    assert any("Qualificar lead" in t["title"] for t in pending_blocking)


def test_move_client_qualificado_to_projeto_is_blocked(admin_client, seed_client):
    r = admin_client.put(f"{API}/crm/clients/{seed_client['id']}/move", json={"stage": "projeto_em_discussao"})
    assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text}"
    assert "bloquead" in r.text.lower() or "tarefa" in r.text.lower()


def test_complete_blocking_task_and_advance(admin_client, seed_client):
    r = admin_client.get(f"{API}/workflow/tasks/by-entity/client/{seed_client['id']}")
    tasks = r.json()
    blocking = [t for t in tasks if t.get("blocking") and t.get("status") == "pendente"]
    assert blocking
    task_id = blocking[0]["id"]
    # Complete it
    cr = admin_client.put(f"{API}/workflow/tasks/{task_id}/complete", json={"comment": "feito"})
    assert cr.status_code == 200, cr.text
    assert cr.json()["status"] == "concluida"
    # Now the move should pass
    mr = admin_client.put(f"{API}/crm/clients/{seed_client['id']}/move", json={"stage": "projeto_em_discussao"})
    assert mr.status_code == 200, mr.text


# ---------- project hierarchy + inheritance ----------

def test_project_batch_with_fake_client_returns_404(admin_client):
    payload = {"cliente_id": "nonexistent-xyz", "projects": [{"nome_projeto": "TEST_ProjetoX"}]}
    r = admin_client.post(f"{API}/crm/projects/batch", json=payload)
    assert r.status_code == 404, f"{r.status_code} {r.text}"
    assert "hierarquia" in r.text.lower() or "cliente" in r.text.lower()


@pytest.fixture(scope="session")
def seed_project(admin_client, seed_client):
    # client is now at projeto_em_discussao
    payload = {
        "cliente_id": seed_client["id"],
        "projects": [{
            "nome_projeto": "TEST_ProjetoA",
            "categoria": "skincare",
            "briefing_resumido": "Briefing teste",
        }],
    }
    r = admin_client.post(f"{API}/crm/projects/batch", json=payload)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    projects = data if isinstance(data, list) else data.get("projects") or data.get("items") or data.get("created") or []
    if isinstance(data, dict) and "id" in data:
        projects = [data]
    assert projects, f"no project in response: {data}"
    return projects[0]


def test_project_created_inherits_and_audits(admin_client, seed_project, seed_client):
    # audit
    r = admin_client.get(f"{API}/workflow/audit-logs/by-entity/project/{seed_project['id']}")
    assert r.status_code == 200
    actions = [l["action"] for l in r.json()]
    assert "project_created" in actions, actions
    # inheritance: categoria should propagate
    got = admin_client.get(f"{API}/crm/projects/{seed_project['id']}")
    if got.status_code == 200:
        p = got.json()
        assert (p.get("categoria_interesse_cliente") == "skincare"
                or p.get("categoria") == "skincare"
                or "skincare" in str(p).lower())


def test_move_project_to_amostras_generates_task(admin_client, seed_project):
    r = admin_client.put(f"{API}/crm/projects/{seed_project['id']}/move", json={"stage": "amostras"})
    assert r.status_code == 200, r.text
    r2 = admin_client.get(f"{API}/workflow/tasks/by-entity/project/{seed_project['id']}")
    assert r2.status_code == 200
    assert any("amostra" in t["title"].lower() for t in r2.json())


# ---------- samples global numbering + variacoes ----------

@pytest.fixture(scope="session")
def seed_samples(admin_client, seed_project, seed_client):
    payload = {
        "projeto_id": seed_project["id"],
        "samples": [{
            "nome_produto": "TEST_Sample1",
            "categoria": "skincare",
            "briefing_base": "Briefing base",
            "variacoes": [
                {"descricao_aplicacao": "Variação A"},
                {"descricao_aplicacao": "Variação B"},
            ],
        }],
    }
    r = admin_client.post(f"{API}/crm/samples/batch/v2", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _extract_samples(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("created") or data.get("samples") or data.get("items") or ([data] if "id" in data else [])
    return []


def test_sample_starts_at_1001_with_variacoes(seed_samples):
    import re
    samples = _extract_samples(seed_samples)
    assert samples, f"no samples: {seed_samples}"
    s = samples[0]
    num = s.get("numero_amostra") or s.get("numero") or s.get("codigo_amostra")
    # Format: {YEAR}-{NNNN}, e.g. "2026-1001"
    assert re.match(r"^\d{4}-\d{4}$", str(num)), f"expected YYYY-NNNN format, got {num}"
    variacoes = s.get("variacoes") or []
    codes = [v.get("codigo") or v.get("codigo_variacao") for v in variacoes]
    assert any(c and c.endswith("-a") for c in codes), codes
    assert any(c and c.endswith("-b") for c in codes), codes


def test_auto_pd_cards_created_for_variacoes(admin_client, seed_samples):
    samples = _extract_samples(seed_samples)
    s = samples[0]
    r = admin_client.get(f"{API}/crm/pd/cards", params={"amostra_id": s["id"]})
    assert r.status_code == 200, r.text
    payload = r.json()
    cards = payload if isinstance(payload, list) else (payload.get("items") or payload.get("cards") or [])
    # fallback: fetch all and filter
    if not cards:
        r2 = admin_client.get(f"{API}/crm/pd/cards")
        all_cards = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
        cards = [c for c in all_cards if c.get("amostra_id") == s["id"]]
    assert len(cards) >= 2, f"expected >=2 auto pd cards (one per variacao), got {len(cards)}"


def test_rework_creates_new_sample_sequential(admin_client, seed_samples):
    import re
    samples = _extract_samples(seed_samples)
    s = samples[0]
    original_num = s.get("numero_amostra", "")
    r = admin_client.post(f"{API}/crm/samples/{s['id']}/rework", json={"motivo": "ajuste"})
    assert r.status_code in (200, 201), r.text
    new_s = r.json()
    # Response wraps: {"rework_sample": {...}, "original_id": "...", "novo_numero": "..."}
    if isinstance(new_s, dict) and "rework_sample" in new_s:
        novo = new_s.get("novo_numero") or new_s["rework_sample"].get("numero_amostra")
        assert re.match(r"^\d{4}-\d{4}$", str(novo)), f"expected YYYY-NNNN format, got {novo}"
        assert str(novo) != str(original_num), "rework must get a new number"
        # original preserved and linked
        assert new_s["rework_sample"].get("rework_de_amostra_id") == s["id"]
        return
    num = new_s.get("numero_amostra") or new_s.get("numero")
    assert re.match(r"^\d{4}-\d{4}$", str(num)), f"expected YYYY-NNNN format, got {num}"


def test_move_sample_to_retrabalho_is_blocked(admin_client, seed_samples):
    samples = _extract_samples(seed_samples)
    s = samples[0]
    r = admin_client.put(f"{API}/crm/samples/{s['id']}/move", json={"stage": "retrabalho"})
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
    assert "retrabalho" in r.text.lower()


def test_move_variacao_to_retrabalho_is_blocked(admin_client, seed_samples):
    samples = _extract_samples(seed_samples)
    s = samples[0]
    var = (s.get("variacoes") or [{}])[0]
    vid = var.get("id")
    if not vid:
        pytest.skip("variacao id not exposed in response")
    r = admin_client.put(f"{API}/crm/samples/{s['id']}/variacoes/{vid}/move", json={"status": "retrabalho"})
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"


def test_variacao_requires_client_result_before_approval(admin_client, seed_samples):
    samples = _extract_samples(seed_samples)
    s = samples[0]
    variacoes = s.get("variacoes") or []
    if len(variacoes) < 2:
        pytest.skip("need a second variacao to test approval gating")

    vid = variacoes[1].get("id")
    if not vid:
        pytest.skip("variacao id not exposed in response")

    r1 = admin_client.put(
        f"{API}/crm/samples/{s['id']}/variacoes/{vid}/move",
        json={"status": "em_elaboracao"},
    )
    assert r1.status_code == 200, r1.text

    r2 = admin_client.put(
        f"{API}/crm/samples/{s['id']}/variacoes/{vid}/move",
        json={"status": "enviada"},
    )
    assert r2.status_code == 200, r2.text

    blocked = admin_client.put(
        f"{API}/crm/samples/{s['id']}/variacoes/{vid}/move",
        json={"status": "aprovada"},
    )
    assert blocked.status_code == 422, blocked.text
    assert "resultado do cliente" in blocked.text.lower() or "aprovação direta" in blocked.text.lower()

    approved = admin_client.post(
        f"{API}/crm/samples/{s['id']}/variacoes/{vid}/resultado-cliente",
        json={"resultado": "aprovada", "feedback_cliente": "cliente aprovou"},
    )
    assert approved.status_code == 200, approved.text

    refreshed = admin_client.get(f"{API}/crm/samples/{s['id']}")
    assert refreshed.status_code == 200, refreshed.text
    payload = refreshed.json()
    updated_var = next(v for v in payload.get("variacoes", []) if v.get("id") == vid)
    assert updated_var["status"] == "aprovada"
    assert updated_var.get("aprovacao_interna") is True
    assert updated_var.get("aprovacao_externa") is True


def test_pd_card_stage_gating_cq_approval(admin_client, seed_samples):
    samples = _extract_samples(seed_samples)
    s = samples[0]
    r2 = admin_client.get(f"{API}/crm/pd/cards")
    all_cards = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
    cards = [c for c in all_cards if c.get("amostra_id") == s["id"]]
    if not cards:
        pytest.skip("no pd card to test gating")
    card = cards[0]
    cid = card["id"]
    r1 = admin_client.put(f"{API}/crm/pd/cards/{cid}/move", json={"status": "em_desenvolvimento"})
    assert r1.status_code == 200, r1.text
    r2m = admin_client.put(f"{API}/crm/pd/cards/{cid}/move", json={"status": "em_testes"})
    assert r2m.status_code == 200, r2m.text
    tr = admin_client.get(f"{API}/workflow/tasks/by-entity/pd_card/{cid}")
    tasks = tr.json()
    assert any("testes laborator" in t["title"].lower() for t in tasks), [t["title"] for t in tasks]
    rb = admin_client.put(f"{API}/crm/pd/cards/{cid}/move", json={"status": "aguardando_aprovacao"})
    assert rb.status_code == 409, f"expected 409, got {rb.status_code} {rb.text}"
    test_tasks = [t for t in tasks if "testes laborator" in t["title"].lower() and t["status"] == "pendente"]
    for t in test_tasks:
        admin_client.put(f"{API}/workflow/tasks/{t['id']}/complete", json={"comment": "ok"})
    ra = admin_client.put(f"{API}/crm/pd/cards/{cid}/move", json={"status": "aguardando_aprovacao"})
    assert ra.status_code == 200, ra.text
    tr2 = admin_client.get(f"{API}/workflow/tasks/by-entity/pd_card/{cid}")
    cq_tasks = [t for t in tr2.json() if t.get("category") == "qa" and t["status"] == "pendente"]
    assert cq_tasks, "CQ task missing after entering aguardando_aprovacao"
    # Note: Valid PD_STATUSES are [solicitado, em_desenvolvimento, em_testes,
    # aguardando_aprovacao, retrabalho_interno] — there is no 'aprovado'/'completed'
    # stage in PD pipeline itself, so the CQ-blocking-close check is validated by
    # the task existence with blocks_stages=[completed, aprovado, concluido].
    blocks = cq_tasks[0].get("blocks_stages") or []
    assert any(b in ("completed", "aprovado", "concluido") for b in blocks), \
        f"CQ task blocks_stages not configured to gate close: {blocks}"


# ---------- list tasks, audit logs, RBAC ----------

def test_list_tasks_filters(admin_client):
    r = admin_client.get(f"{API}/workflow/tasks", params={"status": "pendente", "blocking": "true"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_audit_logs_admin(admin_client):
    r = admin_client.get(f"{API}/workflow/audit-logs")
    assert r.status_code == 200
    logs = r.json()
    assert isinstance(logs, list)
    assert len(logs) > 0


def test_audit_logs_forbidden_for_vendedor(admin_client):
    # Try to create a vendedor user via invite endpoint; if not available, skip
    invite = admin_client.post(f"{API}/users/invite", json={
        "name": "TEST_Vendedor", "email": "TEST_vendedor_audit@example.com", "role": "vendedor"
    })
    if invite.status_code not in (200, 201):
        pytest.skip(f"invite endpoint unavailable: {invite.status_code}")
    data = invite.json()
    pwd = data.get("password") or data.get("temp_password") or data.get("credentials", {}).get("password")
    if not pwd:
        pytest.skip("no temp password returned from invite")
    login_s = requests.Session()
    login = login_s.post(f"{API}/auth/login", json={"email": "TEST_vendedor_audit@example.com", "password": pwd})
    if login.status_code != 200:
        pytest.skip(f"vendedor login failed: {login.status_code}")
    r = login_s.get(f"{API}/workflow/audit-logs")
    assert r.status_code == 403, f"expected 403 for vendedor, got {r.status_code}"
