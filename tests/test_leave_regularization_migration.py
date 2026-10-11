"""Migració dels camps de regularització dels permisos."""

from timeclock import database


def test_leave_regularization_columns_exist_and_migration_is_repeatable(client):
    database.init_database()
    database.init_database()
    with database.get_connection() as db:
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(employee_leave)")
        }
    assert {
        "expected_started_at",
        "expected_ended_at",
        "regularization_reason",
        "regularized_at",
        "regularized_by",
    } <= columns


def test_leave_regularization_fields_start_empty(client, employee):
    worker = employee()
    type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00')
        """, (worker["id"], type_id)).lastrowid
        row = db.execute("""
            SELECT expected_started_at, expected_ended_at,
                   regularization_reason, regularized_at, regularized_by
            FROM employee_leave WHERE id = ?
        """, (leave_id,)).fetchone()
    assert all(value is None for value in row)
