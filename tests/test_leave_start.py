from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from timeclock import database


NOW = datetime(2026, 10, 11, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def _counts():
    with database.get_connection() as db:
        return (
            db.execute("SELECT COUNT(*) FROM punch").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM employee_leave").fetchone()[0],
        )


def test_start_leave_with_exit_creates_linked_punch(client, employee):
    worker = employee()
    kind = database.create_leave_type("Esmorzar", approval_policy="automatic")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T08:00:00+02:00"),
        )
    result = database.start_employee_leave(worker["id"], kind, "sortida", now=NOW)
    assert result["ok"] is True
    assert result["record_state"] == "open"
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (result["leave_id"],)).fetchone()
        assert leave["start_punch_id"] == result["punch_id"]
        assert leave["status"] == "pending"
        assert leave["requires_supervisor"] == 0


def test_start_leave_with_entry_needs_supervisor(client, employee):
    worker = employee()
    kind = database.create_leave_type("Arribada tard", approval_policy="automatic")
    result = database.start_employee_leave(worker["id"], kind, "entrada", now=NOW)
    assert result["record_state"] == "needs_regularization"
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (result["leave_id"],)).fetchone()
        assert leave["requires_supervisor"] == 1
        assert leave["status"] == "pending"


def test_start_leave_incident_requires_confirmation_without_writing(client, employee):
    worker = employee()
    kind = database.create_leave_type("Visita")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-10T08:00:00+02:00"),
        )
    before = _counts()
    response = database.start_employee_leave(worker["id"], kind, "entrada", now=NOW)
    assert response["confirmation_required"] is True
    assert _counts() == before
    confirmed = database.start_employee_leave(
        worker["id"], kind, "entrada", confirm_incident=True, now=NOW
    )
    assert confirmed["incident"] == 1
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_start_leave_refuses_second_open_leave(client, employee):
    worker = employee()
    kind = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO employee_leave (employee_id, leave_type_id, started_at) VALUES (?, ?, ?)",
            (worker["id"], kind, "2026-10-11T09:00:00+02:00"),
        )
    before = _counts()
    with pytest.raises(ValueError, match="permís obert"):
        database.start_employee_leave(worker["id"], kind, "entrada", now=NOW)
    assert _counts() == before


def test_start_leave_rejects_inactive_type_without_writing(client, employee):
    worker = employee()
    kind = database.create_leave_type("Desactivat", active=False)
    before = _counts()
    with pytest.raises(ValueError, match="no disponible"):
        database.start_employee_leave(worker["id"], kind, "entrada", now=NOW)
    assert _counts() == before
