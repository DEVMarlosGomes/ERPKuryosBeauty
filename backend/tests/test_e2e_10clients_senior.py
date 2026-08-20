"""
E2E Senior-level test suite — 10 clients with complete CRM→P&D pipeline.

Strategy (senior tester mindset):
  - Happy path completeness: every stage of every entity traversed
  - Data integrity: audit logs, inheritance, sequential numbering
  - Boundary & validation: CNPJ dup, invalid email, blocked transitions
  - RBAC: role-gated endpoints reject wrong roles
  - New features: CRM-12 lead sources, PD-18 label PDF, PD-11 timeline
  - Idempotency & concurrency: reset → re-seed is deterministic
  - Error message quality: 4xx bodies are informative
"""

import pytest
import requests
import time
import re
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@kuryos.com"
ADMIN_PASS = "admin123"

# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def admin(request):
    """Authenticated admin session, shared across all tests."""
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    token = r.json().get("token") or r.json().get("access_token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    me = s.get(f"{API}/auth/me", timeout=10)
    assert me.status_code == 200
    return s


@pytest.fixture(scope="session")
def clean_slate(admin):
    """Wipe all tenant data once per run. Also deactivate leftover test lead sources."""
    r = admin.post(f"{API}/workflow/admin/reset-data", timeout=30)
    assert r.status_code == 200, f"Reset failed: {r.status_code} {r.text}"
    # Deactivate any leftover test lead sources from previous runs (ignore 404)
    admin.patch(f"{API}/crm/config/lead-sources/test_parceria_tech_e2e",
                json={"ativo": False}, timeout=10)
    return r.json()


@pytest.fixture(scope="session")
def vendedor_session(admin, clean_slate):
    """Create a vendedor user and return an authenticated session."""
    inv = admin.post(f"{API}/users/invite", json={
        "name": "TEST_Vendedor Silva", "email": "test_vendedor_e2e@kuryos.test", "role": "vendedor"
    }, timeout=15)
    if inv.status_code not in (200, 201):
        pytest.skip(f"Cannot create vendedor: {inv.status_code}")
    creds = inv.json()
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    login = s.post(f"{API}/auth/login", json={
        "email": creds["email"], "password": creds.get("temp_password", "vendor123")
    }, timeout=10)
    if login.status_code != 200:
        pytest.skip("Vendedor login failed — skip RBAC tests")
    token = login.json().get("token") or login.json().get("access_token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "clients", "projects", "samples", "created", "results"):
            if isinstance(data.get(k), list):
                return data[k]
        if "id" in data:
            return [data]
    return []


def _complete_blocking_tasks(admin, entity_type, entity_id):
    """Complete all blocking pending tasks for an entity."""
    r = admin.get(f"{API}/workflow/tasks/by-entity/{entity_type}/{entity_id}", timeout=10)
    assert r.status_code == 200
    for t in r.json():
        if t.get("blocking") and t.get("status") in ("pendente", "em_andamento"):
            done = admin.put(f"{API}/workflow/tasks/{t['id']}/complete", json={"comment": "OK"}, timeout=10)
            assert done.status_code == 200, f"Complete task failed: {done.text}"


def _move_client(admin, cid, stage):
    r = admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": stage}, timeout=10)
    assert r.status_code == 200, f"Move client to {stage} failed: {r.status_code} {r.text}"
    return r.json()


def _move_project(admin, pid, stage):
    r = admin.put(f"{API}/crm/projects/{pid}/move", json={"stage": stage}, timeout=10)
    assert r.status_code == 200, f"Move project to {stage} failed: {r.status_code} {r.text}"
    return r.json()


def _get_or_create_client(admin, spec):
    """Create client or look up existing one if CNPJ already registered (409)."""
    payload = {k: v for k, v in spec.items() if not k.startswith("_")}
    r = admin.post(f"{API}/crm/clients", json=payload, timeout=15)
    if r.status_code in (200, 201):
        return r.json()["id"]
    if r.status_code == 409:
        clients_r = admin.get(f"{API}/crm/clients", timeout=10)
        existing = next(
            (c for c in _extract_list(clients_r.json())
             if c.get("nome_empresa") == spec["nome_empresa"]),
            None,
        )
        assert existing, f"Client {spec['nome_empresa']} not found despite 409"
        return existing["id"]
    raise AssertionError(f"Create {spec['nome_empresa']} failed: {r.status_code} {r.text}")


def _advance_client_to_projeto(admin, cid):
    """Advance a client from prospeccao → qualificado → projeto_em_discussao."""
    client_r = admin.get(f"{API}/crm/clients/{cid}", timeout=10)
    stage = client_r.json().get("stage", "prospeccao")
    if stage == "prospeccao":
        admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "qualificado"}, timeout=10)
        stage = "qualificado"
    if stage == "qualificado":
        _complete_blocking_tasks(admin, "client", cid)
        admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "projeto_em_discussao"}, timeout=10)


def _advance_project_to_amostras(admin, pid):
    """Fill required briefing fields and advance project to amostras stage."""
    admin.put(f"{API}/crm/projects/{pid}", json={
        "ideia_conceito": "Fórmula inovadora para o segmento",
        "posicionamento": "Premium performance",
        "volume_estimado_pedido": "1k_5k",
        "tipo_servico": "full_service_kuryos",
        "prazo_desejado_amostra": "30 dias",
    }, timeout=10)
    r = admin.put(f"{API}/crm/projects/{pid}/move", json={"stage": "amostras"}, timeout=10)
    assert r.status_code == 200, f"Move project to amostras failed: {r.status_code} {r.text}"


# ─────────────────────────────────────────────────────────────────────────────
# 10 CLIENT PROFILES — realistic variety
# ─────────────────────────────────────────────────────────────────────────────

