"""
Iteration 5 backend tests - RBAC enforcement, tasks dashboard, banco de formulas
visibility, homologacao MP, live documents, and demo seed users.

Auth uses HttpOnly cookies; we use requests.Session per user.
"""
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)
API = f"{BASE_URL}/api"

USERS = {
    "admin":             ("admin@kuryos.com",       "admin123"),
    "vendedor":          ("vendedor@kuryos.com",    "kuryos123"),
    "sales_ops":         ("salesops@kuryos.com",    "kuryos123"),
    "formulador":        ("formulador@kuryos.com",  "kuryos123"),
    "qa":                ("qa@kuryos.com",          "kuryos123"),
    "lider_pd":          ("liderpd@kuryos.com",     "kuryos123"),
    "engenharia_produto":("engenharia@kuryos.com",  "kuryos123"),
    "sucesso_cliente":   ("sucesso@kuryos.com",     "kuryos123"),
}


def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def sessions():
    out = {}
    for role, (email, pwd) in USERS.items():
        out[role] = login(email, pwd)
    return out


@pytest.fixture(scope="module")
def admin(sessions):
    return sessions["admin"]


# ---------- Seed all 8 RBAC profile users login OK ----------

@pytest.mark.parametrize("role,creds", list(USERS.items()))
def test_login_each_seeded_role(role, creds):
    email, pwd = creds
    s = login(email, pwd)
    me = s.get(f"{API}/auth/me", timeout=15)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body.get("email") == email
    # role should normalize to one of canonical roles
    assert body.get("role") in {
        "admin", "vendedor", "sales_ops", "formulador", "qa",
        "lider_pd", "engenharia_produto", "sucesso_cliente",
    }, f"Unexpected role: {body}"


# ---------- Reset tenant data so tests are deterministic ----------

@pytest.fixture(scope="module", autouse=True)
def _reset(admin):
    r = admin.post(f"{API}/workflow/admin/reset-data", timeout=20)
    assert r.status_code == 200, r.text
    yield


# ---------- Tasks dashboard filters ----------

def test_tasks_dashboard_filters(admin):
    for params in [
        {"mine": "true"},
        {"overdue": "true"},
        {"due_within_days": 7},
        {"blocking": "true"},
        {"status": "concluida"},
        {},  # all
    ]:
        r = admin.get(f"{API}/workflow/tasks", params=params, timeout=15)
        assert r.status_code == 200, f"{params} -> {r.status_code} {r.text}"
        assert isinstance(r.json(), list)


# ---------- RBAC: CRM client create/edit ----------

def _valid_client_payload(name: str = "TEST_RBAC Cliente"):
    return {
        "nome_empresa": name,
        "cnpj": "11.222.333/0001-81",
        "categoria_interesse": ["skincare"],
        "contato_principal": {
            "nome": "Test Contact",
            "email": "test@test.com",
            "telefone": "11999999999",
            "cargo": "Gerente",
        },
    }


def test_rbac_clients_create_forbidden_for_pd(sessions):
    for role in ["formulador", "qa", "engenharia_produto", "lider_pd"]:
        r = sessions[role].post(f"{API}/crm/clients", json=_valid_client_payload(f"TEST_{role}_NOPE"), timeout=15)
        assert r.status_code == 403, f"{role}: expected 403 got {r.status_code} {r.text[:200]}"


def test_rbac_clients_create_allowed_comercial(sessions):
    # vendedor allowed
    r = sessions["vendedor"].post(f"{API}/crm/clients", json=_valid_client_payload("TEST_RBAC Vendedor Cliente"), timeout=15)
    assert r.status_code in (200, 201), r.text


# ---------- RBAC: PD cards endpoints ----------

@pytest.fixture(scope="module")
def seeded_pd_card(admin):
    # create a client, project, sample chain to spawn a PD card
    cl = admin.post(f"{API}/crm/clients", json=_valid_client_payload("TEST_RBAC PD Cliente")).json()
    client_id = cl["id"]
    # advance client to projeto stage
    admin.put(f"{API}/crm/clients/{client_id}/move", json={"stage": "qualificado"})
    admin.put(f"{API}/crm/clients/{client_id}/move", json={"stage": "projeto_em_discussao"})
    proj = admin.post(f"{API}/crm/projects/batch", json={
        "projects": [{
            "client_id": client_id,
            "nome": "TEST_RBAC Projeto",
            "categoria": "skincare",
            "estagio": "kickoff",
        }],
    })
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["created"][0]["id"]
    admin.put(f"{API}/crm/projects/{project_id}/move", json={"stage": "amostras"})
    samples = admin.post(f"{API}/crm/samples/batch/v2", json={
        "samples": [{
            "project_id": project_id,
            "client_id": client_id,
            "nome_produto": "TEST_RBAC Sample",
            "variacoes": [{"nome": "A"}, {"nome": "B"}],
        }],
    })
    assert samples.status_code in (200, 201), samples.text
    # PD cards auto-created on sample variations
    cards = admin.get(f"{API}/crm/pd/cards").json()
    assert isinstance(cards, list) and len(cards) > 0, f"No PD cards created: {cards}"
    return cards[0]


