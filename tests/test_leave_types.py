import sqlite3
from pathlib import Path

import pytest

from timeclock import database


def test_leave_types_create_update_and_delete(admin_client):
    created = admin_client.post("/api/admin/leave-types", json={
        "name": "Esmorzar", "approval_policy": "threshold",
        "auto_approve_minutes": 20, "max_minutes": 40,
        "guaranteed_daily_minutes": 30,
    })
    assert created.status_code == 201
    type_id = created.get_json()["id"]
    rows = admin_client.get("/api/admin/leave-types").get_json()["leave_types"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Esmorzar"
    assert rows[0]["guaranteed_daily_minutes"] == 30
    assert rows[0]["auto_approve_minutes"] == 20
    assert rows[0]["used"] == 0
    assert admin_client.put(f"/api/admin/leave-types/{type_id}", json={
        "name": "Esmorzar", "approval_policy": "threshold",
        "auto_approve_minutes": 20, "max_minutes": 40, "active": False,
        "guaranteed_daily_minutes": 25,
    }).status_code == 200
    updated = admin_client.get("/api/admin/leave-types").get_json()["leave_types"][0]
    assert updated["active"] == 0
    assert updated["guaranteed_daily_minutes"] == 25
    assert admin_client.delete(f"/api/admin/leave-types/{type_id}").status_code == 200
    assert admin_client.get("/api/admin/leave-types").get_json()["leave_types"] == []


def test_used_leave_type_cannot_be_deleted(admin_client, employee):
    type_id = admin_client.post("/api/admin/leave-types", json={
        "name": "Visita mèdica", "approval_policy": "manual",
    }).get_json()["id"]
    worker = employee()
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO employee_leave (employee_id, leave_type_id, started_at) VALUES (?, ?, ?)",
            (worker["id"], type_id, "2026-10-11T09:00:00+02:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM leave_type WHERE id = ?", (type_id,))
    assert admin_client.delete(f"/api/admin/leave-types/{type_id}").status_code == 400
    assert admin_client.put(f"/api/admin/leave-types/{type_id}", json={
        "name": "Visita mèdica", "approval_policy": "manual", "active": False,
    }).status_code == 200
    assert admin_client.get("/api/admin/leave-types").get_json()["leave_types"][0]["used"] == 1


@pytest.mark.parametrize("payload", [
    {"name": ""},
    {"name": "Test", "approval_policy": "unknown"},
    {"name": "Test", "approval_policy": "threshold"},
    {"name": "Test", "approval_policy": "automatic", "auto_approve_minutes": 20},
    {"name": "Test", "max_minutes": -1},
    {"name": "Test", "guaranteed_daily_minutes": -1},
    {"name": "Test", "guaranteed_daily_minutes": True},
    {"name": "Test", "guaranteed_daily_minutes": 1.5},
    {"name": "Test", "max_minutes": True},
    {"name": "Test", "active": "false"},
])
def test_leave_type_invalid_input(admin_client, payload):
    assert admin_client.post("/api/admin/leave-types", json=payload).status_code == 400


def test_leave_type_duplicate_name(admin_client):
    assert admin_client.post("/api/admin/leave-types", json={"name": "Esmorzar"}).status_code == 201
    assert admin_client.post("/api/admin/leave-types", json={"name": "esmorzar"}).status_code == 400


def test_leave_type_guaranteed_minutes_accept_zero_and_default_to_zero(admin_client):
    created = admin_client.post("/api/admin/leave-types", json={
        "name": "Visita mèdica", "guaranteed_daily_minutes": 0,
    })
    assert created.status_code == 201
    listed = admin_client.get("/api/admin/leave-types").get_json()["leave_types"]
    assert listed[0]["guaranteed_daily_minutes"] == 0

    legacy_client = admin_client.post("/api/admin/leave-types", json={"name": "Altres"})
    assert legacy_client.status_code == 201
    listed = admin_client.get("/api/admin/leave-types").get_json()["leave_types"]
    assert listed[1]["guaranteed_daily_minutes"] == 0


def test_supervisor_cannot_manage_leave_types(admin_client):
    assert admin_client.post("/api/admin/users", json={
        "username": "leave-supervisor", "password": "supervisor-password-123",
        "role": "supervisor",
    }).status_code == 201
    admin_client.post("/api/admin/logout")
    login = admin_client.post("/api/admin/login", json={
        "username": "leave-supervisor", "password": "supervisor-password-123",
    })
    assert login.status_code == 200
    assert admin_client.get("/api/admin/leave-types").status_code == 403
    assert admin_client.post("/api/admin/leave-types", json={"name": "Test"}).status_code == 403
    assert admin_client.get("/admin").status_code == 200
    assert 'data-section="leave-types"' not in admin_client.get("/admin").get_data(as_text=True)


def test_leave_types_persist_across_database_init(admin_client):
    assert admin_client.post("/api/admin/leave-types", json={"name": "Esmorzar"}).status_code == 201
    database.init_database()
    assert len(admin_client.get("/api/admin/leave-types").get_json()["leave_types"]) == 1


def test_flexible_approval_threshold_can_exceed_reference_duration(admin_client):
    response = admin_client.post("/api/admin/leave-types", json={
        "name": "Esmorzar flexible", "approval_policy": "threshold",
        "max_minutes": 20, "auto_approve_minutes": 30,
    })
    assert response.status_code == 201


def test_list_active_leave_types_excludes_inactive_and_preserves_configured_order(client):
    database.create_leave_type("Zebra", approval_policy="manual")
    database.create_leave_type(
        "Esmorzar", approval_policy="threshold", guaranteed_daily_minutes=30,
        max_minutes=20, auto_approve_minutes=30,
    )
    database.create_leave_type("Amagat", approval_policy="automatic", active=False)

    rows = database.list_active_leave_types()

    assert [row["name"] for row in rows] == ["Zebra", "Esmorzar"]
    assert rows[1]["approval_policy"] == "threshold"
    assert rows[1]["max_minutes"] == 20
    assert rows[1]["auto_approve_minutes"] == 30
    assert rows[1]["guaranteed_daily_minutes"] == 30
    assert all("active" not in row and "used" not in row for row in rows)


def test_admin_form_exposes_guaranteed_minutes_with_zero_allowed(admin_client):
    page = admin_client.get("/admin").get_data(as_text=True)
    assert 'id="leave-type-guaranteed" type="number" min="0"' in page
    assert 'admin.css?v=6.29' in page
    assert 'admin.js?v=7.14' in page
    assert "Els permisos s’acumulen per treballador, tipus i dia." in page
    assert "El llindar d’aprovació automàtica s’aplica al total acumulat del dia" in page


def test_leave_type_action_controls_use_last_column_at_desktop_breakpoints():
    css = (Path(__file__).resolve().parents[1] / "static" / "admin.css").read_text()
    assert ".leave-type-actions {\n    grid-column: 8;" in css
    assert "@media (max-width: 1250px)" in css
    assert ".leave-type-actions { grid-column: 8; gap: 4px; }" in css
    assert "@media (max-width: 1050px)" in css
    assert "@media (max-width: 780px)" in css
    assert "@media (max-width: 460px)" in css


def test_list_active_leave_types_empty(client):
    assert database.list_active_leave_types() == []
