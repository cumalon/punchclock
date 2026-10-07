from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from werkzeug.security import generate_password_hash, check_password_hash
import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TIMECLOCKPI_DATA_DIR", PROJECT_ROOT / "data"))
DATABASE_PATH = DATA_DIR / "timeclock.db"
SESSION_KEY_PATH = DATA_DIR / "session_key"
LOCAL_TIMEZONE = ZoneInfo("Europe/Madrid")


def parse_local_timestamp(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=LOCAL_TIMEZONE)
    return timestamp


def local_timestamp_date(value):
    return parse_local_timestamp(value).astimezone(LOCAL_TIMEZONE).date().isoformat()


def utc_timestamp_sort_key(value):
    return parse_local_timestamp(value).astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    )


@contextmanager
def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.create_function("utc_timestamp_sort_key", 1, utc_timestamp_sort_key)

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database():
    database_exists = DATABASE_PATH.exists()

    with get_connection() as db:
        if database_exists:
            result = db.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise sqlite3.DatabaseError(
                    f"Database integrity check failed: {result}"
                )

        db.executescript("""
            CREATE TABLE IF NOT EXISTS employee (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS credential (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                value TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (employee_id) REFERENCES employee(id)
            );

            CREATE TABLE IF NOT EXISTS punch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('entrada', 'sortida')),
                method TEXT NOT NULL,
                incident INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (employee_id) REFERENCES employee(id)
            );

            CREATE TABLE IF NOT EXISTS terminal_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS setting (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                pin_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS punch_incident_review (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                punch_id INTEGER NOT NULL UNIQUE,
                admin_user_id INTEGER NOT NULL,
                reviewed_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (punch_id) REFERENCES punch(id),
                FOREIGN KEY (admin_user_id) REFERENCES admin_user(id)
            );

            CREATE TABLE IF NOT EXISTS punch_correction (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                punch_id INTEGER NOT NULL,
                admin_user_id INTEGER NOT NULL,
                corrected_at TEXT NOT NULL,
                old_employee_id INTEGER NOT NULL,
                new_employee_id INTEGER NOT NULL,
                old_timestamp TEXT NOT NULL,
                new_timestamp TEXT NOT NULL,
                old_type TEXT NOT NULL,
                new_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY (punch_id) REFERENCES punch(id),
                FOREIGN KEY (admin_user_id) REFERENCES admin_user(id),
                FOREIGN KEY (old_employee_id) REFERENCES employee(id),
                FOREIGN KEY (new_employee_id) REFERENCES employee(id)
            );
        """)
        admin_columns = {row["name"] for row in db.execute("PRAGMA table_info(admin_user)").fetchall()}
        if "pin_hash" not in admin_columns:
            db.execute("ALTER TABLE admin_user ADD COLUMN pin_hash TEXT")

        review_columns = {row["name"] for row in db.execute("PRAGMA table_info(punch_incident_review)").fetchall()}
        review_indexes = db.execute("PRAGMA index_list(punch_incident_review)").fetchall()
        has_unique_punch_index = any(
            row["unique"] and [
                column["name"]
                for column in db.execute(f"PRAGMA index_info({row['name']})").fetchall()
            ] == ["punch_id"]
            for row in review_indexes
        )
        if has_unique_punch_index:
            db.executescript("""
                ALTER TABLE punch_incident_review RENAME TO punch_incident_review_old;
                CREATE TABLE punch_incident_review (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    punch_id INTEGER NOT NULL,
                    admin_user_id INTEGER NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'reviewed'
                        CHECK (status IN ('reviewed', 'pending')),
                    note TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (punch_id) REFERENCES punch(id),
                    FOREIGN KEY (admin_user_id) REFERENCES admin_user(id)
                );
                INSERT INTO punch_incident_review
                    (id, punch_id, admin_user_id, reviewed_at, status, note)
                SELECT id, punch_id, admin_user_id, reviewed_at, 'reviewed', note
                FROM punch_incident_review_old;
                DROP TABLE punch_incident_review_old;
            """)
        elif "status" not in review_columns:
            db.execute(
                """ALTER TABLE punch_incident_review
                   ADD COLUMN status TEXT NOT NULL DEFAULT 'reviewed'
                   CHECK (status IN ('reviewed', 'pending'))"""
            )

        punch_columns = {row["name"] for row in db.execute("PRAGMA table_info(punch)").fetchall()}
        if "incident" not in punch_columns:
            db.execute("ALTER TABLE punch ADD COLUMN incident INTEGER NOT NULL DEFAULT 0")
        if "note" not in punch_columns:
            db.execute("ALTER TABLE punch ADD COLUMN note TEXT NOT NULL DEFAULT ''")



