import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import pd_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    async def to_list(self, _length):
        return [dict(doc) for doc in self.docs]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    def find(self, query, projection=None):
        tenant_id = query.get("tenant_id")
        status = query.get("status")
        tipo2 = query.get("tipo2")
        filtered = []
        for doc in self.docs:
            if tenant_id and doc.get("tenant_id") != tenant_id:
                continue
            if status and doc.get("status") != status:
                continue
            if tipo2 and doc.get("tipo2") != tipo2:
                continue
            if projection and projection.get("_id") == 0:
                filtered.append({k: v for k, v in doc.items() if k != "_id"})
            else:
                filtered.append(dict(doc))
        return FakeCursor(filtered)


def test_procedure_phase_aliases_accept_frontend_shape():
    payload = pd_routes.ProcedurePhaseCreate.model_validate(
        {"titulo": "Fase A", "descricao": "Aquecer até 80C", "temperatura": "80C"}
    )

    assert payload.nome_fase == "Fase A"
    assert payload.instrucoes == "Aquecer até 80C"
    assert payload.temperatura == "80C"


def test_merge_ficha_analise_with_lab_defaults_autofills_missing_results():
    analise, auto_filled = pd_routes._merge_ficha_analise_with_lab_defaults(
        {"aspecto": {"especificacao": "", "resultado": "", "pa": ""}},
        {
            "sensorial": {"aspecto": "Líquido translúcido", "cor": "Amarela", "odor": "Cítrico"},
            "ph": {"valor_medido": "5.8"},
        },
    )

    assert analise["aspecto"]["resultado"] == "Líquido translúcido"
    assert analise["cor"]["resultado"] == "Amarela"
    assert analise["odor"]["resultado"] == "Cítrico"
    assert analise["ph"]["resultado"] == "5.8"
    assert auto_filled == {"aspecto": True, "cor": True, "odor": True, "ph": True}


def test_catalog_enrichment_merges_material_and_homologated_suppliers():
    pd_routes.db = SimpleNamespace(
        materiais=FakeCollection(
            [
                {
                    "tenant_id": "tenant-1",
                    "tipo2": "MP",
                    "nome": "Base Vegetal",
                    "codigo_interno": "MP-00001",
                    "subtipo": "Emoliente",
                    "fornecedores": [
                        {
                            "fornecedor_nome": "Fornecedor Material",
                            "codigo_fornecedor": "FM-1",
                            "status_homologacao": "homologado",
                            "preco_por_unidade": 18.5,
                            "moeda": "BRL",
                        }
                    ],
                }
            ]
        ),
        homologacao_mps=FakeCollection(
            [
                {
                    "tenant_id": "tenant-1",
                    "status": "homologada",
                    "nome": "Base Vegetal",
                    "codigo_interno": "MP-00001",
                    "inci": "Vegetal Base",
                    "fornecedor_id": "forn-1",
                    "fornecedor_nome": "Fornecedor Homologado",
                    "funcao": "Emoliente",
                    "custo_referencia": 22.0,
                    "unidade": "kg",
                }
            ]
        ),
    )

    enriched = asyncio.run(
        pd_routes._enrich_catalog_items_with_procurement_data(
            "tenant-1",
            [
                {
                    "id": "cat-1",
                    "tenant_id": "tenant-1",
                    "nome": "Base Vegetal",
                    "inci": "",
                    "codigo_interno": "MP-00001",
                    "fornecedor": "",
                    "fornecedores": [],
                }
            ],
        )
    )[0]

    supplier_names = [supplier["nome"] for supplier in enriched["fornecedores"]]
    assert "Fornecedor Material" in supplier_names
    assert "Fornecedor Homologado" in supplier_names
    assert enriched["fornecedor"] == "Fornecedor Material"
    assert enriched["inci"] == "Vegetal Base"
    assert enriched["categoria"] == "Emoliente"


def test_commercial_pd_requests_require_commercial_client_approval():
    pd_req = {"id": "pd-1", "client_card_id": "client-1", "request_type": "Amostra Cliente"}

    assert pd_routes._pd_request_requires_commercial_approval(pd_req) is True
    with pytest.raises(HTTPException) as exc:
        pd_routes._assert_can_register_client_approval(pd_req, {"role": "formulador"})

    assert exc.value.status_code == 403
    pd_routes._assert_can_register_client_approval(pd_req, {"role": "sales_ops"})


def test_internal_research_does_not_require_commercial_client_approval():
    pd_req = {"id": "pd-2", "is_internal_research": True, "request_type": "Pesquisa Interna"}

    assert pd_routes._pd_request_requires_commercial_approval(pd_req) is False
    pd_routes._assert_can_register_client_approval(pd_req, {"role": "formulador"})