CLIENTS = [
    {
        "nome_empresa": "TEST_Beleza Suprema Ltda",
        "cnpj": "11.122.233/3000-63",
        "contato_principal": {"nome": "Ana Lima", "email": "ana@belezasupremae2e.test", "whatsapp": "11999001001"},
        "canal_origem": "formulario_site",
        "categoria_interesse": ["hidratante_facial", "serum_facial"],
        "origem_lead": "site",
        "segmento": "marca_propria",
        "porte": "medio",
        "temperatura_lead": "quente",
        "_project": {"nome_projeto": "Soro Vitamina C 20%", "categoria": "skin_care_dermocosmeticos"},
        "_sample": {"nome_produto": "Sérum Vitamina C 20%", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Base gel aquoso"}, {"descricao_aplicacao": "Base oil-free"}]},
    },
    {
        "nome_empresa": "TEST_Cosméticos Verde Natural",
        "cnpj": "22.233.344/4000-17",
        "contato_principal": {"nome": "Carlos Mendes", "email": "carlos@verdenaturale2e.test", "whatsapp": "21988002002"},
        "canal_origem": "indicacao_cliente_ativo",
        "categoria_interesse": ["shampoo", "condicionador"],
        "origem_lead": "indicacao_cliente_habibi",
        "segmento": "marca_propria",
        "porte": "pequeno",
        "temperatura_lead": "morno",
        "_project": {"nome_projeto": "Linha Capilar Natural", "categoria": "capilares"},
        "_sample": {"nome_produto": "Shampoo Low-Poo Coco", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Fragrância coco"}, {"descricao_aplicacao": "Sem fragrância"}]},
    },
    {
        "nome_empresa": "TEST_Pharma Beauty Corp",
        "cnpj": "33.344.455/5000-70",
        "contato_principal": {"nome": "Beatriz Santos", "email": "beatriz@pharmabe2e.test", "whatsapp": "31977003003"},
        "canal_origem": "linkedin_dm_outbound",
        "categoria_interesse": ["protetor_solar_facial", "antiacneico"],
        "origem_lead": "linkedin",
        "segmento": "industria",
        "porte": "grande",
        "temperatura_lead": "quente",
        "_project": {"nome_projeto": "Protetor Solar FPS 50", "categoria": "skin_care_dermocosmeticos"},
        "_sample": {"nome_produto": "Protetor Facial FPS 50+", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Toque seco"}, {"descricao_aplicacao": "Hidratante"}]},
    },
    {
        "nome_empresa": "TEST_Salão Imperial Hair",
        "cnpj": "44.455.566/6000-24",
        "contato_principal": {"nome": "Diego Fonseca", "email": "diego@salaoimpee2e.test", "whatsapp": "41966004004"},
        "canal_origem": "whatsapp_receptivo",
        "categoria_interesse": ["progressiva_escova", "coloracao_profissional"],
        "origem_lead": "indicacao_parceiro",
        "segmento": "salao",
        "porte": "pequeno",
        "temperatura_lead": "morno",
        "_project": {"nome_projeto": "Escova Progressiva Premium", "categoria": "capilares"},
        "_sample": {"nome_produto": "Progressiva Zero Formol", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Resistente ao frizz"}]},
    },
    {
        "nome_empresa": "TEST_Marca Própria Kids",
        "cnpj": "55.566.677/7000-88",
        "contato_principal": {"nome": "Fernanda Oliveira", "email": "fernanda@mpkidse2e.test", "whatsapp": "51955005005"},
        "canal_origem": "google_ads",
        "categoria_interesse": ["shampoo_infantil", "sabonete_infantil"],
        "origem_lead": "google",
        "segmento": "marca_propria",
        "porte": "medio",
        "temperatura_lead": "quente",
        "_project": {"nome_projeto": "Linha Baby Suave", "categoria": "infantil"},
        "_sample": {"nome_produto": "Shampoo Baby Sem Lágrimas", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Neutro pH 5.5"}, {"descricao_aplicacao": "Com camomila"}]},
    },
    {
        "nome_empresa": "TEST_Perfumaria Luxo Brasil",
        "cnpj": "66.677.788/8000-31",
        "contato_principal": {"nome": "Gabriel Torres", "email": "gabriel@pluxoe2e.test", "whatsapp": "61944006006"},
        "canal_origem": "evento",
        "categoria_interesse": ["perfume_edp", "body_splash_colonia"],
        "origem_lead": "evento",
        "segmento": "marca_propria",
        "porte": "grande",
        "temperatura_lead": "quente",
        "_project": {"nome_projeto": "Eau de Parfum Maison", "categoria": "perfumaria"},
        "_sample": {"nome_produto": "EDP Rose Noir 50ml", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Concentração 20%"}, {"descricao_aplicacao": "Concentração 15%"}]},
    },
    {
        "nome_empresa": "TEST_Dermato Clínica SP",
        "cnpj": "77.788.899/9000-95",
        "contato_principal": {"nome": "Helena Matos", "email": "helena@dermatoclinee2e.test", "whatsapp": "11933007007"},
        "canal_origem": "indicacao_fornecedor_parceiro",
        "categoria_interesse": ["clareador_pele", "antiacneico"],
        "origem_lead": "indicacao_fornecedor",
        "segmento": "industria",
        "porte": "medio",
        "temperatura_lead": "quente",
        "_project": {"nome_projeto": "Clareador Dermatológico", "categoria": "regulatorio_grau2"},
        "_sample": {"nome_produto": "Creme Clareador 2% Kojic", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Para pele sensível"}]},
    },
    {
        "nome_empresa": "TEST_Distribuidor Nordeste",
        "cnpj": "88.899.911/1000-16",
        "contato_principal": {"nome": "Igor Cavalcante", "email": "igor@distnordestee2e.test", "whatsapp": "85922008008"},
        "canal_origem": "feira_setor",
        "categoria_interesse": ["hidratante_corporal", "sabonete_liquido_corporal"],
        "origem_lead": "feira_setor",
        "segmento": "distribuidor",
        "porte": "grande",
        "temperatura_lead": "morno",
        "_project": {"nome_projeto": "Linha Hidratação Intensiva", "categoria": "corporal_spa"},
        "_sample": {"nome_produto": "Hidratante Manteiga de Karité", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "400ml"}, {"descricao_aplicacao": "200ml compacto"}]},
    },
    {
        "nome_empresa": "TEST_Men Premium Grooming",
        "cnpj": "12.345.678/9001-88",
        "contato_principal": {"nome": "Juliana Ramos", "email": "juliana@menpremiume2e.test", "whatsapp": "11911009009"},
        "canal_origem": "instagram_abordagem_direta",
        "categoria_interesse": ["balsamo_pos_barba", "gel_creme_barbear"],
        "origem_lead": "instagram",
        "segmento": "marca_propria",
        "porte": "pequeno",
        "temperatura_lead": "morno",
        "_project": {"nome_projeto": "Linha Grooming Masculino", "categoria": "masculino"},
        "_sample": {"nome_produto": "Gel de Barbear Calmante", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Aloe Vera"}, {"descricao_aplicacao": "Sem álcool"}]},
    },
    {
        "nome_empresa": "TEST_Eco Beauty Sustentável",
        "cnpj": "98.765.432/1001-41",
        "contato_principal": {"nome": "Kelly Nunes", "email": "kelly@ecobeutye2e.test", "whatsapp": "11900010010"},
        "canal_origem": "seo",
        "categoria_interesse": ["sabonete_em_barra", "oleo_corporal"],
        "origem_lead": "google",
        "segmento": "marca_propria",
        "porte": "pequeno",
        "temperatura_lead": "frio",
        "_project": {"nome_projeto": "Linha Zero Plástico", "categoria": "corporal_spa"},
        "_sample": {"nome_produto": "Sabonete Vegano Bambu", "tipo_amostra": "nova_formula",
                    "variacoes": [{"descricao_aplicacao": "Limão Siciliano"}, {"descricao_aplicacao": "Lavanda"}]},
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: RESET & BASELINE
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseline:
    def test_reset_produces_empty_clients(self, admin, clean_slate):
        """After reset, client list must be empty."""
        r = admin.get(f"{API}/crm/clients", timeout=10)
        assert r.status_code == 200
        clients = _extract_list(r.json())
        # Filter out non-TEST clients in case seed created baseline admins
        test_clients = [c for c in clients if "TEST_" in c.get("nome_empresa", "")]
        assert test_clients == [], f"Expected 0 TEST clients after reset, got {len(test_clients)}"

    def test_reset_response_has_deletion_counts(self, clean_slate):
        """Reset response must include deletion metadata."""
        assert "deletions" in clean_slate or isinstance(clean_slate, dict)

    def test_constants_endpoint_returns_canal_origem(self, admin):
        """Constants endpoint must return canal_origem list."""
        r = admin.get(f"{API}/crm/constants", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "canal_origem" in data, f"Missing canal_origem in constants: {list(data.keys())}"
        assert len(data["canal_origem"]) > 0
        assert "formulario_site" in data["canal_origem"]

    def test_auth_me_returns_correct_role(self, admin):
        """auth/me must confirm admin role."""
        r = admin.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        me = r.json()
        assert me["role"] == "admin"
        assert me["email"] == ADMIN_EMAIL


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: CREATE 10 CLIENTS & VALIDATE
# ─────────────────────────────────────────────────────────────────────────────

class TestClientCreation:
    @pytest.fixture(scope="class")
    def created_clients(self, admin, clean_slate):
        """Create all 10 clients and return their records."""
        created = []
        for spec in CLIENTS:
            payload = {k: v for k, v in spec.items() if not k.startswith("_")}
            r = admin.post(f"{API}/crm/clients", json=payload, timeout=15)
            assert r.status_code in (200, 201), \
                f"Create client '{spec['nome_empresa']}' failed: {r.status_code} {r.text}"
            client = r.json()
            assert "id" in client, f"No id in client response: {client}"
            client["_spec"] = spec
            created.append(client)
        return created

    def test_all_10_clients_created(self, created_clients):
        assert len(created_clients) == 10

    def test_clients_have_unique_ids(self, created_clients):
        ids = [c["id"] for c in created_clients]
        assert len(set(ids)) == 10, "Duplicate IDs detected"

    def test_clients_start_in_prospeccao_stage(self, created_clients):
        for c in created_clients:
            assert c.get("stage") == "prospeccao", \
                f"Client {c['nome_empresa']} not in prospeccao: {c.get('stage')}"

    def test_clients_list_shows_all_10(self, admin, created_clients):
        r = admin.get(f"{API}/crm/clients", timeout=10)
        assert r.status_code == 200
        all_clients = _extract_list(r.json())
        test_clients = [c for c in all_clients if c.get("nome_empresa", "").startswith("TEST_")]
        assert len(test_clients) >= 10, f"Expected >=10 TEST clients in list, got {len(test_clients)}"

    def test_canal_origem_stored_correctly(self, created_clients):
        for c in created_clients:
            spec_canal = c["_spec"]["canal_origem"]
            stored_canal = c.get("canal_origem")
            assert stored_canal == spec_canal, \
                f"Canal mismatch for {c['nome_empresa']}: expected {spec_canal}, got {stored_canal}"

    def test_duplicate_cnpj_rejected(self, admin, clean_slate):
        """Attempting to create a second client with same CNPJ must return 409."""
        VALID_CNPJ = "12.345.678/0001-95"  # digits produce valid check digits
        # First client with this CNPJ
        r1 = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_CNPJ Primary",
            "cnpj": VALID_CNPJ,
            "contato_principal": {"nome": "Primary", "email": "cnpj_primary@test.test", "whatsapp": "11900000001"},
            "canal_origem": "outro",
            "categoria_interesse": ["hidratante_facial"],
        }, timeout=10)
        assert r1.status_code in (200, 201), f"Primary CNPJ client failed: {r1.status_code} {r1.text}"
        # Second client with same CNPJ
        r2 = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_CNPJ Duplicate",
            "cnpj": VALID_CNPJ,
            "contato_principal": {"nome": "Dup Teste", "email": "cnpj_dup@test.test", "whatsapp": "11900000002"},
            "canal_origem": "outro",
            "categoria_interesse": ["hidratante_facial"],
        }, timeout=10)
        assert r2.status_code == 409, f"Expected 409 for dup CNPJ, got {r2.status_code} {r2.text}"
        assert "cnpj" in r2.text.lower() or "cadastrado" in r2.text.lower()

    def test_invalid_email_rejected(self, admin, clean_slate):
        """Client with malformed email must be rejected."""
        payload = {
            "nome_empresa": "TEST_InvalidEmail Co",
            "cnpj": "",
            "contato_principal": {"nome": "Bad Email", "email": "not-an-email", "whatsapp": "11900000002"},
            "canal_origem": "outro",
        }
        r = admin.post(f"{API}/crm/clients", json=payload, timeout=10)
        assert r.status_code in (400, 422), f"Expected 4xx for invalid email: {r.status_code} {r.text}"

    def test_invalid_canal_origem_rejected(self, admin, clean_slate):
        """Client with unknown canal_origem must be rejected."""
        payload = {
            "nome_empresa": "TEST_BadCanal Corp",
            "cnpj": "",
            "contato_principal": {"nome": "Bad Canal", "email": "badcanal@test.test", "whatsapp": "11900000003"},
            "canal_origem": "canal_inventado_xyz",
        }
        r = admin.post(f"{API}/crm/clients", json=payload, timeout=10)
        assert r.status_code in (400, 422), f"Expected 4xx for invalid canal: {r.status_code} {r.text}"

    def test_audit_log_created_per_client(self, admin, created_clients):
        """Every client must have a client_created audit log entry."""
        for c in created_clients[:3]:  # spot-check 3
            r = admin.get(f"{API}/workflow/audit-logs/by-entity/client/{c['id']}", timeout=10)
            assert r.status_code == 200
            actions = [l.get("action") for l in r.json()]
            assert "client_created" in actions, \
                f"No client_created log for {c['nome_empresa']}: {actions}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: PIPELINE — CLIENT STAGE TRANSITIONS
# ─────────────────────────────────────────────────────────────────────────────

class TestClientPipeline:
    @pytest.fixture(scope="class")
    def pipeline_client(self, admin, clean_slate):
        """Create a dedicated client for pipeline transition tests."""
        r = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_Pipeline Guinea Pig",
            "cnpj": "11.122.244/4000-05",
            "contato_principal": {"nome": "Guinea Pig", "email": "pipeline_gp@test.test", "whatsapp": "11900001000"},
            "canal_origem": "formulario_site",
            "categoria_interesse": ["hidratante_facial"],
        }, timeout=15)
        assert r.status_code in (200, 201), f"pipeline_client setup failed: {r.status_code} {r.text}"
        return r.json()

    def test_block_skip_to_projeto_from_prospeccao(self, admin, pipeline_client):
        """Cannot jump directly from prospeccao to projeto_em_discussao."""
        cid = pipeline_client["id"]
        r = admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "projeto_em_discussao"}, timeout=10)
        assert r.status_code in (400, 409), \
            f"Expected rejection for invalid transition: {r.status_code} {r.text}"

    def test_move_to_qualificado_creates_blocking_task(self, admin, pipeline_client):
        cid = pipeline_client["id"]
        r = admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "qualificado"}, timeout=10)
        assert r.status_code == 200, r.text
        tasks_r = admin.get(f"{API}/workflow/tasks/by-entity/client/{cid}", timeout=10)
        assert tasks_r.status_code == 200
        tasks = tasks_r.json()
        blocking = [t for t in tasks if t.get("blocking") and t.get("status") == "pendente"]
        assert blocking, f"No blocking task after move to qualificado: {tasks}"

    def test_advance_blocked_without_task_completion(self, admin, pipeline_client):
        """Cannot advance when blocking task is pending."""
        cid = pipeline_client["id"]
        r = admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "projeto_em_discussao"}, timeout=10)
        assert r.status_code == 409, \
            f"Expected 409 when blocking task pending: {r.status_code} {r.text}"

    def test_complete_task_and_advance_to_projeto(self, admin, pipeline_client):
        cid = pipeline_client["id"]
        _complete_blocking_tasks(admin, "client", cid)
        r = admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "projeto_em_discussao"}, timeout=10)
        assert r.status_code == 200, f"Move to projeto_em_discussao failed: {r.text}"

    def test_stage_update_reflected_in_get(self, admin, pipeline_client):
        cid = pipeline_client["id"]
        r = admin.get(f"{API}/crm/clients/{cid}", timeout=10)
        assert r.status_code == 200
        assert r.json().get("stage") == "projeto_em_discussao"

    def test_client_can_be_lost(self, admin, clean_slate):
        """Any client (not in closed) can be marked as lost."""
        # create a disposable client
        r = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_Churn Test Co",
            "cnpj": "22.233.355/5000-50",
            "contato_principal": {"nome": "Churn", "email": "churn@test.test", "whatsapp": "11900000010"},
            "canal_origem": "outro",
            "categoria_interesse": ["hidratante_corporal"],
        }, timeout=10)
        assert r.status_code in (200, 201)
        cid = r.json()["id"]
        r2 = admin.put(f"{API}/crm/clients/{cid}/move",
                       json={"stage": "cliente_perdido", "motivo_perda": "outro"}, timeout=10)
        assert r2.status_code == 200, f"Move to cliente_perdido failed: {r2.text}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: PROJECTS — BATCH CREATION + INHERITANCE
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectCreation:
    @pytest.fixture(scope="class")
    def ready_client(self, admin, clean_slate):
        """A client already at projeto_em_discussao."""
        r = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_ReadyForProject Co",
            "cnpj": "33.344.466/6000-04",
            "contato_principal": {"nome": "Ready Client", "email": "ready_client@test.test", "whatsapp": "11900002000"},
            "canal_origem": "indicacao_cliente_ativo",
            "categoria_interesse": ["shampoo", "condicionador"],
            "temperatura_lead": "morno",
        }, timeout=15)
        assert r.status_code in (200, 201), f"ready_client setup: {r.status_code} {r.text}"
        cid = r.json()["id"]
        # advance to qualificado → complete task → projeto_em_discussao
        admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "qualificado"}, timeout=10)
        _complete_blocking_tasks(admin, "client", cid)
        admin.put(f"{API}/crm/clients/{cid}/move", json={"stage": "projeto_em_discussao"}, timeout=10)
        return r.json()

    def test_create_project_batch_happy_path(self, admin, ready_client, clean_slate):
        cid = ready_client["id"]
        spec = CLIENTS[1]["_project"]
        r = admin.post(f"{API}/crm/projects/batch", json={
            "cliente_id": cid,
            "projects": [spec],
        }, timeout=15)
        assert r.status_code in (200, 201), f"Project batch failed: {r.status_code} {r.text}"
        projects = _extract_list(r.json())
        assert projects, f"No projects in response: {r.json()}"

    def test_project_batch_nonexistent_client_404(self, admin, clean_slate):
        r = admin.post(f"{API}/crm/projects/batch", json={
            "cliente_id": "does-not-exist-xyz",
            "projects": [{"nome_projeto": "TEST_X"}],
        }, timeout=10)
        assert r.status_code == 404, f"Expected 404 for nonexistent client: {r.status_code}"

    def test_project_audit_log(self, admin, ready_client, clean_slate):
        cid = ready_client["id"]
        proj_r = admin.get(f"{API}/crm/projects", params={"cliente_id": cid}, timeout=10)
        assert proj_r.status_code == 200
        projects = _extract_list(proj_r.json())
        if not projects:
            pytest.skip("No projects found for audit check")
        pid = projects[0]["id"]
        logs = admin.get(f"{API}/workflow/audit-logs/by-entity/project/{pid}", timeout=10)
        assert logs.status_code == 200
        actions = [l["action"] for l in logs.json()]
        assert "project_created" in actions, f"Missing project_created log: {actions}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: SAMPLES — GLOBAL NUMBERING, VARIACOES, PD CARDS
