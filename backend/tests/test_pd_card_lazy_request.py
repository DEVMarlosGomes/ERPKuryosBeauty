"""
Backend tests for "P&D card click → full PDDetail" feature.

Coverage (per review_request iteration 11):
  1. GET /api/crm/pd/cards/{id} on a card without pd_request_id auto-creates
     a pd_request and returns the card with pd_request_id populated.
  2. Repeated GETs are idempotent (no duplicates created).
  3. GET /api/pd/requests/{id}/full returns client_info built from crm_samples
     when the pd_request comes from a sample variation.
  4. Adding a new variation (POST /api/crm/samples/{id}/variacoes) auto-creates
     pd_card + pd_request together — newly returned cards have pd_request_id.
  5. The auto-created pd_request has correct fields (status, request_type,
     linked_*_id, internal_code, description, volume).
  6. No regression: the historical CRM end-to-end fixture (Bella / 101 / SKU
     KRY-001) is still intact.
"""
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)

# Pre-existing fixtures from the manual session (do NOT recreate)
SAMPLE_ID = "e6d83c4b-5687-4f36-ac5f-6a4e5aea07cc"
CLIENTE_ID = "60f9d0b1-43b5-4d54-83c4-d855bc18214f"
PROJETO_ID = "0dff86d9-e2f2-4951-8a8e-d85dc13e82f2"
CARD_101A_ID = "b05e3d81-f12c-4d5b-a943-9f0273e99d3f"
CARD_101B_ID = "dc00f1d2-25e2-4cda-b6dc-9f7eaf2a4cce"  # ID prefix from problem statement


# ------------------------- fixtures ---------------------------------- #

@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@kuryos.com", "password": "admin123"},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def card_101a_pd_request_id(admin_session):
    """Resolve pd_request_id of card 101/A (already lazy-created in manual run)."""
    r = admin_session.get(f"{BASE_URL}/api/crm/pd/cards/{CARD_101A_ID}")
    if r.status_code == 404:
        pytest.skip(f"historical card fixture not present in this database: {CARD_101A_ID}")
    assert r.status_code == 200, r.text
    pd_id = r.json().get("pd_request_id")
    assert pd_id, "card 101/A should have pd_request_id after lazy-create"
    return pd_id


# ----------- 1 + 2: lazy creation + idempotency ---------------------- #