DEFAULT_SETTINGS = {
    "terminal_name": "TimeClockPi",
    "terminal_id": "TC01",
    "sound_volume": "20",
}


def get_settings():
    settings = DEFAULT_SETTINGS.copy()
    with get_connection() as db:
        rows = db.execute("SELECT key, value FROM setting").fetchall()

    for row in rows:
        settings[row["key"]] = row["value"]

    return {
        "terminal_name": settings["terminal_name"],
        "terminal_id": settings["terminal_id"],
        "sound_volume": int(settings["sound_volume"]),
    }


def update_settings(terminal_name, terminal_id, sound_volume):
    terminal_name = str(terminal_name).strip()
    terminal_id = str(terminal_id).strip()

    if not terminal_name:
        raise ValueError("El nom del terminal és obligatori")
    if not terminal_id:
        raise ValueError("L'identificador del terminal és obligatori")

    try:
        sound_volume = int(sound_volume)
    except (TypeError, ValueError):
        raise ValueError("El volum ha de ser entre 0 i 100")
    if not 0 <= sound_volume <= 100:
        raise ValueError("El volum ha de ser entre 0 i 100")

    values = {
        "terminal_name": terminal_name,
        "terminal_id": terminal_id,
        "sound_volume": str(sound_volume),
    }

    with get_connection() as db:
        for key, value in values.items():
            db.execute(
                """
                INSERT INTO setting (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    return get_settings()


def create_employee(name, pin):
    name = name.strip()
    pin = str(pin).strip()

    if not name:
        raise ValueError("El nom és obligatori")
    if not pin.isdigit() or not 4 <= len(pin) <= 8:
        raise ValueError("El PIN ha de tenir entre 4 i 8 dígits")
    if pin_in_use(pin):
        raise ValueError("Aquest PIN ja està assignat")

    pin_hash = generate_password_hash(pin)

    with get_connection() as db:
        cursor = db.execute(
            "INSERT INTO employee (name) VALUES (?)",
            (name,)
        )
        employee_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO credential (employee_id, method, value)
            VALUES (?, 'pin', ?)
            """,
            (employee_id, pin_hash)
        )

    return employee_id


def list_employees():
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT id, name, active
            FROM employee
            ORDER BY name COLLATE NOCASE, id
            """
        ).fetchall()

    return [dict(row) for row in rows]


def pin_in_use(pin, exclude_employee_id=None):
    with get_connection() as db:
        credentials = db.execute(
            """
            SELECT employee_id, value
            FROM credential
            WHERE method = 'pin' AND active = 1
            """
        ).fetchall()

    for credential in credentials:
        if exclude_employee_id is not None and credential["employee_id"] == exclude_employee_id:
            continue
        if check_password_hash(credential["value"], pin):
            return True

    return False


def update_employee(employee_id, name=None, pin=None, active=None):
    with get_connection() as db:
        employee = db.execute(
            "SELECT id, name, active FROM employee WHERE id = ?",
            (employee_id,)
        ).fetchone()

        if employee is None:
            return None

        new_name = employee["name"] if name is None else str(name).strip()
        if not new_name:
            raise ValueError("El nom és obligatori")

        new_active = employee["active"] if active is None else int(bool(active))

        db.execute(
            "UPDATE employee SET name = ?, active = ? WHERE id = ?",
            (new_name, new_active, employee_id)
        )

        if pin is not None and str(pin).strip():
            new_pin = str(pin).strip()
            if not new_pin.isdigit() or not 4 <= len(new_pin) <= 8:
                raise ValueError("El PIN ha de tenir entre 4 i 8 dígits")
            if pin_in_use(new_pin, exclude_employee_id=employee_id):
                raise ValueError("Aquest PIN ja està assignat")

            pin_hash = generate_password_hash(new_pin)
            credential = db.execute(
                """
                SELECT id
                FROM credential
                WHERE employee_id = ? AND method = 'pin'
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,)
            ).fetchone()

            if credential is None:
                db.execute(
                    """
                    INSERT INTO credential (employee_id, method, value, active)
                    VALUES (?, 'pin', ?, 1)
                    """,
                    (employee_id, pin_hash)
                )
            else:
                db.execute(
                    "UPDATE credential SET value = ?, active = 1 WHERE id = ?",
                    (pin_hash, credential["id"])
                )

    return {"id": employee_id, "name": new_name, "active": new_active}