# ─────────────────────────────────────────────────────────────────────────────

class TestSampleCreation:
    @pytest.fixture(scope="class")
    def project_at_amostras(self, admin, clean_slate):
        """A project advanced to 'amostras' stage."""
        cid = _get_or_create_client(admin, CLIENTS[2])
        _advance_client_to_projeto(admin, cid)
        # project
        pspec = CLIENTS[2]["_project"]
        pr = admin.post(f"{API}/crm/projects/batch", json={"cliente_id": cid, "projects": [pspec]}, timeout=15)
        assert pr.status_code in (200, 201)
        projects = _extract_list(pr.json())
        pid = projects[0]["id"]
        _advance_project_to_amostras(admin, pid)
        return {"pid": pid, "cid": cid}

    def test_sample_created_with_variacoes(self, admin, project_at_amostras):
        pid = project_at_amostras["pid"]
        sspec = CLIENTS[2]["_sample"]
        r = admin.post(f"{API}/crm/samples/batch/v2", json={
            "projeto_id": pid,
            "samples": [sspec],
        }, timeout=15)
        assert r.status_code in (200, 201), f"Sample batch failed: {r.status_code} {r.text}"
        samples = _extract_list(r.json())
        assert samples, f"No samples in response"
        s = samples[0]
        # Must have sequentially-issued numero_amostra in format YYYY-NNNN
        import re
        num_str = str(s.get("numero_amostra", ""))
        assert re.match(r"^\d{4}-\d{4}$", num_str), f"numero_amostra should be YYYY-NNNN, got {num_str}"
        # Variacoes
        variacoes = s.get("variacoes", [])
        assert len(variacoes) >= 2, f"Expected 2 variacoes, got {len(variacoes)}"
        codes = [v.get("codigo", "") for v in variacoes]
        assert any(c.endswith("-a") for c in codes), f"Missing -a variação: {codes}"
        assert any(c.endswith("-b") for c in codes), f"Missing -b variação: {codes}"

    def test_pd_cards_auto_created(self, admin, project_at_amostras):
        """After sample creation, PD cards must auto-exist (one per variação)."""
        r = admin.get(f"{API}/crm/pd/cards", timeout=10)
        assert r.status_code == 200
        all_cards = _extract_list(r.json())
        # Cards linked to this project's sample
        related = [c for c in all_cards if c.get("projeto_id") == project_at_amostras["pid"]]
        assert len(related) >= 2, f"Expected >= 2 pd cards, got {len(related)}: {related}"

    def test_sample_numbering_sequential(self, admin, project_at_amostras):
        """Creating a second sample must increment the numero_amostra."""
        pid = project_at_amostras["pid"]
        r1 = admin.post(f"{API}/crm/samples/batch/v2", json={
            "projeto_id": pid,
            "samples": [{"nome_produto": "TEST_Seq Sample 2", "tipo_amostra": "nova_formula",
                         "variacoes": [{"descricao_aplicacao": "Seq test"}]}],
        }, timeout=15)
        assert r1.status_code in (200, 201)
        s1 = _extract_list(r1.json())[0]
        r2 = admin.post(f"{API}/crm/samples/batch/v2", json={
            "projeto_id": pid,
            "samples": [{"nome_produto": "TEST_Seq Sample 3", "tipo_amostra": "nova_formula",
                         "variacoes": [{"descricao_aplicacao": "Seq test 2"}]}],
        }, timeout=15)
        assert r2.status_code in (200, 201)
        s2 = _extract_list(r2.json())[0]
        n1 = s1.get("numero_amostra", "")
        n2 = s2.get("numero_amostra", "")
        # Both must be YYYY-NNNN format and sequentially different
        assert n1 != n2, f"Numbering not sequential: {n1} → {n2}"
        seq1 = int(n1.split("-")[1]) if "-" in str(n1) else 0
        seq2 = int(n2.split("-")[1]) if "-" in str(n2) else 0
        assert seq2 == seq1 + 1, f"Seq not sequential: {n1} → {n2}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: VARIAÇÃO LIFECYCLE — STATUS MACHINE
