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
                for key, value in update.get("$push", {}).items():
                    doc.setdefault(key, []).append(value)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

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


def test_sector_review_detail_returns_complete_payload_but_redacts_secrets():
    review = {
        "id": "review-1", "tenant_id": "tenant-1", "assigned_sector": "compras",
        "sector_status": "pendente", "source_payload": {
            "fornecedor": "Fornecedor A", "cnpj": "123", "senha": "nao-expor", "email": "",
        },
    }
    cad.db = SimpleNamespace(legacy_master_data_reviews=FakeCollection([review]))

    result = asyncio.run(cad.get_sector_legacy_review(
        "legacy_master_data_reviews", "review-1", SimpleNamespace()
    ))

    assert result["registro"]["source_payload"]["fornecedor"] == "Fornecedor A"
    assert result["registro"]["source_payload"]["senha"] == "*** protegido ***"
    assert result["cobertura_origem"] == {"campos": 4, "preenchidos": 3, "vazios": 1}
    assert result["operational_activation_allowed"] is False


def test_sector_review_forward_moves_same_document_without_copy(monkeypatch):
    review = {
        "id": "review-2", "tenant_id": "tenant-1", "assigned_sector": "compras",
        "next_sector": "cadastros", "sector_status": "em_revisao", "updated_at": "old",
    }
    collection = FakeCollection([review])
    cad.db = SimpleNamespace(legacy_master_data_reviews=collection)

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", fake_audit)
    result = asyncio.run(cad.action_sector_legacy_review(
        "legacy_master_data_reviews",
        "review-2",
        cad.LegacySectorReviewAction(
            action="encaminhar", observacao="Cadastro conferido pelo setor de compras.", expected_updated_at="old"
        ),
        SimpleNamespace(),
    ))

    assert len(collection.docs) == 1
    assert collection.docs[0]["assigned_sector"] == "cadastros"
    assert collection.docs[0]["next_sector"] is None
    assert collection.docs[0]["sector_status"] == "pendente"
    assert collection.docs[0]["sector_history"][0]["from"] == "compras"
    assert result["operational_records_created"] is False


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


