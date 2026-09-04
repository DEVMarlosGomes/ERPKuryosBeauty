import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update):
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs[idx] = self._apply_update(doc, update)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def update_many(self, query, update):
        count = 0
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs[idx] = self._apply_update(doc, update)
                count += 1
        return SimpleNamespace(modified_count=count)

    def _matches(self, doc, query):
        for key, value in query.items():
            if key == "$or":
                if not any(self._matches(doc, sub) for sub in value):
                    return False
                continue
            current = self._get_nested(doc, key)
            if isinstance(value, dict):
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$nin" in value and current in value["$nin"]:
                    return False
                if "$lte" in value and not (current <= value["$lte"]):
                    return False
                if "$exists" in value:
                    exists = current is not None
                    if bool(value["$exists"]) != exists:
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

    def _apply_update(self, doc, update):
        doc = dict(doc)
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        return doc


def _install_ids():
    seq = {"n": 0}

    def new_id():
        seq["n"] += 1
        return f"id-{seq['n']}"

    compras_routes.new_id_func = new_id
    compras_routes.now_iso_func = lambda: "2026-08-20T10:00:00"


def test_mrp_coleta_demanda_real_do_pcp_e_respeita_quarentena():
    _install_ids()
    compras_routes.db = SimpleNamespace(
        pcp_programacao=FakeCollection([
            {"id": "slot-1", "tenant_id": "t1", "op_id": "op-1", "status": "planejado", "data_inicio": "2026-08-22", "qtd_planejada": 1000}
        ]),
        ops=FakeCollection([
            {
                "id": "op-1",
                "tenant_id": "t1",
                "numero_op": "OP-1",
                "status": "aberta",
                "items": [{"item": "Produto", "qtd_planejada": 1000}],
                "tecnico": {"items": [{"itens_formula": [{"catalog_id": "cat-1", "ingredient_name": "Agua", "percentage": 10}]}]},
            }
        ]),
        pd_catalog=FakeCollection([
            {"id": "cat-1", "tenant_id": "t1", "codigo_interno": "MP-AGU", "nome": "Agua"}
        ]),
        compras_itens=FakeCollection([
            {"id": "item-1", "tenant_id": "t1", "codigo_interno": "MP-AGU", "descricao": "Agua", "categoria": "mp", "estoque_minimo": 0}
        ]),
        estoque_items=FakeCollection([
            {"id": "est-1", "tenant_id": "t1", "tipo_item": "mp", "mp_id": "item-1", "quantidade_atual": 500, "posicao_cq": "quarentena"}
        ]),
        cq_status_lote=FakeCollection([]),
        compras_pos=FakeCollection([]),
        compras_condicoes_comerciais=FakeCollection([]),
    )

    result = asyncio.run(compras_routes._calcular_mrp("t1", None, {"id": "u1"}, 30))

    assert result["origem_demanda"] == "pcp_programacao"
    assert result["ops_consideradas"] == ["op-1"]
    assert result["itens_sugeridos"][0]["item_id"] == "item-1"
    assert result["itens_sugeridos"][0]["necessidade_bruta"] == 100.0
    assert result["itens_sugeridos"][0]["estoque_disponivel"] == 0.0


def test_criar_po_recusa_demanda_ja_vinculada():
    _install_ids()
    compras_routes.db = SimpleNamespace(
        compras_fornecedores=FakeCollection([
            {"id": "forn-1", "tenant_id": "t1", "razao_social": "Fornecedor", "cnpj": "", "homologacao": {"status": "homologado"}}
        ]),
        compras_demandas=FakeCollection([
            {"id": "dem-1", "tenant_id": "t1", "status": "po_emitida", "po_id": "po-old"}
        ]),
        compras_pos=FakeCollection([]),
    )

    async def fake_user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}

    compras_routes.get_current_user = fake_user
    payload = compras_routes.POCreate(
        fornecedor_id="forn-1",
        prazo_pagamento_texto="30 dias",
        prazo_pagamento_dias=30,
        demanda_ids=["dem-1"],
        itens=[
            compras_routes.POItemInput(
                item_id="item-1",
                item_descricao="Agua",
                quantidade_solicitada=10,
                unidade_compra="kg",
                preco_unitario=1,
            )
        ],
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(compras_routes.criar_po(payload, request=SimpleNamespace()))

    assert exc.value.status_code == 409


def test_criar_demanda_manual_com_numero_e_item(monkeypatch):
    _install_ids()
    compras_routes.db = SimpleNamespace(
        compras_itens=FakeCollection([
            {"id": "item-1", "tenant_id": "t1", "codigo_interno": "MP-AGU", "descricao": "Agua", "unidade_compra": "kg"}
        ]),
        compras_fornecedores=FakeCollection([]),
        compras_demandas=FakeCollection([]),
    )

    async def fake_user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}

    async def fake_next_sequence(_tenant_id, _key, start=1):
        return 12

    compras_routes.get_current_user = fake_user
    monkeypatch.setattr(compras_routes, "next_sequence", fake_next_sequence)

    payload = compras_routes.DemandaCompraCreate(
        item_id="item-1",
        quantidade=25,
        data_limite_pedido="2026-08-30",
        motivo="reposicao",
    )

    result = asyncio.run(compras_routes.criar_demanda(payload, request=SimpleNamespace()))

    assert result["numero_solicitacao"] == "SC-2026-012"
    assert result["item_codigo"] == "MP-AGU"
    assert result["status"] == "pendente"
    assert compras_routes.db.compras_demandas.docs[0]["quantidade"] == 25


def test_historico_precos_consolidado_junta_item_fornecedor():
    _install_ids()
    compras_routes.db = SimpleNamespace(
        compras_condicoes_comerciais=FakeCollection([
            {
                "id": "cot-1",
                "tenant_id": "t1",
                "fornecedor_id": "forn-1",
                "fornecedor_nome": "Fornecedor A",
                "item_id": "item-1",
                "item_descricao": "Agua",
                "preco_unitario": 10.0,
                "prazo_pagamento_texto": "30 DDL",
                "created_at": "2026-08-20T10:00:00",
            },
            {
                "id": "cot-2",
                "tenant_id": "t1",
                "fornecedor_id": "forn-2",
                "fornecedor_nome": "Fornecedor B",
                "item_id": "item-1",
                "item_descricao": "Agua",
                "preco_unitario": 8.0,
                "prazo_pagamento_texto": "28 DDL",
                "created_at": "2026-08-21T10:00:00",
            },
        ]),
        compras_itens=FakeCollection([
            {"id": "item-1", "tenant_id": "t1", "codigo_interno": "MP-AGU", "descricao": "Agua", "categoria": "mp", "unidade_compra": "kg"}
        ]),
        compras_fornecedores=FakeCollection([
            {"id": "forn-1", "tenant_id": "t1", "codigo_interno": "FOR-0001", "razao_social": "Fornecedor A", "homologacao": {"status": "homologado"}},
            {"id": "forn-2", "tenant_id": "t1", "codigo_interno": "FOR-0002", "razao_social": "Fornecedor B", "homologacao": {"status": "homologado"}},
        ]),
    )

    async def fake_user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}

    compras_routes.get_current_user = fake_user

    result = asyncio.run(compras_routes.historico_precos_consolidado(
        request=SimpleNamespace(),
        q=None,
        item_id=None,
        fornecedor_id=None,
        limit=120,
    ))

    assert result["total"] == 2
    assert result["total_itens"] == 1
    assert result["historico"][0]["item_codigo"] == "MP-AGU"
    assert result["historico"][0]["menor_preco_item"] == 8.0
    assert result["historico"][0]["status_homologacao"] == "homologado"
