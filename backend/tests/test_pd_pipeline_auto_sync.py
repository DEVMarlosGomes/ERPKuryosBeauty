import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("backend"))

import crm_routes
import pd_routes


class FakeResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class TrackingCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.update_calls = []
        self.insert_calls = []

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        snapshot = dict(doc)
        self.insert_calls.append(snapshot)
        self.docs.append(snapshot)
        return FakeResult()

    async def update_one(self, query, update):
        self.update_calls.append((dict(query), update))
        for doc in self.docs:
            if not self._matches(doc, query):
                continue
            for key, value in (update.get("$set") or {}).items():
                if "." not in key:
                    doc[key] = value
            for key, value in (update.get("$push") or {}).items():
                if "." not in key:
                    doc.setdefault(key, [])
                    doc[key].append(value)
            return FakeResult(matched_count=1)
        return FakeResult(matched_count=0)

    def _matches(self, doc, query):
        for key, value in query.items():
            if "." not in key:
                if doc.get(key) != value:
                    return False
                continue

            head, tail = key.split(".", 1)
            current = doc.get(head)
            if isinstance(current, list):
                if not any(isinstance(item, dict) and item.get(tail) == value for item in current):
                    return False
                continue
            if not isinstance(current, dict) or current.get(tail) != value:
                return False
        return True

    def _project(self, doc, projection):
        if projection is None or projection.get("_id") != 0:
            return dict(doc)
        return {key: value for key, value in doc.items() if key != "_id"}


