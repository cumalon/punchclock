from datetime import datetime, timedelta

from timeclock import database


def _token(client):
    response = client.post("/api/identify", json={"pin": "1234"})
    assert response.status_code == 200
    return response.get_json()["identification_token"]


def test_finish_requires_identification(client, employee):
    employee()
    response = client.post("/api/leave/finish", json={})
    assert response.status_code == 401


def test_finish_without_open_leave_does_not_write(client, employee):
    employee()
    response = client.post("/api/leave/finish", json={
        "identification_token": _token(client),
    })
    assert response.status_code == 409
    with database.get_connection() as db:
        assert db.execute("SELECT COUNT(*) FROM punch").fetchone()[0] == 0


def test_finish_open_leave_creates_linked_return_and_consumes_token(client, employee):
    worker = employee()
    kind = database.create_leave_type("Esmorzar", approval_policy="automatic")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T08:00:00+02:00"),
        )
    started = database.start_employee_leave(worker["id"], kind, "sortida")
    assert started["ok"]
    token = _token(client)
    response = client.post("/api/leave/finish", json={"identification_token": token})
    assert response.status_code == 200
    result = response.get_json()
    assert result["ok"]
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE id = ?", (started["leave_id"],)).fetchone()
        assert leave["record_state"] == "finished"
        assert leave["end_punch_id"] == result["punch_id"]
        punch = db.execute("SELECT type FROM punch WHERE id = ?", (result["punch_id"],)).fetchone()
        assert punch["type"] == "entrada"
    assert client.post("/api/leave/finish", json={"identification_token": token}).status_code == 401


def test_finish_incident_requires_confirmation(client, employee):
    worker = employee()
    kind = database.create_leave_type("Esmorzar")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T08:00:00+02:00"),
        )
    started = database.start_employee_leave(worker["id"], kind, "sortida")
    assert started["ok"]
    # Make the unexpected entry later than the leave start, regardless of today's date.
    with database.get_connection() as db:
        started_at = db.execute(
            "SELECT started_at FROM employee_leave WHERE id = ?",
            (started["leave_id"],),
        ).fetchone()["started_at"]
        unexpected_at = datetime.fromisoformat(started_at) + timedelta(seconds=1)
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], unexpected_at.isoformat(timespec="seconds")),
        )
    token = _token(client)
    response = client.post("/api/leave/finish", json={"identification_token": token})
    assert response.status_code == 409
    assert response.get_json()["confirmation_required"]
    response = client.post("/api/leave/finish", json={
        "identification_token": token, "confirm_incident": True,
    })
    assert response.status_code == 200
    assert response.get_json()["incident"] == 1
