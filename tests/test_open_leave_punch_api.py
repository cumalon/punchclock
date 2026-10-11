from timeclock import database


def _setup(client, employee):
    worker = employee()
    kind = database.create_leave_type("Esmorzar", approval_policy="automatic")
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (worker["id"], "2026-10-11T08:00:00+02:00"),
        )
    started = database.start_employee_leave(worker["id"], kind, "sortida")
    assert started["ok"]
    response = client.post("/api/identify", json={"pin": worker["pin"]})
    assert response.status_code == 200
    return worker, response.get_json()["identification_token"]


def _count():
    with database.get_connection() as db:
        return db.execute("SELECT COUNT(*) FROM punch").fetchone()[0]


def test_open_leave_punch_requires_choice_without_writing(client, employee):
    worker, token = _setup(client, employee)
    before = _count()
    response = client.post("/api/punch", json={
        "identification_token": token, "type": "entrada",
    })
    assert response.status_code == 409
    assert response.get_json()["return_choice_required"]
    assert _count() == before
    assert database.get_employee_leave_context(worker["id"])["open_leave"] is not None


def test_now_reuses_return_punch_and_consumes_token(client, employee):
    worker, token = _setup(client, employee)
    before = _count()
    response = client.post("/api/punch", json={
        "identification_token": token, "type": "entrada", "return_choice": "now",
    })
    assert response.status_code == 200
    result = response.get_json()
    assert result["punch_reused_as_return"]
    assert _count() == before + 1
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE employee_id = ?", (worker["id"],)).fetchone()
        assert leave["record_state"] == "finished"
        assert leave["end_punch_id"] == result["punch_id"]
    assert client.post("/api/punch", json={
        "identification_token": token, "type": "entrada",
    }).status_code == 401


def test_earlier_creates_punch_and_marks_regularization(client, employee):
    worker, token = _setup(client, employee)
    before = _count()
    response = client.post("/api/punch", json={
        "identification_token": token, "type": "entrada", "return_choice": "earlier",
    })
    assert response.status_code == 200
    assert _count() == before + 1
    with database.get_connection() as db:
        leave = db.execute("SELECT * FROM employee_leave WHERE employee_id = ?", (worker["id"],)).fetchone()
        assert leave["record_state"] == "needs_regularization"
        assert leave["status"] == "pending"
        assert leave["requires_supervisor"] == 1
        assert leave["ended_at"] is None


def test_now_with_exit_does_not_write(client, employee):
    _, token = _setup(client, employee)
    before = _count()
    response = client.post("/api/punch", json={
        "identification_token": token, "type": "sortida", "return_choice": "now",
    })
    assert response.status_code == 409
    assert response.get_json()["return_entry_required"]
    assert _count() == before


def test_invalid_return_choice_does_not_write(client, employee):
    _, token = _setup(client, employee)
    before = _count()
    response = client.post("/api/punch", json={
        "identification_token": token, "type": "entrada", "return_choice": "invalid",
    })
    assert response.status_code == 400
    assert _count() == before
