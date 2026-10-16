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
        assert row["daily_decision_id"] is None
        assert db.execute("SELECT COUNT(*) FROM daily_leave_decision").fetchone()[0] == 0


def test_leave_type_migration_preserves_configuration_and_defaults_guarantee(client):
    with database.get_connection() as db:
        db.execute("DROP TABLE leave_type")
        db.execute("""
            CREATE TABLE leave_type (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                sort_order INTEGER NOT NULL DEFAULT 0,
                approval_policy TEXT NOT NULL DEFAULT 'manual'
                    CHECK (approval_policy IN ('manual', 'automatic', 'threshold')),
                max_minutes INTEGER CHECK (max_minutes IS NULL OR max_minutes > 0),
                auto_approve_minutes INTEGER CHECK (
                    auto_approve_minutes IS NULL OR auto_approve_minutes > 0
                ),
                CHECK (
                    (approval_policy = 'threshold' AND auto_approve_minutes IS NOT NULL)
                    OR (approval_policy != 'threshold' AND auto_approve_minutes IS NULL)
                )
            )
        """)
        db.execute("""
            INSERT INTO leave_type (
                id, name, active, sort_order, approval_policy, max_minutes,
                auto_approve_minutes
            ) VALUES (1, 'Esmorzar', 0, 7, 'threshold', 20, 30)
        """)

    database.init_database()
    database.init_database()

    migrated = database.list_leave_types()[0]
    assert migrated["id"] == 1
    assert migrated["name"] == "Esmorzar"
    assert migrated["active"] == 0
    assert migrated["sort_order"] == 7
    assert migrated["approval_policy"] == "threshold"
    assert migrated["max_minutes"] == 20
    assert migrated["auto_approve_minutes"] == 30
    assert migrated["guaranteed_daily_minutes"] == 0


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
