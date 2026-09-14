import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import compras_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, key, direction):
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        return self

    def skip(self, offset):
        self.docs = self.docs[offset:]
        return self

    def limit(self, limit):
        self.docs = self.docs[:limit]
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None, sort=None):
        docs = [doc for doc in self.docs if self._matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        if not docs:
            return None
        return self._project(docs[0], projection)

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    def _matches(self, doc, query):
        for key, value in query.items():
            current = self._get_nested(doc, key)
            if isinstance(value, dict):
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$nin" in value and current in value["$nin"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _get_nested(self, doc, key):
        current = doc
        for part in key.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


async def fake_user(_request):
    return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}


def _install_quote_quality_db(feature_enabled=False):
    compras_routes.get_current_user = fake_user
    compras_routes.db = SimpleNamespace(
        tenant_settings=FakeCollection([
            {
                "tenant_id": "t1",
                "features": {"pcp_supplier_quality_quote_v2": feature_enabled},
            }
        ]),
        compras_itens=FakeCollection([
            {
                "id": "item-1",
                "tenant_id": "t1",
                "codigo_interno": "MP-AGU",
                "descricao": "Agua",
                "categoria": "mp",
                "unidade_compra": "kg",
            }
        ]),
        compras_fornecedores=FakeCollection([
            {
                "id": "forn-safe",
                "tenant_id": "t1",
                "codigo_interno": "FOR-001",
                "razao_social": "Fornecedor Seguro",
                "homologacao": {
                    "status": "homologado",
                    "proxima_reavaliacao": "2027-01-20",
                    "historico_rncs_count": 1,
                    "historico_rncs_criticas_12m": 0,
                },
            },
            {
                "id": "forn-risk",
                "tenant_id": "t1",
                "codigo_interno": "FOR-002",
                "razao_social": "Fornecedor Risco",
                "homologacao": {
                    "status": "suspenso",
                    "proxima_reavaliacao": "2026-08-20",
                    "historico_rncs_count": 4,
                    "historico_rncs_criticas_12m": 3,
                },
            },
        ]),
        compras_condicoes_comerciais=FakeCollection([
            {
                "id": "cot-1",
                "tenant_id": "t1",
                "fornecedor_id": "forn-safe",
                "fornecedor_nome": "Fornecedor Seguro",
                "item_id": "item-1",
                "item_descricao": "Agua",
                "preco_unitario": 10.0,
                "prazo_entrega_dias_uteis": 5,
                "moq": 10,
                "valido_ate": "2027-01-01",
                "created_at": "2026-09-10T10:00:00",
            },
            {
                "id": "cot-2",
                "tenant_id": "t1",
                "fornecedor_id": "forn-risk",
                "fornecedor_nome": "Fornecedor Risco",
                "item_id": "item-1",
                "item_descricao": "Agua",
                "preco_unitario": 8.0,
                "prazo_entrega_dias_uteis": 3,
                "moq": 5,
                "valido_ate": "2027-01-01",
                "created_at": "2026-09-11T10:00:00",
            },
        ]),
        compras_pos=FakeCollection([]),
    )


def test_supplier_quality_contract_preserves_legacy_quote_comparator_fields():
    _install_quote_quality_db(feature_enabled=False)

    result = asyncio.run(compras_routes.historico_precos("item-1", request=SimpleNamespace()))

    assert result["comparativo_fornecedores"][0]["fornecedor_id"] == "forn-risk"
    assert result["comparativo_fornecedores"][0]["status_homologacao"] == "suspenso"
    assert result["comparativo_fornecedores"][0]["ultimo_preco"] == 8.0


def test_supplier_quality_flag_off_omits_optional_enrichment():
    _install_quote_quality_db(feature_enabled=False)

    result = asyncio.run(compras_routes.historico_precos("item-1", request=SimpleNamespace()))

    assert "supplier_quality" not in result["comparativo_fornecedores"][0]


def test_supplier_quality_flag_on_enriches_quote_comparator_from_homologacao_and_rnc():
    _install_quote_quality_db(feature_enabled=True)

    result = asyncio.run(compras_routes.historico_precos("item-1", request=SimpleNamespace()))

    safe = next(row for row in result["comparativo_fornecedores"] if row["fornecedor_id"] == "forn-safe")
    quality = safe["supplier_quality"]
    assert quality["score"] >= 80
    assert quality["selo"] == "Qualificado"
    assert quality["risco"] == "baixo"
    assert quality["status_homologacao"] == "homologado"
    assert quality["rnc_total"] == 1
    assert quality["rnc_criticas_12m"] == 0
    assert quality["proxima_reavaliacao"] == "2027-01-20"
    assert "compras_fornecedores.homologacao" in quality["fontes"]


def test_supplier_quality_flags_suspended_supplier_as_high_risk_even_with_best_price():
    _install_quote_quality_db(feature_enabled=True)

    result = asyncio.run(compras_routes.historico_precos("item-1", request=SimpleNamespace()))

    risky = next(row for row in result["comparativo_fornecedores"] if row["fornecedor_id"] == "forn-risk")
    assert risky["ultimo_preco"] == 8.0
    assert risky["supplier_quality"]["risco"] in {"alto", "bloqueado"}
    assert risky["supplier_quality"]["selo"] in {"Risco alto", "Bloqueado"}
    assert "fornecedor_suspenso" in risky["supplier_quality"]["alertas"]
    assert "rnc_critica_12m" in risky["supplier_quality"]["alertas"]
