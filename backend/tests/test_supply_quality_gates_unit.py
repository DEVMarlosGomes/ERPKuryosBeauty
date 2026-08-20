import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import cq_routes
import estoque_routes
import faturamento_routes


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

    def _matches(self, doc, query):
        for key, value in query.items():
            if doc.get(key) != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


def test_cq_lote_sem_aprovacao_bloqueia_movimento():
    fake_db = SimpleNamespace(cq_status_lote=FakeCollection([]))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(cq_routes.cq_verificar_lote_aprovado(fake_db, "tenant", "lote-1"))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "hard_stop_lote_sem_liberacao_cq"


def test_cq_lote_aprovado_libera_movimento():
    fake_db = SimpleNamespace(
        cq_status_lote=FakeCollection([
            {"tenant_id": "tenant", "lote_id": "lote-1", "status_novo": "aprovado", "created_at": "2026-08-20T10:00:00"}
        ])
    )

    asyncio.run(cq_routes.cq_verificar_lote_aprovado(fake_db, "tenant", "lote-1"))


def test_estoque_saida_quarentena_bloqueia_sem_mexer_em_saldo():
    item = {
        "id": "est-1",
        "tenant_id": "tenant",
        "nome": "MP Teste",
        "posicao_cq": "quarentena",
    }

    with pytest.raises(HTTPException) as exc:
        asyncio.run(estoque_routes._assert_saida_liberada_por_cq(item, "SAIDA_CONSUMO_OP"))

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "hard_stop_estoque_sem_liberacao_cq"


def test_faturamento_bloqueia_nf_para_exp_nao_expedida():
    faturamento_routes.db = SimpleNamespace(
        expedicao_ordens=FakeCollection([
            {"id": "exp-1", "tenant_id": "tenant", "status": "conferido", "items": []}
        ]),
        estoque_items=FakeCollection([]),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(faturamento_routes._assert_expedicao_pronta_para_nf("tenant", "exp-1"))

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "hard_stop_nf_expedicao_nao_liberada"


def test_faturamento_libera_nf_para_exp_expedida_sem_bloqueio_cq():
    faturamento_routes.db = SimpleNamespace(
        expedicao_ordens=FakeCollection([
            {
                "id": "exp-1",
                "tenant_id": "tenant",
                "status": "expedido",
                "numero_exp": "EXP-00001",
                "items": [{"estoque_item_id": "est-1", "produto_nome": "Produto Teste"}],
            }
        ]),
        estoque_items=FakeCollection([
            {"id": "est-1", "tenant_id": "tenant", "posicao_cq": "aprovado"}
        ]),
    )

    exp = asyncio.run(faturamento_routes._assert_expedicao_pronta_para_nf("tenant", "exp-1"))

    assert exp["numero_exp"] == "EXP-00001"
