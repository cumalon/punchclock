import sqlite3

import pytest

import timeclock.database as database


def test_employee_lifecycle(client, employee):
    first = employee("Beta", "1234")
    second = employee("Alfa", "5678")

    employees = database.list_employees()
    assert [item["name"] for item in employees] == ["Alfa", "Beta"]
    assert database.find_employee_by_pin("1234")["id"] == first["id"]
    assert database.find_employee_by_pin("9999") is None

    updated = database.update_employee(first["id"], name="Beta Nova", pin="4321", active=False)
    assert updated == {"id": first["id"], "name": "Beta Nova", "active": 0}
    assert database.find_employee_by_pin("1234") is None
    assert database.find_employee_by_pin("4321") is None

    database.update_employee(first["id"], active=True)
    assert database.find_employee_by_pin("4321")["name"] == "Beta Nova"
    assert second["id"] != first["id"]


@pytest.mark.parametrize("name,pin,error", [
    ("", "1234", "El nom és obligatori"),
    ("Treballador", "12", "El PIN ha de tenir entre 4 i 8 dígits"),
    ("Treballador", "abcd", "El PIN ha de tenir entre 4 i 8 dígits"),
    ("Treballador", "123456789", "El PIN ha de tenir entre 4 i 8 dígits"),
])
def test_create_employee_validation(client, name, pin, error):
    with pytest.raises(ValueError, match=error):
        database.create_employee(name, pin)


def test_duplicate_pin_and_update_validation(client, employee):
    first = employee("Primer", "1234")
    second = employee("Segon", "5678")

    with pytest.raises(ValueError, match="Aquest PIN ja està assignat"):
        database.create_employee("Duplicat", "1234")

    with pytest.raises(ValueError, match="El nom és obligatori"):
        database.update_employee(first["id"], name=" ")

    with pytest.raises(ValueError, match="El PIN ha de tenir entre 4 i 8 dígits"):
        database.update_employee(first["id"], pin="xx")

    with pytest.raises(ValueError, match="Aquest PIN ja està assignat"):
        database.update_employee(second["id"], pin="1234")

    assert database.update_employee(99999, name="Ningú") is None


def test_update_creates_missing_pin_credential(client, employee):
    item = employee()
    with database.get_connection() as db:
        db.execute("DELETE FROM credential WHERE employee_id = ?", (item["id"],))

    database.update_employee(item["id"], pin="8765")
    assert database.find_employee_by_pin("8765")["id"] == item["id"]


def test_punch_sequence_and_inactive_employee(client, employee):
    item = employee()

    first_exit = database.create_punch(item["id"], "sortida", "pin")
    assert first_exit["ok"] is False
    assert first_exit["confirmation_required"] is True

    confirmed_exit = database.create_punch(item["id"], "sortida", "pin", confirm_incident=True)
    assert confirmed_exit["ok"] is True
    assert confirmed_exit["punch"]["incident"] == 1

    entry = database.create_punch(item["id"], "entrada", "pin")
    assert entry["ok"] is True
    assert entry["punch"]["method"] == "pin"

    duplicate_entry = database.create_punch(item["id"], "entrada", "pin")
    assert duplicate_entry["confirmation_required"] is True

    exit_punch = database.create_punch(item["id"], "sortida", "pin")
    assert exit_punch["ok"] is True

    duplicate_exit = database.create_punch(item["id"], "sortida", "pin")
    assert duplicate_exit["confirmation_required"] is True

    database.update_employee(item["id"], active=False)
    assert database.create_punch(item["id"], "entrada", "pin") is None

    with pytest.raises(ValueError, match="Tipus de fitxatge no vàlid"):
        database.create_punch(item["id"], "pausa", "pin")



def test_punch_sequence_across_day_boundary(client, employee):
    item = employee()

    with database.get_connection() as db:
        db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'entrada', 'pin')""",
            (item["id"], "2026-10-05T22:00:00+02:00"),
        )

    # A night shift may legitimately end after midnight.
    overnight_exit = database.create_punch(item["id"], "sortida", "pin")
    assert overnight_exit["ok"] is True
    assert overnight_exit["punch"]["incident"] == 0

    with database.get_connection() as db:
        db.execute("DELETE FROM punch WHERE employee_id = ?", (item["id"],))
        db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'entrada', 'pin')""",
            (item["id"], "2026-10-05T08:00:00+02:00"),
        )

    missing_exit = database.create_punch(item["id"], "entrada", "pin")
    assert missing_exit["ok"] is False
    assert missing_exit["confirmation_required"] is True
    assert "entrada anterior sense sortida" in missing_exit["error"]

    confirmed_entry = database.create_punch(
        item["id"], "entrada", "pin", confirm_incident=True
    )
    assert confirmed_entry["ok"] is True
    assert confirmed_entry["punch"]["incident"] == 1
    assert "entrada anterior sense sortida" in confirmed_entry["punch"]["note"]

    with database.get_connection() as db:
        db.execute("DELETE FROM punch WHERE employee_id = ?", (item["id"],))
        db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'sortida', 'pin')""",
            (item["id"], "2026-10-05T17:00:00+02:00"),
        )

    next_day_exit = database.create_punch(item["id"], "sortida", "pin")
    assert next_day_exit["ok"] is False
    assert next_day_exit["confirmation_required"] is True
    assert "Sortida consecutiva" in next_day_exit["error"]


def test_create_punch_uses_actual_order_during_dst_fall_back(client, employee):
    item = employee()

    with database.get_connection() as db:
        db.executemany(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, ?, 'pin')""",
            [
                (item["id"], "2026-10-25T02:50:00+02:00", "entrada"),
                (item["id"], "2026-10-25T02:10:00+01:00", "sortida"),
            ],
        )

    result = database.create_punch(item["id"], "entrada", "pin")

    assert result["ok"] is True
    assert result["punch"]["incident"] == 0


