import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

import cadastros_master_routes as cad


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self, _length):
        return [dict(doc) for doc in self.docs]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.inserted = []
        self.updated = []

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    async def insert_one(self, doc):
        stored = dict(doc)
        self.docs.append(stored)
        self.inserted.append(stored)
        return SimpleNamespace(inserted_id=stored.get("id"))

    async def update_one(self, query, update):
        self.updated.append((query, update))
        for doc in self.docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    def _matches(self, doc, query):
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                continue
            if value != expected:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {k: v for k, v in doc.items() if k != "_id"}
        return dict(doc)


def setup_module(module):
    cad._new_id = lambda: "new-id"
    cad._now_iso = lambda: "2026-08-18T12:00:00+00:00"

    async def fake_current_user(request):
        return {
            "id": "user-1",
            "tenant_id": "tenant-1",
            "role": "admin",
            "name": "Admin",
        }

    cad._get_current_user = fake_current_user


def test_validate_catmp3_accepts_three_alphanumeric_chars():
    assert cad._validate_catmp3("fra") == "FRA"
    assert cad._validate_catmp3("e01") == "E01"


def test_validate_catmp3_rejects_invalid_codes():
    with pytest.raises(HTTPException) as exc:
        cad._validate_catmp3("fragrance")
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    ("raw", "tipo2"),
    [
        ("mp", "MP"),
        ("materia-prima", "MP"),
        ("insumo", "EP"),
        ("embalagem secundaria", "ES"),
        ("rotulo", "RT"),
    ],
)
def test_material_tipo_business_mapping(raw, tipo2):
    assert cad._material_tipo_from_business(raw) == tipo2


def test_create_produto_final_uses_cat3_cli4_sequence_and_freezes_client(monkeypatch):
    cad.db = SimpleNamespace(
        categorias=FakeCollection([
            {"tenant_id": "tenant-1", "cat3": "BSP", "status": "ativa", "nome": "Body Splash"}
        ]),
        crm_clients=FakeCollection([
            {"tenant_id": "tenant-1", "id": "cli-1", "nome_empresa": "Miss Rose", "cli4": "MISS"}
        ]),
        skus=FakeCollection([]),
    )

    async def fake_next_sku(tenant_id, cat3, cli4):
        assert (tenant_id, cat3, cli4) == ("tenant-1", "BSP", "MISS")
        return 7

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "next_sku_per_pair_v2", fake_next_sku)
    monkeypatch.setattr(cad, "_audit", fake_audit)

    result = asyncio.run(cad.create_produto_final(
        cad.ProdutoFinalCreate(
            nome_produto="Body Splash Flor",
            cliente_id="cli-1",
            cat3="BSP",
            pd_request_id="pd-1",
        ),
        request=SimpleNamespace(),
    ))

    assert result["codigo_interno"] == "BSP-MISS-0007"
    assert result["pd_concluido"] is True
    assert cad.db.skus.inserted[0]["codigo_interno"] == "BSP-MISS-0007"
    assert cad.db.crm_clients.updated[0][1]["$set"]["cli4_congelado"] is True


def test_update_produto_final_saves_formula_bom_specs_and_address(monkeypatch):
    cad.db = SimpleNamespace(
        skus=FakeCollection([
            {
                "tenant_id": "tenant-1",
                "id": "sku-1",
                "codigo_interno": "BSP-MISS-0001",
                "nome_produto": "Body Splash",
                "status": "ativo",
            }
        ]),
    )

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", fake_audit)

    result = asyncio.run(cad.update_produto_final(
        "sku-1",
        cad.ProdutoFinalUpdate(
            formula=[{"material_nome": "Agua", "percentual": 70, "funcao": "base"}],
            bom=[{"material_nome": "Frasco 200 ml", "quantidade": 1, "unidade": "un"}],
            especificacoes_tecnicas={"ph": "5.5", "odor": "caracteristico"},
            enderecamento={"rua": "A", "modulo": "01", "nivel": "02", "posicao": "03"},
        ),
        request=SimpleNamespace(),
    ))

    assert result["formula"][0]["material_nome"] == "Agua"
    assert result["bom"][0]["quantidade"] == 1
    assert result["especificacoes_tecnicas"]["ph"] == "5.5"
    assert result["enderecamento"]["rua"] == "A"


def test_delete_material_cadastro_is_soft_delete(monkeypatch):
    cad.db = SimpleNamespace(
        materiais=FakeCollection([
            {"tenant_id": "tenant-1", "id": "mat-1", "nome": "Frasco", "status": "ativo"}
        ]),
    )

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", fake_audit)

    result = asyncio.run(cad.delete_material_cadastro("mat-1", request=SimpleNamespace()))

    assert result["status"] == "inativo"
    assert result["deleted_at"] == "2026-08-18T12:00:00+00:00"


def test_concluir_cadastro_bom_creates_purchase_release(monkeypatch):
    request_doc = {
        "id": "cad-bom-1",
        "tenant_id": "tenant-1",
        "kickoff_id": "ko-1",
        "numero_kickoff": "KO-2026-0001",
        "bom_chave": "embalagem|novo|frasco novo",
        "descricao": "Frasco novo",
        "tipo_bom": "embalagem_primaria",
        "unidade": "un",
        "quantidade_total_pedido": 1000,
        "status": "pendente_cadastro",
        "anexo_file_ids": ["file-1"],
    }
    cad.db = SimpleNamespace(
        cadastro_bom_solicitacoes=FakeCollection([request_doc]),
        files=FakeCollection([{"id": "file-1", "tenant_id": "tenant-1", "is_deleted": False, "original_filename": "frasco.pdf"}]),
        kickoffs=FakeCollection([]),
    )

    async def fake_material(doc, data, user):
        return {"id": "mat-1", "codigo_interno": "EP-00001", "nome": "Frasco novo", "unidade_compra": "un"}

    async def fake_item(doc, material, user):
        return {"id": "item-1", "codigo_interno": "EP-00001", "descricao": "Frasco novo", "unidade_compra": "un"}

    async def fake_demand(doc, item, user):
        return {"id": "dem-1", "status": "pendente"}

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_ensure_material_from_bom_request", fake_material)
    monkeypatch.setattr(cad, "_ensure_purchase_item_from_material", fake_item)
    monkeypatch.setattr(cad, "_ensure_purchase_demand_from_bom", fake_demand)
    monkeypatch.setattr(cad, "create_workflow_task", no_op)
    monkeypatch.setattr(cad, "_audit", no_op)

    result = asyncio.run(cad.conclude_cadastro_bom_request(
        "cad-bom-1",
        cad.CadastroBomConcluir(nome="Frasco novo", anexo_file_ids=["file-1"]),
        request=SimpleNamespace(),
    ))

    assert result["status"] == "cadastrado"
    assert result["material_id"] == "mat-1"
    assert result["compras_item_id"] == "item-1"
    assert result["demanda_compra_id"] == "dem-1"
    assert result["anexos_count"] == 1


def test_concluir_cadastro_bom_requires_attachment():
    cad.db = SimpleNamespace(
        cadastro_bom_solicitacoes=FakeCollection([{
            "id": "cad-bom-2",
            "tenant_id": "tenant-1",
            "status": "pendente_cadastro",
            "anexo_file_ids": [],
        }]),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cad.conclude_cadastro_bom_request(
            "cad-bom-2", cad.CadastroBomConcluir(), request=SimpleNamespace()
        ))
    assert exc.value.status_code == 422
