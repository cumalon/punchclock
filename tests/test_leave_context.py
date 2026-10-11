from datetime import datetime
from zoneinfo import ZoneInfo

from timeclock import database


TZ = ZoneInfo("Europe/Madrid")


def _punch(employee_id, kind, timestamp):
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, ?, 'pin')",
            (employee_id, timestamp, kind),
        )


def test_leave_context_without_punches(client, employee):
    worker = employee()
    state = database.get_employee_leave_context(
        worker["id"], datetime(2026, 10, 11, 9, 0, tzinfo=TZ)
    )
    assert state["last_punch"] is None
    assert state["open_leave"] is None
    assert state["suggested_direction"] == "entrada"
    assert state["requires_direction_choice"] is False


def test_leave_context_after_today_entry(client, employee):
    worker = employee()
    _punch(worker["id"], "entrada", "2026-10-11T08:00:00+02:00")
    state = database.get_employee_leave_context(
        worker["id"], datetime(2026, 10, 11, 10, 0, tzinfo=TZ)
    )
    assert state["suggested_direction"] == "sortida"
    assert state["requires_direction_choice"] is False


def test_leave_context_after_exit(client, employee):
    worker = employee()
    _punch(worker["id"], "sortida", "2026-10-10T17:00:00+02:00")
    state = database.get_employee_leave_context(
        worker["id"], datetime(2026, 10, 11, 9, 0, tzinfo=TZ)
    )
    assert state["suggested_direction"] == "entrada"
    assert state["requires_direction_choice"] is False


def test_leave_context_previous_day_unclosed_entry(client, employee):
    worker = employee()
    _punch(worker["id"], "entrada", "2026-10-10T08:00:00+02:00")
    state = database.get_employee_leave_context(
        worker["id"], datetime(2026, 10, 11, 9, 0, tzinfo=TZ)
    )
    assert state["requires_direction_choice"] is True
    assert state["suggested_direction"] is None


def test_leave_context_open_leave_takes_precedence(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type("Esmorzar")
    _punch(worker["id"], "sortida", "2026-10-11T10:00:00+02:00")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO employee_leave (employee_id, leave_type_id, started_at) VALUES (?, ?, ?)",
            (worker["id"], leave_type_id, "2026-10-11T10:00:00+02:00"),
        )
    state = database.get_employee_leave_context(
        worker["id"], datetime(2026, 10, 11, 10, 20, tzinfo=TZ)
    )
    assert state["open_leave"]["leave_type_name"] == "Esmorzar"
    assert state["suggested_direction"] is None
    assert state["requires_direction_choice"] is False


def test_leave_context_unknown_or_inactive_employee(client, employee):
    worker = employee()
    with database.get_connection() as db:
        db.execute("UPDATE employee SET active = 0 WHERE id = ?", (worker["id"],))
    assert database.get_employee_leave_context(worker["id"]) is None
    assert database.get_employee_leave_context(999999) is None