def test_list_punches_uses_actual_order_during_dst_fall_back(client, employee):
    item = employee()

    with database.get_connection() as db:
        db.executemany(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, ?, 'pin')""",
            [
                (item["id"], "2026-10-25T02:50:00+02:00", "entrada"),
                (item["id"], "2026-10-25T02:10:00+01:00", "sortida"),
            ],
        )

    punches = database.list_punches(employee_id=item["id"])

    assert [punch["type"] for punch in punches] == ["sortida", "entrada"]


def test_create_punch_interprets_legacy_naive_timestamp_as_local(client, employee):
    item = employee()

    with database.get_connection() as db:
        db.executemany(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, ?, 'pin')""",
            [
                (item["id"], "2026-10-25T02:20:00+02:00", "entrada"),
                (item["id"], "2026-10-25T02:10:00", "sortida"),
            ],
        )

    result = database.create_punch(item["id"], "sortida", "pin")

    assert result["ok"] is True
    assert result["punch"]["incident"] == 0


def test_corrected_punch_timestamp_controls_dst_chronology(client, employee):
    item = employee()
    admin = database.authenticate_admin("admin", "test-administrator-password")

    with database.get_connection() as db:
        db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'entrada', 'pin')""",
            (item["id"], "2026-10-25T02:50:00+02:00"),
        )
        cursor = db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'sortida', 'pin')""",
            (item["id"], "2026-10-25T02:10:00+01:00"),
        )
        corrected_punch_id = cursor.lastrowid

    database.correct_punch(
        corrected_punch_id,
        admin["id"],
        item["id"],
        "2026-10-25T02:20:00+01:00",
        "sortida",
        "Correcció de prova",
    )

    result = database.create_punch(item["id"], "entrada", "pin")
    punches = database.list_punches(employee_id=item["id"])

    assert result["ok"] is True
    assert result["punch"]["incident"] == 0
    assert punches[0]["timestamp"] == "2026-10-25T02:20:00+01:00"


def test_naive_corrected_timestamp_is_stored_with_local_offset(client, employee):
    item = employee()
    admin = database.authenticate_admin("admin", "test-administrator-password")
    with database.get_connection() as db:
        cursor = db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'entrada', 'pin')""",
            (item["id"], "2026-06-01T08:00:00+02:00"),
        )

    corrected = database.correct_punch(
        cursor.lastrowid,
        admin["id"],
        item["id"],
        "2026-06-01T08:15:00",
        "entrada",
        "Correcció de prova",
    )

    assert corrected["timestamp"] == "2026-06-01T08:15:00+02:00"


def test_corrected_timestamp_is_normalized_to_local_timezone(client, employee):
    item = employee()
    admin = database.authenticate_admin("admin", "test-administrator-password")
    with database.get_connection() as db:
        cursor = db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'entrada', 'pin')""",
            (item["id"], "2026-06-01T08:00:00+02:00"),
        )

    corrected = database.correct_punch(
        cursor.lastrowid,
        admin["id"],
        item["id"],
        "2026-06-01T06:15:00-04:00",
        "entrada",
        "Correcció de prova",
    )

    assert corrected["timestamp"] == "2026-06-01T12:15:00+02:00"