def test_supplier_review_requires_valid_cnpj_when_creating(monkeypatch):
    cad.db = SimpleNamespace(
        legacy_master_data_reviews=FakeCollection([{
            "id": "review-supplier-1",
            "tenant_id": "tenant-1",
            "record_type": "supplier",
            "legacy_name": "Fornecedor legado",
            "activation_status": "bloqueado",
        }]),
        compras_fornecedores=FakeCollection([]),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(cad.decide_blocked_legacy_supplier(
            "review-supplier-1",
            cad.LegacySupplierDecision(
                decision="aprovar",
                justificativa="CNPJ conferido no documento fiscal.",
                resolution_mode="criar",
                cnpj_corrigido="123",
                razao_social_corrigida="Fornecedor legado",
            ),
            request=SimpleNamespace(),
        ))

    assert exc.value.status_code == 422


def test_supplier_review_approves_consolidation_without_creating_duplicate(monkeypatch):
    cad.db = SimpleNamespace(
        legacy_master_data_reviews=FakeCollection([{
            "id": "review-supplier-2",
            "tenant_id": "tenant-1",
            "record_type": "supplier",
            "legacy_name": "Fornecedor repetido",
            "activation_status": "bloqueado",
            "review_status": "pendente_revisao",
        }]),
        compras_fornecedores=FakeCollection([{
            "id": "supplier-official",
            "tenant_id": "tenant-1",
            "codigo_interno": "FOR-00001",
            "razao_social": "Fornecedor Oficial Ltda",
            "cnpj_normalizado": "11222333000181",
        }]),
    )

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", no_op)

    result = asyncio.run(cad.decide_blocked_legacy_supplier(
        "review-supplier-2",
        cad.LegacySupplierDecision(
            decision="aprovar",
            justificativa="Cadastro oficial conferido.",
            resolution_mode="consolidar",
            target_supplier_id="supplier-official",
        ),
        request=SimpleNamespace(),
    ))

    assert result["review_status"] == "aprovado"
    assert result["activation_status"] == "bloqueado"
    assert result["resolution"]["mode"] == "consolidar"
    assert result["resolution"]["target_supplier_id"] == "supplier-official"
    assert cad.db.compras_fornecedores.inserted == []


def test_sku_review_approves_client_and_keeps_record_blocked(monkeypatch):
    cad.db = SimpleNamespace(
        legacy_master_data_reviews=FakeCollection([{
            "id": "review-sku-1",
            "tenant_id": "tenant-1",
            "record_type": "sku",
            "legacy_name": "Produto legado",
            "activation_status": "bloqueado",
            "review_status": "pendente_revisao",
        }]),
        crm_clients=FakeCollection([{
            "id": "client-1",
            "tenant_id": "tenant-1",
            "nome_empresa": "Cliente Oficial",
            "cli3": "CLI",
            "cli4": "CLIE",
        }]),
        skus=FakeCollection([]),
    )

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", no_op)

    result = asyncio.run(cad.decide_blocked_legacy_sku(
        "review-sku-1",
        cad.LegacySkuDecision(
            decision="aprovar",
            justificativa="Cliente e código conferidos.",
            resolution_mode="criar",
            cliente_id="client-1",
            codigo_corrigido="SKU-LEGADO-001",
            nome_corrigido="Produto legado",
        ),
        request=SimpleNamespace(),
    ))

    assert result["review_status"] == "aprovado"
    assert result["activation_status"] == "bloqueado"
    assert result["resolution"]["cliente_id"] == "client-1"
    assert result["resolution"]["codigo"] == "SKU-LEGADO-001"
    assert cad.db.skus.inserted == []


def test_sku_review_can_consolidate_into_existing_sku(monkeypatch):
    cad.db = SimpleNamespace(
        legacy_master_data_reviews=FakeCollection([{
            "id": "review-sku-2",
            "tenant_id": "tenant-1",
            "record_type": "sku",
            "activation_status": "bloqueado",
        }]),
        crm_clients=FakeCollection([]),
        skus=FakeCollection([{
            "id": "sku-official",
            "tenant_id": "tenant-1",
            "codigo_interno": "SKU-001",
            "nome_produto": "Produto oficial",
            "cliente_id": "client-1",
            "cliente_nome": "Cliente Oficial",
        }]),
    )

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", no_op)

    result = asyncio.run(cad.decide_blocked_legacy_sku(
        "review-sku-2",
        cad.LegacySkuDecision(
            decision="aprovar",
            justificativa="Duplicidade técnica confirmada.",
            resolution_mode="consolidar",
            target_sku_id="sku-official",
        ),
        request=SimpleNamespace(),
    ))

    assert result["resolution"]["mode"] == "consolidar"
    assert result["resolution"]["target_sku_id"] == "sku-official"


def test_quality_approval_routes_legacy_lot_to_logistics(monkeypatch):
    cad.db = SimpleNamespace(
        legacy_inventory_cutover_reviews=FakeCollection([{
            "id": "lot-review-1", "tenant_id": "tenant-1", "record_type": "lot",
            "assigned_sector": "qualidade", "next_sector": "logistica",
            "review_stage": "validacao_cq_lote_legado", "sector_status": "pendente",
            "activation_status": "bloqueado", "operational_eligible": False,
            "sector_history": [],
        }]),
    )

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", no_op)
    result = asyncio.run(cad.decide_inventory_cutover_quality(
        "lot-review-1",
        cad.LegacyLotQualityDecision(decision="aprovar", justificativa="Documentação do lote conferida."),
        request=SimpleNamespace(),
    ))

    assert result["quality_decision"] == "aprovar"
    assert result["assigned_sector"] == "logistica"
    assert result["review_stage"] == "conferencia_fisica_lote"
    assert result["activation_status"] == "bloqueado"
    assert result["operational_eligible"] is False


def test_logistics_confirmation_keeps_legacy_address_non_operational(monkeypatch):
    cad.db = SimpleNamespace(
        legacy_inventory_cutover_reviews=FakeCollection([{
            "id": "address-review-1", "tenant_id": "tenant-1", "record_type": "address",
            "assigned_sector": "logistica", "review_stage": "conferencia_endereco_wms",
            "sector_status": "pendente", "activation_status": "bloqueado",
            "operational_eligible": False, "sector_history": [],
        }]),
    )

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "_audit", no_op)
    result = asyncio.run(cad.confirm_inventory_cutover_logistics(
        "address-review-1",
        cad.LegacyPhysicalConfirmation(
            decision="confirmar", observacoes="Posição física identificada.", endereco_codigo="FAB-1.1.1"
        ),
        request=SimpleNamespace(),
    ))

    assert result["physical_status"] == "conferido"
    assert result["review_status"] == "pronto_para_corte"
    assert result["activation_status"] == "bloqueado"
    assert result["operational_eligible"] is False


