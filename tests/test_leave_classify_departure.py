"""Classificació de sortides pendents de regularització."""

import pytest

from timeclock import database


def make_departure(employee_id):
    type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, '2026-10-11T10:00:00+02:00', 'sortida', 'pin')
        """, (employee_id,)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at,
                 record_state, requires_supervisor, start_punch_id)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00',
                    'needs_regularization', 1, ?)
        """, (employee_id, type_id, punch_id)).lastrowid
        admin_id = db.execute(
            "SELECT id FROM admin_user WHERE username = 'admin'"
        ).fetchone()["id"]
    return leave_id, admin_id


def test_supervisor_can_classify_return(client, employee):
    leave_id, admin_id = make_departure(employee()["id"])
    result = database.classify_employee_leave_departure(
        leave_id, "return", admin_id
    )
    assert result["regularization_kind"] == "return"
    with database.get_connection() as db:
        row = db.execute(
            "SELECT regularization_kind FROM employee_leave WHERE id = ?",
            (leave_id,)
        ).fetchone()
    assert row["regularization_kind"] == "return"


def test_supervisor_can_classify_early_departure(client, employee):
    leave_id, admin_id = make_departure(employee()["id"])
    assert database.classify_employee_leave_departure(
        leave_id, "early_departure", admin_id
    )["ok"]


def test_classification_rejects_unknown_kind_and_reclassification(client, employee):
    leave_id, admin_id = make_departure(employee()["id"])
    with pytest.raises(ValueError):
        database.classify_employee_leave_departure(
            leave_id, "late_arrival", admin_id
        )
    database.classify_employee_leave_departure(leave_id, "return", admin_id)
    with pytest.raises(ValueError, match="classificat"):
        database.classify_employee_leave_departure(
            leave_id, "early_departure", admin_id
        )


def test_return_classification_blocks_early_departure_regularization(client, employee):
    from datetime import datetime, timedelta

    leave_id, admin_id = make_departure(employee()["id"])
    database.classify_employee_leave_departure(leave_id, "return", admin_id)
    expected = (datetime.now(database.LOCAL_TIMEZONE) + timedelta(minutes=30)).isoformat()
    with pytest.raises(ValueError, match="sortida anticipada"):
        database.regularize_employee_leave_early_departure(
            leave_id, expected, admin_id, "Prova de procediment incorrecte"
        )
    with database.get_connection() as db:
        leave = db.execute(
            "SELECT ended_at, record_state, status, regularization_kind "
            "FROM employee_leave WHERE id = ?", (leave_id,)
        ).fetchone()
    assert leave["ended_at"] is None
    assert leave["record_state"] == "needs_regularization"
    assert leave["status"] == "pending"
    assert leave["regularization_kind"] == "return"


def test_early_departure_classification_blocks_return_regularization(client, employee):
    from datetime import datetime

    leave_id, admin_id = make_departure(employee()["id"])
    database.classify_employee_leave_departure(leave_id, "early_departure", admin_id)
    returned = datetime.now(database.LOCAL_TIMEZONE).isoformat()
    with pytest.raises(ValueError, match="retorn oblidat"):
        database.regularize_employee_leave_return(
            leave_id, returned, admin_id, "Prova de procediment incorrecte"
        )
    with database.get_connection() as db:
        leave = db.execute(
            "SELECT ended_at, record_state, status, regularization_kind "
            "FROM employee_leave WHERE id = ?", (leave_id,)
        ).fetchone()
    assert leave["ended_at"] is None
    assert leave["record_state"] == "needs_regularization"
    assert leave["status"] == "pending"
    assert leave["regularization_kind"] == "early_departure"