def test_correction_history_orders_by_actual_time_across_dst_fall_back(
    client, employee
):
    item = employee()
    admin = database.authenticate_admin("admin", "test-administrator-password")
    with database.get_connection() as db:
        cursor = db.execute(
            """INSERT INTO punch (employee_id, timestamp, type, method)
               VALUES (?, ?, 'entrada', 'pin')""",
            (item["id"], "2026-10-25T02:50:00+02:00"),
        )
        punch_id = cursor.lastrowid
        db.executemany(
            """INSERT INTO punch_correction
               (punch_id, admin_user_id, corrected_at,
                old_employee_id, new_employee_id, old_timestamp,
                new_timestamp, old_type, new_type, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'entrada', 'entrada', 'Prova')""",
            [
                (
                    punch_id, admin["id"], "2026-10-25T02:50:00+02:00",
                    item["id"], item["id"], "2026-10-25T08:00:00+02:00",
                    "2026-10-25T08:01:00+02:00",
                ),
                (
                    punch_id, admin["id"], "2026-10-25T02:10:00+01:00",
                    item["id"], item["id"], "2026-10-25T08:01:00+02:00",
                    "2026-10-25T08:02:00+02:00",
                ),
            ],
        )

    corrections = database.list_punch_corrections(punch_id)

    assert [correction["corrected_at"] for correction in corrections] == [
        "2026-10-25T02:10:00+01:00",
        "2026-10-25T02:50:00+02:00",
    ]


def test_list_punches_filters(client, employee):
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

    assert len(database.list_punches()) == 3
    assert len(database.list_punches(employee_id=first["id"])) == 2
    assert len(database.list_punches(date_from="2026-10-01")) == 1
    assert len(database.list_punches(date_to="2026-09-30")) == 2
    assert len(database.list_punches(first["id"], "2026-09-30", "2026-09-30")) == 2


def test_settings_defaults_update_and_validation(client):
    assert database.get_settings() == {
        "terminal_name": "TimeClockPi",
        "terminal_id": "TC01",
        "sound_volume": 20,
    }

    updated = database.update_settings("Recepció", "TC02", 35)
    assert updated == {
        "terminal_name": "Recepció",
        "terminal_id": "TC02",
        "sound_volume": 35,
    }
    assert database.get_settings() == updated

    with pytest.raises(ValueError, match="El nom del terminal és obligatori"):
        database.update_settings("", "TC02", 20)

    with pytest.raises(ValueError, match="L'identificador del terminal és obligatori"):
        database.update_settings("Recepció", "", 20)


def test_terminal_events(client):
    event = database.create_terminal_event("startup", "Terminal iniciat")
    assert event["type"] == "startup"
    events = database.list_terminal_events()
    assert len(events) == 1
    assert events[0]["detail"] == "Terminal iniciat"


def test_admin_password_change_and_local_reset(client):
    admin = database.authenticate_admin("admin", "test-administrator-password")
    assert admin is not None

    database.change_admin_password(
        admin["id"],
        "test-administrator-password",
        "new-administrator-password",
    )
    assert database.authenticate_admin("admin", "test-administrator-password") is None
    assert database.authenticate_admin("admin", "new-administrator-password") is not None

    with pytest.raises(ValueError, match="contrasenya actual"):
        database.change_admin_password(
            admin["id"],
            "incorrect-password",
            "another-administrator-password",
        )

    database.reset_admin_password("admin", "reset-administrator-password")
    assert database.authenticate_admin("admin", "new-administrator-password") is None
    assert database.authenticate_admin("admin", "reset-administrator-password") is not None


def test_admin_password_management_requires_long_password(client):
    admin = database.authenticate_admin("admin", "test-administrator-password")
    with pytest.raises(ValueError, match="12 caràcters"):
        database.change_admin_password(admin["id"], "test-administrator-password", "curta")
    with pytest.raises(ValueError, match="12 caràcters"):
        database.reset_admin_password("admin", "curta")


def test_local_admin_account_state_management(client):
    database.create_admin_user("segon", "second-administrator-password")
    users = database.list_admin_users()
    assert [user["username"] for user in users] == ["admin", "segon"]

    database.set_admin_user_active("segon", False)
    assert database.authenticate_admin("segon", "second-administrator-password") is None

    database.set_admin_user_active("segon", True)
    assert database.authenticate_admin("segon", "second-administrator-password") is not None

    database.set_admin_user_active("segon", False)
    with pytest.raises(ValueError, match="últim administrador actiu"):
        database.set_admin_user_active("admin", False)



def test_init_database_rejects_corrupt_existing_database(tmp_path, monkeypatch):
    test_database = tmp_path / "corrupt.db"
    test_database.write_bytes(b"CORRUPTED-DATABASE")
    original_contents = test_database.read_bytes()

    monkeypatch.setattr(database, "DATABASE_PATH", test_database)

    with pytest.raises(sqlite3.DatabaseError):
        database.init_database()

    assert test_database.read_bytes() == original_contents


def test_data_dir_environment_selects_persistent_paths(tmp_path):
    import os
    import subprocess
    import sys

    data_dir = tmp_path / "persistent-data"
    env = os.environ.copy()
    env["TIMECLOCKPI_DATA_DIR"] = str(data_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from timeclock.database import DATABASE_PATH, SESSION_KEY_PATH; "
            "print(DATABASE_PATH); print(SESSION_KEY_PATH)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.splitlines() == [
        str(data_dir / "timeclock.db"),
        str(data_dir / "session_key"),
    ]
