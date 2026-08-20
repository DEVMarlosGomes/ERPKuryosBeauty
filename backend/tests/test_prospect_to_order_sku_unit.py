import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, *_args):
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
                docs.sort(key=lambda doc: self._get_nested(doc, key) or "", reverse=direction < 0)
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
                self.docs[idx] = self._apply_update(doc, query, update)
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
                if "$ne" in value and current == value["$ne"]:
                    return False
                if "$in" in value and current not in value["$in"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _get_nested(self, doc, key):
        current = doc
        for part in key.split("."):
            if part == "$":
                return current
            if isinstance(current, list):
                return None
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _set_nested(self, doc, key, value, query=None):
        parts = key.split(".")
        current = doc
        idx = 0
        while idx < len(parts):
            part = parts[idx]
            if part == "$":
                prev = parts[idx - 1]
                match_id = (query or {}).get(f"{prev}.id")
                array = current if isinstance(current, list) else []
                target = next((item for item in array if item.get("id") == match_id), None)
                if target is None:
                    return
                current = target
                idx += 1
                continue
            if idx == len(parts) - 1:
                current[part] = value
                return
            current = current.setdefault(part, {})
            idx += 1

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    def _apply_update(self, doc, query, update):
        doc = dict(doc)
        for key, value in update.get("$set", {}).items():
            self._set_nested(doc, key, value, query)
        return doc


def test_projeto_aprovado_gera_sku_sem_cgi_e_sem_duplicar(monkeypatch):
    seq = {"id": 0, "sku": 0}

    def new_id():
        seq["id"] += 1
        return f"id-{seq['id']}"

    async def next_sku(_tenant_id, _cat3, _cli4):
        seq["sku"] += 1
        return seq["sku"]

    async def fake_find_or_create_produto_pai(**_kwargs):
        return {"id": "pai-1"}

    async def fake_vincular(**_kwargs):
        return {"ok": True}

    monkeypatch.setattr(crm_routes, "_new_id", new_id)
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-08-20T10:00:00")
    monkeypatch.setattr(crm_routes, "next_sku_per_pair_v2", next_sku)
    monkeypatch.setattr(crm_routes, "find_or_create_produto_pai", fake_find_or_create_produto_pai)
    monkeypatch.setattr(crm_routes, "_vincular_sku_ao_produto_pai_internal", fake_vincular)

    crm_routes.db = SimpleNamespace(
        crm_clients=FakeCollection([{
            "id": "cli-1",
            "tenant_id": "t1",
            "nome_empresa": "Miss Rose",
            "cli4": "MISR",
            "cli4_congelado": False,
        }]),
        crm_projects=FakeCollection([{
            "id": "proj-1",
            "tenant_id": "t1",
            "stage": "pedido_aprovado",
            "categoria": "Body Splash",
        }]),
        categorias=FakeCollection([{
            "id": "cat-1",
            "tenant_id": "t1",
            "status": "ativa",
            "cat3": "BSP",
            "nome": "Body Splash",
        }]),
        crm_samples=FakeCollection([{
            "id": "sample-1",
            "tenant_id": "t1",
            "projeto_id": "proj-1",
            "projeto_nome": "Projeto Body Splash",
            "cliente_id": "cli-1",
            "cliente_nome": "Miss Rose",
            "nome_produto": "Body Splash Flor D Aura",
            "categoria": "Body Splash",
            "variacoes": [{
                "id": "var-1",
                "codigo": "2026-1001-a",
                "status": "aprovada",
                "resultado": "aprovada",
            }],
        }]),
        skus=FakeCollection([]),
    )

    user = {"id": "u1", "name": "Admin", "tenant_id": "t1"}
    first = asyncio.run(crm_routes._generate_skus_for_project_approved_variations("proj-1", user))
    second = asyncio.run(crm_routes._generate_skus_for_project_approved_variations("proj-1", user))

    assert first[0]["sku"]["codigo_interno"] == "BSP-MISR-0001"
    assert second[0]["sku"]["codigo_interno"] == "BSP-MISR-0001"
    assert len(crm_routes.db.skus.docs) == 1
    assert seq["sku"] == 1
    assert crm_routes.db.skus.docs[0]["produto_pai_id"] == "pai-1"