def test_prepare_legacy_op_routes_missing_bom_to_cadastros_without_creating_op(monkeypatch):
    review_collection = FakeCollection([{
        "id": "legacy-op-1",
        "tenant_id": "tenant-1",
        "record_type": "production_order",
        "source_key": "26261-04",
        "legacy_status": "Em Producao",
        "activation_status": "bloqueado",
        "assigned_sector": "pcp",
        "target_sku_id": "sku-1",
        "target_sku_code": "SKU-001",
        "source_payload": {
            "status": "Em Producao",
            "produto": "Produto legado",
            "qtdPlanejada": 1000,
            "produzido": 100,
            "lote": "26261/04",
        },
    }])
    cad.db = SimpleNamespace(
        legacy_op_reviews=review_collection,
        ops=FakeCollection([]),
        orders=FakeCollection([]),
        crm_clients=FakeCollection([{
            "id": "client-1", "tenant_id": "tenant-1", "nome_empresa": "Cliente", "stage": "cliente_fechado",
        }]),
        skus=FakeCollection([{
            "id": "sku-1", "tenant_id": "tenant-1", "codigo_interno": "SKU-001", "nome_produto": "Produto",
        }]),
        pcp_linhas=FakeCollection([{
            "id": "line-1", "tenant_id": "tenant-1", "nome": "Linha 1", "status": "ativa", "tipo": "envase",
        }]),
        bom_items=FakeCollection([]),
        workflow_tasks=FakeCollection([]),
    )

    async def fake_task(**kwargs):
        assert kwargs["blocking"] is True
        assert kwargs["category"] == "cadastros"
        return {"id": "task-1", "display_code": "TRF-2026-00001", "title": kwargs["title"], "status": "pendente"}

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(cad, "create_workflow_task", fake_task)
    monkeypatch.setattr(cad, "_audit", no_op)
    result = asyncio.run(cad.prepare_legacy_op_for_production(
        "legacy-op-1",
        cad.LegacyOPProductionAction(
            cliente_id="client-1",
            linha_id="line-1",
            qtd_planejada=1000,
            qtd_produzida_importada=100,
            justificativa="Conferencia operacional realizada pelo PCP.",
        ),
        request=SimpleNamespace(),
    ))

    assert result["status"] == "encaminhado_cadastros"
    assert result["promovido"] is False
    assert result["blockers"] == ["formula_bulk", "bom_embalagem"]
    assert cad.db.ops.inserted == []
    assert cad.db.orders.inserted == []
    updated = review_collection.docs[0]
    assert updated["assigned_sector"] == "cadastros"
    assert updated["next_sector"] == "pcp"
    assert updated["activation_status"] == "bloqueado"
