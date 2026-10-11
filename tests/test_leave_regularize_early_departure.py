"""Regularització d'una sortida anticipada."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from timeclock import database


def make_early_departure(employee_id):
    type_id = database.create_leave_type("Sortida anticipada")
    actual = datetime.now(ZoneInfo("Europe/Madrid")) - timedelta(hours=2)
    actual_at = actual.isoformat(timespec="seconds")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'sortida', 'pin')
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
    database.classify_employee_leave_departure(leave_id, "early_departure", admin_id)
    return leave_id, punch_id, admin_id, actual


def test_early_departure_preserves_punch_and_pending_status(client, employee):
    worker = employee()
    leave_id, punch_id, admin_id, actual = make_early_departure(worker["id"])
    expected = (actual + timedelta(minutes=45)).isoformat(timespec="seconds")
    result = database.regularize_employee_leave_early_departure(
        leave_id, expected, admin_id, "Hora prevista confirmada"
    )
    assert result["status"] == "pending"
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (leave_id,)).fetchone()
        punch = db.execute("SELECT * FROM punch WHERE id = ?", (punch_id,)).fetchone()
        assert leave["expected_ended_at"] == expected
        assert leave["ended_at"] == expected
        assert leave["record_state"] == "finished"
        assert leave["requires_supervisor"] == 1
        assert leave["regularized_by"] == admin_id
        assert punch["timestamp"] == leave["started_at"]


def test_early_departure_rejects_invalid_times_and_reason(client, employee):
    worker = employee()
    leave_id, _, admin_id, actual = make_early_departure(worker["id"])
    for expected, reason in [
        ((actual - timedelta(minutes=1)).isoformat(), "Abans de la sortida"),
        ((actual + timedelta(minutes=30)).isoformat(), " "),
        ("2026-10-11T10:00:00", "Sense zona horària"),
    ]:
        with pytest.raises(ValueError):
            database.regularize_employee_leave_early_departure(
                leave_id, expected, admin_id, reason
            )


def test_early_departure_cannot_overlap_next_punch(client, employee):
    worker = employee()
    leave_id, _, admin_id, actual = make_early_departure(worker["id"])
    next_at = (actual + timedelta(minutes=30)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'entrada', 'pin')
        """, (worker["id"], next_at))
    with pytest.raises(ValueError, match="següent fitxatge"):
        database.regularize_employee_leave_early_departure(
            leave_id, (actual + timedelta(minutes=45)).isoformat(timespec="seconds"),
            admin_id, "Interval solapat"
        )
