"""Detall de permisos per a supervisió."""

from timeclock import database


def test_supervisor_leave_detail_includes_linked_punch(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, '2026-10-11T10:00:00+02:00', 'sortida', 'pin')
        """, (worker["id"],)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, start_punch_id,
                 record_state, requires_supervisor)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00', ?,
                    'needs_regularization', 1)
        """, (worker["id"], leave_type_id, punch_id)).lastrowid
    detail = database.get_employee_leave_for_supervision(leave_id)
    assert detail["employee_name"] == worker["name"]
    assert detail["leave_type_name"] == "Esmorzar"
    assert detail["record_state"] == "needs_regularization"
    assert len(detail["punches"]) == 1
    assert detail["punches"][0]["id"] == punch_id
    assert detail["decision_history"] == []


def test_supervisor_leave_detail_missing_returns_none(client):
    assert database.get_employee_leave_for_supervision(999999) is None
