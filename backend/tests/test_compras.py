"""
Compras Module — Integration Tests (Passos 1–8)

Fluxo principal: Fornecedor → Item → Cotação → MRP → Demanda → PO → Recebimento
Hard stops: DELETE 405, PO imutável, fornecedor reprovado bloqueia emissão.
Feature: Estoque Projetado sem dupla contagem.

Pré-requisitos:
  - Servidor rodando em BASE_URL
  - Admin criado pelo seed: admin@kuryos.com / admin123
  - Role 'qa'  : qa@kuryos.com       / kuryos123
  - Role 'compras' não existe por padrão — admin age como compras nestes testes

Execução:
  pytest backend/tests/test_compras.py -v
"""

import pytest
import requests
from integration_helpers import get_backend_url, skip_without_backend_url

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = get_backend_url()
pytestmark = skip_without_backend_url(BASE_URL)

API = f"{BASE_URL}/api/compras"

CNPJ_VALIDO   = "11.444.777/0001-61"
CNPJ_INVALIDO = "11.111.111/1111-11"


# ---------------------------------------------------------------------------
# Fixtures de autenticação
# ---------------------------------------------------------------------------

def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"Login {email} falhou: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="session")
def admin():
    return _login("admin@kuryos.com", "admin123")


@pytest.fixture(scope="session")
def qa():
    return _login("qa@kuryos.com", "kuryos123")


# ---------------------------------------------------------------------------
# Estado compartilhado entre testes (IDs criados no fluxo)
# ---------------------------------------------------------------------------

_state: dict = {}


# ============================================================================
# BLOCO A — PASSO 2: Fornecedores + Homologação
# ============================================================================

class TestFornecedores:

    def test_cnpj_invalido_retorna_422(self, admin):
        r = admin.post(f"{API}/fornecedores", json={
            "razao_social": "Teste Inválido", "cnpj": CNPJ_INVALIDO, "categorias": [],
        })
        assert r.status_code == 422, f"Esperado 422 para CNPJ inválido, recebeu {r.status_code}: {r.text}"

    def test_criar_fornecedor_valido(self, admin):
        r = admin.post(f"{API}/fornecedores", json={
            "razao_social": "Fornecedor Alfa Ltda",
            "nome_fantasia": "Alfa",
            "cnpj": CNPJ_VALIDO,
            "categorias": ["MP Química", "Fragrância"],
            "contatos": [{"nome": "João Compras", "email": "joao@alfa.com", "principal_compras": True}],
        })
        assert r.status_code == 201, f"Criar fornecedor falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["codigo_interno"].startswith("FOR-")
        assert data["homologacao"]["status"] == "nao_iniciada"
        assert data["status_cadastro"] == "ativo"
        _state["fornecedor_id"] = data["id"]
        _state["fornecedor_codigo"] = data["codigo_interno"]

    def test_cnpj_duplicado_retorna_409(self, admin):
        r = admin.post(f"{API}/fornecedores", json={
            "razao_social": "Duplicado Ltda", "cnpj": CNPJ_VALIDO, "categorias": [],
        })
        assert r.status_code == 409, f"Esperado 409 para CNPJ duplicado, recebeu {r.status_code}"

    def test_listar_fornecedores(self, admin):
        r = admin.get(f"{API}/fornecedores")
        assert r.status_code == 200
        data = r.json()
        assert "fornecedores" in data
        assert data["total"] >= 1

    def test_filtro_status_homologacao(self, admin):
        r = admin.get(f"{API}/fornecedores", params={"status_homologacao": "nao_iniciada"})
        assert r.status_code == 200
        fornecedores = r.json()["fornecedores"]
        for f in fornecedores:
            assert f["homologacao"]["status"] == "nao_iniciada"

    def test_detalhar_fornecedor(self, admin):
        fid = _state["fornecedor_id"]
        r = admin.get(f"{API}/fornecedores/{fid}")
        assert r.status_code == 200
        assert r.json()["id"] == fid

    def test_atualizar_cadastro_fornecedor(self, admin):
        fid = _state["fornecedor_id"]
        r = admin.put(f"{API}/fornecedores/{fid}", json={"nome_fantasia": "Alfa Cosméticos"})
        assert r.status_code == 200
        assert r.json()["nome_fantasia"] == "Alfa Cosméticos"

    def test_iniciar_homologacao(self, admin):
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/fornecedores/{fid}/homologacao/iniciar")
        assert r.status_code == 200
        assert r.json()["homologacao"]["status"] == "em_processo"

    def test_decidir_reprovado_sem_justificativa_422(self, admin):
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/fornecedores/{fid}/homologacao/decidir",
                       json={"decisao": "reprovado"})
        assert r.status_code == 422

    def test_decidir_homologado(self, admin):
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/fornecedores/{fid}/homologacao/decidir",
                       json={"decisao": "homologado", "validade_dias": 365})
        assert r.status_code == 200
        hom = r.json()["homologacao"]
        assert hom["status"] == "homologado"
        assert hom["data_homologacao"] is not None
        assert hom["proxima_reavaliacao"] is not None

    def test_delete_fornecedor_405(self, admin):
        fid = _state["fornecedor_id"]
        r = admin.delete(f"{API}/fornecedores/{fid}")
        assert r.status_code == 405

    def test_incrementar_rnc_suspensao_automatica(self, admin):
        """3 RNCs críticas em 12m → suspensão automática."""
        # Criar fornecedor novo para não contaminar o fluxo principal
        r = admin.post(f"{API}/fornecedores", json={
            "razao_social": "Fornecedor RNC Ltda",
            "cnpj": "02.303.034/0001-51",
            "categorias": ["Frasco"],
        })
        assert r.status_code == 201
        fid = r.json()["id"]
        # Ativar homologação
        admin.post(f"{API}/fornecedores/{fid}/homologacao/iniciar")
        admin.post(f"{API}/fornecedores/{fid}/homologacao/decidir", json={"decisao": "homologado"})

        for i in range(3):
            rnc_r = admin.post(f"{API}/fornecedores/{fid}/incrementar-rnc",
                               json={"rnc_id": f"RNC-TEST-{i}", "classificacao": "critica"})
            assert rnc_r.status_code == 200

        forn_r = admin.get(f"{API}/fornecedores/{fid}")
        forn = forn_r.json()
        assert forn["homologacao"]["status"] == "suspenso"
        assert forn["homologacao"]["historico_rncs_criticas_12m"] >= 3


