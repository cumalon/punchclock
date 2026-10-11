"""Regularització d'una arribada tardana."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from timeclock import database


def make_late_arrival(employee_id):
    type_id = database.create_leave_type("Arribada tardana")
    actual = datetime.now(ZoneInfo("Europe/Madrid")) - timedelta(hours=1)
    actual_at = actual.isoformat(timespec="seconds")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'entrada', 'pin')
        """, (employee_id, actual_at)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'needs_regularization', 1, ?)
        """, (employee_id, type_id, actual_at, punch_id)).lastrowid
        admin_id = db.execute(
            "SELECT id FROM admin_user WHERE username = 'admin'"
        ).fetchone()["id"]
    return leave_id, punch_id, admin_id, actual


def test_late_arrival_keeps_real_punch_and_pending_status(client, employee):
    worker = employee()
    leave_id, punch_id, admin_id, actual = make_late_arrival(worker["id"])
    expected = (actual - timedelta(minutes=30)).isoformat(timespec="seconds")
    result = database.regularize_employee_leave_late_arrival(
        leave_id, expected, admin_id, "Entrada prevista verificada"
    )
    assert result["status"] == "pending"
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (leave_id,)).fetchone()
        punch = db.execute("SELECT * FROM punch WHERE id = ?", (punch_id,)).fetchone()
        assert leave["expected_started_at"] == expected
        assert leave["ended_at"] == leave["started_at"]
        assert leave["record_state"] == "finished"
        assert leave["requires_supervisor"] == 1
        assert leave["regularized_by"] == admin_id
        assert punch["timestamp"] == leave["started_at"]


def test_late_arrival_rejects_invalid_times_and_reason(client, employee):
    worker = employee()
    leave_id, _, admin_id, actual = make_late_arrival(worker["id"])
    for expected, reason in [
        ((actual + timedelta(minutes=1)).isoformat(), "Després de l'entrada"),
        ((actual - timedelta(minutes=30)).isoformat(), " "),
        ("2026-10-11T10:00:00", "Sense zona horària"),
    ]:
        with pytest.raises(ValueError):
            database.regularize_employee_leave_late_arrival(
                leave_id, expected, admin_id, reason
            )
