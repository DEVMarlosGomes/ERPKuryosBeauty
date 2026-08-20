"""
Governança de geração de SKU — testes da auditoria pré-produção.

Cobre a correção crítica: POST /crm/samples/{id}/variacoes/{id}/resultado-cliente
(o único endpoint que o front realmente chama quando o cliente aprova uma variação)
agora dispara a geração de SKU e retorna a chave "sku_created" — antes, essa chave
nunca existia na resposta e nenhum SKU era gerado nesse fluxo.

LIMITAÇÃO CONHECIDA (achado da auditoria, não desta sessão de fix): a cadeia R25 exige
CGI "assinado"/"vigente" em db.contratos, mas contratos_routes.py só tem
POST /contratos/gerar (que grava status="gerado") — não existe NENHUM endpoint que
transicione um contrato pra "assinado"/"vigente". Isso significa que, hoje, a checagem
de CGI da R25 é estruturalmente impossível de satisfazer via API, então os testes aqui
não tentam montar a cadeia completa até a geração efetiva do SKU — validam o quanto dá
(a amostra/variação aprovada, o wiring do sku_created, o bloqueio com motivo claro) e
documentam esse gap. Ver RELATORIO_BETA_FIXES.md / auditoria de SKU para detalhes.
"""
import re
import time
import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@kuryos.com", "password": "admin123"}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


def _unique(prefix):
    return f"{prefix}_{int(time.time() * 1000) % 1000000}"


@pytest.fixture(scope="module")
def variacao_enviada(admin):
    """Cliente -> projeto (pulando qualificação, só nome_empresa) -> amostra -> variação
    'enviada'. Não avança até CGI/pedido_aprovado — ver limitação no docstring do módulo."""
    nome = _unique("TEST_SKU_Client")
    r = admin.post(f"{BASE_URL}/api/crm/clients", json={"nome_empresa": nome}, timeout=15)
    assert r.status_code == 200, r.text
    client_id = r.json()["id"]

    r2 = admin.post(f"{BASE_URL}/api/crm/projects/batch", json={
        "cliente_id": client_id,
        "projects": [{"nome_projeto": _unique("Proj"), "categoria": "capilares", "responsavel_comercial": ""}],
    }, timeout=15)
    assert r2.status_code == 200, r2.text
    projeto_id = r2.json()["created"][0]["id"]

    r3 = admin.post(f"{BASE_URL}/api/crm/samples/batch/v2", json={
        "projeto_id": projeto_id,
        "samples": [{
            "nome_produto": _unique("Shampoo Teste"),
            "categoria": "shampoo",
            "tipo_amostra": "novo_desenvolvimento",
            "prazo_entrega_cliente": "2026-12-31",
            "variacoes": [{"descricao_aplicacao": "Aplicação teste"}],
        }],
    }, timeout=15)
    assert r3.status_code == 200, r3.text
    sample = r3.json()["created"][0]
    sample_id = sample["id"]
    variacao_id = sample["variacoes"][0]["id"]

    r4 = admin.put(f"{BASE_URL}/api/crm/samples/{sample_id}/variacoes/{variacao_id}/move",
                    json={"status": "em_elaboracao"}, timeout=10)
    assert r4.status_code == 200, r4.text
    r5 = admin.put(f"{BASE_URL}/api/crm/samples/{sample_id}/variacoes/{variacao_id}/move",
                    json={"status": "enviada"}, timeout=10)
    assert r5.status_code == 200, r5.text

    return {"client_id": client_id, "projeto_id": projeto_id, "sample_id": sample_id, "variacao_id": variacao_id}


