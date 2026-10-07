import pytest

import timeclock.database as database
from timeclock import branding
import app as app_module
from app import app, identification_tokens


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data-dir"
    monkeypatch.setattr(database, "DATA_DIR", data_dir)
    return data_dir


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_database = tmp_path / "timeclock-test.db"
    monkeypatch.setattr(database, "DATABASE_PATH", test_database)
    database.init_database()
    database.create_admin_user("admin", "test-administrator-password")
    identification_tokens.clear()
    app_module.employee_pin_failures.clear()
    app_module.employee_pin_lockout_until = 0

    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client
    identification_tokens.clear()
    app_module.employee_pin_failures.clear()
    app_module.employee_pin_lockout_until = 0


@pytest.fixture
def employee():
    def create(name="Treballador Prova", pin="1234"):
        employee_id = database.create_employee(name, pin)
        return {"id": employee_id, "name": name, "pin": pin}
    return create


@pytest.fixture
def admin_client(client):
    response = client.post("/api/admin/login", json={
        "username": "admin",
        "password": "test-administrator-password",
    })
    assert response.status_code == 200
    client.csrf_token = response.get_json()["csrf_token"]
    original_open = client.open

    def open_with_csrf(*args, **kwargs):
        method = str(kwargs.get("method", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", client.csrf_token)
            kwargs["headers"] = headers
        return original_open(*args, **kwargs)

    client.open = open_with_csrf
    return client