def test_bootstrap_syncs_card_and_sample_to_development(monkeypatch):
    sample_doc = {
        "id": "sample-1",
        "tenant_id": "tenant-1",
        "nome_produto": "Base Teste",
        "quantidade_por_variacao": 15,
        "unidade_quantidade": "ml",
        "variacoes": [
            {
                "id": "var-1",
                "codigo": "2026-1001-A",
                "descricao_aplicacao": "Versão A",
                "percentual_fragrancia": 0,
            }
        ],
    }
    card_doc = {
        "id": "card-1",
        "tenant_id": "tenant-1",
        "status_pd": "solicitado",
        "amostra_id": "sample-1",
        "amostra_variacao_id": "var-1",
    }

    fake_db = SimpleNamespace(
        crm_samples=TrackingCollection([sample_doc]),
        pd_requests=TrackingCollection([{"id": "req-1", "tenant_id": "tenant-1", "status": "OPEN"}]),
        pd_request_status_history=TrackingCollection(),
        pd_developments=TrackingCollection(),
        pd_formulas=TrackingCollection(),
        pd_formula_items=TrackingCollection(),
        pd_cards=TrackingCollection([card_doc]),
    )
    crm_routes.db = fake_db
    crm_routes._broadcast_event = None

    generated_ids = iter(["hist-1", "dev-1", "formula-1"])
    monkeypatch.setattr(crm_routes, "_new_id", lambda: next(generated_ids))
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-07-15T15:00:00+00:00")

    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)

    user = {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1"}
    card_payload = dict(card_doc)

    asyncio.run(
        crm_routes._bootstrap_pd_development_for_variacao(
            pd_request_id="req-1",
            card=card_payload,
            user=user,
        )
    )

    assert fake_db.pd_requests.docs[0]["status"] == "IN_PROGRESS"
    assert fake_db.pd_cards.docs[0]["status_pd"] == "em_desenvolvimento"
    assert fake_db.pd_cards.docs[0]["pd_request_id"] == "req-1"
    assert fake_db.pd_request_status_history.insert_calls[-1]["to_status"] == "IN_PROGRESS"

    sample_update = fake_db.crm_samples.update_calls[-1][1]["$set"]
    assert sample_update["variacoes.$.status"] == "em_elaboracao"
    assert sample_update["variacoes.$.status_pd_raw"] == "em_desenvolvimento"
    assert sample_update["variacoes.$.status_pd_label"] == "Em Desenvolvimento"


def test_bootstrap_prefills_usd_fragrance_with_brl_conversion(monkeypatch):
    sample_doc = {
        "id": "sample-1",
        "tenant_id": "tenant-1",
        "nome_produto": "Base Teste",
        "quantidade_por_variacao": 15,
        "unidade_quantidade": "ml",
        "variacoes": [
            {
                "id": "var-1",
                "codigo": "2026-1001-A",
                "descricao_aplicacao": "Versão A",
                "percentual_fragrancia": 3.0,
                "referencia_fragrancia": "FR-00001 - Citrus",
                "custo_fragrancia": 10.0,
                "custo_fragrancia_currency": "USD",
            }
        ],
    }
    card_doc = {
        "id": "card-1",
        "tenant_id": "tenant-1",
        "status_pd": "solicitado",
        "amostra_id": "sample-1",
        "amostra_variacao_id": "var-1",
    }

    fake_db = SimpleNamespace(
        crm_samples=TrackingCollection([sample_doc]),
        pd_requests=TrackingCollection([{"id": "req-1", "tenant_id": "tenant-1", "status": "OPEN"}]),
        pd_request_status_history=TrackingCollection(),
        pd_developments=TrackingCollection(),
        pd_formulas=TrackingCollection(),
        pd_formula_items=TrackingCollection(),
        pd_cards=TrackingCollection([card_doc]),
    )
    crm_routes.db = fake_db
    crm_routes._broadcast_event = None

    generated_ids = iter(["hist-1", "dev-1", "formula-1", "item-1"])
    monkeypatch.setattr(crm_routes, "_new_id", lambda: next(generated_ids))
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-07-15T15:00:00+00:00")

    async def fake_audit_log(**_kwargs):
        return None

    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)

    user = {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1"}

    asyncio.run(
        crm_routes._bootstrap_pd_development_for_variacao(
            pd_request_id="req-1",
            card=dict(card_doc),
            user=user,
        )
    )

    fragrancia_item = fake_db.pd_formula_items.insert_calls[-1]
    assert fragrancia_item["ingredient_name"] == "FR-00001 - Citrus"
    assert fragrancia_item["price_usd"] == 10.0
    assert fragrancia_item["price_per_kg"] == 60.0
    assert fragrancia_item["cost_brl"] == 1.8
    assert fragrancia_item["cost_kg_usd"] == 10.0
    assert fragrancia_item["cost_brl_via_cambio"] == 1.8


def test_save_lab_results_auto_moves_request_to_tests(monkeypatch):
    fake_db = SimpleNamespace(
        pd_developments=TrackingCollection(
            [{"id": "dev-1", "tenant_id": "tenant-1", "pd_request_id": "req-1"}]
        ),
        pd_lab_results=TrackingCollection(),
        pd_requests=TrackingCollection(
            [
                {
                    "id": "req-1",
                    "tenant_id": "tenant-1",
                    "status": "IN_PROGRESS",
                    "linked_pd_card_id": "card-1",
                }
            ]
        ),
        pd_cards=TrackingCollection(
            [
                {
                    "id": "card-1",
                    "tenant_id": "tenant-1",
                    "pd_request_id": "req-1",
                    "status_pd": "em_desenvolvimento",
                    "amostra_id": "sample-1",
                    "amostra_variacao_id": "var-1",
                }
            ]
        ),
        crm_samples=TrackingCollection(
            [{"id": "sample-1", "tenant_id": "tenant-1", "variacoes": [{"id": "var-1"}]}]
        ),
        pd_request_status_history=TrackingCollection(),
    )
    pd_routes.db = fake_db
    pd_routes._broadcast_event = None
    pd_routes.new_id_func = lambda: "hist-lab-1"
    pd_routes.now_iso_func = lambda: "2026-07-15T16:00:00+00:00"

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1"}

    async def fake_auto_generate_documents(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pd_routes, "get_current_user", fake_get_current_user)
    monkeypatch.setattr(pd_routes, "_auto_generate_documents_for_development", fake_auto_generate_documents)

    result = asyncio.run(
        pd_routes.save_lab_results(
            "dev-1",
            pd_routes.LabResultsUpdate(ph={"valor_medido": "5.5"}),
            SimpleNamespace(),
        )
    )

    assert result["ph"] == {"valor_medido": "5.5"}
    assert fake_db.pd_requests.docs[0]["status"] == "IN_TESTS"
    assert fake_db.pd_cards.docs[0]["status_pd"] == "em_testes"
    assert fake_db.pd_request_status_history.insert_calls[-1]["to_status"] == "IN_TESTS"

    sample_update = fake_db.crm_samples.update_calls[-1][1]["$set"]
    assert sample_update["variacoes.$.status_pd_raw"] == "em_testes"
    assert sample_update["variacoes.$.status_pd_label"] == "Em Testes"


def test_sync_request_status_to_pipeline_advances_linked_project(monkeypatch):
    fake_db = SimpleNamespace(
        pd_cards=TrackingCollection(
            [
                {
                    "id": "card-1",
                    "tenant_id": "tenant-1",
                    "pd_request_id": "req-1",
                    "status_pd": "em_testes",
                    "amostra_id": "sample-1",
                    "amostra_variacao_id": "var-1",
                    "projeto_id": "proj-1",
                }
            ]
        ),
        crm_samples=TrackingCollection(
            [
                {
                    "id": "sample-1",
                    "tenant_id": "tenant-1",
                    "projeto_id": "proj-1",
                    "variacoes": [{"id": "var-1"}],
                }
            ]
        ),
    )
    pd_routes.db = fake_db
    pd_routes._broadcast_event = None
    pd_routes.now_iso_func = lambda: "2026-07-17T20:00:00+00:00"

    advanced = []

    async def fake_advance(project_id, target_stage, user, *, movement_source, extra_set=None):
        advanced.append(
            {
                "project_id": project_id,
                "target_stage": target_stage,
                "movement_source": movement_source,
                "extra_set": extra_set,
                "user_id": user["id"],
            }
        )
        return {"id": project_id, "stage": target_stage}

    monkeypatch.setattr(crm_routes, "_advance_project_stage_if_needed", fake_advance)

    updated = asyncio.run(
        pd_routes._sync_request_status_to_pipeline(
            req_id="req-1",
            tenant_id="tenant-1",
            new_status="WAITING_APPROVAL",
            user={"id": "user-1", "name": "Tester", "tenant_id": "tenant-1"},
        )
    )

    assert updated["status_pd"] == "aguardando_aprovacao"
    assert fake_db.pd_cards.docs[0]["status_pd"] == "aguardando_aprovacao"
    sample_set = fake_db.crm_samples.update_calls[-1][1]["$set"]
    assert sample_set["variacoes.$.status"] == "enviada"
    assert sample_set["variacoes.$.aprovacao_interna"] is True
    assert sample_set["variacoes.$.enviado_comercial_em"] == "2026-07-17T20:00:00+00:00"
    assert advanced == [
        {
            "project_id": "proj-1",
            "target_stage": "amostra_enviada",
            "movement_source": "pd_request_waiting_approval",
            "extra_set": {"data_ultima_amostra_enviada": "2026-07-17T20:00:00+00:00"},
            "user_id": "user-1",
        }
    ]


def test_move_pd_card_advances_linked_project_to_development(monkeypatch):
    fake_db = SimpleNamespace(
        pd_cards=TrackingCollection(
            [
                {
                    "id": "card-1",
                    "tenant_id": "tenant-1",
                    "status_pd": "solicitado",
                    "amostra_id": "sample-1",
                    "amostra_variacao_id": "var-1",
                    "projeto_id": "proj-1",
                }
            ]
        ),
        crm_samples=TrackingCollection(
            [
                {
                    "id": "sample-1",
                    "tenant_id": "tenant-1",
                    "projeto_id": "proj-1",
                    "variacoes": [{"id": "var-1"}],
                }
            ]
        ),
    )
    crm_routes.db = fake_db

    async def fake_get_current_user(_request):
        return {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1", "role": "lider_pd"}

    async def fake_assert_no_blocking_tasks(**_kwargs):
        return None

    async def fake_trigger_tasks_for_transition(**_kwargs):
        return []

    async def fake_audit_log(**_kwargs):
        return None

    async def fake_broadcast_pd_card_update(*_args, **_kwargs):
        return None

    advanced = []

    async def fake_advance(project_id, target_stage, user, *, movement_source, extra_set=None):
        advanced.append(
            {
                "project_id": project_id,
                "target_stage": target_stage,
                "movement_source": movement_source,
                "extra_set": extra_set,
                "user_id": user["id"],
            }
        )
        return {"id": project_id, "stage": target_stage}

    monkeypatch.setattr(crm_routes, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(crm_routes, "require_roles", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(crm_routes, "assert_no_blocking_tasks", fake_assert_no_blocking_tasks)
    monkeypatch.setattr(crm_routes, "trigger_tasks_for_transition", fake_trigger_tasks_for_transition)
    monkeypatch.setattr(crm_routes, "audit_log", fake_audit_log)
    monkeypatch.setattr(crm_routes, "_broadcast_pd_card_update", fake_broadcast_pd_card_update)
    monkeypatch.setattr(crm_routes, "_advance_project_stage_if_needed", fake_advance)
    monkeypatch.setattr(crm_routes, "_now_iso", lambda: "2026-07-17T20:05:00+00:00")

    result = asyncio.run(
        crm_routes.move_pd_card(
            "card-1",
            crm_routes.PDCardMove(status="em_desenvolvimento", observacao="Iniciado"),
            SimpleNamespace(),
        )
    )

    assert result["card"]["status_pd"] == "em_desenvolvimento"
    assert fake_db.pd_cards.docs[0]["status_pd"] == "em_desenvolvimento"
    assert advanced == [
        {
            "project_id": "proj-1",
            "target_stage": "amostra_em_desenvolvimento",
            "movement_source": "pd_card_in_development",
            "extra_set": {"data_inicio_desenvolvimento": "2026-07-17T20:05:00+00:00"},
            "user_id": "user-1",
        }
    ]


def test_repair_prefilled_fragrance_item_from_variacao_updates_legacy_brl_value():
    fake_db = SimpleNamespace(
        pd_formula_items=TrackingCollection(
            [
                {
                    "id": "item-1",
                    "formula_id": "formula-1",
                    "ingredient_name": "FR-00001 - Citrus",
                    "percentage": 3.0,
                    "price_per_kg": 10.0,
                    "cost_brl": 0.3,
                    "cost_kg_usd": 1.6667,
                    "phase": "Fragrância",
                    "function": "Fragrância",
                }
            ]
        )
    )
    pd_routes.db = fake_db

    repaired = asyncio.run(
        pd_routes._repair_prefilled_fragrance_item_from_variacao(
            {"id": "formula-1", "cotacao_usd": 6.0},
            dict(fake_db.pd_formula_items.docs[0]),
            {
                "percentual_fragrancia": 3.0,
                "referencia_fragrancia": "FR-00001 - Citrus",
                "custo_fragrancia": 10.0,
                "custo_fragrancia_currency": "USD",
            },
        )
    )

    assert repaired["price_usd"] == 10.0
    assert repaired["price_per_kg"] == 60.0
    assert repaired["cost_brl"] == 1.8
    assert repaired["cost_kg_usd"] == 10.0
    assert repaired["cost_brl_via_cambio"] == 1.8
    assert fake_db.pd_formula_items.update_calls[-1][1]["$set"]["price_usd"] == 10.0


def test_sync_linked_variacao_from_pd_approval_generates_fasttrack_sku(monkeypatch):
    fake_db = SimpleNamespace(
        crm_samples=TrackingCollection(
            [
                {
                    "id": "sample-1",
                    "tenant_id": "tenant-1",
                    "data_envio": None,
                    "variacoes": [
                        {
                            "id": "var-1",
                            "status": "enviada",
                            "enviado_comercial_em": None,
                        }
                    ],
                }
            ]
        )
    )
    pd_routes.db = fake_db

    called = {}

    async def fake_create_sku(sample, variacao, user, *, fasttrack_variacao=False):
        called["sample_id"] = sample["id"]
        called["variacao_id"] = variacao["id"]
        called["fasttrack"] = fasttrack_variacao
        return {"codigo_interno": "CAPA-TEST-0001"}

    monkeypatch.setattr(pd_routes, "now_iso_func", lambda: "2026-07-17T21:00:00+00:00")
    monkeypatch.setattr(crm_routes, "_create_sku_from_variacao_v2", fake_create_sku)

    updated_sample, updated_variacao, sku_created = asyncio.run(
        pd_routes._sync_linked_variacao_from_pd_approval(
            {"linked_amostra_id": "sample-1", "linked_variacao_id": "var-1"},
            {"id": "user-1", "name": "Tester", "tenant_id": "tenant-1"},
            "APPROVED",
        )
    )

    sample_set = fake_db.crm_samples.update_calls[-1][1]["$set"]
    assert sample_set["variacoes.$.status"] == "aprovada"
    assert sample_set["variacoes.$.resultado"] == "aprovada"
    assert sample_set["variacoes.$.aprovacao_externa"] is True
    assert updated_sample["id"] == "sample-1"
    assert updated_variacao["id"] == "var-1"
    assert sku_created["codigo_interno"] == "CAPA-TEST-0001"
    assert called == {
        "sample_id": "sample-1",
        "variacao_id": "var-1",
        "fasttrack": True,
    }


def test_sync_linked_variacao_from_pd_rejection_pushes_rework_notes():
    fake_db = SimpleNamespace(
        crm_samples=TrackingCollection(
            [
                {
                    "id": "sample-1",
                    "tenant_id": "tenant-1",
                    "variacoes": [
                        {
                            "id": "var-1",
                            "status": "enviada",
                        }
                    ],
                }
            ]
        ),
        pd_updates=TrackingCollection(),
    )
    pd_routes.db = fake_db
    pd_routes.new_id_func = lambda: "update-rework-1"
    pd_routes.now_iso_func = lambda: "2026-07-17T21:30:00+00:00"

    asyncio.run(
        pd_routes._sync_linked_variacao_from_pd_approval(
            {"id": "req-1", "linked_amostra_id": "sample-1", "linked_variacao_id": "var-1"},
            {"id": "user-1", "name": "Comercial", "tenant_id": "tenant-1", "role": "vendedor"},
            "REJECTED",
            "Trocar fragrancia para uma opcao menos doce e manter base.",
        )
    )

    sample_set = fake_db.crm_samples.update_calls[-1][1]["$set"]
    assert sample_set["variacoes.$.status"] == "retrabalho"
    assert sample_set["variacoes.$.retrabalho_anotacoes"] == "Trocar fragrancia para uma opcao menos doce e manter base."
    assert fake_db.pd_updates.insert_calls[-1]["tipo"] == "retrabalho"
    assert "menos doce" in fake_db.pd_updates.insert_calls[-1]["mensagem"]
