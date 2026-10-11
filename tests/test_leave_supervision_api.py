"""API de consulta de permisos del supervisor."""

from timeclock import database


def test_leave_list_requires_authentication(client):
    response = client.get("/api/admin/leaves")
    assert response.status_code == 401


def test_admin_can_list_and_filter_leaves(admin_client):
    response = admin_client.get("/api/admin/leaves?filter=regularization")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "leaves": []}
    bad = admin_client.get("/api/admin/leaves?filter=invalid")
    assert bad.status_code == 400


def test_admin_leave_detail_not_found(admin_client):
    response = admin_client.get("/api/admin/leaves/999999")
    assert response.status_code == 404


def test_supervisor_can_read_leaves_but_not_admin_settings(client):
    database.create_admin_user(
        "supervisor-prova", "contrasenya-supervisor-123", role="supervisor"
    )
    response = client.post("/api/admin/login", json={
        "username": "supervisor-prova",
        "password": "contrasenya-supervisor-123",
    })
    assert response.status_code == 200
    listing = client.get("/api/admin/leaves")
    assert listing.status_code == 200
    assert listing.get_json()["leaves"] == []
    detail = client.get("/api/admin/leaves/999999")
    assert detail.status_code == 404
    settings = client.get("/api/admin/settings")
    assert settings.status_code == 403


def test_classification_api_requires_authentication_and_csrf(client):
    response = client.post("/api/admin/leaves/1/classify", json={"kind": "return"})
    assert response.status_code == 401
    login = client.post("/api/admin/login", json={
        "username": "admin", "password": "test-administrator-password"
    })
    assert login.status_code == 200
    response = client.post("/api/admin/leaves/1/classify", json={"kind": "return"})
    assert response.status_code == 403


def test_classification_api_rejects_invalid_kind(admin_client):
    response = admin_client.post(
        "/api/admin/leaves/999999/classify", json={"kind": "invalid"}
    )
    assert response.status_code == 400


def test_classification_api_persists_change(admin_client, employee):
    worker = employee()
    type_id = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, '2026-10-11T10:00:00+02:00', 'sortida', 'pin')
        """, (worker["id"],)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00',
                    'needs_regularization', 1, ?)
        """, (worker["id"], type_id, punch_id)).lastrowid
    response = admin_client.post(
        f"/api/admin/leaves/{leave_id}/classify", json={"kind": "return"}
    )
    assert response.status_code == 200
    detail = admin_client.get(f"/api/admin/leaves/{leave_id}")
    assert detail.get_json()["leave"]["regularization_kind"] == "return"


def test_regularize_return_api_requires_authentication(client):
    response = client.post(
        "/api/admin/leaves/1/regularize-return",
        json={"returned_at": "2026-10-11T10:20:00+02:00", "reason": "Verificat"},
    )
    assert response.status_code == 401


def test_regularize_return_api_rejects_invalid_data(admin_client):
    response = admin_client.post(
        "/api/admin/leaves/999999/regularize-return",
        json={"returned_at": "not-a-date", "reason": "Verificat"},
    )
    assert response.status_code == 400
