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


def test_regularize_return_api_preserves_punch_and_pending_status(admin_client, employee):
    from datetime import datetime, timedelta

    worker = employee()
    type_id = database.create_leave_type("Pausa supervisada")
    start = (datetime.now(database.LOCAL_TIMEZONE) - timedelta(hours=2))
    start_at = start.isoformat(timespec="seconds")
    returned_at = (start + timedelta(minutes=20)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'sortida', 'pin')
        """, (worker["id"], start_at)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'needs_regularization', 1, ?)
        """, (worker["id"], type_id, start_at, punch_id)).lastrowid
        punch_count = db.execute("SELECT count(*) FROM punch").fetchone()[0]

    classify = admin_client.post(
        f"/api/admin/leaves/{leave_id}/classify", json={"kind": "return"}
    )
    assert classify.status_code == 200
    response = admin_client.post(
        f"/api/admin/leaves/{leave_id}/regularize-return",
        json={"returned_at": returned_at, "reason": "Retorn confirmat"},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "pending"
    detail = admin_client.get(f"/api/admin/leaves/{leave_id}").get_json()["leave"]
    assert detail["ended_at"] == returned_at
    assert detail["record_state"] == "finished"
    assert detail["regularization_kind"] == "return"
    assert detail["requires_supervisor"] == 1
    assert detail["end_punch_id"] is None
    assert detail["regularization_reason"] == "Retorn confirmat"
    with database.get_connection() as db:
        assert db.execute("SELECT count(*) FROM punch").fetchone()[0] == punch_count
        assert db.execute(
            "SELECT timestamp FROM punch WHERE id = ?", (punch_id,)
        ).fetchone()[0] == start_at


def test_regularize_late_arrival_api_requires_authentication(client):
    response = client.post(
        "/api/admin/leaves/1/regularize-late-arrival",
        json={"expected_started_at": "2026-10-11T09:00:00+02:00",
              "reason": "Hora prevista verificada"},
    )
    assert response.status_code == 401


def test_regularize_early_departure_api_requires_authentication(client):
    response = client.post(
        "/api/admin/leaves/1/regularize-early-departure",
        json={"expected_ended_at": "2026-10-11T17:00:00+02:00",
              "reason": "Hora prevista verificada"},
    )
    assert response.status_code == 401


def test_regularization_apis_reject_invalid_input(admin_client):
    late = admin_client.post(
        "/api/admin/leaves/999999/regularize-late-arrival",
        json={"expected_started_at": "invalid", "reason": "Verificat"},
    )
    early = admin_client.post(
        "/api/admin/leaves/999999/regularize-early-departure",
        json={"expected_ended_at": "invalid", "reason": "Verificat"},
    )
    assert late.status_code == 400
    assert early.status_code == 400


def test_late_arrival_regularization_api_end_to_end(admin_client, employee):
    from datetime import datetime, timedelta

    worker = employee()
    type_id = database.create_leave_type("Arribada tardana")
    actual = datetime.now(database.LOCAL_TIMEZONE) - timedelta(hours=1)
    actual_at = actual.isoformat(timespec="seconds")
    expected_at = (actual - timedelta(minutes=30)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'entrada', 'pin')
        """, (worker["id"], actual_at)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'needs_regularization', 1, ?)
        """, (worker["id"], type_id, actual_at, punch_id)).lastrowid
        count_before = db.execute("SELECT count(*) FROM punch").fetchone()[0]

    response = admin_client.post(
        f"/api/admin/leaves/{leave_id}/regularize-late-arrival",
        json={"expected_started_at": expected_at, "reason": "Entrada prevista comprovada"},
    )
    assert response.status_code == 200
    detail = admin_client.get(f"/api/admin/leaves/{leave_id}").get_json()["leave"]
    assert detail["expected_started_at"] == expected_at
    assert detail["regularization_kind"] == "late_arrival"
    assert detail["record_state"] == "finished"
    assert detail["status"] == "pending"
    assert detail["requires_supervisor"] == 1
    with database.get_connection() as db:
        assert db.execute("SELECT count(*) FROM punch").fetchone()[0] == count_before
        assert db.execute(
            "SELECT timestamp FROM punch WHERE id = ?", (punch_id,)
        ).fetchone()[0] == actual_at


def test_early_departure_regularization_api_end_to_end(admin_client, employee):
    from datetime import datetime, timedelta

    worker = employee()
    type_id = database.create_leave_type("Sortida anticipada")
    actual = datetime.now(database.LOCAL_TIMEZONE) - timedelta(hours=2)
    actual_at = actual.isoformat(timespec="seconds")
    expected_at = (actual + timedelta(minutes=45)).isoformat(timespec="seconds")
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'sortida', 'pin')
        """, (worker["id"], actual_at)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'needs_regularization', 1, ?)
        """, (worker["id"], type_id, actual_at, punch_id)).lastrowid
        count_before = db.execute("SELECT count(*) FROM punch").fetchone()[0]

    classified = admin_client.post(
        f"/api/admin/leaves/{leave_id}/classify",
        json={"kind": "early_departure"},
    )
    assert classified.status_code == 200
    response = admin_client.post(
        f"/api/admin/leaves/{leave_id}/regularize-early-departure",
        json={"expected_ended_at": expected_at, "reason": "Final de jornada verificat"},
    )
    assert response.status_code == 200
    detail = admin_client.get(f"/api/admin/leaves/{leave_id}").get_json()["leave"]
    assert detail["expected_ended_at"] == expected_at
    assert detail["regularization_kind"] == "early_departure"
    assert detail["record_state"] == "finished"
    assert detail["status"] == "pending"
    assert detail["requires_supervisor"] == 1
    with database.get_connection() as db:
        assert db.execute("SELECT count(*) FROM punch").fetchone()[0] == count_before
        assert db.execute(
            "SELECT timestamp FROM punch WHERE id = ?", (punch_id,)
        ).fetchone()[0] == actual_at


def test_leave_decision_api_requires_authentication(client):
    response = client.post(
        "/api/admin/leaves/1/decision",
        json={"status": "approved", "reason": "Validat"},
    )
    assert response.status_code == 401


def test_leave_decision_api_rejects_invalid_status(admin_client):
    response = admin_client.post(
        "/api/admin/leaves/999999/decision",
        json={"status": "unknown", "reason": "Validat"},
    )
    assert response.status_code == 400


def test_leave_decision_api_records_reversals(admin_client, employee):
    worker = employee()
    type_id = database.create_leave_type("Permís revisable")
    with database.get_connection() as db:
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, ended_at,
                 record_state, status, requires_supervisor)
            VALUES (?, ?, '2026-10-11T10:00:00+02:00',
                    '2026-10-11T10:20:00+02:00', 'finished', 'pending', 1)
        """, (worker["id"], type_id)).lastrowid
    for status, previous in [
        ("rejected", "pending"),
        ("approved", "rejected"),
        ("rejected", "approved"),
    ]:
        response = admin_client.post(
            f"/api/admin/leaves/{leave_id}/decision",
            json={"status": status, "reason": "Revisió justificada"},
        )
        assert response.status_code == 200
        assert response.get_json()["previous_status"] == previous
    detail = admin_client.get(f"/api/admin/leaves/{leave_id}").get_json()["leave"]
    assert detail["status"] == "rejected"
    assert len(detail["decision_history"]) == 3
    assert [row["new_status"] for row in detail["decision_history"]] == [
        "rejected", "approved", "rejected"
    ]
