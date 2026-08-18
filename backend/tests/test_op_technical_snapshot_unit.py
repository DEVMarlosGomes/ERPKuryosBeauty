import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import orders_routes


class FakeCursor:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def sort(self, key, direction):
        reverse = direction < 0
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=reverse)
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    def _matches(self, doc, query):
        for key, value in query.items():
            current = doc.get(key)
            if isinstance(value, dict) and "$in" in value:
                if current not in value["$in"]:
                    return False
                continue
            if current != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection and projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)


def setup_db(*, items, approval=True, pd_status="APPROVED", ficha=True):
    orders_routes.db = SimpleNamespace(
        skus=FakeCollection([
            {
                "codigo_interno": "SKU-001",
                "tenant_id": "tenant-1",
                "amostra_id": "sample-1",
                "amostra_variacao_id": "var-1",
            }
        ]),
        pd_requests=FakeCollection([
            {
                "id": "pd-1",
                "tenant_id": "tenant-1",
                "status": pd_status,
                "linked_amostra_id": "sample-1",
                "linked_variacao_id": "var-1",
                "updated_at": "2026-08-13T10:00:00+00:00",
            }
        ]),
        pd_developments=FakeCollection([
            {"id": "dev-1", "tenant_id": "tenant-1", "pd_request_id": "pd-1"}
        ]),
        pd_formulas=FakeCollection([
            {"id": "formula-1", "tenant_id": "tenant-1", "development_id": "dev-1", "version": 1, "name": "Formula OP"}
        ]),
        pd_approvals=FakeCollection([
            {
                "development_id": "dev-1",
                "approved_by_internal": approval,
                "approved_by_client": approval,
            }
        ]),
        pd_formula_items=FakeCollection(items),
        pd_ficha_tecnica=FakeCollection([
            {"pd_request_id": "pd-1", "tenant_id": "tenant-1"}
        ] if ficha else []),
    )
    orders_routes.now_iso_func = lambda: "2026-08-13T12:00:00+00:00"


def test_op_technical_snapshot_accepts_approved_formula():
    setup_db(items=[
        {"formula_id": "formula-1", "ingredient_name": "Agua", "percentage": 70, "phase": "A"},
        {"formula_id": "formula-1", "ingredient_name": "Alcool", "percentage": 25, "phase": "A"},
        {"formula_id": "formula-1", "ingredient_name": "Fragrancia", "percentage": 5, "phase": "B"},
    ])

    snapshot = asyncio.run(orders_routes._build_op_technical_snapshot({
        "origem": "direto",
        "items": [{"codigo_kuryos": "SKU-001", "item": "Body Splash", "qtd": 100}],
    }, "tenant-1"))

    assert snapshot["apto_operacao"] is True
    assert snapshot["bloqueios"] == []
    assert snapshot["items"][0]["formula_versao"] == 1
    assert snapshot["items"][0]["total_percentual"] == 100


def test_op_technical_snapshot_blocks_unapproved_or_bad_formula():
    setup_db(
        approval=False,
        ficha=False,
        items=[
            {"formula_id": "formula-1", "ingredient_name": "Agua", "percentage": 60, "phase": ""},
            {"formula_id": "formula-1", "ingredient_name": "Alcool", "percentage": 25, "phase": "A"},
        ],
    )

    snapshot = asyncio.run(orders_routes._build_op_technical_snapshot({
        "origem": "direto",
        "items": [{"codigo_kuryos": "SKU-001", "item": "Body Splash", "qtd": 100}],
    }, "tenant-1"))

    assert snapshot["apto_operacao"] is False
    assert any("Formula sem aprovacao" in reason for reason in snapshot["bloqueios"])
    assert any("soma 85.0%" in reason for reason in snapshot["bloqueios"])
    assert any("Itens sem fase" in reason for reason in snapshot["bloqueios"])
    assert any("Ficha tecnica" in reason for reason in snapshot["alertas"])


def test_collect_op_rework_notes_includes_operational_annotations():
    data = orders_routes.OPReworkCreate(motivo="Ajustar odor", anotacoes="Cliente pediu menos alcool")
    notes = orders_routes._collect_op_rework_notes({
        "observacoes": "OP com divergencia sensorial",
        "numero_op": "OP-001",
        "tecnico": {
            "bloqueios": ["Formula sem fase"],
            "alertas": ["Ficha tecnica pendente"],
            "items": [{"item": "Body Splash", "pd_request_id": "pd-1", "formula_versao": 3, "total_percentual": 100}],
        },
        "historico": [{"tipo": "status", "observacao": "Linha pausada para avaliacao", "em": "2026-08-13T10:00:00"}],
        "apontamentos": [{"observacoes": "Odor muito alcoolico", "item_nome": "Body Splash"}],
        "perdas": [{"motivo": "Ajuste descartado", "quantidade": 2, "unidade": "kg"}],
        "pausas": [{"motivo": "Aguardando liberacao CQ", "tipo": "outro"}],
        "checklist": [{"item": "CQ", "status": "pendente", "observacoes": "Reavaliar odor"}],
    }, data, {
        "id": "order-1",
        "numero_pedido": "0007",
        "cliente": {"nome": "MISS ROSE"},
        "observacoes": "Cliente solicitou fragrancia mais suave",
        "items": [{"item": "Body Splash", "codigo_kuryos": "SKU-001", "qtd": 100, "prazo_entrega": "10 dias"}],
    })

    origins = {note["origem"] for note in notes}
    assert {
        "solicitacao_retrabalho",
        "observacoes_op",
        "pedido_comercial",
        "item_pedido",
        "ficha_tecnica_bloqueios",
        "ficha_tecnica_alertas",
        "snapshot_tecnico_item",
        "historico_op",
        "apontamento",
        "perda",
        "pausa",
        "checklist_op",
    } <= origins
