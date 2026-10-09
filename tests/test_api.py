import csv
import io

import timeclock.database as database
import app as app_module


def test_pages_load(client):
    assert client.get("/").status_code == 200
    response = client.get("/admin")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/login")
    assert client.get("/admin/login").status_code == 200


def test_admin_authentication(client):
    assert client.get("/api/admin/employees").status_code == 401

    response = client.post("/api/admin/login", json={
        "username": "admin",
        "password": "incorrect-password",
    })
    assert response.status_code == 401

    response = client.post("/api/admin/login", json={
        "username": "admin",
        "password": "test-administrator-password",
    })
    assert response.status_code == 200
    assert response.get_json()["username"] == "admin"
    csrf_token = response.get_json()["csrf_token"]
    assert client.get("/api/admin/employees").status_code == 200
    assert client.get("/admin").status_code == 200

    assert client.post("/api/admin/logout").status_code == 403
    assert client.get("/api/admin/employees").status_code == 200
    assert client.post(
        "/api/admin/logout",
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 200
    assert client.get("/api/admin/employees").status_code == 401




def test_admin_mutation_requires_csrf_token(client):
    response = client.post("/api/admin/login", json={
        "username": "admin",
        "password": "test-administrator-password",
    })
    assert response.status_code == 200
    csrf_token = response.get_json()["csrf_token"]

    response = client.post(
        "/api/admin/employees",
        json={"name": "Sense CSRF", "pin": "2468"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Token CSRF no vàlid"

    response = client.post(
        "/api/admin/employees",
        json={"name": "Amb CSRF", "pin": "2468"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 201


def test_admin_get_does_not_require_csrf_token(client):
    response = client.post("/api/admin/login", json={
        "username": "admin",
        "password": "test-administrator-password",
    })
    assert response.status_code == 200
    assert client.get("/api/admin/employees").status_code == 200

def test_admin_can_change_own_password(admin_client):
    response = admin_client.post("/api/admin/change-password", json={
        "current_password": "test-administrator-password",
        "new_password": "changed-administrator-password",
        "confirmation": "changed-administrator-password",
    })
    assert response.status_code == 200

    # Changing the password invalidates the current web session.
    assert admin_client.get("/api/admin/employees").status_code == 401

    response = admin_client.post("/api/admin/login", json={
        "username": "admin",
        "password": "changed-administrator-password",
    })
    assert response.status_code == 200


def test_admin_password_change_validates_current_password_and_confirmation(admin_client):
    response = admin_client.post("/api/admin/change-password", json={
        "current_password": "incorrect-password",
        "new_password": "changed-administrator-password",
        "confirmation": "changed-administrator-password",
    })
    assert response.status_code == 400

    response = admin_client.post("/api/admin/change-password", json={
        "current_password": "test-administrator-password",
        "new_password": "changed-administrator-password",
        "confirmation": "different-administrator-password",
    })
    assert response.status_code == 400


def test_identification_api(client, employee):
    item = employee()

    response = client.post("/api/identify", json={})
    assert response.status_code == 400

    response = client.post("/api/identify", json={"pin": "9999"})
    assert response.status_code == 401

    response = client.post("/api/identify", json={"pin": item["pin"]})
    assert response.status_code == 200
    assert response.get_json()["employee"]["id"] == item["id"]


def test_kiosk_hides_keypad_for_lockout_message_then_restores_it(client):
    script = client.get("/static/app.js").get_data(as_text=True)

    assert "if (response.status === 429)" in script
    assert (
        "Massa intents incorrectes. Identificació bloquejada temporalment. "
        "Torna-ho a provar d'aquí a un minut."
    ) in script
    assert "pinKeypad.classList.add(\"hidden\")" in script
    assert "setTimeout(showPinScreen, 3000)" in script
    assert "pinKeypad.classList.remove(\"hidden\")" in script
    assert 'display.textContent = "PIN incorrecte";' in script


def test_employee_pin_rate_limit_blocks_after_repeated_invalid_attempts(client, employee):
    employee()
    responses = [
        client.post("/api/identify", json={"pin": "9999"})
        for _ in range(app_module.EMPLOYEE_PIN_MAX_FAILURES)
    ]

    assert [response.status_code for response in responses] == [401] * 4 + [429]
    assert responses[-1].get_json()["error"] == (
        "PIN incorrecte o identificació temporalment limitada"
    )
    events = database.list_terminal_events()
    assert [event["type"] for event in events] == ["employee_pin_rate_limited"]
    assert "9999" not in events[0]["detail"]


def test_employee_pin_lockout_expires(client, employee, monkeypatch):
    item = employee()
    now = [100]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: now[0])

    for _ in range(app_module.EMPLOYEE_PIN_MAX_FAILURES):
        client.post("/api/identify", json={"pin": "9999"})

    blocked = client.post("/api/identify", json={"pin": item["pin"]})
    assert blocked.status_code == 429

    now[0] += app_module.EMPLOYEE_PIN_LOCKOUT_SECONDS
    allowed = client.post("/api/identify", json={"pin": item["pin"]})
    assert allowed.status_code == 200


def test_successful_employee_authentication_does_not_reset_failures(client, employee):
    item = employee()

    for _ in range(app_module.EMPLOYEE_PIN_MAX_FAILURES - 1):
        assert client.post("/api/identify", json={"pin": "9999"}).status_code == 401
    assert client.post("/api/identify", json={"pin": item["pin"]}).status_code == 200

    limited = client.post("/api/identify", json={"pin": "9999"})
    assert limited.status_code == 429
    assert client.post("/api/identify", json={"pin": item["pin"]}).status_code == 429


def test_employee_and_admin_usb_pin_rate_limits_are_independent(client, employee, monkeypatch):
    item = employee()
    admin = database.authenticate_admin("admin", "test-administrator-password")
    database.set_admin_pin(admin["id"], "123456")
    monkeypatch.setattr(app_module, "get_usb_status", lambda: {"state": "available"})

    for _ in range(app_module.EMPLOYEE_PIN_MAX_FAILURES):
        client.post("/api/identify", json={"pin": "9999"})
    for _ in range(app_module.USB_PIN_MAX_FAILURES):
        response = client.post(
            "/api/usb/authorize-export",
            json={"pin": "000000"},
        )
        assert response.status_code == 401

    assert client.post(
        "/api/usb/authorize-export",
        json={"pin": "000000"},
    ).status_code == 429
    assert client.post("/api/identify", json={"pin": item["pin"]}).status_code == 429


def test_employee_admin_api(admin_client, employee):
    response = admin_client.get("/api/admin/employees")
    assert response.status_code == 200
    assert response.get_json()["employees"] == []

    response = admin_client.post("/api/admin/employees", json={"name": "Maria", "pin": "2468"})
    assert response.status_code == 201
    employee_id = response.get_json()["employee_id"]

    response = admin_client.post("/api/admin/employees", json={"name": "", "pin": "12"})
    assert response.status_code == 400

    response = admin_client.patch(
        f"/api/admin/employees/{employee_id}",
        json={"name": "Maria Nova", "pin": "8642", "active": True},
    )
    assert response.status_code == 200
    assert response.get_json()["employee"]["name"] == "Maria Nova"

    response = admin_client.patch(f"/api/admin/employees/{employee_id}", json={"name": ""})
    assert response.status_code == 400

    response = admin_client.patch("/api/admin/employees/99999", json={"name": "Ningú"})
    assert response.status_code == 404


def identify_token(client, pin):
    response = client.post("/api/identify", json={"pin": pin})
    assert response.status_code == 200
    return response.get_json()["identification_token"]


def punch_with_token(client, token, punch_type, confirm_incident=False):
    return client.post("/api/punch", json={
        "identification_token": token,
        "type": punch_type,
        "confirm_incident": confirm_incident,
    })


def test_punch_requires_valid_identification_token(client, employee):
    item = employee()

    assert client.post("/api/punch", json={}).status_code == 400
    assert client.post("/api/punch", json={"type": "entrada"}).status_code == 401
    assert client.post("/api/punch", json={
        "identification_token": "invalid",
        "type": "entrada",
    }).status_code == 401

    token = identify_token(client, item["pin"])
    response = punch_with_token(client, token, "entrada")
    assert response.status_code == 200
    assert response.get_json()["punch"]["employee_id"] == item["id"]

    # A successful punch consumes the token.
    assert punch_with_token(client, token, "sortida").status_code == 401


def test_punch_ignores_forged_employee_id(client, employee):
    first = employee("Primer", "1234")
    second = employee("Segon", "5678")
    token = identify_token(client, first["pin"])

    response = client.post("/api/punch", json={
        "identification_token": token,
        "employee_id": second["id"],
        "type": "entrada",
    })
    assert response.status_code == 200
    assert response.get_json()["punch"]["employee_id"] == first["id"]


def test_first_exit_incident_can_be_confirmed(client, employee):
    item = employee()
    token = identify_token(client, item["pin"])

    response = punch_with_token(client, token, "sortida")
    assert response.status_code == 409
    data = response.get_json()
    assert data["confirmation_required"] is True
    assert "Primera acció del dia" in data["error"]
    assert database.list_punches() == []

    response = punch_with_token(client, token, "sortida", confirm_incident=True)
    assert response.status_code == 200
    punch = response.get_json()["punch"]
    assert punch["incident"] == 1
    assert "Primera acció del dia" in punch["note"]
    assert punch_with_token(client, token, "entrada").status_code == 401


def test_duplicate_entry_incident_requires_confirmation(client, employee):
    item = employee()

    token = identify_token(client, item["pin"])
    assert punch_with_token(client, token, "entrada").status_code == 200

    token = identify_token(client, item["pin"])
    response = punch_with_token(client, token, "entrada")
    assert response.status_code == 409
    assert response.get_json()["confirmation_required"] is True
    assert "Entrada consecutiva" in response.get_json()["error"]
    assert len(database.list_punches()) == 1

    response = punch_with_token(client, token, "entrada", confirm_incident=True)
    assert response.status_code == 200
    assert response.get_json()["punch"]["incident"] == 1
    assert "Entrada consecutiva" in response.get_json()["punch"]["note"]


def test_duplicate_exit_incident_requires_confirmation(client, employee):
    item = employee()

    token = identify_token(client, item["pin"])
    assert punch_with_token(client, token, "entrada").status_code == 200
    token = identify_token(client, item["pin"])
    assert punch_with_token(client, token, "sortida").status_code == 200

    token = identify_token(client, item["pin"])
    response = punch_with_token(client, token, "sortida")
    assert response.status_code == 409
    assert response.get_json()["confirmation_required"] is True
    assert "Sortida consecutiva" in response.get_json()["error"]
    assert len(database.list_punches()) == 2

    response = punch_with_token(client, token, "sortida", confirm_incident=True)
    assert response.status_code == 200
    assert response.get_json()["punch"]["incident"] == 1
    assert "Sortida consecutiva" in response.get_json()["punch"]["note"]

def test_punch_history_api_filters(admin_client, employee):
    first = employee("Primer", "1234")
    second = employee("Segon", "5678")
    with database.get_connection() as db:
        db.executemany(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, ?, 'pin')",
            [
                (first["id"], "2026-09-30T08:00:00+02:00", "entrada"),
                (first["id"], "2026-09-30T17:00:00+02:00", "sortida"),
                (second["id"], "2026-10-01T09:00:00+02:00", "entrada"),
            ],
        )

    response = admin_client.get(
        f"/api/admin/punches?employee_id={first['id']}&date_from=2026-09-30&date_to=2026-09-30"
    )
    assert response.status_code == 200
    punches = response.get_json()["punches"]
    assert len(punches) == 2
    assert {punch["employee_name"] for punch in punches} == {"Primer"}


def test_csv_export(admin_client, employee):
    item = employee("Treballador Àngel", "1234")
    with database.get_connection() as db:
        db.executemany(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, ?, 'pin')",
            [
                (item["id"], "2026-10-01T08:15:30+02:00", "entrada"),
                (item["id"], "2026-10-01T17:45:00+02:00", "sortida"),
            ],
        )

    response = admin_client.get(
        f"/api/admin/export.csv?employee_id={item['id']}&date_from=2026-10-01&date_to=2026-10-01"
    )
    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == 'attachment; filename="fitxatges.csv"'
    assert response.data.startswith(b"\xef\xbb\xbf")

    text = response.data.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[0] == ["Data", "Hora", "Treballador", "Tipus", "Metode", "Incidencia"]
    assert rows[1] == ["2026-10-01", "17:45:00", "Treballador Àngel", "Sortida", "pin", ""]
    assert rows[2] == ["2026-10-01", "08:15:30", "Treballador Àngel", "Entrada", "pin", ""]


def test_settings_api(admin_client):
    response = admin_client.get("/api/admin/settings")
    assert response.status_code == 200
    data = response.get_json()
    assert data["settings"]["terminal_id"] == "TC01"
    assert data["system"]["timezone"] == "Europe/Madrid"
    assert data["system"]["database"] == "OK"

    response = admin_client.put("/api/admin/settings", json={
        "terminal_name": "Taller",
        "terminal_id": "TC03",
        "sound_volume": 0,
    })
    assert response.status_code == 200
    assert response.get_json()["settings"] == {
        "terminal_name": "Taller",
        "terminal_id": "TC03",
        "sound_volume": 0,
    }

    response = admin_client.put("/api/admin/settings", json={
        "terminal_name": "",
        "terminal_id": "TC03",
        "sound_volume": 20,
    })
    assert response.status_code == 400


def test_public_kiosk_settings(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {
        "ok": True,
        "settings": {
            "terminal_name": "TimeClockPi",
            "sound_volume": 20,
        },
    }

    database.update_settings("Recepció", "TC01", 0)
    data = client.get("/api/settings").get_json()
    assert data["settings"]["terminal_name"] == "Recepció"
    assert data["settings"]["sound_volume"] == 0


def test_timeline_and_terminal_event_export(admin_client):
    database.create_terminal_event("startup", "Terminal iniciat")
    response = admin_client.get("/api/admin/timeline")
    assert response.status_code == 200
    assert any(item["kind"] == "terminal_event" for item in response.get_json()["items"])

    response = admin_client.get("/api/admin/terminal-events.csv")
    assert response.status_code == 200
    assert "esdeveniments-terminal.csv" in response.headers["Content-Disposition"]



def test_admin_can_correct_punch_with_audit_trail(admin_client, employee):
    first = employee("Primer", "1234")
    second = employee("Segon", "5678")
    with database.get_connection() as db:
        cursor = db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (first["id"], "2026-10-02T08:00:00+02:00"),
        )
        punch_id = cursor.lastrowid

    response = admin_client.patch(f"/api/admin/punches/{punch_id}", json={
        "employee_id": second["id"],
        "timestamp": "2026-10-02T08:15:00",
        "type": "sortida",
        "reason": "Correcció administrativa de prova",
    })
    assert response.status_code == 200

    punches = database.list_punches()
    assert punches[0]["employee_id"] == second["id"]
    assert punches[0]["timestamp"] == "2026-10-02T08:15:00+02:00"
    assert punches[0]["type"] == "sortida"

    response = admin_client.get(f"/api/admin/punches/{punch_id}/corrections")
    assert response.status_code == 200
    corrections = response.get_json()["corrections"]
    assert len(corrections) == 1
    assert corrections[0]["old_employee_id"] == first["id"]
    assert corrections[0]["new_employee_id"] == second["id"]
    assert corrections[0]["old_timestamp"] == "2026-10-02T08:00:00+02:00"
    assert corrections[0]["new_timestamp"] == "2026-10-02T08:15:00+02:00"
    assert corrections[0]["old_type"] == "entrada"
    assert corrections[0]["new_type"] == "sortida"
    assert corrections[0]["admin_username"] == "admin"


def test_punch_correction_requires_reason_and_authentication(client, admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        cursor = db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (item["id"], "2026-10-02T08:00:00+02:00"),
        )
        punch_id = cursor.lastrowid

    response = admin_client.patch(f"/api/admin/punches/{punch_id}", json={
        "employee_id": item["id"],
        "timestamp": "2026-10-02T08:05:00",
        "type": "entrada",
        "reason": "",
    })
    assert response.status_code == 400

    admin_client.post("/api/admin/logout")
    response = client.patch(f"/api/admin/punches/{punch_id}", json={
        "employee_id": item["id"],
        "timestamp": "2026-10-02T08:05:00+02:00",
        "type": "entrada",
        "reason": "No autoritzat",
    })
    assert response.status_code == 401



def test_punch_correction_uses_madrid_winter_offset(admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        cursor = db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (item["id"], "2026-01-15T08:00:00+01:00"),
        )
        punch_id = cursor.lastrowid

    response = admin_client.patch(f"/api/admin/punches/{punch_id}", json={
        "employee_id": item["id"],
        "timestamp": "2026-01-15T08:30:00",
        "type": "entrada",
        "reason": "Prova d'horari d'hivern",
    })
    assert response.status_code == 200
    assert response.get_json()["punch"]["timestamp"] == "2026-01-15T08:30:00+01:00"



def test_admin_can_review_incident_without_erasing_it(admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        cursor = db.execute(
            """INSERT INTO punch
               (employee_id, timestamp, type, method, incident, note)
               VALUES (?, ?, 'sortida', 'pin', 1, ?)""",
            (
                item["id"],
                "2026-10-02T08:00:00+02:00",
                "Primera acció del dia: sortida confirmada pel treballador",
            ),
        )
        punch_id = cursor.lastrowid

    response = admin_client.post(
        f"/api/admin/punches/{punch_id}/incident-review",
        json={"note": "Comprovat amb el treballador"},
    )
    assert response.status_code == 200

    punch = database.list_punches()[0]
    assert punch["incident"] == 1
    assert "Primera acció del dia" in punch["note"]
    assert punch["incident_reviewed"] == 1
    assert punch["incident_review_note"] == "Comprovat amb el treballador"
    assert punch["incident_reviewed_by"] == "admin"


def test_incident_review_rejects_normal_punch(admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        cursor = db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (item["id"], "2026-10-02T08:00:00+02:00"),
        )
        punch_id = cursor.lastrowid

    response = admin_client.post(
        f"/api/admin/punches/{punch_id}/incident-review",
        json={"note": "No s'hauria de poder revisar"},
    )
    assert response.status_code == 400



def test_incident_can_be_reopened_with_full_history(admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        cursor = db.execute(
            """INSERT INTO punch
               (employee_id, timestamp, type, method, incident, note)
               VALUES (?, ?, 'sortida', 'pin', 1, 'Incidència de prova')""",
            (item["id"], "2026-10-02T08:00:00+02:00"),
        )
        punch_id = cursor.lastrowid

    response = admin_client.post(
        f"/api/admin/punches/{punch_id}/incident-review",
        json={"status": "reviewed", "note": "Primera revisió"},
    )
    assert response.status_code == 200
    assert database.list_punches()[0]["incident_reviewed"] == 1

    response = admin_client.post(
        f"/api/admin/punches/{punch_id}/incident-review",
        json={"status": "pending", "note": "Reoberta perquè la revisió era incorrecta"},
    )
    assert response.status_code == 200
    assert database.list_punches()[0]["incident_reviewed"] == 0

    response = admin_client.get(
        f"/api/admin/punches/{punch_id}/incident-reviews"
    )
    assert response.status_code == 200
    reviews = response.get_json()["reviews"]
    assert [review["status"] for review in reviews] == ["pending", "reviewed"]
    assert reviews[0]["note"] == "Reoberta perquè la revisió era incorrecta"
    assert reviews[1]["note"] == "Primera revisió"
    assert all(review["admin_username"] == "admin" for review in reviews)


def test_reopening_incident_requires_reason(admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        cursor = db.execute(
            """INSERT INTO punch
               (employee_id, timestamp, type, method, incident, note)
               VALUES (?, ?, 'sortida', 'pin', 1, 'Incidència de prova')""",
            (item["id"], "2026-10-02T08:00:00+02:00"),
        )
        punch_id = cursor.lastrowid

    response = admin_client.post(
        f"/api/admin/punches/{punch_id}/incident-review",
        json={"status": "pending", "note": ""},
    )
    assert response.status_code == 400



def test_admin_timeline_can_filter_terminal_events_only(admin_client, employee):
    item = employee()
    with database.get_connection() as db:
        db.execute(
            "INSERT INTO punch (employee_id, timestamp, type, method) VALUES (?, ?, 'entrada', 'pin')",
            (item["id"], "2026-10-02T08:00:00+02:00"),
        )
        db.execute(
            "INSERT INTO terminal_event (timestamp, type, detail) VALUES (?, 'startup', 'Terminal iniciat')",
            ("2026-10-02T07:55:00+02:00",),
        )

    response = admin_client.get("/api/admin/timeline?employee_id=terminal")
    assert response.status_code == 200
    items = response.get_json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "terminal_event"
    assert items[0]["detail"] == "Terminal iniciat"



def test_admin_usb_backup_requires_available_usb(admin_client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_usb_status",
        lambda: {"state": "absent", "device": None},
    )
    response = admin_client.post("/api/admin/usb/backup")
    assert response.status_code == 409
    assert response.get_json()["ok"] is False


def test_admin_usb_backup_creates_verified_archive(admin_client, monkeypatch, tmp_path):
    archive = tmp_path / "timeclockpi-backup-20261003-120000.zip"
    archive.write_bytes(b"test-backup")

    monkeypatch.setattr(
        app_module,
        "get_usb_status",
        lambda: {"state": "available", "device": "/dev/sda1"},
    )
    monkeypatch.setattr(app_module, "create_backup", lambda destination: archive)
    monkeypatch.setattr(
        app_module,
        "verify_backup",
        lambda path: {"created_at": "2026-10-03T12:00:00+02:00"},
    )

    response = admin_client.post("/api/admin/usb/backup")
    assert response.status_code == 201
    data = response.get_json()
    assert data["ok"] is True
    assert data["filename"] == archive.name
    assert data["created_at"] == "2026-10-03T12:00:00+02:00"


def test_apply_restore_does_not_write_to_root_owned_status_directory(
    admin_client, monkeypatch, tmp_path
):
    status_dir = tmp_path / "restore-status"
    status_dir.mkdir()
    status_file = status_dir / "result"
    status_file.write_text("success\n", encoding="utf-8")
    status_dir.chmod(0o555)
    restore_dir = tmp_path / "restore"
    (restore_dir / "data").mkdir(parents=True)
    (restore_dir / "data/timeclock.db").write_bytes(b"prepared database")

    token = "test-apply-restore-token"
    app_module.usb_authorization_tokens[token] = {
        "admin_user_id": 1,
        "operation": "apply-restore",
        "filename": "timeclockpi-backup-test.zip",
        "expires_at": app_module.time.monotonic() + 30,
    }
    monkeypatch.setattr(app_module, "USB_RESTORE_DIR", restore_dir)
    monkeypatch.setattr(app_module, "USB_RESTORE_STATUS", status_file)
    monkeypatch.setattr(
        app_module,
        "subprocess",
        type("SubprocessStub", (), {
            "run": staticmethod(lambda *args, **kwargs: None),
        }),
    )

    try:
        response = admin_client.post(
            "/api/admin/usb/apply-restore",
            json={"apply_token": token, "confirmation": "RESTAURAR"},
        )
    finally:
        status_dir.chmod(0o755)

    assert response.status_code == 202
    assert status_file.read_text(encoding="utf-8") == "success\n"


def test_supervisor_permissions_and_admin_user_management(client):
    import timeclock.database as database
    created = client.post("/api/admin/login", json={"username": "admin", "password": "test-administrator-password"})
    csrf = {"X-CSRF-Token": created.get_json()["csrf_token"]}
    response = client.post("/api/admin/users", headers=csrf, json={
        "username": "supervisor1", "password": "supervisor-password-123", "role": "supervisor",
    })
    assert response.status_code == 201
    supervisor_id = response.get_json()["id"]
    assert client.get("/api/admin/users").get_json()["users"][-1]["role"] == "supervisor"
    client.post("/api/admin/logout", headers=csrf)
    login = client.post("/api/admin/login", json={
        "username": "supervisor1", "password": "supervisor-password-123",
    })
    assert login.status_code == 200
    assert login.get_json()["role"] == "supervisor"
    csrf = {"X-CSRF-Token": login.get_json()["csrf_token"]}
    assert client.get("/api/admin/punches").status_code == 200
    assert client.get("/api/admin/timeline").status_code == 200
    assert client.get("/api/admin/export.csv").status_code == 200
    assert client.get("/api/admin/employees").status_code == 200
    assert client.get("/api/admin/settings").status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/usb/backups").status_code == 403
    assert client.get("/api/admin/logo").status_code == 403
    assert client.post("/api/admin/employees", headers=csrf, json={"name": "No", "pin": "1234"}).status_code == 403
    assert client.put("/api/admin/settings", headers=csrf, json={}).status_code == 403
    assert client.get("/admin").status_code == 200
    html = client.get("/admin").get_data(as_text=True)
    assert 'data-section="backups"' not in html
    assert 'data-section="users"' not in html
    assert 'data-section="punches"' in html
    assert 'name="user-role" content="supervisor"' in html
    assert client.patch("/api/admin/users/" + str(supervisor_id), headers=csrf, json={"active": False}).status_code == 403


def test_existing_admin_roles_and_last_admin_guard(client):
    import timeclock.database as database
    with database.get_connection() as db:
        row = db.execute("SELECT role FROM admin_user WHERE username = 'admin'").fetchone()
        assert row["role"] == "admin"
    database.create_admin_user("supervisor2", "supervisor-password-123", role="supervisor")
    import pytest
    with pytest.raises(ValueError, match="últim administrador"):
        database.set_admin_user_active("admin", False)
    with pytest.raises(ValueError, match="Rol no vàlid"):
        database.create_admin_user("bad-role", "supervisor-password-123", role="other")