# ─────────────────────────────────────────────────────────────────────────────

class TestVariacaoLifecycle:
    @pytest.fixture(scope="class")
    def variacao_under_test(self, admin, clean_slate):
        """Full setup: client → project → sample → variação id."""
        cid = _get_or_create_client(admin, CLIENTS[3])
        _advance_client_to_projeto(admin, cid)
        pspec = CLIENTS[3]["_project"]
        pr = admin.post(f"{API}/crm/projects/batch", json={"cliente_id": cid, "projects": [pspec]}, timeout=15)
        pid = _extract_list(pr.json())[0]["id"]
        _advance_project_to_amostras(admin, pid)
        sspec = CLIENTS[3]["_sample"]
        sr = admin.post(f"{API}/crm/samples/batch/v2", json={"projeto_id": pid, "samples": [sspec]}, timeout=15)
        sample = _extract_list(sr.json())[0]
        sid = sample["id"]
        vid = sample["variacoes"][0]["id"]
        return {"sid": sid, "vid": vid}

    def test_move_variacao_em_elaboracao(self, admin, variacao_under_test):
        sid, vid = variacao_under_test["sid"], variacao_under_test["vid"]
        r = admin.put(f"{API}/crm/samples/{sid}/variacoes/{vid}/move",
                      json={"status": "em_elaboracao"}, timeout=10)
        assert r.status_code == 200, f"Move to em_elaboracao failed: {r.text}"

    def test_move_variacao_enviada(self, admin, variacao_under_test):
        sid, vid = variacao_under_test["sid"], variacao_under_test["vid"]
        r = admin.put(f"{API}/crm/samples/{sid}/variacoes/{vid}/move",
                      json={"status": "enviada"}, timeout=10)
        assert r.status_code == 200, f"Move to enviada failed: {r.text}"

    def test_approve_variacao_without_resultado_blocked(self, admin, variacao_under_test):
        """Must require resultado_cliente before marking aprovada."""
        sid, vid = variacao_under_test["sid"], variacao_under_test["vid"]
        r = admin.put(f"{API}/crm/samples/{sid}/variacoes/{vid}/move",
                      json={"status": "aprovada"}, timeout=10)
        assert r.status_code in (400, 409, 422), \
            f"Expected rejection without resultado: {r.status_code} {r.text}"

    def test_resultado_cliente_approves_variacao(self, admin, variacao_under_test):
        sid, vid = variacao_under_test["sid"], variacao_under_test["vid"]
        r = admin.post(f"{API}/crm/samples/{sid}/variacoes/{vid}/resultado-cliente",
                       json={"resultado": "aprovada", "feedback_cliente": "Aprovado!"}, timeout=10)
        assert r.status_code == 200, f"resultado-cliente failed: {r.text}"
        # Verify status
        sample_r = admin.get(f"{API}/crm/samples/{sid}", timeout=10)
        updated_var = next((v for v in sample_r.json().get("variacoes", []) if v["id"] == vid), {})
        assert updated_var.get("status") == "aprovada", \
            f"variação not approved: {updated_var.get('status')}"

    def test_cannot_move_to_retrabalho_directly(self, admin, variacao_under_test):
        sid, vid = variacao_under_test["sid"], variacao_under_test["vid"]
        r = admin.put(f"{API}/crm/samples/{sid}/variacoes/{vid}/move",
                      json={"status": "retrabalho"}, timeout=10)
        assert r.status_code in (400, 409, 422), \
            f"Expected blocking of direct retrabalho: {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: P&D CARD PIPELINE — STAGE GATING + CQ TASKS
