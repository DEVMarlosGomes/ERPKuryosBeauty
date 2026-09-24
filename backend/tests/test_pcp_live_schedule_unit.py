from datetime import datetime, timezone
import asyncio
from types import SimpleNamespace

import pytest

import pcp_routes
from pcp_routes import _apply_schedule_cascade, _build_schedule_cascade, _live_slot_prediction


def _slot(slot_id, start_date, start_time, end_date, end_time, **extra):
    return {
        "id": slot_id,
        "data": start_date,
        "data_inicio": start_date,
        "data_fim": end_date,
        "hora_inicio": start_time,
        "hora_fim": end_time,
        "status": "planejado",
        **extra,
    }


def _op(produced, status="em_processo"):
    return {
        "id": "op-1",
        "status": status,
        "items": [{"qtd_planejada": 100, "qtd_produzida": produced}],
        "apontamentos": [],
        "pausas": [],
    }


def test_delay_moves_all_following_slots_preserving_duration_and_gap():
    current = _slot("s1", "2026-09-18", "08:00", "2026-09-18", "10:00", op_id="op-1", qtd_planejada=100)
    following = [
        _slot("s2", "2026-09-18", "10:15", "2026-09-18", "11:00"),
        _slot("s3", "2026-09-18", "11:15", "2026-09-18", "12:00"),
    ]
    now = datetime(2026, 9, 18, 9, 30, tzinfo=timezone.utc)

    prediction = _live_slot_prediction(current, _op(30), now)
    moves = _build_schedule_cascade(current, [current, *following], prediction)

    assert prediction["timing"] == "atrasado"
    assert prediction["deviation_minutes"] == 180
    assert [(m["new_start"].strftime("%H:%M"), m["new_end"].strftime("%H:%M")) for m in moves] == [
        ("13:15", "14:00"),
        ("14:15", "15:00"),
    ]


def test_ahead_of_schedule_pulls_following_slots_earlier():
    current = _slot("s1", "2026-09-18", "08:00", "2026-09-18", "10:00", op_id="op-1", qtd_planejada=100)
    following = [_slot("s2", "2026-09-18", "10:15", "2026-09-18", "11:00")]
    now = datetime(2026, 9, 18, 8, 30, tzinfo=timezone.utc)

    prediction = _live_slot_prediction(current, _op(50), now)
    moves = _build_schedule_cascade(current, [current, *following], prediction)

    assert prediction["timing"] == "adiantado"
    assert prediction["deviation_minutes"] == -60
    assert moves[0]["new_start"].strftime("%H:%M") == "09:15"
    assert moves[0]["new_end"].strftime("%H:%M") == "10:00"


def test_delay_crosses_midnight_without_losing_duration():
    current = _slot("s1", "2026-09-18", "23:00", "2026-09-19", "01:00", op_id="op-1", qtd_planejada=100)
    next_slot = _slot("s2", "2026-09-19", "01:30", "2026-09-19", "02:30")
    prediction = {
        "start": datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
        "predicted_end": datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc),
        "deviation_minutes": 120,
    }

    moves = _build_schedule_cascade(current, [current, next_slot], prediction)

    assert moves[0]["new_start"].isoformat() == "2026-09-19T03:30:00+00:00"
    assert moves[0]["new_end"].isoformat() == "2026-09-19T04:30:00+00:00"


def test_open_op_without_posting_does_not_move_the_schedule():
    current = _slot("s1", "2026-09-18", "08:00", "2026-09-18", "10:00", op_id="op-1", qtd_planejada=100)
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)

    prediction = _live_slot_prediction(current, _op(0, status="aberta"), now)

    assert prediction["live_status"] == "planejado"
    assert prediction["deviation_minutes"] == 0


def test_repeated_refresh_keeps_total_deviation_without_shifting_twice():
    adjusted = _slot(
        "s1", "2026-09-18", "08:00", "2026-09-18", "13:00",
        op_id="op-1", qtd_planejada=100,
        data_fim_original="2026-09-18", hora_fim_original="10:00",
    )
    following = [_slot("s2", "2026-09-18", "13:15", "2026-09-18", "14:00")]
    now = datetime(2026, 9, 18, 9, 30, tzinfo=timezone.utc)

    prediction = _live_slot_prediction(adjusted, _op(30), now)
    moves = _build_schedule_cascade(adjusted, [adjusted, *following], prediction)

    assert prediction["deviation_minutes"] == 180
    assert prediction["cascade_delta_minutes"] == 0
    assert moves == []


def test_schedule_cascade_restores_every_slot_when_standalone_write_fails():
    class FailingCollection:
        def __init__(self):
            self.docs = {
                "s1": {"id": "s1", "tenant_id": "t1", "hora_inicio": "08:00"},
                "s2": {"id": "s2", "tenant_id": "t1", "hora_inicio": "10:00"},
            }
            self.calls = 0

        async def update_one(self, query, update, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("falha injetada na cascata")
            self.docs[query["id"]].update(update["$set"])

        async def replace_one(self, query, replacement, upsert=False):
            self.docs[query["id"]] = dict(replacement)

    collection = FailingCollection()
    pcp_routes.db = SimpleNamespace(pcp_programacao=collection)
    changes = [
        {"snapshot": dict(collection.docs["s1"]), "updates": {"hora_inicio": "09:00"}},
        {"snapshot": dict(collection.docs["s2"]), "updates": {"hora_inicio": "11:00"}},
    ]

    with pytest.raises(RuntimeError):
        asyncio.run(_apply_schedule_cascade("t1", changes))

    assert collection.docs["s1"]["hora_inicio"] == "08:00"
    assert collection.docs["s2"]["hora_inicio"] == "10:00"