# ============================================================================
# BLOCO B — PASSO 3: Itens + Condições Comerciais
# ============================================================================

class TestItens:

    def test_criar_item(self, admin):
        r = admin.post(f"{API}/itens", json={
            "codigo_interno": "MP-TEST-001",
            "descricao": "Álcool Cetílico (teste)",
            "categoria": "mp",
            "unidade_compra": "kg",
            "lead_time_dias": 7,
            "estoque_minimo": 100.0,
            "estoque_seguranca": 20.0,
        })
        assert r.status_code == 201, f"Criar item falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["codigo_interno"] == "MP-TEST-001"
        _state["item_id"] = data["id"]

    def test_codigo_duplicado_409(self, admin):
        r = admin.post(f"{API}/itens", json={
            "codigo_interno": "MP-TEST-001",
            "descricao": "Duplicado",
            "categoria": "mp",
            "unidade_compra": "kg",
        })
        assert r.status_code == 409

    def test_listar_itens(self, admin):
        r = admin.get(f"{API}/itens")
        assert r.status_code == 200
        assert "itens" in r.json()

    def test_detalhar_item_com_fornecedores(self, admin):
        iid = _state["item_id"]
        r = admin.get(f"{API}/itens/{iid}")
        assert r.status_code == 200
        data = r.json()
        assert "fornecedores" in data

    def test_atualizar_item(self, admin):
        iid = _state["item_id"]
        r = admin.put(f"{API}/itens/{iid}", json={"lead_time_dias": 10})
        assert r.status_code == 200
        assert r.json()["lead_time_dias"] == 10

    def test_delete_item_405(self, admin):
        iid = _state["item_id"]
        r = admin.delete(f"{API}/itens/{iid}")
        assert r.status_code == 405

    def test_registrar_cotacao(self, admin):
        iid = _state["item_id"]
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/itens/{iid}/cotar", json={
            "fornecedor_id": fid,
            "preco_unitario": 15.50,
            "prazo_pagamento_texto": "30 DDL",
            "prazo_pagamento_dias": 30,
            "prazo_entrega_dias_uteis": 7,
            "moq": 50.0,
            "frete_tipo": "cif",
            "frete_valor": 0,
        })
        assert r.status_code == 201, f"Cotar falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["preco_unitario"] == 15.50
        assert data["item_id"] == iid
        assert "created_at" in data
        _state["cond_id"] = data["id"]

    def test_cotacao_nova_nao_sobrescreve(self, admin):
        """Segunda cotação deve criar novo registro, nunca sobrescrever."""
        iid = _state["item_id"]
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/itens/{iid}/cotar", json={
            "fornecedor_id": fid,
            "preco_unitario": 14.80,
            "prazo_pagamento_texto": "28 DDL",
            "prazo_pagamento_dias": 28,
            "prazo_entrega_dias_uteis": 5,
            "moq": 50.0,
            "frete_tipo": "cif",
            "frete_valor": 0,
        })
        assert r.status_code == 201
        assert r.json()["id"] != _state["cond_id"]  # novo ID = novo registro

    def test_historico_precos_duas_cotacoes(self, admin):
        iid = _state["item_id"]
        r = admin.get(f"{API}/itens/{iid}/historico-precos")
        assert r.status_code == 200
        data = r.json()
        assert data["total_cotacoes"] >= 2
        hist = data["historico"]
        assert len(hist) >= 2
        # A segunda (mais antiga) não tem variação; a primeira tem
        com_variacao = [h for h in hist if h.get("variacao_pct") is not None]
        assert len(com_variacao) >= 1

    def test_comparativo_ordenado_menor_preco(self, admin):
        iid = _state["item_id"]
        r = admin.get(f"{API}/itens/{iid}/historico-precos")
        comparativo = r.json()["comparativo_fornecedores"]
        if len(comparativo) >= 2:
            precos = [c["ultimo_preco"] for c in comparativo]
            assert precos == sorted(precos)

    def test_cotacao_valido_ate_expirada_422(self, admin):
        iid = _state["item_id"]
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/itens/{iid}/cotar", json={
            "fornecedor_id": fid,
            "preco_unitario": 10.0,
            "prazo_pagamento_texto": "30 DDL",
            "prazo_pagamento_dias": 30,
            "prazo_entrega_dias_uteis": 7,
            "moq": 1.0,
            "frete_tipo": "cif",
            "frete_valor": 0,
            "valido_ate": "2020-01-01",
        })
        assert r.status_code == 422

    def test_put_condicao_comercial_405(self, admin):
        cid = _state["cond_id"]
        r = admin.put(f"{API}/condicoes-comerciais/{cid}", json={"preco_unitario": 9.99})
        assert r.status_code == 405

    def test_delete_condicao_405(self, admin):
        cid = _state["cond_id"]
        r = admin.delete(f"{API}/condicoes-comerciais/{cid}")
        assert r.status_code == 405