def find_employee_by_pin(pin):
    with get_connection() as db:
        credentials = db.execute(
            """
            SELECT
                employee.id,
                employee.name,
                credential.value
            FROM credential
            JOIN employee ON employee.id = credential.employee_id
            WHERE credential.method = 'pin'
              AND credential.active = 1
              AND employee.active = 1
            """
        ).fetchall()

    for credential in credentials:
        if check_password_hash(credential["value"], pin):
            return {
                "id": credential["id"],
                "name": credential["name"]
            }

    return None



def list_punches(employee_id=None, date_from=None, date_to=None):
    query = """
        SELECT
            punch.id,
            punch.timestamp,
            punch.type,
            punch.method,
            punch.incident,
            punch.note,
            employee.id AS employee_id,
            employee.name AS employee_name,
            CASE WHEN incident_state.status = 'reviewed' THEN 1 ELSE 0 END AS incident_reviewed,
            incident_state.reviewed_at AS incident_reviewed_at,
            incident_state.note AS incident_review_note,
            admin_user.username AS incident_reviewed_by
        FROM punch
        JOIN employee ON employee.id = punch.employee_id
        LEFT JOIN punch_incident_review AS incident_state
          ON incident_state.id = (
              SELECT review.id
              FROM punch_incident_review AS review
              WHERE review.punch_id = punch.id
              ORDER BY review.id DESC
              LIMIT 1
          )
        LEFT JOIN admin_user ON admin_user.id = incident_state.admin_user_id
        WHERE 1 = 1
    """
    params = []

    if employee_id:
        query += " AND employee.id = ?"
        params.append(employee_id)
    if date_from:
        query += " AND substr(punch.timestamp, 1, 10) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND substr(punch.timestamp, 1, 10) <= ?"
        params.append(date_to)

    query += " ORDER BY utc_timestamp_sort_key(punch.timestamp) DESC, punch.id DESC"

    with get_connection() as db:
        rows = db.execute(query, params).fetchall()

    return [dict(row) for row in rows]

