from timeclock import database


def _identify(client, pin="1234"):
    response = client.post("/api/identify", json={"pin": pin})
    assert response.status_code == 200
    return response.get_json()["identification_token"]


def _counts():
    with database.get_connection() as db:
        return (
            db.execute("SELECT COUNT(*) FROM punch").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM employee_leave").fetchone()[0],
        )


def test_leave_start_requires_identification(client, employee):
    employee()
    kind = database.create_leave_type("Esmorzar")
    response = client.post("/api/leave/start", json={
        "leave_type_id": kind, "type": "sortida",
    })
    assert response.status_code == 401
    assert _counts() == (0, 0)


def test_leave_start_validates_direction_and_type(client, employee):
    employee()
    kind = database.create_leave_type("Esmorzar")
    token = _identify(client)
    for payload in (
        {"leave_type_id": kind, "type": "invalid"},
        {"leave_type_id": "bad", "type": "entrada"},
    ):
        response = client.post("/api/leave/start", json={
            "identification_token": token, **payload,
        })
        assert response.status_code == 400
    assert _counts() == (0, 0)


def test_leave_start_creates_one_linked_entry(client, employee):
    worker = employee()
    kind = database.create_leave_type("Arribada tard")
    token = _identify(client)
    response = client.post("/api/leave/start", json={
        "identification_token": token, "leave_type_id": kind, "type": "entrada",
    })
    assert response.status_code == 200
    result = response.get_json()
    assert result["ok"] is True
    assert result["record_state"] == "needs_regularization"
    assert _counts() == (1, 1)
    with database.get_connection() as db:
        row = db.execute("SELECT * FROM employee_leave").fetchone()
        assert row["employee_id"] == worker["id"]
        assert row["start_punch_id"] == result["punch_id"]
        assert row["requires_supervisor"] == 1
    assert client.post("/api/leave/start", json={
        "identification_token": token, "leave_type_id": kind, "type": "entrada",
    }).status_code == 401


def test_leave_start_incident_requires_explicit_confirmation(client, employee):
    employee()
    kind = database.create_leave_type("Esmorzar")
    token = _identify(client)
    response = client.post("/api/leave/start", json={
        "identification_token": token, "leave_type_id": kind, "type": "sortida",
    })
    assert response.status_code == 409
    assert response.get_json()["confirmation_required"] is True
    assert _counts() == (0, 0)
    response = client.post("/api/leave/start", json={
        "identification_token": token, "leave_type_id": kind,
        "type": "sortida", "confirm_incident": True,
    })
    assert response.status_code == 200
    assert response.get_json()["incident"] == 1
    assert _counts() == (1, 1)


def test_leave_start_rejects_inactive_type(client, employee):
    employee()
    kind = database.create_leave_type("Inactiu", active=False)
    token = _identify(client)
    response = client.post("/api/leave/start", json={
        "identification_token": token, "leave_type_id": kind, "type": "entrada",
    })
    assert response.status_code == 409
    assert _counts() == (0, 0)
