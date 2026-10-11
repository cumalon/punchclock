"""Consulta de permisos per al panell del supervisor."""

import pytest

from timeclock import database


def test_supervisor_leave_filters(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        for started, state, status in [
            ("2026-10-11T10:00:00+02:00", "needs_regularization", "pending"),
            ("2026-10-11T11:00:00+02:00", "finished", "pending"),
            ("2026-10-11T12:00:00+02:00", "finished", "approved"),
            ("2026-10-11T13:00:00+02:00", "finished", "rejected"),
        ]:
            db.execute("""
                INSERT INTO employee_leave
                    (employee_id, leave_type_id, started_at, ended_at,
                     record_state, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (worker["id"], leave_type_id, started,
                  started if state == "finished" else None, state, status))
    assert len(database.list_employee_leaves_for_supervision("all")) == 4
    regularization = database.list_employee_leaves_for_supervision("regularization")
    assert len(regularization) == 1
    assert regularization[0]["employee_name"] == worker["name"]
    assert regularization[0]["leave_type_name"] == "Esmorzar"
    assert regularization[0]["requires_supervisor"] == 0
    assert len(database.list_employee_leaves_for_supervision("approval")) == 1
    assert len(database.list_employee_leaves_for_supervision("history")) == 2
    assert [r["status"] for r in database.list_employee_leaves_for_supervision("all")] == [
        "rejected", "approved", "pending", "pending"
    ]


def test_supervisor_leave_filter_rejects_unknown_values(client):
    with pytest.raises(ValueError, match="Filtre"):
        database.list_employee_leaves_for_supervision("anything")