def create_punch(employee_id, punch_type, method, confirm_incident=False):
    if punch_type not in ("entrada", "sortida"):
        raise ValueError("Tipus de fitxatge no vàlid")

    now = datetime.now(ZoneInfo("Europe/Madrid"))
    timestamp = now.isoformat(timespec="seconds")
    today = now.date().isoformat()

    with get_connection() as db:
        employee = db.execute(
            "SELECT id, name FROM employee WHERE id = ? AND active = 1",
            (employee_id,)
        ).fetchone()
        if employee is None:
            return None

        last_punch = db.execute(
            """SELECT type, timestamp FROM punch
               WHERE employee_id = ?
               ORDER BY utc_timestamp_sort_key(timestamp) DESC, id DESC LIMIT 1""",
            (employee_id,)
        ).fetchone()

        last_punch_today = (
            last_punch is not None
            and local_timestamp_date(last_punch["timestamp"]) == today
        )
        previous_day_open_entry = (
            last_punch is not None
            and not last_punch_today
            and last_punch["type"] == "entrada"
        )

        unexpected = (
            (last_punch is None and punch_type == "sortida")
            or (last_punch is not None and last_punch["type"] == punch_type)
        )
        note = ""
        if unexpected:
            if last_punch is None:
                note = "Primera acció del dia: sortida confirmada pel treballador"
            elif previous_day_open_entry and punch_type == "entrada":
                note = "Nova entrada amb una entrada anterior sense sortida confirmada pel treballador"
            elif punch_type == "entrada":
                note = "Entrada consecutiva confirmada pel treballador"
            else:
                note = "Sortida consecutiva confirmada pel treballador"

            if not confirm_incident:
                return {"ok": False, "confirmation_required": True, "error": note}

        cursor = db.execute(
            """INSERT INTO punch
               (employee_id, timestamp, type, method, incident, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (employee_id, timestamp, punch_type, method, int(unexpected), note)
        )
        punch_id = cursor.lastrowid

    return {
        "ok": True,
        "punch": {
            "id": punch_id, "employee_id": employee_id,
            "employee_name": employee["name"], "timestamp": timestamp,
            "type": punch_type, "method": method,
            "incident": int(unexpected), "note": note
        }
    }


def create_terminal_event(event_type, detail=""):
    timestamp = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
    with get_connection() as db:
        cursor = db.execute(
            "INSERT INTO terminal_event (timestamp, type, detail) VALUES (?, ?, ?)",
            (timestamp, event_type, detail)
        )
    return {"id": cursor.lastrowid, "timestamp": timestamp, "type": event_type, "detail": detail}


def list_terminal_events(date_from=None, date_to=None):
    query = "SELECT id, timestamp, type, detail FROM terminal_event WHERE 1 = 1"
    params = []
    if date_from:
        query += " AND substr(timestamp, 1, 10) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND substr(timestamp, 1, 10) <= ?"
        params.append(date_to)
    query += " ORDER BY timestamp DESC, id DESC"
    with get_connection() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def create_admin_user(username, password):
    username = str(username).strip()
    password = str(password)
    if not username:
        raise ValueError("El nom d'usuari és obligatori")
    if len(password) < 12:
        raise ValueError("La contrasenya ha de tenir com a mínim 12 caràcters")
    timestamp = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
    password_hash = generate_password_hash(password)
    with get_connection() as db:
        existing = db.execute("SELECT id FROM admin_user WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if existing is not None:
            raise ValueError("Aquest usuari administrador ja existeix")
        cursor = db.execute(
            "INSERT INTO admin_user (username, password_hash, active, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
            (username, password_hash, timestamp, timestamp),
        )
    return cursor.lastrowid


def authenticate_admin(username, password):
    username = str(username).strip()
    password = str(password)
    if not username or not password:
        return None
    with get_connection() as db:
        row = db.execute(
            "SELECT id, username, password_hash, updated_at FROM admin_user WHERE username = ? COLLATE NOCASE AND active = 1",
            (username,),
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return {"id": row["id"], "username": row["username"], "updated_at": row["updated_at"]}


def get_active_admin_session_version(admin_user_id):
    with get_connection() as db:
        row = db.execute(
            "SELECT updated_at FROM admin_user WHERE id = ? AND active = 1",
            (admin_user_id,),
        ).fetchone()
    return None if row is None else row["updated_at"]


def set_admin_pin(admin_user_id, pin):
    pin = str(pin)
    if len(pin) != 6 or not pin.isdigit():
        raise ValueError("El PIN d'administrador ha de tenir exactament 6 dígits")

    with get_connection() as db:
        row = db.execute(
            "SELECT id FROM admin_user WHERE id = ? AND active = 1",
            (admin_user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Administrador no trobat o inactiu")

        active_pins = db.execute(
            "SELECT id, pin_hash FROM admin_user WHERE active = 1 AND id != ? AND pin_hash IS NOT NULL",
            (admin_user_id,),
        ).fetchall()
        if any(check_password_hash(other["pin_hash"], pin) for other in active_pins):
            raise ValueError("Aquest PIN ja està assignat a un altre administrador")

        db.execute(
            "UPDATE admin_user SET pin_hash = ?, updated_at = ? WHERE id = ?",
            (
                generate_password_hash(pin),
                datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds"),
                admin_user_id,
            ),
        )


def authenticate_admin_pin(pin):
    pin = str(pin)
    if len(pin) != 6 or not pin.isdigit():
        return None

    with get_connection() as db:
        rows = db.execute(
            "SELECT id, username, pin_hash FROM admin_user WHERE active = 1 AND pin_hash IS NOT NULL"
        ).fetchall()

    matches = [
        row for row in rows
        if check_password_hash(row["pin_hash"], pin)
    ]
    if len(matches) != 1:
        return None

    row = matches[0]
    return {"id": row["id"], "username": row["username"]}




def change_admin_password(admin_user_id, current_password, new_password):
    current_password = str(current_password)
    new_password = str(new_password)
    if len(new_password) < 12:
        raise ValueError("La nova contrasenya ha de tenir com a mínim 12 caràcters")

    with get_connection() as db:
        row = db.execute(
            "SELECT password_hash FROM admin_user WHERE id = ? AND active = 1",
            (admin_user_id,),
        ).fetchone()
        if row is None or not check_password_hash(row["password_hash"], current_password):
            raise ValueError("La contrasenya actual no és correcta")

        timestamp = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
        db.execute(
            "UPDATE admin_user SET password_hash = ?, updated_at = ? WHERE id = ?",
            (generate_password_hash(new_password), timestamp, admin_user_id),
        )


def reset_admin_password(username, new_password):
    username = str(username).strip()
    new_password = str(new_password)
    if not username:
        raise ValueError("L'usuari és obligatori")
    if len(new_password) < 12:
        raise ValueError("La nova contrasenya ha de tenir com a mínim 12 caràcters")

    with get_connection() as db:
        cursor = db.execute(
            """UPDATE admin_user
               SET password_hash = ?, updated_at = ?
               WHERE username = ? COLLATE NOCASE""",
            (
                generate_password_hash(new_password),
                datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds"),
                username,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Administrador no trobat")


def list_admin_users():
    with get_connection() as db:
        rows = db.execute(
            "SELECT id, username, active, created_at, updated_at FROM admin_user ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def set_admin_user_active(username, active):
    username = str(username).strip()
    if not username:
        raise ValueError("L'usuari és obligatori")

    with get_connection() as db:
        row = db.execute(
            "SELECT id, active FROM admin_user WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if row is None:
            raise ValueError("Administrador no trobat")

        if not active and row["active"]:
            count = db.execute(
                "SELECT COUNT(*) AS count FROM admin_user WHERE active = 1"
            ).fetchone()["count"]
            if count <= 1:
                raise ValueError("No es pot desactivar l'últim administrador actiu")

        db.execute(
            "UPDATE admin_user SET active = ?, updated_at = ? WHERE id = ?",
            (
                1 if active else 0,
                datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds"),
                row["id"],
            ),
        )

def correct_punch(punch_id, admin_user_id, employee_id, timestamp, punch_type, reason):
    reason = str(reason).strip()
    timestamp = str(timestamp).strip()
    if punch_type not in ("entrada", "sortida"):
        raise ValueError("Tipus de fitxatge no vàlid")
    if not reason:
        raise ValueError("Cal indicar el motiu de la correcció")
    try:
        parsed_timestamp = parse_local_timestamp(timestamp)
    except ValueError:
        raise ValueError("Data i hora no vàlides")
    timestamp = parsed_timestamp.astimezone(LOCAL_TIMEZONE).isoformat()

    corrected_at = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
    with get_connection() as db:
        punch = db.execute(
            "SELECT id, employee_id, timestamp, type FROM punch WHERE id = ?",
            (punch_id,)
        ).fetchone()
        if punch is None:
            return None

        employee = db.execute(
            "SELECT id FROM employee WHERE id = ?",
            (employee_id,)
        ).fetchone()
        if employee is None:
            raise ValueError("Treballador no trobat")

        db.execute(
            """INSERT INTO punch_correction
               (punch_id, admin_user_id, corrected_at,
                old_employee_id, new_employee_id,
                old_timestamp, new_timestamp, old_type, new_type, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                punch_id, admin_user_id, corrected_at,
                punch["employee_id"], employee_id,
                punch["timestamp"], timestamp, punch["type"], punch_type, reason
            )
        )
        db.execute(
            "UPDATE punch SET employee_id = ?, timestamp = ?, type = ? WHERE id = ?",
            (employee_id, timestamp, punch_type, punch_id)
        )

    return {
        "id": punch_id,
        "employee_id": employee_id,
        "timestamp": timestamp,
        "type": punch_type,
    }