class TestLazyPDRequestCreation:
    """Auto-creation of pd_request when GET hits a CRM-variation card."""

    def test_card_101a_returns_pd_request_id(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/crm/pd/cards/{CARD_101A_ID}")
        if r.status_code == 404:
            pytest.skip(f"historical card fixture not present in this database: {CARD_101A_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == CARD_101A_ID
        assert body.get("pd_request_id"), "pd_request_id must be present after GET"
        assert body.get("numero_completo") == "101/A"
        assert body.get("amostra_id") == SAMPLE_ID
        assert body.get("amostra_variacao_id"), "must link to variacao"

    def test_repeated_get_is_idempotent(self, admin_session):
        # Capture pd_request_id 3 times — must always be the SAME id.
        ids = []
        for _ in range(3):
            r = admin_session.get(f"{BASE_URL}/api/crm/pd/cards/{CARD_101A_ID}")
            if r.status_code == 404:
                pytest.skip(f"historical card fixture not present in this database: {CARD_101A_ID}")
            assert r.status_code == 200
            ids.append(r.json()["pd_request_id"])
        assert len(set(ids)) == 1, f"GET created duplicate pd_requests: {ids}"


# ----------- 3: /full mounts client_info from crm_sample ------------- #

class TestPDRequestFullClientInfo:
    """/api/pd/requests/{id}/full builds client_info from crm_samples."""

    def test_full_returns_client_info_from_crm_sample(
        self, admin_session, card_101a_pd_request_id
    ):
        r = admin_session.get(
            f"{BASE_URL}/api/pd/requests/{card_101a_pd_request_id}/full"
        )
        assert r.status_code == 200
        ci = r.json().get("client_info")
        assert ci, "client_info must not be null for CRM-variation pd_request"

        # Required fields per problem statement
        assert ci.get("_source") == "crm_sample"
        assert ci.get("_variacao_codigo") == "101/A"
        for k in [
            "produto",
            "nome_cliente",
            "nome_projeto",
            "textura_esperada",
            "aplicacao",
            "sensorial",
            "ph",
            "objetivo_projeto",
            "ativos_claims",
        ]:
            assert k in ci, f"missing client_info field: {k}"

        # Spot-check actual values from the seed (Bella Cosmética / 101 / shampoo)
        assert "Bella" in (ci.get("nome_cliente") or "")
        assert ci.get("produto"), "produto should be populated"
        assert ci.get("ph"), "ph should be populated"

    def test_full_returns_pd_request_metadata(
        self, admin_session, card_101a_pd_request_id
    ):
        r = admin_session.get(
            f"{BASE_URL}/api/pd/requests/{card_101a_pd_request_id}/full"
        )
        assert r.status_code == 200
        req = r.json().get("request")
        assert req, "/full must return 'request' object"
        assert req["id"] == card_101a_pd_request_id
        assert req.get("status") == "OPEN"
        assert req.get("request_type") == "Amostra"
        assert req.get("linked_amostra_id") == SAMPLE_ID
        assert req.get("linked_variacao_id"), "linked_variacao_id should be set"
        assert req.get("linked_pd_card_id") == CARD_101A_ID
        assert req.get("internal_code") == "101/A"
        assert req.get("description"), "description should not be empty"
        # A9: quantidade_por_variacao/unidade_quantidade saiu da criação de amostras.
        # volume vem de quantidade_por_variacao+unidade quando presente (dados legados),
        # senão cai no placeholder "A definir" — nunca fica vazio.
        assert req.get("volume"), "volume should be populated (from sample or placeholder)"


# ----------- 4 + 5: new variacao auto-creates card+request ----------- #

class TestNewVariationAutoCreatesPDRequest:
    """POST /api/crm/samples/{id}/variacoes → new pd_card + pd_request."""

    def test_add_new_variacao_creates_card_and_pd_request(self, admin_session):
        # Add a new variation. The endpoint generates the next letter (D, E, ...)
        payload = {
            "variacoes": [
                {
                    "descricao_aplicacao": "TEST_iter11 nova variação para validar lazy pd_request",
                    "percentual_fragrancia": 1.0,
                    "referencia_fragrancia": "TEST_REF",
                    "observacoes_especificas": "Criada pelo teste automatizado iter11",
                }
            ]
        }
        existing_sample = admin_session.get(f"{BASE_URL}/api/crm/samples/{SAMPLE_ID}")
        if existing_sample.status_code == 404:
            pytest.skip(f"historical sample fixture not present in this database: {SAMPLE_ID}")
        r = admin_session.post(
            f"{BASE_URL}/api/crm/samples/{SAMPLE_ID}/variacoes", json=payload
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("added") == 1
        new_vars = body.get("new_variacoes") or []
        assert len(new_vars) == 1
        new_var = new_vars[0]
        codigo = new_var["codigo"]
        variacao_id = new_var["id"]
        assert codigo.startswith("101/")

        # The endpoint auto-creates the pd_card. List cards filtered by sample
        # and find the freshly-created one.
        r2 = admin_session.get(f"{BASE_URL}/api/crm/pd/cards")
        assert r2.status_code == 200
        cards = r2.json()
        match = next(
            (c for c in cards if c.get("amostra_variacao_id") == variacao_id),
            None,
        )
        assert match, f"pd_card for variacao {codigo} not found"

        # Newly-created card MUST carry pd_request_id immediately.
        assert match.get("pd_request_id"), (
            "new card must already have pd_request_id (eager auto-create on POST)"
        )
        assert match["numero_completo"] == codigo
        assert match["amostra_id"] == SAMPLE_ID

        # Verify the pd_request itself
        pd_id = match["pd_request_id"]
        r3 = admin_session.get(f"{BASE_URL}/api/pd/requests/{pd_id}/full")
        assert r3.status_code == 200, r3.text
        full = r3.json()
        req = full["request"]
        assert req["status"] == "OPEN"
        assert req["request_type"] == "Amostra"
        assert req["internal_code"] == codigo
        assert req["linked_amostra_id"] == SAMPLE_ID
        assert req["linked_variacao_id"] == variacao_id
        assert req["linked_pd_card_id"] == match["id"]
        # description should be non-empty (briefing concatenation)
        assert req.get("description"), "description must be populated"
        # A9: sem quantidade_por_variacao (removida da criação), cai no placeholder "A definir"
        assert req.get("volume"), "volume must be populated (from sample or placeholder)"

        ci = full.get("client_info") or {}
        assert ci.get("_source") == "crm_sample"
        assert ci.get("_variacao_codigo") == codigo


# ----------- 6: regression — existing CRM data intact --------------- #

class TestNoRegression:
    """Existing CRM end-to-end fixture is unchanged."""

    def test_sample_101_still_intact(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/crm/samples/{SAMPLE_ID}")
        if r.status_code == 404:
            pytest.skip(f"historical sample fixture not present in this database: {SAMPLE_ID}")
        assert r.status_code == 200
        sample = r.json()
        assert sample.get("numero_amostra") == "101"
        assert sample.get("cliente_id") == CLIENTE_ID
        assert sample.get("projeto_id") == PROJETO_ID
        # Should still have at least 2 variations (101/A + 101/B + any added by tests)
        variacoes = sample.get("variacoes") or []
        assert len(variacoes) >= 2
        codigos = [v["codigo"] for v in variacoes]
        assert "101/A" in codigos
        assert "101/B" in codigos

    def test_sku_kry_001_still_exists(self, admin_session):
        # SKU was generated when 101/A got approved — confirm it still exists.
        r = admin_session.get(f"{BASE_URL}/api/crm/skus")
        assert r.status_code == 200
        skus = r.json()
        if isinstance(skus, dict):
            skus = skus.get("items") or skus.get("skus") or []
        codigos = [s.get("codigo_sku") or s.get("sku_code") or s.get("codigo_interno") for s in skus]
        if not any(c and "KRY-001" in c for c in codigos):
            sample = admin_session.get(f"{BASE_URL}/api/crm/samples/{SAMPLE_ID}")
            if sample.status_code == 404:
                pytest.skip(f"historical sample fixture not present in this database: {SAMPLE_ID}")
        assert any(
            c and "KRY-001" in c for c in codigos
        ), f"KRY-001 SKU missing — possible regression. SKUs found: {codigos}"
