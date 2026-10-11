import sqlite3

import pytest

from timeclock import database


def test_leave_migration_preserves_legacy_records(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        db.execute("DROP INDEX idx_employee_leave_one_open")
        db.execute("ALTER TABLE employee_leave RENAME TO employee_leave_current")
        db.execute("""
            CREATE TABLE employee_leave (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employee(id),
                leave_type_id INTEGER NOT NULL REFERENCES leave_type(id) ON DELETE RESTRICT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected'))
            )
        """)
        db.execute("""
            INSERT INTO employee_leave (id, employee_id, leave_type_id, started_at, ended_at, status)
            VALUES (1, ?, ?, '2026-10-10T10:00:00+02:00',
                    '2026-10-10T10:15:00+02:00', 'approved')
        """, (worker["id"], leave_type_id))
        db.execute("DROP TABLE employee_leave_current")

    database.init_database()
    database.init_database()
    with database.get_connection() as db:
        row = db.execute("SELECT * FROM employee_leave WHERE id = 1").fetchone()
        assert row["employee_id"] == worker["id"]
        assert row["status"] == "approved"
        assert row["record_state"] == "finished"
        assert row["requires_supervisor"] == 0
        assert row["ended_at"] == "2026-10-10T10:15:00+02:00"


def test_one_open_leave_per_employee(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO employee_leave (employee_id, leave_type_id, started_at) VALUES (?, ?, ?)",
            (worker["id"], leave_type_id, "2026-10-11T10:00:00+02:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO employee_leave (employee_id, leave_type_id, started_at) VALUES (?, ?, ?)",
                (worker["id"], leave_type_id, "2026-10-11T11:00:00+02:00"),
            )
