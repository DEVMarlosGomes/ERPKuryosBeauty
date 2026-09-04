import os
import sys

sys.path.insert(0, os.path.abspath("."))

from scripts.saneamento_audit_v2 import build_saneamento_plan


NOW = "2026-08-25T10:00:00+00:00"


def test_existing_parent_in_produtos_pai_prevents_false_positive():
    plan = build_saneamento_plan(
        now=NOW,
        skus=[
            {
                "id": "sku-1",
                "tenant_id": "t1",
                "cliente_id": "cli-1",
                "produto_pai_id": "pai-1",
                "nome_produto": "Body Splash Flor - 2026-1001-a",
            }
        ],
        orders=[],
        clients=[{"id": "cli-1", "tenant_id": "t1", "nome_empresa": "Cliente"}],
        produtos_pai=[{"id": "pai-1", "tenant_id": "t1", "cliente_id": "cli-1", "nome": "Body Splash Flor"}],
        materiais=[],
        pd_stock_items=[],
    )

    assert plan["summary"]["operations"] == 0
    assert plan["summary"]["issues"] == 0


def test_missing_parent_creates_parent_and_links_sku_once():
    plan = build_saneamento_plan(
        now=NOW,
        skus=[
            {
                "id": "sku-1",
                "tenant_id": "t1",
                "cliente_id": "cli-1",
                "produto_pai_id": "missing-pai",
                "projeto_nome": "Body Splash Flor",
                "nome_produto": "Body Splash Flor - 2026-1001-a",
            },
            {
                "id": "sku-2",
                "tenant_id": "t1",
                "cliente_id": "cli-1",
                "produto_pai_id": "",
                "projeto_nome": "Body Splash Flor",
            },
        ],
        orders=[],
        clients=[{"id": "cli-1", "tenant_id": "t1", "nome_empresa": "Cliente"}],
        produtos_pai=[],
        materiais=[],
        pd_stock_items=[],
    )

    inserts = [op for op in plan["operations"] if op["action"] == "insert_one" and op["collection"] == "produtos_pai"]
    sku_updates = [op for op in plan["operations"] if op["collection"] == "skus"]

    assert len(inserts) == 1
    assert len(sku_updates) == 2
    assert {op["update"]["$set"]["produto_pai_id"] for op in sku_updates} == {inserts[0]["document"]["id"]}


def test_order_saneamento_recovers_client_id_and_pending_manual_items():
    plan = build_saneamento_plan(
        now=NOW,
        skus=[],
        orders=[
            {
                "id": "ord-1",
                "tenant_id": "t1",
                "origem": "gerador",
                "cliente": {"nome": "Cliente A", "cnpj": "12.345.678/0001-90"},
                "items": [
                    {"item": "Produto novo", "codigo_kuryos": "", "qtd": 100},
                    {"item": "Produto cadastrado", "sku_id": "sku-1", "codigo_kuryos": "BSP-CLIA-0001"},
                ],
                "cadastro_pendente": False,
                "cadastro_pendente_items": [],
            }
        ],
        clients=[
            {
                "id": "cli-1",
                "tenant_id": "t1",
                "nome_empresa": "Cliente A",
                "cnpj": "12.345.678/0001-90",
            }
        ],
        produtos_pai=[],
        materiais=[],
        pd_stock_items=[],
    )

    order_update = next(op for op in plan["operations"] if op["collection"] == "orders")
    update = order_update["update"]["$set"]

    assert update["cliente_id"] == "cli-1"
    assert update["cadastro_pendente"] is True
    assert update["cadastro_pendente_items"][0]["item"] == "Produto novo"


def test_lab_stock_creates_material_master_and_links_stock():
    plan = build_saneamento_plan(
        now=NOW,
        skus=[],
        orders=[],
        clients=[],
        produtos_pai=[],
        materiais=[],
        pd_stock_items=[
            {
                "id": "stock-1",
                "tenant_id": "t1",
                "categoria": "mp",
                "nome": "Agua",
                "codigo_interno": "MP-001",
                "unidade_medida": "L",
                "quantidade_atual": 10,
                "fornecedor": "Fornecedor A",
            }
        ],
    )

    insert = next(op for op in plan["operations"] if op["action"] == "insert_one" and op["collection"] == "materiais")
    update = next(op for op in plan["operations"] if op["collection"] == "pd_stock_items")

    assert insert["document"]["codigo_interno"] == "MP-90001"
    assert insert["document"]["nome"] == "Agua"
    assert update["update"]["$set"]["material_master_id"] == insert["document"]["id"]
