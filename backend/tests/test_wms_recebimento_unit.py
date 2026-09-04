import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import estoque_routes
import recebimento_routes


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

    async def update_one(self, query, update, upsert=False):
        for idx, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs[idx] = self._apply_update(doc, update)
                return SimpleNamespace(modified_count=1)
        if upsert:
            doc = dict(query)
            doc = self._apply_update(doc, update)
            self.docs.append(doc)
            return SimpleNamespace(modified_count=1, upserted_id=doc.get("id"))
        return SimpleNamespace(modified_count=0)

    async def count_documents(self, query):
        return len([doc for doc in self.docs if self._matches(doc, query)])

    async def distinct(self, key, query):
        return list({doc.get(key) for doc in self.docs if self._matches(doc, query)})

    def _matches(self, doc, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(doc, sub) for sub in expected):
                    return False
                continue
            value = self._get(doc, key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                if "$gt" in expected and not (value is not None and value > expected["$gt"]):
                    return False
                if "$gte" in expected and not (value is not None and value >= expected["$gte"]):
                    return False
                if "$lte" in expected and not (value is not None and value <= expected["$lte"]):
                    return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                continue
            if value != expected:
                return False
        return True

    def _get(self, doc, key):
        cur = doc
        for part in key.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _set(self, doc, key, value):
        cur = doc
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {k: v for k, v in doc.items() if k != "_id"}
        return dict(doc)

    def _apply_update(self, doc, update):
        doc = dict(doc)
        for key, value in update.get("$set", {}).items():
            self._set(doc, key, value)
        for key, value in update.get("$push", {}).items():
            arr = self._get(doc, key)
            if arr is None:
                self._set(doc, key, [])
                arr = self._get(doc, key)
            if isinstance(value, dict) and "$each" in value:
                arr.extend(value["$each"])
            else:
                arr.append(value)
        return doc


def _install_estoque():
    seq = {"n": 0}

    def new_id():
        seq["n"] += 1
        return f"id-{seq['n']}"

    async def fake_user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}

    estoque_routes._new_id = new_id
    estoque_routes._now_iso = lambda: "2026-08-20T10:00:00+00:00"
    estoque_routes._get_current_user = fake_user


def _install_recebimento():
    seq = {"n": 0}

    def new_id():
        seq["n"] += 1
        return f"id-{seq['n']}"

    async def fake_user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "admin", "name": "Admin"}

    recebimento_routes.new_id_func = new_id
    recebimento_routes.now_iso_func = lambda: "2026-08-20T10:00:00+00:00"
    recebimento_routes.get_current_user = fake_user


def test_wms_gera_enderecos_ajusta_saldo_e_transfere_lote():
    _install_estoque()
    estoque_routes.db = SimpleNamespace(
        wms_enderecos=FakeCollection([]),
        estoque_saldos_lote=FakeCollection([]),
        estoque_movimentos_lote=FakeCollection([]),
        estoque_items=FakeCollection([
            {
                "id": "est-1",
                "tenant_id": "t1",
                "tipo_item": "mp",
                "setor": "LOGISTICA",
                "nome": "Frasco 200ml",
                "codigo": "FR200",
                "quantidade_atual": 0,
                "unidade": "un",
                "posicao_cq": "aprovado",
            }
        ]),
    )

    gerados = asyncio.run(estoque_routes.gerar_wms_enderecos(
        estoque_routes.WMSGerarEnderecos(predios=1, ruas_por_predio=1, niveis_por_rua=1, posicoes_por_nivel=2),
        request=SimpleNamespace(),
    ))
    assert gerados["created"] == 2

    end1, end2 = estoque_routes.db.wms_enderecos.docs
    ajuste = asyncio.run(estoque_routes.ajustar_saldo_lote(
        estoque_routes.AjusteSaldoLoteCreate(
            item_id="est-1",
            lote="L-001",
            endereco_id=end1["id"],
            quantidade=100,
            modo="absoluto",
            motivo="inventario inicial",
        ),
        request=SimpleNamespace(),
    ))
    assert ajuste["saldo"]["quantidade"] == 100
    assert estoque_routes.db.estoque_items.docs[0]["quantidade_atual"] == 100

    transferencia = asyncio.run(estoque_routes.transferir_lote_endereco(
        estoque_routes.TransferenciaLoteCreate(
            item_id="est-1",
            lote="L-001",
            endereco_origem_id=end1["id"],
            endereco_destino_id=end2["id"],
            quantidade=40,
            motivo="realocacao",
        ),
        request=SimpleNamespace(),
    ))
    assert transferencia["origem"]["quantidade"] == 60
    assert transferencia["destino"]["quantidade"] == 40

    relatorio = asyncio.run(estoque_routes.relatorio_saldos_lote(request=SimpleNamespace()))
    assert relatorio["base"] == "estoque_saldos_lote"
    assert relatorio["total_quantidade"] == 100


