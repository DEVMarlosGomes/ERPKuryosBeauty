"""Teste integrado obrigatorio do ciclo fisico.

Nao depende de servidor, variavel de ambiente ou banco externo e, por isso,
nao pode ser pulado pela suite: PO -> recebimento unico -> CQ -> expedicao ->
devolucao -> retrabalho -> reinspecao -> reexpedicao -> NF.
"""

import asyncio
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import compras_routes
import cq_routes
import expedicao_routes
import recebimento_routes
import retrabalho_routes
from stock_ledger import baixar_saldo_lote_expedicao


class Cursor:
    def __init__(self, docs):
        self.docs = [deepcopy(doc) for doc in docs]

    def sort(self, key, direction):
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class Collection:
    def __init__(self, docs=None):
        self.docs = [deepcopy(doc) for doc in (docs or [])]

    @staticmethod
    def _get(doc, path):
        values = [doc]
        for part in path.split("."):
            next_values = []
            for value in values:
                if isinstance(value, list):
                    next_values.extend(item.get(part) for item in value if isinstance(item, dict))
                elif isinstance(value, dict):
                    next_values.append(value.get(part))
            values = next_values
        return values if len(values) > 1 else (values[0] if values else None)

    @staticmethod
    def _set(doc, path, value):
        target = doc
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = deepcopy(value)

    def _matches(self, doc, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(doc, branch) for branch in expected):
                    return False
                continue
            if key == "$expr":
                left, threshold = expected["$gte"]
                if isinstance(left, dict) and "$ifNull" in left:
                    actual = float(doc.get("quantidade", doc.get("quantidade_atual", 0)) or 0)
                else:
                    actual = 0
                if actual < float(threshold):
                    return False
                continue
            current = self._get(doc, key)
            current_values = current if isinstance(current, list) else [current]
            if isinstance(expected, dict):
                if "$ne" in expected and any(value == expected["$ne"] for value in current_values):
                    return False
                if "$in" in expected and not any(value in expected["$in"] for value in current_values):
                    return False
                if "$gte" in expected and not any(value is not None and value >= expected["$gte"] for value in current_values):
                    return False
                if "$exists" in expected and bool(any(value is not None for value in current_values)) != bool(expected["$exists"]):
                    return False
                continue
            if expected not in current_values:
                return False
        return True

    async def find_one(self, query, projection=None, sort=None):
        matches = [doc for doc in self.docs if self._matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                matches.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        return deepcopy(matches[0]) if matches else None

    def find(self, query, projection=None):
        return Cursor([doc for doc in self.docs if self._matches(doc, query)])

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    async def insert_one(self, doc):
        self.docs.append(deepcopy(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    def _apply(self, doc, query, update, inserting=False):
        if inserting:
            for key, value in update.get("$setOnInsert", {}).items():
                self._set(doc, key, value)
        for key, value in update.get("$set", {}).items():
            if ".$." in key:
                array_name, nested = key.split(".$.", 1)
                match_key = next((q for q in query if q.startswith(array_name + ".")), None)
                match_value = query.get(match_key) if match_key else None
                match_field = match_key.split(".", 1)[1] if match_key else None
                for item in doc.get(array_name, []):
                    if not match_field or item.get(match_field) == match_value:
                        self._set(item, nested, value)
                        break
            else:
                self._set(doc, key, value)
        for key, value in update.get("$inc", {}).items():
            self._set(doc, key, float(self._get(doc, key) or 0) + float(value))
        for key, value in update.get("$push", {}).items():
            target = self._get(doc, key)
            if not isinstance(target, list):
                self._set(doc, key, [])
                target = self._get(doc, key)
            target.extend(deepcopy(value["$each"])) if isinstance(value, dict) and "$each" in value else target.append(deepcopy(value))
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return doc

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, query, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            doc = {key: deepcopy(value) for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
            self._apply(doc, query, update, inserting=True)
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc.get("id"))
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def update_many(self, query, update):
        count_updated = 0
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, query, update)
                count_updated += 1
        return SimpleNamespace(matched_count=count_updated, modified_count=count_updated)

    async def find_one_and_update(self, query, update, **_kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply(doc, query, update)
                return deepcopy(doc)
        return None


def test_ciclo_integrado_obrigatorio_recebimento_ate_reexpedicao(monkeypatch):
    ids = count(1)
    new_id = lambda: f"flow-{next(ids)}"
    clock = count()
    base_time = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    now = lambda: (base_time + timedelta(milliseconds=next(clock))).isoformat()
    user = {"id": "admin-1", "name": "Admin", "role": "admin", "tenant_id": "tenant-flow"}

    async def auth(_request):
        return user

    async def noop(*_args, **_kwargs):
        return None

    sequence = count(1)

    async def next_sequence(*_args, **_kwargs):
        return next(sequence)

    db = SimpleNamespace(**{name: Collection([]) for name in [
        "tenant_settings", "recebimento_sla_config", "ops", "estoque_items", "estoque_movimentos",
        "estoque_movimentos_lote", "cq_registros_analise", "cq_status_lote", "cq_retencoes", "cq_rncs",
        "crm_clients", "recebimentos", "wms_enderecos", "estoque_saldos_lote", "wms_paletes",
        "recebimento_agendamentos", "retrabalho_ordens", "devolucoes_cliente", "expedicao_ordens",
        "expedicao_transacoes", "faturamento_notas", "cq_checklists", "compras_financeiro_eventos",
    ]})
    db.compras_pos = Collection([{
        "id": "po-1", "tenant_id": user["tenant_id"], "numero_po": "PO-1", "status": "confirmada",
        "fornecedor_id": "for-1", "fornecedor_nome": "Fornecedor",
        "itens": [{"id": "po-item-1", "item_id": "mp-1", "item_codigo": "MP-1", "item_descricao": "Materia Prima",
                   "tipo_mp": "FORMULACAO", "quantidade_solicitada": 60, "quantidade_recebida": 0, "unidade_compra": "kg"}],
        "nfs_vinculadas": [], "log_auditoria": [],
    }])

    for module in (compras_routes, recebimento_routes, cq_routes, retrabalho_routes, expedicao_routes):
        module.db = db
    compras_routes.get_current_user = auth
    recebimento_routes.get_current_user = auth
    cq_routes.get_current_user = auth
    retrabalho_routes.get_current_user = auth
    expedicao_routes.get_current_user = auth
    compras_routes.new_id_func = recebimento_routes.new_id_func = cq_routes.new_id_func = new_id
    retrabalho_routes.new_id_func = expedicao_routes.new_id_func = new_id
    compras_routes.now_iso_func = recebimento_routes.now_iso_func = cq_routes.now_iso_func = now
    retrabalho_routes.now_iso_func = expedicao_routes.now_iso_func = now
    monkeypatch.setattr(cq_routes, "audit_log", noop)
    monkeypatch.setattr(cq_routes, "create_workflow_task", noop)
    monkeypatch.setattr(cq_routes, "next_sequence", next_sequence)
    cq_routes._broadcast_event = None

    purchase = asyncio.run(compras_routes.receber_parcial_po(
        "po-1",
        compras_routes.POReceberParcialInput(
            nf_numero="NF-1", nf_data="2026-09-23", idempotency_key="mandatory-receipt-1",
            itens_recebidos=[compras_routes.POReceberItemInput(item_id="mp-1", quantidade_recebida=60, lote="FORN-1")],
        ), SimpleNamespace(),
    ))
    receipt = purchase["recebimento"]
    assert receipt["origem_registro"] == "compras_po"
    assert len(db.recebimentos.docs) == len(db.cq_registros_analise.docs) == len(db.estoque_saldos_lote.docs) == 1

    inbound_ra = receipt["items"][0]["ra_id"]
    asyncio.run(cq_routes.aprovar_ra(
        inbound_ra, cq_routes.AprovarInput(decisao="aprovado"), SimpleNamespace()
    ))
    inbound_saldo = db.estoque_saldos_lote.docs[0]
    assert inbound_saldo["status"] == "disponivel"

    # Simula a transformacao em PA e a primeira expedicao pelo mesmo ledger/lote.
    inbound_saldo["tipo_item"] = "produto_acabado"
    db.estoque_items.docs[0]["tipo_item"] = "produto_acabado"
    db.estoque_items.docs[0]["codigo"] = "SKU-1"
    inbound_saldo["codigo_item"] = "SKU-1"
    asyncio.run(baixar_saldo_lote_expedicao(
        db, new_id_fn=new_id, now_iso_fn=now, tenant_id=user["tenant_id"],
        saldo_lote_id=inbound_saldo["id"], quantidade=40, expedicao_id="exp-original",
        item_index=0, idempotency_key="mandatory-dispatch-original", usuario=user,
    ))
    db.expedicao_ordens.docs.append({
        "id": "exp-original", "tenant_id": user["tenant_id"], "numero_exp": "EXP-00001", "status": "entregue",
        "order_id": "order-1", "order_numero": "PED-1", "cliente_id": "client-1", "cliente_nome": "Cliente",
        "endereco_entrega": "Rua A", "items": [{"produto_nome": "Produto", "sku": "SKU-1", "quantidade": 40,
        "unidade": "un", "lote": inbound_saldo["lote"], "estoque_item_id": inbound_saldo["item_id"],
        "saldo_lote_id": inbound_saldo["id"], "lote_id": inbound_saldo["cq_lote_id"]}],
    })

    returned = asyncio.run(retrabalho_routes.registrar_devolucao_cliente(
        retrabalho_routes.DevolucaoClienteCreate(
            expedicao_id="exp-original", quantidade=20, motivo="Avaria identificada pelo cliente",
            idempotency_key="mandatory-return-1",
        ), SimpleNamespace(),
    ))
    assert returned["status"] == "aguardando_retrabalho"
    assert len(db.cq_rncs.docs) == 1
    rt_id = returned["rt_id"]
    asyncio.run(retrabalho_routes.update_ordem(
        rt_id, retrabalho_routes.RTUpdate(status="em_retrabalho"), SimpleNamespace()
    ))
    rt = asyncio.run(retrabalho_routes.concluir_ordem(
        rt_id, retrabalho_routes.RTConcluir(observacoes_conclusao="Reprocessado"), SimpleNamespace()
    ))
    assert rt["status"] == "aguardando_cq"

    asyncio.run(cq_routes.aprovar_ra(
        rt["nova_ra_id"], cq_routes.AprovarInput(decisao="aprovado"), SimpleNamespace()
    ))
    released = asyncio.run(db.devolucoes_cliente.find_one({"id": returned["id"]}))
    assert released["status"] == "liberado_cq"
    db.cq_checklists.docs.append({
        "id": "ck7-1", "tenant_id": user["tenant_id"], "lote_id": released["lote_id"],
        "tipo": "CK-7", "status": "aprovado",
    })

    reexp = asyncio.run(retrabalho_routes.gerar_reexpedicao_devolucao(
        returned["id"], retrabalho_routes.ReexpedicaoCreate(idempotency_key="mandatory-reexp-1"), SimpleNamespace()
    ))
    baixas = asyncio.run(expedicao_routes._baixar_lotes_da_expedicao(reexp, user, "mandatory-reexp-dispatch"))
    assert baixas[0]["saldo_lote_id"] == released["saldo_lote_id"]
    reexp["status"] = "expedido"
    asyncio.run(expedicao_routes._finalizar_reexpedicao_devolucao(reexp, user))

    final_return = asyncio.run(db.devolucoes_cliente.find_one({"id": returned["id"]}))
    assert final_return["status"] == "reexpedido"
    assert final_return["nf_reexpedicao_id"]
    assert db.faturamento_notas.docs[0]["tipo_nota"] == "reexpedicao_retrabalho"
    assert [event["evento"] for event in db.estoque_movimentos_lote.docs] == [
        "ENTRADA_RECEBIMENTO", "CQ_STATUS_ALTERADO", "SAIDA_EXPEDICAO",
        "ENTRADA_DEVOLUCAO_CLIENTE", "CQ_STATUS_ALTERADO", "SAIDA_EXPEDICAO",
    ]
