"""Homologacao opt-in do ciclo fisico contra MongoDB persistente real.

Executar com RUN_PERSISTENT_HOMOLOGATION=1. Cada execucao usa um banco exclusivo
e o remove em ``finally``; nenhuma colecao operacional da base local e tocada.
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.abspath("backend"))

import compras_routes
import cq_routes
import estoque_routes
import expedicao_routes
import orders_routes
import recebimento_routes
import retrabalho_routes


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PERSISTENT_HOMOLOGATION") != "1",
    reason="Defina RUN_PERSISTENT_HOMOLOGATION=1 para executar contra MongoDB real isolado.",
)


async def _run_persistent_cycle(monkeypatch):
    mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    run_id = uuid.uuid4().hex[:12]
    db_name = f"kuryos_homologacao_supply_{run_id}"
    tenant_id = f"homolog-{run_id}"
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")
    database = client[db_name]
    dropped = False

    ids = count(1)
    clock = count()
    base_time = datetime.now(timezone.utc)
    new_id = lambda: f"persist-{run_id}-{next(ids)}"
    now_iso = lambda: (base_time + timedelta(milliseconds=next(clock))).isoformat()
    user = {"id": "admin-homolog", "name": "Homologacao", "role": "admin", "tenant_id": tenant_id}

    async def auth(_request):
        return user

    async def noop(*_args, **_kwargs):
        return None

    sequence = count(1)

    async def next_sequence(*_args, **_kwargs):
        return next(sequence)

    try:
        compras_routes.init_compras(database, auth, new_id, now_iso)
        recebimento_routes.init_recebimento(database, auth, new_id, now_iso)
        estoque_routes.init_estoque(database, auth, new_id, now_iso)
        cq_routes.init_cq(database, auth, new_id, now_iso)
        orders_routes.init_orders(database, auth, new_id, now_iso)
        expedicao_routes.init_expedicao(database, auth, new_id, now_iso)
        retrabalho_routes.init_retrabalho(database, auth, new_id, now_iso)

        monkeypatch.setattr(cq_routes, "audit_log", noop)
        monkeypatch.setattr(cq_routes, "create_workflow_task", noop)
        monkeypatch.setattr(cq_routes, "next_sequence", next_sequence)
        monkeypatch.setattr(orders_routes, "_refresh_pcp_live_schedule", noop)

        await compras_routes.create_compras_indexes()
        await recebimento_routes.create_recebimento_indexes()
        await estoque_routes.create_estoque_indexes()
        await cq_routes.create_cq_indexes()
        await retrabalho_routes.create_retrabalho_indexes()

        await database.tenant_settings.insert_one({
            "tenant_id": tenant_id,
            "features": {
                orders_routes.PCP_MATERIAL_PICKING_FLAG: True,
                orders_routes.PCP_QUANTITY_PLANNING_FLAG: True,
            },
        })
        await database.compras_pos.insert_one({
            "id": "po-1", "tenant_id": tenant_id, "numero_po": "PO-HOMOLOG-1", "status": "confirmada",
            "fornecedor_id": "for-1", "fornecedor_nome": "Fornecedor Homologacao",
            "itens": [{
                "id": "po-item-1", "item_id": "mp-1", "item_codigo": "MP-1",
                "item_descricao": "Materia Prima Homologacao", "tipo_mp": "FORMULACAO",
                "quantidade_solicitada": 60, "quantidade_recebida": 0, "unidade_compra": "kg",
            }],
            "nfs_vinculadas": [], "log_auditoria": [], "created_at": now_iso(),
        })

        purchase = await compras_routes.receber_parcial_po(
            "po-1",
            compras_routes.POReceberParcialInput(
                nf_numero="NF-HOMOLOG-1", nf_data=base_time.date().isoformat(),
                idempotency_key=f"receipt-{run_id}",
                itens_recebidos=[compras_routes.POReceberItemInput(
                    item_id="mp-1", quantidade_recebida=60, lote="MP-HOMOLOG-1", quantidade_paletes=1,
                )],
            ),
            SimpleNamespace(),
        )
        receipt = purchase["recebimento"]
        await cq_routes.aprovar_ra(
            receipt["items"][0]["ra_id"], cq_routes.AprovarInput(decisao="aprovado"), SimpleNamespace()
        )

        await database.skus.insert_one({
            "id": "sku-1", "tenant_id": tenant_id, "codigo_interno": "SKU-HOMOLOG-1",
            "apresentacao": {"qtd_envase": 1}, "status": "ativo",
        })
        await database.bom_items.insert_one({
            "id": "bom-1", "tenant_id": tenant_id, "sku_id": "sku-1", "camada": "embalagem",
            "material_id": "mp-1", "codigo_material": "MP-1", "nome_material": "Materia Prima Homologacao",
            "quantidade_por_unidade": 1, "unidade_consumo": "kg", "vigente": True,
        })
        await database.ops.insert_one({
            "id": "op-1", "tenant_id": tenant_id, "numero_op": "OP-HOMOLOG-1", "pedido_id": "order-1",
            "status": "em_processo", "pcp_status": "em_execucao", "apontamentos": [],
            "items": [{
                "sku_id": "sku-1", "codigo_kuryos": "SKU-HOMOLOG-1", "item": "Produto Homologacao",
                "qtd_planejada": 40, "qtd_produzida": 0, "unidade": "un", "lote": "PA-HOMOLOG-1",
            }],
            "created_at": now_iso(), "updated_at": now_iso(),
        })

        picking = await orders_routes.confirm_wms_picking_for_op(
            "op-1", orders_routes.WMSPickingConfirm(idempotency_key=f"picking-{run_id}"), SimpleNamespace()
        )
        assert picking["status"] == "confirmada"
        assert picking["reserva_aplicada"] is True

        pointed = await orders_routes.apontar_producao(
            "op-1",
            orders_routes.ApontamentoCreate(
                qtd_produzida=40, setor="envase", idempotency_key=f"pointing-{run_id}"
            ),
            SimpleNamespace(),
        )
        assert pointed["items"][0]["qtd_produzida"] == 40
        await database.ops.update_one(
            {"id": "op-1", "tenant_id": tenant_id},
            {"$set": {"status": "aguardando_confirmacao_pcp", "updated_at": now_iso()}},
        )
        conference = await orders_routes.conferir_produto_acabado(
            "op-1",
            orders_routes.PAConferenceCreate(
                quantidade_paletes=2, data_validade=(base_time.date() + timedelta(days=365)).isoformat(),
                idempotency_key=f"conference-{run_id}",
            ),
            SimpleNamespace(),
        )
        pa = conference["itens"][0]
        await cq_routes.aprovar_ra(pa["ra_id"], cq_routes.AprovarInput(decisao="aprovado"), SimpleNamespace())
        await database.cq_checklists.insert_one({
            "id": "ck7-pa", "tenant_id": tenant_id, "lote_id": pa["lote_id"],
            "tipo": "CK-7", "status": "aprovado", "created_at": now_iso(),
        })

        expedition = await expedicao_routes.create_ordem(
            expedicao_routes.ExpCreate(
                order_id="order-1", order_numero="PED-HOMOLOG-1", cliente_id="client-1",
                cliente_nome="Cliente Homologacao", endereco_entrega="Endereco de teste",
                items=[expedicao_routes.ExpItem(
                    produto_nome="Produto Homologacao", sku="SKU-HOMOLOG-1", quantidade=30,
                    lote=pa["lote"], estoque_item_id=pa["estoque_item_id"], saldo_lote_id=pa["saldo_lote_id"],
                    lote_id=pa["lote_id"], palete_id=pa["palete_ids"][0],
                )],
            ),
            SimpleNamespace(),
        )
        await expedicao_routes.update_ordem(
            expedition["id"], expedicao_routes.ExpUpdate(status="preparando"), SimpleNamespace()
        )
        await expedicao_routes.conferir_ordem(
            expedition["id"],
            expedicao_routes.ConferenciaCreate(items=[expedicao_routes.ConferenciaItem(
                produto_nome="Produto Homologacao", quantidade_conferida=30, lote_conferido=pa["lote"], ok=True,
            )]),
            SimpleNamespace(),
        )
        dispatched = await expedicao_routes.update_ordem(
            expedition["id"],
            expedicao_routes.ExpUpdate(status="expedido", idempotency_key=f"dispatch-{run_id}"),
            SimpleNamespace(),
        )
        assert dispatched["status"] == "expedido"

        returned = await retrabalho_routes.registrar_devolucao_cliente(
            retrabalho_routes.DevolucaoClienteCreate(
                expedicao_id=expedition["id"], quantidade=10, motivo="Avaria identificada na homologacao",
                idempotency_key=f"return-{run_id}",
            ),
            SimpleNamespace(),
        )
        await retrabalho_routes.update_ordem(
            returned["rt_id"], retrabalho_routes.RTUpdate(status="em_retrabalho"), SimpleNamespace()
        )
        rt = await retrabalho_routes.concluir_ordem(
            returned["rt_id"], retrabalho_routes.RTConcluir(observacoes_conclusao="Retrabalho homologado"),
            SimpleNamespace(),
        )
        await cq_routes.aprovar_ra(
            rt["nova_ra_id"], cq_routes.AprovarInput(decisao="aprovado"), SimpleNamespace()
        )
        released = await database.devolucoes_cliente.find_one({"id": returned["id"]}, {"_id": 0})
        await database.cq_checklists.insert_one({
            "id": "ck7-return", "tenant_id": tenant_id, "lote_id": released["lote_id"],
            "tipo": "CK-7", "status": "aprovado", "created_at": now_iso(),
        })
        reexpedition = await retrabalho_routes.gerar_reexpedicao_devolucao(
            returned["id"], retrabalho_routes.ReexpedicaoCreate(idempotency_key=f"reexp-{run_id}"),
            SimpleNamespace(),
        )
        await expedicao_routes.update_ordem(
            reexpedition["id"], expedicao_routes.ExpUpdate(status="preparando"), SimpleNamespace()
        )
        await expedicao_routes.conferir_ordem(
            reexpedition["id"],
            expedicao_routes.ConferenciaCreate(items=[expedicao_routes.ConferenciaItem(
                produto_nome="Produto Homologacao", quantidade_conferida=10,
                lote_conferido=released["lote"], ok=True,
            )]),
            SimpleNamespace(),
        )
        await expedicao_routes.update_ordem(
            reexpedition["id"],
            expedicao_routes.ExpUpdate(status="expedido", idempotency_key=f"reexp-dispatch-{run_id}"),
            SimpleNamespace(),
        )

        collections = {
            "pos": "compras_pos",
            "recebimentos": "recebimentos",
            "saldos_lote": "estoque_saldos_lote",
            "ledger": "estoque_movimentos_lote",
            "paletes": "wms_paletes",
            "separacoes_empenhos": "wms_separacoes",
            "conferencias_pa": "pa_conferencias",
            "expedicoes": "expedicao_ordens",
            "devolucoes": "devolucoes_cliente",
            "retrabalhos": "retrabalho_ordens",
            "notas_fiscais": "faturamento_notas",
        }
        counts = {
            label: await database[name].count_documents({"tenant_id": tenant_id})
            for label, name in collections.items()
        }
        assert all(value > 0 for value in counts.values()), counts
        assert await database.estoque_movimentos_lote.count_documents({
            "tenant_id": tenant_id, "evento": "CONSUMO_OP",
        }) == 1
        assert await database.estoque_movimentos_lote.count_documents({
            "tenant_id": tenant_id, "evento": "ENTRADA_PRODUTO_ACABADO",
        }) == 1
        final_return = await database.devolucoes_cliente.find_one({"id": returned["id"]}, {"_id": 0})
        assert final_return["status"] == "reexpedido"
        assert final_return["nf_reexpedicao_id"]

        report = {
            "run_id": run_id,
            "database": db_name,
            "tenant_id": tenant_id,
            "status": "homologado",
            "counts_before_rollback": counts,
        }
        print("PERSISTENT_HOMOLOGATION=" + json.dumps(report, sort_keys=True))
        return report
    finally:
        await client.drop_database(db_name)
        dropped = db_name not in await client.list_database_names()
        print("PERSISTENT_HOMOLOGATION_ROLLBACK=" + json.dumps({"database": db_name, "dropped": dropped}))
        client.close()
        assert dropped, f"Rollback falhou: banco {db_name} ainda existe"


def test_full_supply_cycle_against_persistent_mongo_with_controlled_rollback(monkeypatch):
    report = asyncio.run(_run_persistent_cycle(monkeypatch))
    assert report["status"] == "homologado"
