import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import pd_routes


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None, sort=None):
        docs = [doc for doc in self.docs if self._matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda doc: self._get_nested(doc, key) or "", reverse=direction < 0)
        if not docs:
            return None
        return self._project(docs[0], projection)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update):
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs[idx] = self._apply_update(doc, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

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

    def _set_nested(self, doc, key, value):
        current = doc
        parts = key.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    def _apply_update(self, doc, update):
        doc = dict(doc)
        for key, value in update.get("$set", {}).items():
            self._set_nested(doc, key, value)
        for key, value in update.get("$push", {}).items():
            current = self._get_nested(doc, key) or []
            current.append(value)
            self._set_nested(doc, key, current)
        return doc


def _install_runtime(monkeypatch):
    seq = {"id": 0, "next": 0}

    def new_id():
        seq["id"] += 1
        return f"id-{seq['id']}"

    async def fake_next_sequence(_tenant_id, _key, start=0):
        seq["next"] += 1
        return start + seq["next"]

    pd_routes.new_id_func = new_id
    pd_routes.now_iso_func = lambda: "2026-08-20T10:00:00"
    monkeypatch.setattr(pd_routes, "next_sequence", fake_next_sequence)


def test_pd_fornecedor_homologado_sincroniza_com_compras_sem_duplicar(monkeypatch):
    _install_runtime(monkeypatch)
    supplier = {
        "id": "hom-for-1",
        "tenant_id": "t1",
        "razao_social": "Fornecedor Alpha",
        "nome_fantasia": "Alpha",
        "cnpj": "12.345.678/0001-95",
        "cnpj_normalized": "12345678000195",
        "contato_nome": "Maria",
        "contato_email": "maria@alpha.com",
        "contato_telefone": "11999999999",
        "categoria": "MP_FORMULACAO",
        "status": "pendente",
    }
    pd_routes.db = SimpleNamespace(
        homologacao_fornecedores=FakeCollection([supplier]),
        compras_fornecedores=FakeCollection([]),
    )

    synced = asyncio.run(pd_routes._upsert_compras_fornecedor_from_homologacao("t1", supplier, {"id": "u1", "name": "Admin"}))

    assert synced["homologacao"]["status"] == "em_processo"
    assert synced["origem_homologacao_id"] == "hom-for-1"
    assert len(pd_routes.db.compras_fornecedores.docs) == 1
    assert pd_routes.db.homologacao_fornecedores.docs[0]["compras_fornecedor_id"] == synced["id"]

    supplier = {**supplier, "status": "homologado", "data_homologacao": "2026-08-20T10:00:00"}
    synced_again = asyncio.run(pd_routes._upsert_compras_fornecedor_from_homologacao("t1", supplier, {"id": "u1", "name": "Admin"}))

    assert len(pd_routes.db.compras_fornecedores.docs) == 1
    assert synced_again["id"] == synced["id"]
    assert synced_again["homologacao"]["status"] == "homologado"


def test_pd_mp_homologada_cria_material_item_compras_e_catalogo(monkeypatch):
    _install_runtime(monkeypatch)
    supplier = {
        "id": "hom-for-1",
        "tenant_id": "t1",
        "razao_social": "Fornecedor Alpha",
        "nome_fantasia": "Alpha",
        "cnpj": "",
        "status": "homologado",
    }
    mp = {
        "id": "mp-1",
        "tenant_id": "t1",
        "nome": "Acido Hialuronico",
        "codigo_interno": "",
        "inci": "Sodium Hyaluronate",
        "tipo_mp": "FORMULACAO",
        "fornecedor_id": "hom-for-1",
        "fornecedor_nome": "Alpha",
        "funcao": "ativo",
        "custo_referencia": 120.5,
        "unidade": "kg",
        "status": "homologada",
    }
    pd_routes.db = SimpleNamespace(
        homologacao_fornecedores=FakeCollection([supplier]),
        homologacao_mps=FakeCollection([mp]),
        compras_fornecedores=FakeCollection([]),
        materiais=FakeCollection([]),
        compras_itens=FakeCollection([]),
        pd_catalog=FakeCollection([]),
    )

    synced_mp = asyncio.run(pd_routes._upsert_material_from_homologacao_mp("t1", mp, {"id": "u1", "name": "Admin"}))

    assert synced_mp["codigo_interno"].startswith("MP-")
    assert synced_mp["material_id"]
    assert synced_mp["compras_item_id"]
    assert len(pd_routes.db.materiais.docs) == 1
    assert len(pd_routes.db.compras_itens.docs) == 1
    assert len(pd_routes.db.pd_catalog.docs) == 1
    assert pd_routes.db.compras_itens.docs[0]["fornecedores_homologados"]

    asyncio.run(pd_routes._upsert_material_from_homologacao_mp("t1", synced_mp, {"id": "u1", "name": "Admin"}))

    assert len(pd_routes.db.materiais.docs) == 1
    assert len(pd_routes.db.compras_itens.docs) == 1
    assert len(pd_routes.db.pd_catalog.docs) == 1