def test_rbac_pd_cards_read_vendedor_ok(sessions, seeded_pd_card):
    r = sessions["vendedor"].get(f"{API}/crm/pd/cards", timeout=15)
    assert r.status_code == 200


def test_rbac_pd_cards_move_vendedor_forbidden(sessions, seeded_pd_card):
    card_id = seeded_pd_card["id"]
    r = sessions["vendedor"].put(f"{API}/crm/pd/cards/{card_id}/move", json={"status": "em_desenvolvimento"}, timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"


def test_rbac_pd_cards_move_lider_pd_ok(sessions, seeded_pd_card):
    card_id = seeded_pd_card["id"]
    r = sessions["lider_pd"].put(f"{API}/crm/pd/cards/{card_id}/move", json={"status": "em_desenvolvimento"}, timeout=15)
    assert r.status_code == 200, r.text


# ---------- RBAC: Homologacao MPs ----------

def _mp_payload(name="TEST_MP1"):
    return {
        "nome": name,
        "codigo_interno": "MP-T1",
        "inci": "Aqua",
        "tipo_mp": "FORMULACAO",
        "fornecedor_nome": "TestFornecedor",
        "funcao": "veiculo",
    }


def test_rbac_mp_create_vendedor_forbidden(sessions):
    r = sessions["vendedor"].post(f"{API}/pd/homologacao/mps", json=_mp_payload("TEST_MP_vendedor"), timeout=15)
    assert r.status_code == 403


def test_rbac_mp_create_formulador_ok(sessions):
    r = sessions["formulador"].post(f"{API}/pd/homologacao/mps", json=_mp_payload("TEST_MP_formulador"), timeout=15)
    assert r.status_code in (200, 201), r.text


def test_rbac_mp_homologar_only_approvers(sessions, admin):
    # create as formulador
    r = sessions["formulador"].post(f"{API}/pd/homologacao/mps", json=_mp_payload("TEST_MP_homologar"), timeout=15)
    assert r.status_code in (200, 201), r.text
    mp_id = r.json()["id"]
    # formulador cannot homologar
    r2 = sessions["formulador"].post(f"{API}/pd/homologacao/mps/{mp_id}/homologar",
                                     json={"aprovado": True, "parecer": "ok"}, timeout=15)
    assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text[:200]}"
    # qa can homologar
    r3 = sessions["qa"].post(f"{API}/pd/homologacao/mps/{mp_id}/homologar",
                             json={"aprovado": True, "parecer": "ok"}, timeout=15)
    assert r3.status_code in (200, 201), r3.text


# ---------- RBAC: Workflow audit-logs ----------

def test_rbac_audit_logs_admin_ok(admin):
    r = admin.get(f"{API}/workflow/audit-logs", timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_rbac_audit_logs_vendedor_forbidden(sessions):
    r = sessions["vendedor"].get(f"{API}/workflow/audit-logs", timeout=15)
    assert r.status_code == 403


def test_rbac_audit_logs_formulador_forbidden(sessions):
    r = sessions["formulador"].get(f"{API}/workflow/audit-logs", timeout=15)
    assert r.status_code == 403


def test_rbac_audit_logs_qa_ok(sessions):
    r = sessions["qa"].get(f"{API}/workflow/audit-logs", timeout=15)
    assert r.status_code == 200


# ---------- Banco de Formulas visibility ----------

def test_banco_formulas_vendedor_restricted(sessions):
    r = sessions["vendedor"].get(f"{API}/pd/formulas/bank", timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    if items:
        for it in items:
            # restricted view: should not expose composition/cost
            assert it.get("restricted_view") is True or it.get("items") in (None, [])
            assert it.get("total_cost_per_kg") in (None, 0, 0.0)


def test_banco_formulas_lider_pd_full(sessions):
    r = sessions["lider_pd"].get(f"{API}/pd/formulas/bank", timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    if items:
        # at least restricted_view must not be True for PD roles
        first = items[0]
        assert first.get("restricted_view") is not True


# ---------- Admin-only invite + role management ----------

def test_invite_admin_only(admin, sessions):
    # vendedor cannot invite
    r = sessions["vendedor"].post(f"{API}/users/invite",
                                  json={"email": "TEST_invite@x.com", "name": "NoOne", "role": "vendedor"},
                                  timeout=15)
    assert r.status_code == 403


def test_role_update_admin_only(sessions):
    r = sessions["formulador"].put(f"{API}/users/some-id/role", json={"role": "vendedor"}, timeout=15)
    assert r.status_code in (403, 404)
    # 403 should come BEFORE we hit not-found; main expectation is forbidden
    if r.status_code == 404:
        # acceptable only if handler short-circuits, but RBAC must catch first
        pytest.fail(f"expected 403 RBAC denial, got 404: {r.text[:200]}")