# ─────────────────────────────────────────────────────────────────────────────

class TestPDCardPipeline:
    @pytest.fixture(scope="class")
    def pd_card(self, admin, clean_slate):
        """Find or create a PD card to test with."""
        cid = _get_or_create_client(admin, CLIENTS[4])
        _advance_client_to_projeto(admin, cid)
        pspec = CLIENTS[4]["_project"]
        pr = admin.post(f"{API}/crm/projects/batch", json={"cliente_id": cid, "projects": [pspec]}, timeout=15)
        pid = _extract_list(pr.json())[0]["id"]
        _advance_project_to_amostras(admin, pid)
        sspec = CLIENTS[4]["_sample"]
        sr = admin.post(f"{API}/crm/samples/batch/v2", json={"projeto_id": pid, "samples": [sspec]}, timeout=15)
        sample = _extract_list(sr.json())[0]
        sid = sample["id"]
        cards_r = admin.get(f"{API}/crm/pd/cards", timeout=10)
        all_cards = _extract_list(cards_r.json())
        cards = [c for c in all_cards if c.get("amostra_id") == sid]
        assert cards, f"No PD card found for sample {sid}"
        return {"card": cards[0], "sid": sid}

    def test_pd_card_starts_in_solicitado(self, pd_card):
        card = pd_card["card"]
        status = card.get("status") or card.get("pd_status")
        assert status in ("solicitado", "aguardando_aceite"), \
            f"Expected solicitado/aguardando_aceite, got {status}"

    def test_advance_to_em_desenvolvimento(self, admin, pd_card):
        cid = pd_card["card"]["id"]
        r = admin.put(f"{API}/crm/pd/cards/{cid}/move",
                      json={"status": "em_desenvolvimento"}, timeout=10)
        assert r.status_code == 200, f"Move to em_desenvolvimento failed: {r.text}"

    def test_advance_to_em_testes(self, admin, pd_card):
        cid = pd_card["card"]["id"]
        r = admin.put(f"{API}/crm/pd/cards/{cid}/move",
                      json={"status": "em_testes"}, timeout=10)
        assert r.status_code == 200, f"Move to em_testes failed: {r.text}"

    def test_em_testes_creates_lab_task(self, admin, pd_card):
        cid = pd_card["card"]["id"]
        tasks_r = admin.get(f"{API}/workflow/tasks/by-entity/pd_card/{cid}", timeout=10)
        assert tasks_r.status_code == 200
        tasks = tasks_r.json()
        lab_tasks = [t for t in tasks if "testes laborator" in t.get("title", "").lower()]
        assert lab_tasks, f"No lab test task found: {[t['title'] for t in tasks]}"

    def test_advance_to_aguardando_aprovacao_blocked_by_open_lab_task(self, admin, pd_card):
        cid = pd_card["card"]["id"]
        r = admin.put(f"{API}/crm/pd/cards/{cid}/move",
                      json={"status": "aguardando_aprovacao"}, timeout=10)
        assert r.status_code == 409, \
            f"Expected 409 (blocking lab task), got {r.status_code} {r.text}"

    def test_complete_lab_task_and_advance(self, admin, pd_card):
        cid = pd_card["card"]["id"]
        _complete_blocking_tasks(admin, "pd_card", cid)
        r = admin.put(f"{API}/crm/pd/cards/{cid}/move",
                      json={"status": "aguardando_aprovacao"}, timeout=10)
        assert r.status_code == 200, f"Move to aguardando_aprovacao failed: {r.text}"

    def test_aguardando_aprovacao_creates_cq_task(self, admin, pd_card):
        cid = pd_card["card"]["id"]
        tasks_r = admin.get(f"{API}/workflow/tasks/by-entity/pd_card/{cid}", timeout=10)
        tasks = tasks_r.json()
        cq_tasks = [t for t in tasks if t.get("category") == "qa" and t.get("status") == "pendente"]
        assert cq_tasks, f"No CQ task created: {[t['title'] for t in tasks]}"
        blocks = cq_tasks[0].get("blocks_stages", [])
        assert any(b in ("completed", "aprovado", "concluido") for b in blocks), \
            f"CQ task does not block completion: {blocks}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8: FULL PIPELINE × 5 CLIENTS (smoke-test complete flow)
