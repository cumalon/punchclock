from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from timeclock import database


NOW = datetime(2026, 10, 11, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def _start(client, employee):
    worker = employee()
    kind = database.create_leave_type("Pausa", approval_policy="automatic")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T08:00:00+02:00"),
        )
    started = database.start_employee_leave(worker["id"], kind, "sortida", now=NOW)
    return worker, started


def test_deferred_return_has_no_fabricated_end_time(client, employee):
    worker, started = _start(client, employee)
    result = database.defer_employee_leave_return(worker["id"])
    assert result["record_state"] == "needs_regularization"
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (started["leave_id"],)).fetchone()
        assert leave["ended_at"] is None
        assert leave["end_punch_id"] is None
        assert leave["requires_supervisor"] == 1
        assert leave["status"] == "pending"


def test_deferred_return_no_longer_blocks_new_leave(client, employee):
    worker, started = _start(client, employee)
    database.defer_employee_leave_return(worker["id"])
    state = database.get_employee_leave_context(worker["id"], now=NOW)
    assert state["open_leave"] is None
    with database.get_connection() as db:
        row = db.execute("SELECT record_state FROM employee_leave WHERE id = ?", (started["leave_id"],)).fetchone()
        assert row["record_state"] == "needs_regularization"


def test_deferred_return_does_not_add_punch(client, employee):
    worker, started = _start(client, employee)
    with database.get_connection() as db:
        before = db.execute("SELECT COUNT(*) FROM punch").fetchone()[0]
    database.defer_employee_leave_return(worker["id"])
    with database.get_connection() as db:
        after = db.execute("SELECT COUNT(*) FROM punch").fetchone()[0]
    assert before == after


def test_deferred_return_without_open_leave_rejected(client, employee):
    worker = employee()
    with pytest.raises(ValueError, match="permís obert"):
        database.defer_employee_leave_return(worker["id"])


def test_deferred_return_cannot_repeat(client, employee):
    worker, started = _start(client, employee)
    database.defer_employee_leave_return(worker["id"])
    with pytest.raises(ValueError, match="permís obert"):
        database.defer_employee_leave_return(worker["id"])
