"""Identificació explícita del procediment de regularització."""

from timeclock import database


def test_regularization_kind_migration_is_repeatable(client):
    database.init_database()
    database.init_database()
    with database.get_connection() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(employee_leave)")}
    assert "regularization_kind" in columns


def test_legacy_leave_kind_remains_unclassified(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at,
                 record_state, requires_supervisor)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00',
                    'needs_regularization', 1)
        """, (worker["id"], leave_type_id)).lastrowid
    database.init_database()
    with database.get_connection() as db:
        row = db.execute(
            "SELECT regularization_kind FROM employee_leave WHERE id = ?",
            (leave_id,)
        ).fetchone()
    assert row["regularization_kind"] is None