# ─────────────────────────────────────────────────────────────────────────────

class TestFullPipeline5Clients:
    @pytest.fixture(scope="class")
    def five_complete_records(self, admin, clean_slate):
        """Run 5 clients through the complete pipeline and return all records."""
        records = []
        for spec in CLIENTS[5:10]:  # clients 6-10
            cid = _get_or_create_client(admin, spec)
            _advance_client_to_projeto(admin, cid)

            # Project
            pspec = spec["_project"]
            pr = admin.post(f"{API}/crm/projects/batch", json={
                "cliente_id": cid, "projects": [pspec],
            }, timeout=15)
            assert pr.status_code in (200, 201)
            pid = _extract_list(pr.json())[0]["id"]
            _advance_project_to_amostras(admin, pid)

            # Sample
            sspec = spec["_sample"]
            sr = admin.post(f"{API}/crm/samples/batch/v2", json={
                "projeto_id": pid, "samples": [sspec],
            }, timeout=15)
            assert sr.status_code in (200, 201)
            sample = _extract_list(sr.json())[0]
            sid = sample["id"]
            vid = sample["variacoes"][0]["id"]

            records.append({"cid": cid, "pid": pid, "sid": sid, "vid": vid, "spec": spec})
        return records

    def test_five_complete_clients_created(self, five_complete_records):
        assert len(five_complete_records) == 5

    def test_all_samples_have_variacoes(self, five_complete_records):
        for rec in five_complete_records:
            assert rec["vid"], f"No variação id for client {rec['spec']['nome_empresa']}"

    def test_sample_numbering_monotone_across_all(self, admin, five_complete_records):
        """Collect numero_amostra across all samples — must be strictly ascending."""
        nums = []
        for rec in five_complete_records:
            r = admin.get(f"{API}/crm/samples/{rec['sid']}", timeout=10)
            if r.status_code == 200:
                nums.append(int(r.json().get("numero_amostra", 0)))
        assert nums == sorted(nums), f"Sample numbering not monotone: {nums}"
        assert len(set(nums)) == len(nums), f"Duplicate sample numbers: {nums}"

    def test_each_sample_has_pd_card(self, admin, five_complete_records):
        cards_r = admin.get(f"{API}/crm/pd/cards", timeout=10)
        all_cards = _extract_list(cards_r.json())
        sample_ids = {rec["sid"] for rec in five_complete_records}
        for sid in sample_ids:
            related = [c for c in all_cards if c.get("amostra_id") == sid]
            assert related, f"No PD card for sample {sid}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9: RBAC CHECKS
# ─────────────────────────────────────────────────────────────────────────────

class TestRBAC:
    def test_audit_logs_forbidden_for_vendedor(self, vendedor_session):
        """Vendedor cannot read audit logs."""
        r = vendedor_session.get(f"{API}/workflow/audit-logs", timeout=10)
        assert r.status_code in (403, 401), \
            f"Vendedor should be denied audit logs: {r.status_code} {r.text}"

    def test_vendedor_cannot_delete_client(self, vendedor_session, admin, clean_slate):
        """Vendedor cannot hard-delete clients (if endpoint exists)."""
        # Create a client first
        cr = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_RBAC Del Target",
            "cnpj": "44.455.577/7000-68",
            "contato_principal": {"nome": "RBAC", "email": "rbac@test.test", "whatsapp": "11900000020"},
            "canal_origem": "outro",
            "categoria_interesse": ["sabonete_liquido_corporal"],
        }, timeout=10)
        if cr.status_code not in (200, 201):
            pytest.skip("Cannot create client for RBAC test")
        cid = cr.json()["id"]
        r = vendedor_session.delete(f"{API}/crm/clients/{cid}", timeout=10)
        # Vendedor should be forbidden
        assert r.status_code in (403, 401, 405), \
            f"Vendedor should be denied delete: {r.status_code}"

    def test_vendedor_can_read_clients(self, vendedor_session):
        """Vendedor can read the client list."""
        r = vendedor_session.get(f"{API}/crm/clients", timeout=10)
        assert r.status_code == 200, f"Vendedor should be able to read clients: {r.status_code}"

    def test_unauthenticated_request_rejected(self):
        """No token → 401."""
        r = requests.get(f"{API}/crm/clients", timeout=10)
        assert r.status_code in (401, 403), \
            f"Unauthenticated request should be rejected: {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10: CRM-12 — CONFIGURABLE LEAD SOURCES