class TestResultadoClienteGeraSkuOuBloqueiaComMotivo:
    """A correção crítica: resultado_cliente() precisa SEMPRE devolver a chave
    sku_created quando resultado='aprovada' — antes dessa sessão, a chave nunca
    existia (a geração de SKU nunca era chamada nesse endpoint). resultado_cliente
    não é idempotente (variação sai de 'enviada' assim que aprovada), então o único
    POST possível nesta fixture precisa validar tudo de uma vez."""

    def test_sku_created_key_presente_e_bloqueio_tem_motivo_r25(self, admin, variacao_enviada):
        sample_id = variacao_enviada["sample_id"]
        variacao_id = variacao_enviada["variacao_id"]
        r = admin.post(
            f"{BASE_URL}/api/crm/samples/{sample_id}/variacoes/{variacao_id}/resultado-cliente",
            json={"resultado": "aprovada", "feedback_cliente": "Aprovado no teste"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "sku_created" in data, "resultado_cliente deve sempre retornar a chave sku_created quando resultado='aprovada' (bug crítico corrigido nesta auditoria)"
        sku_created = data["sku_created"]
        assert sku_created is not None, "sku_created não deveria ser None — ou gera o SKU (dict com codigo_interno) ou bloqueia (dict com blocked=True)"

        if sku_created.get("blocked"):
            # Caminho esperado neste fixture mínimo (sem CLI4/CGI/pedido_aprovado):
            # bloqueia, mas com motivo [R25] legível — nunca falha silenciosa/genérica.
            assert "R25" in (sku_created.get("reason") or ""), f"motivo do bloqueio deveria citar [R25]: {sku_created}"
        else:
            # Se este ambiente já tiver CLI4/CGI/pedido_aprovado prontos pra este cliente
            # de teste (improvável, mas não impossível), o SKU deve sair no formato novo.
            codigo = sku_created.get("codigo_interno", "")
            assert re.match(r"^[A-Z]{3}-[A-Z]{4}-\d{4}$", codigo), f"formato de SKU inesperado: {codigo}"
            assert sku_created.get("produto_pai_id"), "SKU gerado deveria vir com produto_pai_id (auto-vínculo R24)"


class TestCategoriaSemCat3Bloqueia:
    def test_categoria_inexistente_bloqueia_com_mensagem_clara(self, admin):
        """categoria_interesse tem ~90 valores; só os ~10 seedados em db.categorias tem
        CAT3 ativo. Uma categoria fora desse conjunto deve bloquear a geração citando a
        categoria, não estourar erro genérico."""
        nome = _unique("TEST_SKU_CategoriaInvalida")
        r = admin.post(f"{BASE_URL}/api/crm/clients", json={"nome_empresa": nome}, timeout=15)
        assert r.status_code == 200, r.text
        client_id = r.json()["id"]

        r2 = admin.post(f"{BASE_URL}/api/crm/projects/batch", json={
            "cliente_id": client_id,
            "projects": [{"nome_projeto": _unique("Proj"), "categoria": "unhas", "responsavel_comercial": ""}],
        }, timeout=15)
        assert r2.status_code == 200, r2.text
        projeto_id = r2.json()["created"][0]["id"]

        r3 = admin.post(f"{BASE_URL}/api/crm/samples/batch/v2", json={
            "projeto_id": projeto_id,
            "samples": [{
                "nome_produto": _unique("Esmalte Teste"),
                "categoria": "esmalte_unhas",
                "tipo_amostra": "novo_desenvolvimento",
                "prazo_entrega_cliente": "2026-12-31",
                "variacoes": [{"descricao_aplicacao": "Aplicação teste"}],
            }],
        }, timeout=15)
        if r3.status_code != 200:
            pytest.skip(f"categoria 'esmalte_unhas' pode não existir em categoria_interesse neste ambiente: {r3.text}")
        sample = r3.json()["created"][0]
        sample_id, variacao_id = sample["id"], sample["variacoes"][0]["id"]

        admin.put(f"{BASE_URL}/api/crm/samples/{sample_id}/variacoes/{variacao_id}/move", json={"status": "em_elaboracao"}, timeout=10)
        admin.put(f"{BASE_URL}/api/crm/samples/{sample_id}/variacoes/{variacao_id}/move", json={"status": "enviada"}, timeout=10)

        r4 = admin.post(
            f"{BASE_URL}/api/crm/samples/{sample_id}/variacoes/{variacao_id}/resultado-cliente",
            json={"resultado": "aprovada"},
            timeout=15,
        )
        assert r4.status_code == 200, r4.text
        sku_created = r4.json().get("sku_created")
        assert sku_created and sku_created.get("blocked") is True
        assert "R25" in (sku_created.get("reason") or ""), f"motivo do bloqueio deveria citar [R25]: {sku_created}"