def test_recebimento_integrado_atualiza_po_cria_checklist_paletes_e_saldo_wms():
    _install_recebimento()
    recebimento_routes.db = SimpleNamespace(
        recebimento_sla_config=FakeCollection([]),
        ops=FakeCollection([]),
        compras_pos=FakeCollection([
            {
                "id": "po-1",
                "tenant_id": "t1",
                "numero_po": "PO-2026-001",
                "fornecedor_id": "for-1",
                "fornecedor_nome": "Fornecedor A",
                "status": "confirmada",
                "itens": [
                    {
                        "id": "poi-1",
                        "item_id": "mp-1",
                        "item_descricao": "Agua",
                        "quantidade_solicitada": 100,
                        "quantidade_recebida": 0,
                        "unidade_compra": "kg",
                    }
                ],
                "nfs_vinculadas": [],
                "log_auditoria": [],
            }
        ]),
        estoque_items=FakeCollection([]),
        estoque_movimentos=FakeCollection([]),
        cq_registros_analise=FakeCollection([]),
        recebimentos=FakeCollection([]),
        wms_enderecos=FakeCollection([
            {"id": "end-1", "tenant_id": "t1", "codigo": "P01-R01-N01-P01", "setor": "LOGISTICA", "status": "livre"}
        ]),
        estoque_saldos_lote=FakeCollection([]),
        wms_paletes=FakeCollection([]),
        recebimento_agendamentos=FakeCollection([
            {"id": "ag-1", "tenant_id": "t1", "status": "confirmado"}
        ]),
    )

    entrada = asyncio.run(recebimento_routes.create_entrada(
        recebimento_routes.RecebimentoCreate(
            po_id="po-1",
            po_numero="PO-2026-001",
            fornecedor_id="for-1",
            fornecedor_nome="Fornecedor A",
            numero_nf="NF-100",
            data_nf="2026-08-20",
            agendamento_id="ag-1",
            items=[
                recebimento_routes.RecebimentoItem(
                    nome="Agua",
                    codigo="MP-AGU",
                    tipo_mp="FORMULACAO",
                    quantidade=60,
                    unidade="kg",
                    lote="L-AGU-1",
                    mp_id="mp-1",
                    po_item_id="poi-1",
                    endereco_id="end-1",
                    endereco_codigo="P01-R01-N01-P01",
                    palete=recebimento_routes.RecebimentoPaleteInput(quantidade_paletes=2),
                )
            ],
        ),
        request=SimpleNamespace(),
    ))

    assert entrada["integracao_po"]["status"] == "sincronizado"
    assert entrada["items"][0]["checklist_status"] == "ok"
    assert len(entrada["items"][0]["paletes"]) == 2
    assert recebimento_routes.db.compras_pos.docs[0]["itens"][0]["quantidade_recebida"] == 60
    assert recebimento_routes.db.compras_pos.docs[0]["status"] == "parcialmente_recebida"
    assert recebimento_routes.db.estoque_saldos_lote.docs[0]["quantidade"] == 60
    assert recebimento_routes.db.recebimento_agendamentos.docs[0]["status"] == "em_recebimento"


def test_agendamento_calendario_filtra_coleta_entrega_e_status():
    _install_recebimento()
    recebimento_routes.db = SimpleNamespace(
        compras_pos=FakeCollection([]),
        recebimento_agendamentos=FakeCollection([]),
    )

    created = asyncio.run(recebimento_routes.create_agendamento(
        recebimento_routes.AgendamentoRecebimentoCreate(
            tipo="entrega",
            titulo="Entrega PO",
            data="2026-08-21",
            status="agendado",
            fornecedor_nome="Fornecedor A",
        ),
        request=SimpleNamespace(),
    ))
    assert created["tipo"] == "entrega"

    updated = asyncio.run(recebimento_routes.update_agendamento(
        created["id"],
        recebimento_routes.AgendamentoRecebimentoUpdate(status="confirmado", doca="D1"),
        request=SimpleNamespace(),
    ))
    assert updated["status"] == "confirmado"

    calendario = asyncio.run(recebimento_routes.calendario_agendamentos(
        request=SimpleNamespace(),
        inicio="2026-08-20",
        fim="2026-08-22",
        tipo="entrega",
        status="confirmado",
    ))
    assert calendario["total"] == 1
    assert "2026-08-21" in calendario["por_data"]
