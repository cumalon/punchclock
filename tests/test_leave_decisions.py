"""Decisions supervisades amb historial d'auditoria."""

import pytest

from timeclock import database


def make_finished_leave(employee_id):
    type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, ended_at,
                 record_state, status, requires_supervisor)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00',
                    '2026-10-11T10:20:00+02:00', 'finished', 'pending', 1)
        """, (employee_id, type_id)).lastrowid
        admin_id = db.execute(
            "SELECT id FROM admin_user WHERE username = 'admin'"
        ).fetchone()["id"]
    return leave_id, admin_id


def test_decision_can_change_both_directions_with_history(client, employee):
    leave_id, admin_id = make_finished_leave(employee()["id"])
    for new_status, previous in [
        ("rejected", "pending"),
        ("approved", "rejected"),
        ("rejected", "approved"),
    ]:
        result = database.decide_employee_leave(
            leave_id, new_status, admin_id, "Decisió justificada"
        )
        assert result["previous_status"] == previous
        assert result["status"] == new_status
    detail = database.get_employee_leave_for_supervision(leave_id)
    assert detail["status"] == "rejected"
    assert [(h["previous_status"], h["new_status"]) for h in detail["decision_history"]] == [
        ("pending", "rejected"), ("rejected", "approved"), ("approved", "rejected")
    ]
    assert all(h["reviewer_name"] == "admin" for h in detail["decision_history"])


def test_decision_rejects_unfinished_leave_and_blank_reason(client, employee):
    leave_id, admin_id = make_finished_leave(employee()["id"])
    with database.get_connection() as db:
        db.execute("""
            UPDATE employee_leave SET record_state = 'needs_regularization'
            WHERE id = ?
        """, (leave_id,))
    with pytest.raises(ValueError, match="regularitzar"):
        database.decide_employee_leave(leave_id, "approved", admin_id, "Justificat")
    with database.get_connection() as db:
        db.execute("UPDATE employee_leave SET record_state = 'finished' WHERE id = ?", (leave_id,))
    with pytest.raises(ValueError, match="justificar"):
        database.decide_employee_leave(leave_id, "approved", admin_id, "  ")
    assert database.get_employee_leave_for_supervision(leave_id)["decision_history"] == []


def test_decision_rejects_repeated_status(client, employee):
    leave_id, admin_id = make_finished_leave(employee()["id"])
    database.decide_employee_leave(leave_id, "approved", admin_id, "Aprovat")
    with pytest.raises(ValueError, match="ja té"):
        database.decide_employee_leave(leave_id, "approved", admin_id, "Duplicat")
    assert len(database.get_employee_leave_for_supervision(leave_id)["decision_history"]) == 1