# ============================================================================
# BLOCO C — PASSO 4: MRP Engine
# ============================================================================

class TestMRP:

    def test_calcular_mrp_sem_ops(self, admin):
        """Sem OPs manuais: item aparece por reposicao_seguranca (estoque < mínimo)."""
        r = admin.post(f"{API}/mrp/calcular", json={"ops_input": []})
        assert r.status_code == 201, f"Calcular MRP falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["numero_mrp"].startswith("MRP-")
        assert data["status"] == "gerada"
        _state["mrp_id"] = data["id"]
        _state["mrp_numero"] = data["numero_mrp"]

    def test_calcular_mrp_com_op_manual(self, admin):
        """Com OP manual: item aparece com motivo demanda_op."""
        iid = _state["item_id"]
        r = admin.post(f"{API}/mrp/calcular", json={
            "ops_input": [{
                "op_id": "OP-TEST-001",
                "op_numero": "OP-TEST-001",
                "sku_descricao": "Body Splash Teste",
                "quantidade_op": 500,
                "data_necessidade": "2026-06-01",
                "bom_items": [{"item_id": iid, "quantidade_por_unidade": 0.3}],
            }]
        })
        assert r.status_code == 201
        data = r.json()
        itens = data["itens_sugeridos"]
        # item deve aparecer na lista
        item_match = [i for i in itens if i["item_id"] == iid]
        assert len(item_match) >= 1, "Item com demanda de OP não apareceu no MRP"
        it = item_match[0]
        assert it["necessidade_bruta"] == 150.0  # 500 * 0.3
        assert it["quantidade_sugerida"] >= it["necessidade_liquida"]

    def test_listar_mrp(self, admin):
        r = admin.get(f"{API}/mrp")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1

    def test_detalhar_mrp(self, admin):
        mrp_id = _state["mrp_id"]
        r = admin.get(f"{API}/mrp/{mrp_id}")
        assert r.status_code == 200
        assert r.json()["id"] == mrp_id

    def test_revisar_item_remover_sem_justificativa_422(self, admin):
        mrp_id = _state["mrp_id"]
        r = admin.get(f"{API}/mrp/{mrp_id}")
        itens = r.json().get("itens_sugeridos", [])
        if not itens:
            pytest.skip("MRP sem itens para remover")
        iid = itens[0]["item_id"]
        r = admin.put(f"{API}/mrp/{mrp_id}/revisar-item", json={
            "item_id": iid, "acao": "remover",
        })
        assert r.status_code == 422

    def test_revisar_item_aprovar(self, admin):
        mrp_id = _state["mrp_id"]
        r = admin.get(f"{API}/mrp/{mrp_id}")
        itens = r.json().get("itens_sugeridos", [])
        if not itens:
            pytest.skip("MRP sem itens")
        iid = itens[0]["item_id"]
        r = admin.put(f"{API}/mrp/{mrp_id}/revisar-item", json={
            "item_id": iid, "acao": "aprovar",
        })
        assert r.status_code == 200
        it_updated = next(i for i in r.json()["itens_sugeridos"] if i["item_id"] == iid)
        assert it_updated["aprovado_pcp"] is True

    def test_aprovar_mrp_com_item_pendente_400(self, admin):
        """Não pode aprovar se há item ainda pendente."""
        # Calcular rodada nova com OP para ter múltiplos itens
        iid = _state["item_id"]
        r = admin.post(f"{API}/mrp/calcular", json={"ops_input": []})
        assert r.status_code == 201
        mrp_id2 = r.json()["id"]
        _state["mrp_id2"] = mrp_id2
        itens = r.json().get("itens_sugeridos", [])
        if not itens:
            pytest.skip("MRP sem itens")
        # Aprovar apenas o primeiro, deixar os restantes pendentes
        iid = itens[0]["item_id"]
        admin.put(f"{API}/mrp/{mrp_id2}/revisar-item", json={"item_id": iid, "acao": "aprovar"})
        # Se há mais itens, ainda deve bloquear
        if len(itens) > 1:
            r_ap = admin.post(f"{API}/mrp/{mrp_id2}/aprovar")
            assert r_ap.status_code == 400

    def test_aprovar_mrp_completo(self, admin):
        """Aprovar todos os itens e então aprovar a rodada."""
        mrp_id = _state["mrp_id"]
        r = admin.get(f"{API}/mrp/{mrp_id}")
        itens = r.json().get("itens_sugeridos", [])
        # Aprovar todos os pendentes
        for it in itens:
            if it.get("aprovado_pcp") is None:
                admin.put(f"{API}/mrp/{mrp_id}/revisar-item", json={
                    "item_id": it["item_id"], "acao": "aprovar",
                })
        # Agora aprovar a rodada
        r = admin.post(f"{API}/mrp/{mrp_id}/aprovar")
        assert r.status_code == 200, f"Aprovar MRP falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["status"] == "aprovada"
        assert data["demandas_criadas"] >= 0
        _state["mrp_aprovado_id"] = mrp_id

    def test_texto_disparo(self, admin):
        mrp_id = _state["mrp_id"]
        r = admin.get(f"{API}/mrp/{mrp_id}/texto-disparo")
        assert r.status_code == 200
        data = r.json()
        assert "blocos" in data
        assert "texto_completo" in data

    def test_delete_mrp_405(self, admin):
        mrp_id = _state["mrp_id"]
        r = admin.delete(f"{API}/mrp/{mrp_id}")
        assert r.status_code == 405


