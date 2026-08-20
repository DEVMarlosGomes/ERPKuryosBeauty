import os
import sys

sys.path.insert(0, os.path.abspath("backend"))

from scripts.saneamento_skus_prospect_pedido import build_sku_saneamento_plan


def test_build_plan_recovers_safe_sku_links_and_pd_status():
    plan = build_sku_saneamento_plan(
        now="2026-08-20T12:00:00+00:00",
        skus=[
            {
                "id": "sku-1",
                "tenant_id": "t1",
                "codigo_interno": "BSP-MISS-0001",
                "nome_produto": "Body Splash Flor - V1",
                "cliente_id": "cli-1",
                "projeto_id": "proj-1",
                "amostra_id": "sample-1",
                "pd_concluido": False,
                "produto_pai_id": "",
                "status": "ativo",
            }
        ],
        samples=[
            {
                "id": "sample-1",
                "tenant_id": "t1",
                "cliente_id": "cli-1",
                "projeto_id": "proj-1",
                "nome_produto": "Body Splash Flor",
                "stage": "aprovada",
                "variacoes": [
                    {
                        "id": "var-1",
                        "codigo": "V1",
                        "status": "aprovada",
                    }
                ],
            }
        ],
        projects=[
            {
                "id": "proj-1",
                "tenant_id": "t1",
                "stage": "pedido_aprovado",
            }
        ],
        produtos_pai=[
            {
                "id": "pai-1",
                "tenant_id": "t1",
                "cliente_id": "cli-1",
                "nome": "Body Splash Flor",
            }
        ],
    )

    sku_update = next(update for update in plan["updates"] if update["collection"] == "skus")
    sample_update = next(update for update in plan["updates"] if update["collection"] == "crm_samples")

    assert sku_update["query"] == {"tenant_id": "t1", "id": "sku-1"}
    assert sku_update["set"]["amostra_variacao_id"] == "var-1"
    assert sku_update["set"]["pd_concluido"] is True
    assert sku_update["set"]["produto_pai_id"] == "pai-1"
    assert sample_update["query"] == {"tenant_id": "t1", "id": "sample-1", "variacoes.id": "var-1"}
    assert sample_update["set"]["variacoes.$.sku_id"] == "sku-1"
    assert plan["summary"]["updates_planejados"] == 2
    assert plan["summary"]["issues"] == 0


def test_build_plan_blocks_ambiguous_variation_and_parent():
    plan = build_sku_saneamento_plan(
        now="2026-08-20T12:00:00+00:00",
        skus=[
            {
                "id": "sku-1",
                "tenant_id": "t1",
                "nome_produto": "Body Splash Flor",
                "cliente_id": "cli-1",
                "projeto_id": "proj-1",
                "amostra_id": "sample-1",
                "status": "ativo",
            },
            {
                "id": "sku-2",
                "tenant_id": "t1",
                "nome_produto": "Body Splash Flor",
                "cliente_id": "cli-1",
                "projeto_id": "proj-1",
                "amostra_id": "sample-1",
                "status": "ativo",
            },
        ],
        samples=[
            {
                "id": "sample-1",
                "tenant_id": "t1",
                "cliente_id": "cli-1",
                "projeto_id": "proj-1",
                "nome_produto": "Body Splash Flor",
                "stage": "aprovada",
                "variacoes": [
                    {"id": "var-1", "status": "aprovada"},
                    {"id": "var-2", "status": "aprovada"},
                ],
            }
        ],
        projects=[{"id": "proj-1", "tenant_id": "t1", "stage": "pedido_aprovado"}],
        produtos_pai=[
            {"id": "pai-1", "tenant_id": "t1", "cliente_id": "cli-1", "nome": "Body Splash Flor"},
            {"id": "pai-2", "tenant_id": "t1", "cliente_id": "cli-1", "nome": "Body Splash Flor"},
        ],
    )

    issue_types = {issue["type"] for issue in plan["issues"]}

    assert "amostra_variacao_ambigua" in issue_types
    assert "produto_pai_ambiguidade" in issue_types
    assert all("amostra_variacao_id" not in update["set"] for update in plan["updates"])
    assert all("produto_pai_id" not in update["set"] for update in plan["updates"])