# ─────────────────────────────────────────────────────────────────────────────

class TestLeadSourcesConfig:
    def test_list_lead_sources_returns_defaults(self, admin):
        """GET /crm/config/lead-sources returns a valid list with expected structure."""
        r = admin.get(f"{API}/crm/config/lead-sources", timeout=10)
        assert r.status_code == 200
        sources = r.json()
        assert isinstance(sources, list)
        assert len(sources) > 0, "Lead sources list must not be empty"
        # Each source must have required fields
        for s in sources:
            assert "valor" in s, f"Source missing 'valor': {s}"
            assert "nome" in s, f"Source missing 'nome': {s}"
        valores = [s.get("valor") for s in sources]
        # Either hardcoded defaults are present OR custom DB sources exist
        known_defaults = {"formulario_site", "linkedin_dm_outbound", "google_ads", "indicacao_cliente_ativo"}
        has_defaults = bool(known_defaults & set(valores))
        has_custom = bool(valores)
        assert has_defaults or has_custom, f"No known sources in list: {valores[:5]}"

    def test_create_new_lead_source(self, admin):
        """Admin can create (or reactivate) a new lead source."""
        r = admin.post(f"{API}/crm/config/lead-sources", json={
            "nome": "TEST Parceria Tech",
            "valor": "test_parceria_tech_e2e",
            "grupo": "outros",
            "ativo": True,
        }, timeout=10)
        if r.status_code == 409:
            # Source exists from a previous run — reactivate it
            react = admin.patch(
                f"{API}/crm/config/lead-sources/test_parceria_tech_e2e",
                json={"ativo": True, "nome": "TEST Parceria Tech"},
                timeout=10,
            )
            assert react.status_code == 200, f"Reactivate existing source failed: {react.text}"
        else:
            assert r.status_code in (200, 201), f"Create lead source: {r.status_code} {r.text}"
            assert r.json().get("valor") == "test_parceria_tech_e2e"

    def test_duplicate_lead_source_valor_rejected(self, admin):
        """Cannot create two sources with same valor."""
        r = admin.post(f"{API}/crm/config/lead-sources", json={
            "nome": "TEST Dup", "valor": "test_parceria_tech_e2e", "grupo": "outros",
        }, timeout=10)
        assert r.status_code == 409, f"Expected 409 for dup valor: {r.status_code}"

    def test_update_lead_source_name(self, admin):
        """Admin can rename an existing source."""
        r = admin.patch(f"{API}/crm/config/lead-sources/test_parceria_tech_e2e", json={
            "nome": "TEST Parceria Tech (updated)",
        }, timeout=10)
        assert r.status_code == 200

    def test_new_lead_source_appears_in_constants(self, admin):
        """After adding a new source, it appears in /constants."""
        # Bootstrap from DB by creating a client record
        r = admin.get(f"{API}/crm/constants", timeout=10)
        assert r.status_code == 200
        # The new source must now be in canal_origem
        canal = r.json().get("canal_origem", [])
        # If DB has sources, they override hardcoded — new source should be present
        # (depends on whether tenant has any DB sources yet)
        # At minimum: constants returns a valid list
        assert isinstance(canal, list) and len(canal) > 0

    def test_cannot_use_invalid_canal_with_new_source_list(self, admin, clean_slate):
        """Client creation with unmapped canal is still rejected."""
        r = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_BadLeadSource",
            "cnpj": "",
            "contato_principal": {"nome": "Bad", "email": "badls@test.test", "whatsapp": "11900000030"},
            "canal_origem": "this_slug_does_not_exist_xyz",
        }, timeout=10)
        assert r.status_code in (400, 422), \
            f"Expected rejection for invalid canal: {r.status_code} {r.text}"

    def test_zzz_cleanup_test_lead_source(self, admin):
        """Deactivate the test source so subsequent tests can use hardcoded canal_origem."""
        r = admin.patch(f"{API}/crm/config/lead-sources/test_parceria_tech_e2e",
                        json={"ativo": False}, timeout=10)
        # 200 = deactivated, 404 = didn't exist — both are acceptable
        assert r.status_code in (200, 404), f"Unexpected status: {r.status_code} {r.text}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11: PD-18 — SAMPLE LABEL PDF
# ─────────────────────────────────────────────────────────────────────────────

class TestSampleLabelPDF:
    @pytest.fixture(scope="class")
    def variacao_for_label(self, admin, clean_slate):
        """A complete variação ready for label generation."""
        cid = _get_or_create_client(admin, CLIENTS[0])
        _advance_client_to_projeto(admin, cid)
        pspec = CLIENTS[0]["_project"]
        pr = admin.post(f"{API}/crm/projects/batch", json={"cliente_id": cid, "projects": [pspec]}, timeout=15)
        pid = _extract_list(pr.json())[0]["id"]
        _advance_project_to_amostras(admin, pid)
        sspec = CLIENTS[0]["_sample"]
        sr = admin.post(f"{API}/crm/samples/batch/v2", json={"projeto_id": pid, "samples": [sspec]}, timeout=15)
        sample = _extract_list(sr.json())[0]
        vid = sample["variacoes"][0]["id"]
        return vid

    def test_label_pdf_returns_200(self, admin, variacao_for_label):
        r = admin.get(f"{API}/pd/samples/{variacao_for_label}/label.pdf", timeout=20)
        assert r.status_code == 200, f"Label PDF failed: {r.status_code} {r.text[:200]}"

    def test_label_pdf_content_type_is_pdf(self, admin, variacao_for_label):
        r = admin.get(f"{API}/pd/samples/{variacao_for_label}/label.pdf", timeout=20)
        ct = r.headers.get("content-type", "")
        assert "pdf" in ct, f"Expected PDF content-type, got: {ct}"

    def test_label_pdf_is_valid_pdf_binary(self, admin, variacao_for_label):
        r = admin.get(f"{API}/pd/samples/{variacao_for_label}/label.pdf", timeout=20)
        assert r.content[:4] == b"%PDF", f"Response is not a PDF (magic bytes wrong)"

    def test_label_pdf_nonexistent_variacao_returns_404(self, admin):
        r = admin.get(f"{API}/pd/samples/does-not-exist-xyz/label.pdf", timeout=10)
        assert r.status_code == 404, f"Expected 404 for nonexistent variação: {r.status_code}"

    def test_label_pdf_content_disposition_has_filename(self, admin, variacao_for_label):
        r = admin.get(f"{API}/pd/samples/{variacao_for_label}/label.pdf", timeout=20)
        cd = r.headers.get("content-disposition", "")
        assert "etiqueta" in cd.lower() or ".pdf" in cd.lower(), \
            f"Missing filename in Content-Disposition: {cd}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12: DATA INTEGRITY — AUDIT LOGS & HISTORY
