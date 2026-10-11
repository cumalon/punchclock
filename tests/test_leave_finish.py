from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from timeclock import database


TZ = ZoneInfo("Europe/Madrid")
START = datetime(2026, 10, 11, 10, 0, tzinfo=TZ)


def _open_leave(employee_id, policy="automatic", limit=None):
    kind = database.create_leave_type(
        "Pausa", approval_policy=policy, auto_approve_minutes=limit
    )
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (employee_id, "2026-10-11T08:00:00+02:00"),
        )
    started = database.start_employee_leave(employee_id, kind, "sortida", now=START)
    assert started["ok"]
    return started


def test_finish_automatic_leave_approves(client, employee):
    worker = employee()
    started = _open_leave(worker["id"])
    result = database.finish_employee_leave(worker["id"], now=START + timedelta(minutes=15))
    assert result["status"] == "approved"
    assert result["duration_seconds"] == 900
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (started["leave_id"],)).fetchone()
        assert leave["record_state"] == "finished"
        assert leave["end_punch_id"] == result["punch_id"]
        assert leave["status"] == "approved"


def test_finish_manual_leave_pending(client, employee):
    worker = employee()
    _open_leave(worker["id"], policy="manual")
    result = database.finish_employee_leave(worker["id"], now=START + timedelta(minutes=5))
    assert result["status"] == "pending"


def test_finish_threshold_policy(client, employee):
    worker = employee()
    _open_leave(worker["id"], policy="threshold", limit=20)
    result = database.finish_employee_leave(worker["id"], now=START + timedelta(minutes=20))
    assert result["status"] == "approved"


def test_finish_threshold_exceeded(client, employee):
    worker = employee()
    _open_leave(worker["id"], policy="threshold", limit=20)
    result = database.finish_employee_leave(worker["id"], now=START + timedelta(minutes=21))
    assert result["status"] == "pending"


def test_finish_supervisor_required_stays_pending(client, employee):
    worker = employee()
    started = _open_leave(worker["id"])
    with database.get_connection() as db:
        db.execute("UPDATE employee_leave SET requires_supervisor = 1 WHERE id = ?", (started["leave_id"],))
    result = database.finish_employee_leave(worker["id"], now=START + timedelta(minutes=10))
    assert result["status"] == "pending"


def test_finish_without_open_leave_rejected(client, employee):
    worker = employee()
    try:
        database.finish_employee_leave(worker["id"], now=START)
        assert False, "S'esperava un error"
    except ValueError as exc:
        assert "permís obert" in str(exc)


def test_finish_before_start_does_not_write(client, employee):
    worker = employee()
    started = _open_leave(worker["id"])
    try:
        database.finish_employee_leave(worker["id"], now=START - timedelta(minutes=1))
        assert False, "S'esperava un error"
    except ValueError:
        pass
    with database.get_connection() as db:
        leave = db.execute("SELECT record_state FROM employee_leave WHERE id = ?", (started["leave_id"],)).fetchone()
        assert leave["record_state"] == "open"


def test_finish_incident_requires_confirmation(client, employee):
    worker = employee()
    started = _open_leave(worker["id"])
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T10:05:00+02:00"),
        )
    response = database.finish_employee_leave(worker["id"], now=START + timedelta(minutes=10))
    assert response["confirmation_required"]
    confirmed = database.finish_employee_leave(
        worker["id"], confirm_incident=True, now=START + timedelta(minutes=10)
    )
    assert confirmed["status"] == "pending"
    assert confirmed["incident"] == 1
    with database.get_connection() as db:
        leave = db.execute("SELECT requires_supervisor FROM employee_leave WHERE id = ?", (started["leave_id"],)).fetchone()
        assert leave["requires_supervisor"] == 1