# ============================================================================
# BLOCO D — PASSO 5: Pedido de Compra (PO)
# ============================================================================

class TestPO:

    def _criar_po_rascunho(self, admin):
        iid = _state["item_id"]
        fid = _state["fornecedor_id"]
        r = admin.post(f"{API}/pos", json={
            "fornecedor_id": fid,
            "origem": "manual",
            "prazo_pagamento_texto": "30 DDL",
            "prazo_pagamento_dias": 30,
            "data_entrega_solicitada": "2026-08-01",
            "itens": [{
                "item_id": iid,
                "item_descricao": "Álcool Cetílico (teste)",
                "quantidade_solicitada": 200.0,
                "unidade_compra": "kg",
                "preco_unitario": 15.50,
                "frete_rateado": 0.0,
            }],
        })
        return r

    def test_criar_po_rascunho(self, admin):
        r = self._criar_po_rascunho(admin)
        assert r.status_code == 201, f"Criar PO falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["status"] == "rascunho"
        assert data["numero_po"] is None
        assert data["valor_total_po"] == 200.0 * 15.50
        _state["po_id"] = data["id"]

    def test_listar_pos(self, admin):
        r = admin.get(f"{API}/pos")
        assert r.status_code == 200
        assert "pos" in r.json()

    def test_detalhar_po(self, admin):
        po_id = _state["po_id"]
        r = admin.get(f"{API}/pos/{po_id}")
        assert r.status_code == 200
        assert r.json()["id"] == po_id

    def test_editar_rascunho_ok(self, admin):
        po_id = _state["po_id"]
        r = admin.put(f"{API}/pos/{po_id}", json={"prazo_pagamento_texto": "28 DDL", "prazo_pagamento_dias": 28})
        assert r.status_code == 200
        assert r.json()["prazo_pagamento_texto"] == "28 DDL"

    def test_emitir_fornecedor_reprovado_400(self, admin):
        """Criar fornecedor reprovado → PO → emitir → 400 hard stop."""
        forn_r = admin.post(f"{API}/fornecedores", json={
            "razao_social": "Fornecedor Reprovado SA",
            "cnpj": "07.526.557/0001-00",
            "categorias": [],
        })
        assert forn_r.status_code == 201
        fid_rep = forn_r.json()["id"]
        # Iniciar e reprovar
        admin.post(f"{API}/fornecedores/{fid_rep}/homologacao/iniciar")
        admin.post(f"{API}/fornecedores/{fid_rep}/homologacao/decidir",
                   json={"decisao": "reprovado", "justificativa": "Qualidade insatisfatória"})

        # Criar PO com fornecedor reprovado
        iid = _state["item_id"]
        po_r = admin.post(f"{API}/pos", json={
            "fornecedor_id": fid_rep,
            "prazo_pagamento_texto": "30 DDL",
            "prazo_pagamento_dias": 30,
            "itens": [{"item_id": iid, "item_descricao": "Test", "quantidade_solicitada": 10.0, "unidade_compra": "kg", "preco_unitario": 5.0}],
        })
        assert po_r.status_code == 201
        po_rep_id = po_r.json()["id"]

        # Emitir → deve bloquear com 400
        emit_r = admin.post(f"{API}/pos/{po_rep_id}/emitir")
        assert emit_r.status_code == 400
        detail = emit_r.json().get("detail", {})
        error_code = detail.get("error") if isinstance(detail, dict) else str(detail)
        assert "hard_stop_fornecedor_reprovado" in error_code

    def test_emitir_po_homologado(self, admin):
        po_id = _state["po_id"]
        r = admin.post(f"{API}/pos/{po_id}/emitir")
        assert r.status_code == 200, f"Emitir PO falhou: {r.status_code} {r.text}"
        data = r.json()
        assert data["status"] == "emitida"
        assert data["numero_po"] is not None
        assert data["numero_po"].startswith("PO-")
        assert data["data_emissao"] is not None
        _state["po_numero"] = data["numero_po"]

    def test_put_po_emitida_400_imutavel(self, admin):
        po_id = _state["po_id"]
        r = admin.put(f"{API}/pos/{po_id}", json={"prazo_pagamento_texto": "15 DDL"})
        assert r.status_code == 400
        assert "imutável" in r.json().get("detail", "").lower() or "imutavel" in r.json().get("detail", "").lower()

    def test_gerar_pdf_po(self, admin):
        po_id = _state["po_id"]
        r = admin.get(f"{API}/pos/{po_id}/pdf")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 500  # PDF não-vazio

    def test_gerar_whatsapp_po(self, admin):
        po_id = _state["po_id"]
        r = admin.get(f"{API}/pos/{po_id}/whatsapp")
        assert r.status_code == 200
        data = r.json()
        assert "texto" in data
        texto = data["texto"]
        assert "Kuryos Cosméticos" in texto
        assert _state["po_numero"] in texto
        assert "Álcool Cetílico" in texto  # item aparece no texto

    def test_confirmar_po(self, admin):
        po_id = _state["po_id"]
        r = admin.post(f"{API}/pos/{po_id}/confirmar",
                       json={"data_entrega_confirmada": "2026-08-10"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "confirmada"
        assert data["data_entrega_confirmada"] == "2026-08-10"

    def test_receber_parcial_divergencia_cria_tarefa(self, admin):
        po_id = _state["po_id"]
        iid = _state["item_id"]
        # Receber apenas 100 de 200 → divergência
        r = admin.post(f"{API}/pos/{po_id}/receber-parcial", json={
            "nf_numero": "NF-001",
            "nf_data": "2026-08-10",
            "itens_recebidos": [{"item_id": iid, "quantidade_recebida": 100.0}],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "parcialmente_recebida"
        assert len(data["divergencias"]) >= 1
        assert "nf_registrada" in data

    def test_receber_total_status_recebida(self, admin):
        po_id = _state["po_id"]
        iid = _state["item_id"]
        # Receber os 100 restantes
        r = admin.post(f"{API}/pos/{po_id}/receber-parcial", json={
            "nf_numero": "NF-002",
            "nf_data": "2026-08-11",
            "itens_recebidos": [{"item_id": iid, "quantidade_recebida": 100.0}],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "recebida"
        assert len(data["divergencias"]) == 0

    def test_cancelar_sem_motivo_422(self, admin):
        r = self._criar_po_rascunho(admin)
        po_id = r.json()["id"]
        _state["po_cancelar_id"] = po_id
        cancel_r = admin.post(f"{API}/pos/{po_id}/cancelar", json={"motivo": ""})
        assert cancel_r.status_code == 422

    def test_cancelar_com_motivo(self, admin):
        po_id = _state["po_cancelar_id"]
        r = admin.post(f"{API}/pos/{po_id}/cancelar",
                       json={"motivo": "Fornecedor não atende especificação"})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelada"
        assert r.json()["cancelado_motivo"] is not None

    def test_delete_po_405(self, admin):
        po_id = _state["po_id"]
        r = admin.delete(f"{API}/pos/{po_id}")
        assert r.status_code == 405

    def test_delete_demandas_405(self, admin):
        r = admin.delete(f"{API}/demandas/qualquer-id")
        assert r.status_code == 405


# ============================================================================
# BLOCO E — Dashboard
# ============================================================================

class TestDashboard:

    def test_dashboard_retorna_5_secoes(self, admin):
        r = admin.get(f"{API}/dashboard")
        assert r.status_code == 200
        data = r.json()
        for secao in ("visao_operacional", "visao_fornecedores", "visao_estoque_reposicao", "visao_financeira", "estoque_projetado_resumo"):
            assert secao in data, f"Seção '{secao}' ausente do dashboard"

    def test_dashboard_visao_operacional_campos(self, admin):
        r = admin.get(f"{API}/dashboard")
        op = r.json()["visao_operacional"]
        for campo in ("pos_aguardando_confirmacao", "pos_entrega_proximos_7_dias", "pos_atrasadas", "itens_urgentes_mrp"):
            assert campo in op

    def test_dashboard_visao_financeira_totais_numericos(self, admin):
        r = admin.get(f"{API}/dashboard")
        fin = r.json()["visao_financeira"]
        assert isinstance(fin["total_a_pagar_semana"], (int, float))
        assert isinstance(fin["total_a_pagar_mes"], (int, float))

    def test_estoque_projetado_resumo_campos(self, admin):
        r = admin.get(f"{API}/dashboard")
        ep = r.json()["estoque_projetado_resumo"]
        for k in ("ruptura", "critico", "atencao", "ok"):
            assert k in ep
            assert isinstance(ep[k], int)


# ============================================================================
# BLOCO F — Estoque Projetado
# ============================================================================

class TestEstoqueProjetado:

    def test_estoque_projetado_retorna_estrutura(self, admin):
        r = admin.get(f"{API}/estoque-projetado")
        assert r.status_code == 200
        data = r.json()
        assert "resumo" in data
        assert "itens" in data
        assert "horizonte_dias" in data
        assert data["horizonte_dias"] == 90

    def test_filtro_horizonte(self, admin):
        r = admin.get(f"{API}/estoque-projetado", params={"horizonte_dias": 30})
        assert r.status_code == 200
        assert r.json()["horizonte_dias"] == 30

    def test_filtro_apenas_criticos(self, admin):
        r = admin.get(f"{API}/estoque-projetado", params={"apenas_criticos": True})
        assert r.status_code == 200
        itens = r.json()["itens"]
        for i in itens:
            assert i["risco"] != "ok", f"Item com risco 'ok' não deveria aparecer: {i['item_id']}"

    def test_campos_4_camadas_presentes(self, admin):
        r = admin.get(f"{API}/estoque-projetado")
        itens = r.json()["itens"]
        if itens:
            i = itens[0]
            for campo in ("estoque_atual", "demanda_firme", "demanda_projetada",
                          "suprimento_transito", "saldo_firme", "saldo_conservador", "risco"):
                assert campo in i, f"Campo '{campo}' ausente no item projetado"

    def test_saldo_conservador_consistente(self, admin):
        r = admin.get(f"{API}/estoque-projetado")
        for it in r.json()["itens"]:
            esperado = it["estoque_atual"] - it["demanda_firme"] - it["demanda_projetada"] + it["suprimento_transito"]
            # Tolerância por arredondamento
            assert abs(it["saldo_conservador"] - round(esperado, 4)) < 0.01, (
                f"saldo_conservador inconsistente para {it['item_id']}: "
                f"calculado={esperado:.4f}, retornado={it['saldo_conservador']}"
            )

    def test_drill_down_item(self, admin):
        iid = _state.get("item_id")
        if not iid:
            pytest.skip("item_id não disponível")
        r = admin.get(f"{API}/estoque-projetado/{iid}")
        assert r.status_code == 200
        data = r.json()
        assert "item" in data
        assert "timeline_demanda" in data
        assert "saldo_por_data" in data
        assert "fornecedores_disponiveis" in data
        assert "historico_precos" in data

    def test_risco_ruptura_quando_saldo_negativo(self, admin):
        """Item com saldo_conservador < 0 deve ter risco=ruptura."""
        r = admin.get(f"{API}/estoque-projetado")
        rupturas = [i for i in r.json()["itens"] if i["risco"] == "ruptura"]
        for i in rupturas:
            assert i["saldo_conservador"] < 0, (
                f"Item classificado como ruptura mas saldo_conservador={i['saldo_conservador']}"
            )

    def test_risco_critico_entre_zero_e_minimo(self, admin):
        """Item com 0 <= saldo < estoque_minimo deve ser critico."""
        r = admin.get(f"{API}/estoque-projetado")
        for i in r.json()["itens"]:
            if i["risco"] == "critico":
                assert 0 <= i["saldo_conservador"] < i["estoque_minimo"], (
                    f"Item 'critico' com saldo={i['saldo_conservador']}, min={i['estoque_minimo']}"
                )


# ============================================================================
# BLOCO G — Invariantes / Regras de Negócio
# ============================================================================

class TestInvariantes:

    def test_todas_6_colecoes_bloqueiam_delete(self, admin):
        """DELETE em qualquer nova coleção → 405."""
        endpoints = [
            "/fornecedores/fake-id",
            "/itens/fake-id",
            "/condicoes-comerciais/fake-id",
            "/pos/fake-id",
            "/mrp/fake-id",
            "/demandas/fake-id",
        ]
        for ep in endpoints:
            r = admin.delete(f"{API}{ep}")
            assert r.status_code == 405, f"DELETE {ep} deveria retornar 405, recebeu {r.status_code}"

    def test_condicoes_comerciais_sem_put(self, admin):
        """PUT em condições comerciais → 405 (imutável)."""
        r = admin.put(f"{API}/condicoes-comerciais/fake-id", json={"preco_unitario": 99.0})
        assert r.status_code == 405

    def test_po_imutavel_apos_emissao(self, admin):
        """PUT na PO após emissão → 400."""
        po_id = _state.get("po_id")
        if not po_id:
            pytest.skip("po_id não disponível")
        r = admin.put(f"{API}/pos/{po_id}", json={"prazo_pagamento_texto": "Alteração indevida"})
        assert r.status_code == 400

    def test_condicao_nova_sem_sobrescrita(self, admin):
        """POST /cotar sempre cria novo doc — nunca atualiza o anterior."""
        iid = _state.get("item_id")
        fid = _state.get("fornecedor_id")
        if not iid or not fid:
            pytest.skip("ids não disponíveis")
        cond_anterior = _state.get("cond_id")
        r = admin.post(f"{API}/itens/{iid}/cotar", json={
            "fornecedor_id": fid,
            "preco_unitario": 12.00,
            "prazo_pagamento_texto": "30 DDL",
            "prazo_pagamento_dias": 30,
            "prazo_entrega_dias_uteis": 5,
            "moq": 1.0,
            "frete_tipo": "cif",
            "frete_valor": 0,
        })
        assert r.status_code == 201
        nova_cond = r.json()["id"]
        assert nova_cond != cond_anterior  # IDs diferentes → registro novo

    def test_mrp_urgente_quando_data_limite_passada(self, admin):
        """Item com data_necessidade no passado e lead_time alto → urgente=true."""
        iid = _state.get("item_id")
        if not iid:
            pytest.skip("item_id não disponível")
        r = admin.post(f"{API}/mrp/calcular", json={
            "ops_input": [{
                "op_id": "OP-URGENTE-001",
                "op_numero": "OP-URGENTE-001",
                "sku_descricao": "Produto Urgente",
                "quantidade_op": 100,
                "data_necessidade": "2024-01-01",  # data no passado → urgente
                "bom_items": [{"item_id": iid, "quantidade_por_unidade": 1.0}],
            }]
        })
        assert r.status_code == 201
        itens = r.json()["itens_sugeridos"]
        item_match = [i for i in itens if i["item_id"] == iid]
        if item_match:
            assert item_match[0]["urgente"] is True


# ============================================================================
# BLOCO H — RBAC básico
# ============================================================================

class TestRBAC:

    def test_unauthenticated_blocked(self):
        r = requests.get(f"{API}/fornecedores", timeout=10)
        assert r.status_code in (401, 403)

    def test_qa_pode_ler_fornecedores(self, qa):
        r = qa.get(f"{API}/fornecedores")
        assert r.status_code == 200

    def test_qa_nao_pode_criar_po(self, qa):
        """QA não está em _CMP_WRITE → não pode criar PO."""
        iid = _state.get("item_id", "fake")
        fid = _state.get("fornecedor_id", "fake")
        r = qa.post(f"{API}/pos", json={
            "fornecedor_id": fid,
            "prazo_pagamento_texto": "30 DDL",
            "prazo_pagamento_dias": 30,
            "itens": [{"item_id": iid, "item_descricao": "t", "quantidade_solicitada": 1, "unidade_compra": "kg", "preco_unitario": 1}],
        })
        # QA não tem permissão de escrita em POs
        assert r.status_code in (403, 422), f"QA deveria ser bloqueado, recebeu {r.status_code}"
