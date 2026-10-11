"""Regularització supervisada d'un retorn anterior."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from timeclock import database


def make_leave(employee_id):
    type_id = database.create_leave_type("Esmorzar")
    started = (datetime.now(ZoneInfo("Europe/Madrid")) - timedelta(hours=2)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'sortida', 'pin')
        """, (employee_id, started)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'needs_regularization', 1, ?)
        """, (employee_id, type_id, started, punch_id)).lastrowid
    return leave_id, punch_id, started


def test_regularization_keeps_punch_and_requires_manual_approval(client, employee):
    worker = employee()
    leave_id, punch_id, started = make_leave(worker["id"])
    returned = (datetime.fromisoformat(started) + timedelta(minutes=20)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        admin_id = db.execute("SELECT id FROM admin_user WHERE username = 'admin'").fetchone()["id"]
        punch_count = db.execute("SELECT count(*) FROM punch").fetchone()[0]
    result = database.regularize_employee_leave_return(leave_id, returned, admin_id, "Retorn verificat")
    assert result["status"] == "pending"
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (leave_id,)).fetchone()
        assert leave["ended_at"] == returned
        assert leave["record_state"] == "finished"
        assert leave["requires_supervisor"] == 1
        assert leave["end_punch_id"] is None
        assert leave["regularized_by"] == admin_id
        assert leave["regularization_reason"] == "Retorn verificat"
        assert db.execute("SELECT count(*) FROM punch").fetchone()[0] == punch_count
        assert db.execute("SELECT type FROM punch WHERE id = ?", (punch_id,)).fetchone()[0] == "sortida"


def test_regularization_rejects_invalid_times_and_reason(client, employee):
    worker = employee()
    leave_id, _, started = make_leave(worker["id"])
    with database.get_connection() as db:
        admin_id = db.execute("SELECT id FROM admin_user WHERE username = 'admin'").fetchone()["id"]
    for returned, reason in [
        (started, " "),
        ("2026-01-01T10:00:00+01:00", "Abans de la sortida"),
        ("2999-01-01T10:00:00+01:00", "En el futur"),
        ("2026-10-11T10:00:00", "Sense zona horària"),
    ]:
        with pytest.raises(ValueError):
            database.regularize_employee_leave_return(leave_id, returned, admin_id, reason)


def test_regularization_cannot_extend_past_next_punch(client, employee):
    worker = employee()
    leave_id, _, started = make_leave(worker["id"])
    start_dt = datetime.fromisoformat(started)
    next_punch = (start_dt + timedelta(minutes=30)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        admin_id = db.execute(
            "SELECT id FROM admin_user WHERE username = 'admin'"
        ).fetchone()["id"]
        db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'entrada', 'pin')
        """, (worker["id"], next_punch))
    late_return = (start_dt + timedelta(minutes=45)).isoformat(timespec="seconds")
    with pytest.raises(ValueError, match="següent fitxatge"):
        database.regularize_employee_leave_return(
            leave_id, late_return, admin_id, "Hora impossible"
        )
    valid_return = (start_dt + timedelta(minutes=20)).isoformat(timespec="seconds")
    assert database.regularize_employee_leave_return(
        leave_id, valid_return, admin_id, "Retorn confirmat"
    )["ok"]