def list_punch_corrections(punch_id):
    with get_connection() as db:
        rows = db.execute(
            """SELECT punch_correction.*, admin_user.username AS admin_username
               FROM punch_correction
               JOIN admin_user ON admin_user.id = punch_correction.admin_user_id
               WHERE punch_correction.punch_id = ?
               ORDER BY utc_timestamp_sort_key(punch_correction.corrected_at) DESC,
                        punch_correction.id DESC""",
            (punch_id,)
        ).fetchall()
    return [dict(row) for row in rows]



def set_punch_incident_status(punch_id, admin_user_id, status, note=""):
    note = str(note).strip()
    if status not in ("reviewed", "pending"):
        raise ValueError("Estat d'incidència no vàlid")
    if status == "pending" and not note:
        raise ValueError("Cal indicar el motiu per reobrir la incidència")

    reviewed_at = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
    with get_connection() as db:
        punch = db.execute(
            "SELECT id, incident FROM punch WHERE id = ?",
            (punch_id,)
        ).fetchone()
        if punch is None:
            return None
        if not punch["incident"]:
            raise ValueError("Aquest fitxatge no té cap incidència")

        db.execute(
            """INSERT INTO punch_incident_review
               (punch_id, admin_user_id, reviewed_at, status, note)
               VALUES (?, ?, ?, ?, ?)""",
            (punch_id, admin_user_id, reviewed_at, status, note)
        )

    return {
        "punch_id": punch_id,
        "reviewed_at": reviewed_at,
        "status": status,
        "note": note,
    }


def list_punch_incident_reviews(punch_id):
    with get_connection() as db:
        rows = db.execute(
            """SELECT punch_incident_review.*, admin_user.username AS admin_username
               FROM punch_incident_review
               JOIN admin_user ON admin_user.id = punch_incident_review.admin_user_id
               WHERE punch_incident_review.punch_id = ?
               ORDER BY punch_incident_review.id DESC""",
            (punch_id,)
        ).fetchall()
    return [dict(row) for row in rows]