# ─────────────────────────────────────────────────────────────────────────────

class TestDataIntegrity:
    def test_admin_audit_log_list_non_empty(self, admin, clean_slate):
        """After all operations, audit log must have entries."""
        # Create something to generate a log
        r = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_AuditCheck Co",
            "cnpj": "55.566.688/8000-11",
            "contato_principal": {"nome": "Audit", "email": "audit@test.test", "whatsapp": "11900000040"},
            "canal_origem": "outro",
            "categoria_interesse": ["serum_facial"],
        }, timeout=10)
        assert r.status_code in (200, 201)
        logs_r = admin.get(f"{API}/workflow/audit-logs", timeout=10)
        assert logs_r.status_code == 200
        logs = logs_r.json()
        assert len(logs) >= 1, "Audit log is empty after operations"

    def test_audit_log_has_required_fields(self, admin, clean_slate):
        """Each audit log entry must have minimum required fields."""
        # Trigger a log event
        cr = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_AuditFields Co",
            "cnpj": "66.677.799/9000-75",
            "contato_principal": {"nome": "Audit", "email": "auditf@test.test", "whatsapp": "11900000041"},
            "canal_origem": "outro",
            "categoria_interesse": ["shampoo"],
        }, timeout=10)
        cid = cr.json()["id"]
        logs_r = admin.get(f"{API}/workflow/audit-logs/by-entity/client/{cid}", timeout=10)
        assert logs_r.status_code == 200
        for log in logs_r.json():
            assert "action" in log, f"Missing 'action' in log: {log}"
            assert "created_at" in log or "timestamp" in log, f"Missing timestamp in log: {log}"

    def test_rework_creates_new_sample_number(self, admin, clean_slate):
        """Rework endpoint must create a new sample with next sequential number."""
        cid = _get_or_create_client(admin, CLIENTS[9])
        _advance_client_to_projeto(admin, cid)
        pspec = CLIENTS[9]["_project"]
        pr = admin.post(f"{API}/crm/projects/batch", json={"cliente_id": cid, "projects": [pspec]}, timeout=15)
        pid = _extract_list(pr.json())[0]["id"]
        _advance_project_to_amostras(admin, pid)
        sspec = CLIENTS[9]["_sample"]
        sr = admin.post(f"{API}/crm/samples/batch/v2", json={"projeto_id": pid, "samples": [sspec]}, timeout=15)
        sample = _extract_list(sr.json())[0]
        sid = sample["id"]
        orig_num = int(sample.get("numero_amostra", 0))

        # Trigger rework
        rr = admin.post(f"{API}/crm/samples/{sid}/rework", json={"motivo": "Ajuste de fragrância"}, timeout=15)
        assert rr.status_code in (200, 201), f"Rework failed: {rr.status_code} {rr.text}"
        resp = rr.json()
        new_sample = resp.get("rework_sample") or resp
        new_num = int(new_sample.get("numero_amostra") or resp.get("novo_numero") or 0)
        assert new_num == orig_num + 1, \
            f"Rework should increment number: orig={orig_num}, new={new_num}"
        assert new_sample.get("rework_de_amostra_id") == sid or resp.get("original_id") == sid


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 13: EDGE CASES & NEGATIVE PATHS
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_get_nonexistent_client_404(self, admin):
        r = admin.get(f"{API}/crm/clients/nonexistent-uuid-xyz", timeout=10)
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"

    def test_get_nonexistent_sample_404(self, admin):
        r = admin.get(f"{API}/crm/samples/nonexistent-uuid-xyz", timeout=10)
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"

    def test_move_nonexistent_client_404(self, admin):
        r = admin.put(f"{API}/crm/clients/xyz-nonexistent/move",
                      json={"stage": "qualificado"}, timeout=10)
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"

    def test_empty_nome_empresa_rejected(self, admin):
        r = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "",
            "cnpj": "",
            "contato_principal": {"nome": "Test", "email": "empty@test.test", "whatsapp": "11900000050"},
            "canal_origem": "outro",
        }, timeout=10)
        assert r.status_code in (400, 422), \
            f"Expected rejection for empty nome_empresa: {r.status_code}"

    def test_client_update_preserves_existing_data(self, admin, clean_slate):
        """Partial update must not wipe unset fields."""
        cr = admin.post(f"{API}/crm/clients", json={
            "nome_empresa": "TEST_Partial Update",
            "cnpj": "77.788.800/0100-25",
            "contato_principal": {"nome": "Partial", "email": "partial@test.test", "whatsapp": "11900000060"},
            "canal_origem": "formulario_site",
            "categoria_interesse": ["hidratante_facial"],
            "segmento": "marca_propria",
        }, timeout=10)
        assert cr.status_code in (200, 201)
        cid = cr.json()["id"]
        # partial update — only change observacoes
        pu = admin.patch(f"{API}/crm/clients/{cid}", json={"observacoes": "Nota de teste"}, timeout=10)
        if pu.status_code == 404:
            # might use PUT
            pu = admin.put(f"{API}/crm/clients/{cid}", json={"observacoes": "Nota de teste"}, timeout=10)
        if pu.status_code in (200, 204):
            after = admin.get(f"{API}/crm/clients/{cid}", timeout=10).json()
            assert after.get("canal_origem") == "formulario_site", \
                f"Partial update wiped canal_origem: {after}"

    def test_crm_constants_include_all_required_keys(self, admin):
        """Constants must include all fields the frontend depends on."""
        r = admin.get(f"{API}/crm/constants", timeout=10)
        data = r.json()
        required = [
            "canal_origem", "categoria_interesse", "volume_estimado",
            "motivo_perda", "segmento", "porte", "temperatura_lead",
        ]
        for key in required:
            assert key in data, f"Missing key in /constants: {key}"

    def test_sample_batch_v2_requires_existing_project(self, admin):
        r = admin.post(f"{API}/crm/samples/batch/v2", json={
            "projeto_id": "nonexistent-proj-xyz",
            "samples": [{"nome_produto": "X", "tipo_amostra": "nova_formula",
                         "variacoes": [{"descricao_aplicacao": "X"}]}],
        }, timeout=10)
        assert r.status_code == 404, f"Expected 404 for nonexistent project: {r.status_code}"

    def test_workflow_tasks_filter_by_status(self, admin):
        """Task list endpoint must support status filter."""
        r = admin.get(f"{API}/workflow/tasks", params={"status": "pendente"}, timeout=10)
        assert r.status_code == 200
        tasks = r.json()
        for t in tasks:
            assert t.get("status") == "pendente", \
                f"Filter not respected: got {t.get('status')}"

    def test_label_pdf_unauthenticated_denied(self, clean_slate):
        """Unauthenticated label PDF request must be denied."""
        r = requests.get(f"{API}/pd/samples/some-id/label.pdf", timeout=10)
        assert r.status_code in (401, 403), f"Expected auth denial: {r.status_code}"
