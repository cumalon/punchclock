from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from timeclock import database


NOW = datetime(2026, 10, 11, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def _setup(employee):
    worker = employee()
    kind = database.create_leave_type("Pausa", approval_policy="automatic")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T08:00:00+02:00"),
        )
    database.start_employee_leave(worker["id"], kind, "sortida", now=NOW)
    return worker


def _punch_count():
    with database.get_connection() as db:
        return db.execute("SELECT COUNT(*) FROM punch").fetchone()[0]


def test_open_leave_requires_return_choice(client, employee):
    worker = _setup(employee)
    before = _punch_count()
    result = database.punch_with_open_leave(worker["id"], "entrada", now=NOW)
    assert result["return_choice_required"]
    assert _punch_count() == before


def test_return_now_reuses_single_entry(client, employee):
    worker = _setup(employee)
    before = _punch_count()
    result = database.punch_with_open_leave(
        worker["id"], "entrada", return_choice="now",
        now=NOW + timedelta(minutes=10)
    )
    assert result["punch_reused_as_return"]
    assert result["ordinary_punch_required"] is False
    assert _punch_count() == before + 1


def test_return_earlier_marks_leave_without_creating_punch(client, employee):
    worker = _setup(employee)
    before = _punch_count()
    result = database.punch_with_open_leave(
        worker["id"], "entrada", return_choice="earlier", now=NOW
    )
    assert result["ordinary_punch_required"]
    assert _punch_count() == before
    assert database.get_employee_leave_context(worker["id"], now=NOW)["open_leave"] is None


def test_return_now_with_exit_requires_entry_first(client, employee):
    worker = _setup(employee)
    before = _punch_count()
    result = database.punch_with_open_leave(
        worker["id"], "sortida", return_choice="now", now=NOW
    )
    assert result["return_entry_required"]
    assert _punch_count() == before


def test_return_now_incident_keeps_leave_open_until_confirmed(client, employee):
    worker = _setup(employee)
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T10:05:00+02:00"),
        )
    before = _punch_count()
    result = database.punch_with_open_leave(
        worker["id"], "entrada", return_choice="now",
        now=NOW + timedelta(minutes=10)
    )
    assert result["confirmation_required"]
    assert _punch_count() == before
    confirmed = database.punch_with_open_leave(
        worker["id"], "entrada", return_choice="now",
        confirm_incident=True, now=NOW + timedelta(minutes=10)
    )
    assert confirmed["punch_reused_as_return"]
    assert _punch_count() == before + 1
