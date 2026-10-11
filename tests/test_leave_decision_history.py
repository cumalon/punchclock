"""Proves de l'esquema d'auditoria de decisions sobre permisos."""

import sqlite3

import pytest

from timeclock import database


def test_decision_history_table_exists_and_is_idempotent(client):
    database.init_database()
    database.init_database()
    with database.get_connection() as db:
        columns = {
            row["name"] for row in
            db.execute("PRAGMA table_info(employee_leave_decision_history)")
        }
    assert {
        "id", "leave_id", "admin_user_id", "changed_at",
        "previous_status", "new_status", "reason",
    } <= columns


def test_decision_history_rejects_invalid_status_and_blank_reason(client):
    with database.get_connection() as db:
        # Les restriccions CHECK s'apliquen abans de validar les claus foranes.
        for previous, new, reason in [
            ("approved", "approved", "Repetit"),
            ("pending", "pending", "No decidit"),
            ("pending", "approved", "  "),
            ("unknown", "approved", "Estat incorrecte"),
            ("approved", "unknown", "Estat incorrecte"),
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("""
                    INSERT INTO employee_leave_decision_history
                        (leave_id, admin_user_id, changed_at,
                         previous_status, new_status, reason)
                    VALUES (99999, 99999, '2026-10-11T12:00:00+02:00', ?, ?, ?)
                """, (previous, new, reason))
