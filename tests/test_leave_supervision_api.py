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
