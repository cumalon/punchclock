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

            CREATE TABLE IF NOT EXISTS leave_type (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                sort_order INTEGER NOT NULL DEFAULT 0,
                guaranteed_daily_minutes INTEGER NOT NULL DEFAULT 0
                    CHECK (guaranteed_daily_minutes >= 0),
                approval_policy TEXT NOT NULL DEFAULT 'manual'
                    CHECK (approval_policy IN ('manual', 'automatic', 'threshold')),
                max_minutes INTEGER CHECK (max_minutes IS NULL OR max_minutes > 0),
                auto_approve_minutes INTEGER CHECK (
                    auto_approve_minutes IS NULL OR auto_approve_minutes > 0
                ),
                CHECK (
                    (approval_policy = 'threshold' AND auto_approve_minutes IS NOT NULL)
                    OR (approval_policy != 'threshold' AND auto_approve_minutes IS NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS employee_leave (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employee(id),
                leave_type_id INTEGER NOT NULL REFERENCES leave_type(id) ON DELETE RESTRICT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected'))
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
                role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'supervisor')),
                must_change_password INTEGER NOT NULL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS employee_leave_decision_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                leave_id INTEGER NOT NULL REFERENCES employee_leave(id),
                admin_user_id INTEGER NOT NULL REFERENCES admin_user(id),
                changed_at TEXT NOT NULL,
                previous_status TEXT NOT NULL
                    CHECK (previous_status IN ('pending', 'approved', 'rejected')),
                new_status TEXT NOT NULL
                    CHECK (new_status IN ('approved', 'rejected')),
                reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
                CHECK (previous_status != new_status)
            );
            CREATE TABLE IF NOT EXISTS daily_leave_decision (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employee(id),
                leave_type_id INTEGER NOT NULL REFERENCES leave_type(id),
                local_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                decision_source TEXT NOT NULL DEFAULT 'system'
                    CHECK (decision_source IN ('system', 'automatic', 'supervisor')),
                total_seconds INTEGER NOT NULL DEFAULT 0 CHECK (total_seconds >= 0),
                approval_policy TEXT NOT NULL
                    CHECK (approval_policy IN ('manual', 'automatic', 'threshold')),
                auto_approve_minutes INTEGER,
                guaranteed_daily_minutes INTEGER NOT NULL
                    CHECK (guaranteed_daily_minutes >= 0),
                updated_at TEXT NOT NULL,
                UNIQUE (employee_id, leave_type_id, local_date)
            );
            CREATE TABLE IF NOT EXISTS daily_leave_decision_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL REFERENCES daily_leave_decision(id),
                admin_user_id INTEGER REFERENCES admin_user(id),
                changed_at TEXT NOT NULL,
                action TEXT NOT NULL CHECK (
                    action IN ('created', 'total_changed', 'invalidated',
                               'automatic_approval', 'supervisor_decision')
                ),
                previous_status TEXT CHECK (
                    previous_status IS NULL
                    OR previous_status IN ('pending', 'approved', 'rejected')
                ),
                new_status TEXT NOT NULL
                    CHECK (new_status IN ('pending', 'approved', 'rejected')),
                total_seconds INTEGER NOT NULL CHECK (total_seconds >= 0),
                approval_policy TEXT NOT NULL
                    CHECK (approval_policy IN ('manual', 'automatic', 'threshold')),
                auto_approve_minutes INTEGER,
                guaranteed_daily_minutes INTEGER NOT NULL
                    CHECK (guaranteed_daily_minutes >= 0),
                reason TEXT NOT NULL DEFAULT '',
                CHECK (
                    (action = 'supervisor_decision' AND admin_user_id IS NOT NULL
                        AND length(trim(reason)) > 0)
                    OR (action != 'supervisor_decision' AND admin_user_id IS NULL)
                )
            );
        """)
        # Migration compatible amb els permisos creats abans del sprint 3.
        leave_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(employee_leave)").fetchall()
        }
        leave_migrations = {
            "record_state": "TEXT NOT NULL DEFAULT 'open' CHECK (record_state IN ('open', 'finished', 'needs_regularization'))",
            "requires_supervisor": "INTEGER NOT NULL DEFAULT 0 CHECK (requires_supervisor IN (0, 1))",
            "start_punch_id": "INTEGER REFERENCES punch(id)",
            "end_punch_id": "INTEGER REFERENCES punch(id)",
            "regularized_at": "TEXT",
            "regularized_by": "INTEGER REFERENCES admin_user(id)",
            "expected_started_at": "TEXT",
            "expected_ended_at": "TEXT",
            "regularization_reason": "TEXT",
            "regularization_kind": "TEXT CHECK (regularization_kind IN ('return', 'late_arrival', 'early_departure'))",
            "daily_decision_id": "INTEGER REFERENCES daily_leave_decision(id)",
        }
        for column, definition in leave_migrations.items():
            if column not in leave_columns:
                db.execute(f"ALTER TABLE employee_leave ADD COLUMN {column} {definition}")
        # Els permisos antics amb hora final ja tenen el registre complet.
        db.execute("""
            UPDATE employee_leave SET record_state = 'finished'
            WHERE ended_at IS NOT NULL AND record_state = 'open'
        """)
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_employee_leave_one_open
            ON employee_leave(employee_id) WHERE record_state = 'open'
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_leave_decision_pending
            ON daily_leave_decision(status, local_date)
        """)

        admin_columns = {row["name"] for row in db.execute("PRAGMA table_info(admin_user)").fetchall()}
        if "pin_hash" not in admin_columns:
            db.execute("ALTER TABLE admin_user ADD COLUMN pin_hash TEXT")

        admin_columns = {row["name"] for row in db.execute("PRAGMA table_info(admin_user)").fetchall()}
        if "role" not in admin_columns:
            db.execute("ALTER TABLE admin_user ADD COLUMN role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'supervisor'))")

        if "must_change_password" not in admin_columns:
            db.execute("ALTER TABLE admin_user ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

        leave_type_columns = {row["name"] for row in db.execute("PRAGMA table_info(leave_type)").fetchall()}
        if "sort_order" not in leave_type_columns:
            db.execute("ALTER TABLE leave_type ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE leave_type SET sort_order = id")
        if "guaranteed_daily_minutes" not in leave_type_columns:
            db.execute("""
                ALTER TABLE leave_type
                ADD COLUMN guaranteed_daily_minutes INTEGER NOT NULL DEFAULT 0
                    CHECK (guaranteed_daily_minutes >= 0)
            """)

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


def create_admin_user(username, password, role='admin'):
    username = str(username).strip()
    password = str(password)
    if not username:
        raise ValueError("El nom d'usuari és obligatori")
    if role not in ('admin', 'supervisor'):
        raise ValueError('Rol no vàlid')
    if len(password) < 12:
        raise ValueError("La contrasenya ha de tenir com a mínim 12 caràcters")
    timestamp = datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds")
    password_hash = generate_password_hash(password)
    with get_connection() as db:
        existing = db.execute("SELECT id FROM admin_user WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if existing is not None:
            raise ValueError("Aquest usuari ja existeix")
        cursor = db.execute(
            "INSERT INTO admin_user (username, password_hash, active, role, created_at, updated_at) VALUES (?, ?, 1, ?, ?, ?)",
            (username, password_hash, role, timestamp, timestamp),
        )
    return cursor.lastrowid


def authenticate_admin(username, password):
    username = str(username).strip()
    password = str(password)
    if not username or not password:
        return None
    with get_connection() as db:
        row = db.execute(
            "SELECT id, username, password_hash, role, must_change_password, updated_at FROM admin_user WHERE username = ? COLLATE NOCASE AND active = 1",
            (username,),
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"], "must_change_password": bool(row["must_change_password"]), "updated_at": row["updated_at"]}


def get_active_admin_identity(admin_user_id):
    with get_connection() as db:
        row = db.execute(
            "SELECT id, role, must_change_password, updated_at FROM admin_user WHERE id = ? AND active = 1",
            (admin_user_id,),
        ).fetchone()
    return None if row is None else dict(row)


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
            "SELECT id, username, role, active, must_change_password, created_at, updated_at FROM admin_user ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def set_temporary_admin_password(user_id, password):
    password = str(password)
    if len(password) < 12:
        raise ValueError("La contrasenya temporal ha de tenir com a mínim 12 caràcters")
    with get_connection() as db:
        row = db.execute("SELECT id FROM admin_user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("Usuari no trobat")
        db.execute(
            "UPDATE admin_user SET password_hash = ?, must_change_password = 1, updated_at = ? WHERE id = ?",
            (generate_password_hash(password), datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="microseconds"), user_id),
        )


def complete_forced_password_change(user_id, temporary_password, new_password):
    new_password = str(new_password)
    if len(new_password) < 12:
        raise ValueError("La nova contrasenya ha de tenir com a mínim 12 caràcters")
    with get_connection() as db:
        row = db.execute(
            "SELECT password_hash, must_change_password FROM admin_user WHERE id = ? AND active = 1",
            (user_id,),
        ).fetchone()
        if row is None or not row["must_change_password"]:
            raise ValueError("No hi ha cap canvi de contrasenya pendent")
        if not check_password_hash(row["password_hash"], str(temporary_password)):
            raise ValueError("La contrasenya temporal no és correcta")
        if check_password_hash(row["password_hash"], new_password):
            raise ValueError("La contrasenya nova ha de ser diferent de la temporal")
        db.execute(
            "UPDATE admin_user SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
            (generate_password_hash(new_password), datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="microseconds"), user_id),
        )


def delete_inactive_admin_user(user_id):
    with get_connection() as db:
        row = db.execute("SELECT active FROM admin_user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("Usuari no trobat")
        if row["active"]:
            raise ValueError("Cal desactivar l'usuari abans d'eliminar-lo")
        try:
            db.execute("DELETE FROM admin_user WHERE id = ?", (user_id,))
        except sqlite3.IntegrityError as error:
            raise ValueError("No es pot eliminar aquest usuari perquè té registres històrics associats") from error


def set_admin_user_active(username, active):
    username = str(username).strip()
    if not username:
        raise ValueError("L'usuari és obligatori")

    with get_connection() as db:
        row = db.execute(
            "SELECT id, active, role FROM admin_user WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if row is None:
            raise ValueError("Administrador no trobat")

        if not active and row["active"] and row["role"] == 'admin':
            count = db.execute(
                "SELECT COUNT(*) AS count FROM admin_user WHERE active = 1 AND role = 'admin'"
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


def _validate_leave_type(name, approval_policy, max_minutes, auto_approve_minutes,
                         guaranteed_daily_minutes):
    name = str(name or "").strip()
    if not name or len(name) > 100:
        raise ValueError("El nom ha de tenir entre 1 i 100 caràcters")
    if approval_policy not in ("manual", "automatic", "threshold"):
        raise ValueError("Política d'aprovació no vàlida")
    for value in (max_minutes, auto_approve_minutes):
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError("La durada ha de ser un nombre enter positiu")
    if type(guaranteed_daily_minutes) is not int or guaranteed_daily_minutes < 0:
        raise ValueError("Els minuts garantits han de ser un nombre enter no negatiu")
    if approval_policy == "threshold" and auto_approve_minutes is None:
        raise ValueError("Cal indicar el límit d'aprovació automàtica")
    if approval_policy != "threshold" and auto_approve_minutes is not None:
        raise ValueError("Aquest tipus no admet un límit d'aprovació automàtica")
    return name


def list_leave_types():
    with get_connection() as db:
        rows = db.execute("""
            SELECT lt.*, EXISTS(
                SELECT 1 FROM employee_leave el WHERE el.leave_type_id = lt.id
            ) AS used
            FROM leave_type lt ORDER BY lt.sort_order, lt.id
        """).fetchall()
    return [dict(row) for row in rows]


def create_leave_type(name, approval_policy="manual", max_minutes=None,
                      auto_approve_minutes=None, active=True,
                      guaranteed_daily_minutes=0):
    name = _validate_leave_type(
        name, approval_policy, max_minutes, auto_approve_minutes,
        guaranteed_daily_minutes,
    )
    if type(active) is not bool:
        raise ValueError("Estat actiu no vàlid")
    with get_connection() as db:
        try:
            cursor = db.execute("""
                INSERT INTO leave_type (
                    name, approval_policy, max_minutes, auto_approve_minutes,
                    active, guaranteed_daily_minutes, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT MAX(sort_order) + 1 FROM leave_type), 1))
            """, (
                name, approval_policy, max_minutes, auto_approve_minutes,
                int(active), guaranteed_daily_minutes,
            ))
        except sqlite3.IntegrityError:
            raise ValueError("Ja existeix un tipus de permís amb aquest nom")
        return cursor.lastrowid


def update_leave_type(type_id, name, approval_policy, max_minutes=None,
                      auto_approve_minutes=None, active=True,
                      guaranteed_daily_minutes=0):
    name = _validate_leave_type(
        name, approval_policy, max_minutes, auto_approve_minutes,
        guaranteed_daily_minutes,
    )
    if type(active) is not bool:
        raise ValueError("Estat actiu no vàlid")
    with get_connection() as db:
        try:
            cursor = db.execute("""
                UPDATE leave_type
                SET name = ?, approval_policy = ?, max_minutes = ?,
                    auto_approve_minutes = ?, active = ?,
                    guaranteed_daily_minutes = ?
                WHERE id = ?
            """, (
                name, approval_policy, max_minutes, auto_approve_minutes,
                int(active), guaranteed_daily_minutes, type_id,
            ))
        except sqlite3.IntegrityError:
            raise ValueError("Ja existeix un tipus de permís amb aquest nom")
        if not cursor.rowcount:
            raise ValueError("Tipus de permís no trobat")


def delete_leave_type(type_id):
    with get_connection() as db:
        row = db.execute("SELECT id FROM leave_type WHERE id = ?", (type_id,)).fetchone()
        if row is None:
            raise ValueError("Tipus de permís no trobat")
        if db.execute("SELECT 1 FROM employee_leave WHERE leave_type_id = ? LIMIT 1", (type_id,)).fetchone():
            raise ValueError("Aquest tipus ja s'ha utilitzat; només es pot desactivar")
        try:
            db.execute("DELETE FROM leave_type WHERE id = ?", (type_id,))
        except sqlite3.IntegrityError:
            raise ValueError("Aquest tipus ja s'ha utilitzat; només es pot desactivar")


def reorder_leave_types(ordered_ids):
    """Desa l'ordre complet dels tipus de permís de forma atòmica."""
    if not isinstance(ordered_ids, list) or any(type(item) is not int for item in ordered_ids):
        raise ValueError("Ordre de permisos no vàlid")
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("L'ordre conté identificadors repetits")
    with get_connection() as db:
        existing = {row["id"] for row in db.execute("SELECT id FROM leave_type")}
        if set(ordered_ids) != existing:
            raise ValueError("L'ordre ha d'incloure tots els tipus de permís")
        db.executemany(
            "UPDATE leave_type SET sort_order = ? WHERE id = ?",
            [(index, type_id) for index, type_id in enumerate(ordered_ids, 1)],
        )


def list_active_leave_types():
    """Tipus disponibles al terminal, sense exposar els inactius."""
    with get_connection() as db:
        rows = db.execute("""
            SELECT id, name, approval_policy, max_minutes, auto_approve_minutes,
                   guaranteed_daily_minutes
            FROM leave_type WHERE active = 1
            ORDER BY sort_order, id
        """).fetchall()
    return [dict(row) for row in rows]


def get_employee_leave_context(employee_id, now=None):
    """Estat de fitxatge i permís per decidir la següent acció al terminal."""
    now = now or datetime.now(LOCAL_TIMEZONE)
    today = now.astimezone(LOCAL_TIMEZONE).date()
    with get_connection() as db:
        employee = db.execute(
            "SELECT id FROM employee WHERE id = ? AND active = 1", (employee_id,)
        ).fetchone()
        if employee is None:
            return None
        last = db.execute("""
            SELECT id, type, timestamp FROM punch WHERE employee_id = ?
            ORDER BY utc_timestamp_sort_key(timestamp) DESC, id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        open_leave = db.execute("""
            SELECT el.id, el.leave_type_id, lt.name AS leave_type_name,
                   el.started_at, el.record_state
            FROM employee_leave el JOIN leave_type lt ON lt.id = el.leave_type_id
            WHERE el.employee_id = ? AND el.record_state = 'open'
            ORDER BY el.id DESC LIMIT 1
        """, (employee_id,)).fetchone()

    previous_day_entry = (
        last is not None and last["type"] == "entrada"
        and parse_local_timestamp(last["timestamp"]).astimezone(LOCAL_TIMEZONE).date() < today
    )
    suggested = None
    if not previous_day_entry:
        suggested = "sortida" if last is not None and last["type"] == "entrada" else "entrada"
    return {
        "last_punch": dict(last) if last is not None else None,
        "open_leave": dict(open_leave) if open_leave is not None else None,
        "requires_direction_choice": bool(previous_day_entry and open_leave is None),
        "suggested_direction": None if open_leave is not None else suggested,
    }


def start_employee_leave(employee_id, leave_type_id, punch_type, method="pin",
                         confirm_incident=False, now=None):
    """Desa atòmicament el fitxatge i el permís que s'inicia."""
    if punch_type not in ("entrada", "sortida"):
        raise ValueError("Tipus de fitxatge no vàlid")
    if method != "pin":
        raise ValueError("Mètode de registre no vàlid")
    now = now or datetime.now(LOCAL_TIMEZONE)
    timestamp = now.astimezone(LOCAL_TIMEZONE).isoformat(timespec="seconds")
    today = now.astimezone(LOCAL_TIMEZONE).date()

    with get_connection() as db:
        employee = db.execute(
            "SELECT id, name FROM employee WHERE id = ? AND active = 1",
            (employee_id,),
        ).fetchone()
        if employee is None:
            raise ValueError("Treballador no trobat o inactiu")
        leave_type = db.execute(
            "SELECT id FROM leave_type WHERE id = ? AND active = 1",
            (leave_type_id,),
        ).fetchone()
        if leave_type is None:
            raise ValueError("Tipus de permís no disponible")
        if db.execute(
            "SELECT 1 FROM employee_leave WHERE employee_id = ? AND record_state = 'open'",
            (employee_id,),
        ).fetchone():
            raise ValueError("Ja hi ha un permís obert")

        last = db.execute("""
            SELECT type, timestamp FROM punch WHERE employee_id = ?
            ORDER BY utc_timestamp_sort_key(timestamp) DESC, id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        previous_day_entry = (
            last is not None and last["type"] == "entrada"
            and parse_local_timestamp(last["timestamp"]).astimezone(LOCAL_TIMEZONE).date() < today
        )
        unexpected = (
            (last is None and punch_type == "sortida")
            or (last is not None and last["type"] == punch_type)
        )
        note = ""
        if unexpected:
            if last is None:
                note = "Primera acció del dia: sortida confirmada pel treballador"
            elif previous_day_entry and punch_type == "entrada":
                note = "Nova entrada amb una entrada anterior sense sortida confirmada pel treballador"
            elif punch_type == "entrada":
                note = "Entrada consecutiva confirmada pel treballador"
            else:
                note = "Sortida consecutiva confirmada pel treballador"
            if not confirm_incident:
                return {"ok": False, "confirmation_required": True, "error": note}

        punch = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method, incident, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (employee_id, timestamp, punch_type, method, int(unexpected), note))
        # Les entrades amb permís necessiten l'hora prevista del supervisor.
        needs_supervisor = punch_type == "entrada" or unexpected
        leave = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, status, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
        """, (
            employee_id, leave_type_id, timestamp,
            "needs_regularization" if punch_type == "entrada" else "open",
            int(needs_supervisor), punch.lastrowid,
        ))
        return {
            "ok": True, "leave_id": leave.lastrowid,
            "punch_id": punch.lastrowid, "timestamp": timestamp,
            "punch_type": punch_type, "incident": int(unexpected),
            "record_state": "needs_regularization" if punch_type == "entrada" else "open",
        }


def finish_employee_leave(employee_id, method="pin", confirm_incident=False, now=None):
    """Tanca un permís temporal i desa l'entrada de retorn atòmicament."""
    if method != "pin":
        raise ValueError("Mètode de registre no vàlid")
    now = now or datetime.now(LOCAL_TIMEZONE)
    timestamp = now.astimezone(LOCAL_TIMEZONE).isoformat(timespec="seconds")

    with get_connection() as db:
        employee = db.execute(
            "SELECT id FROM employee WHERE id = ? AND active = 1", (employee_id,)
        ).fetchone()
        if employee is None:
            raise ValueError("Treballador no trobat o inactiu")
        leave = db.execute("""
            SELECT el.*, lt.approval_policy, lt.auto_approve_minutes
            FROM employee_leave el JOIN leave_type lt ON lt.id = el.leave_type_id
            WHERE el.employee_id = ? AND el.record_state = 'open'
            ORDER BY el.id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        if leave is None:
            raise ValueError("No hi ha cap permís obert")
        start = parse_local_timestamp(leave["started_at"]).astimezone(timezone.utc)
        end = now.astimezone(timezone.utc)
        if end < start:
            raise ValueError("El retorn no pot ser anterior a l'inici del permís")

        last = db.execute("""
            SELECT type FROM punch WHERE employee_id = ?
            ORDER BY utc_timestamp_sort_key(timestamp) DESC, id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        unexpected = last is None or last["type"] == "entrada"
        note = "Entrada consecutiva confirmada pel treballador" if unexpected else ""
        if unexpected and not confirm_incident:
            return {"ok": False, "confirmation_required": True, "error": note}

        duration_seconds = (end - start).total_seconds()
        crosses_local_day = (
            local_timestamp_date(leave["started_at"])
            != now.astimezone(LOCAL_TIMEZONE).date().isoformat()
        )
        punch = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method, incident, note)
            VALUES (?, ?, 'entrada', ?, ?, ?)
        """, (employee_id, timestamp, method, int(unexpected), note))
        db.execute("""
            UPDATE employee_leave
            SET ended_at = ?, end_punch_id = ?, record_state = 'finished',
                status = 'pending', requires_supervisor = ?
            WHERE id = ?
        """, (timestamp, punch.lastrowid,
              int(bool(leave["requires_supervisor"] or unexpected or crosses_local_day)),
              leave["id"]))
        daily_decision = (
            None if crosses_local_day
            else _refresh_daily_leave_decision(db, leave["id"])
        )
        status = daily_decision["status"] if daily_decision else "pending"
        return {
            "ok": True, "leave_id": leave["id"], "punch_id": punch.lastrowid,
            "timestamp": timestamp, "duration_seconds": duration_seconds,
            "status": status, "incident": int(unexpected),
            "daily_decision": daily_decision,
            "crosses_local_day": crosses_local_day,
        }


def defer_employee_leave_return(employee_id):
    """Marca un retorn oblidat sense atribuir-li cap hora fictícia."""
    with get_connection() as db:
        employee = db.execute(
            "SELECT id FROM employee WHERE id = ? AND active = 1", (employee_id,)
        ).fetchone()
        if employee is None:
            raise ValueError("Treballador no trobat o inactiu")
        leave = db.execute("""
            SELECT id FROM employee_leave
            WHERE employee_id = ? AND record_state = 'open'
            ORDER BY id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        if leave is None:
            raise ValueError("No hi ha cap permís obert")
        db.execute("""
            UPDATE employee_leave
            SET record_state = 'needs_regularization',
                requires_supervisor = 1, status = 'pending'
            WHERE id = ?
        """, (leave["id"],))
        return {"ok": True, "leave_id": leave["id"],
                "record_state": "needs_regularization", "status": "pending"}


def punch_with_open_leave(employee_id, punch_type, return_choice=None,
                          confirm_incident=False, now=None):
    """Resol el retorn d'un permís i el fitxatge sol·licitat."""
    if punch_type not in ("entrada", "sortida"):
        raise ValueError("Tipus de fitxatge no vàlid")
    context = get_employee_leave_context(employee_id, now=now)
    if context is None:
        raise ValueError("Treballador no trobat o inactiu")
    if context["open_leave"] is None:
        raise ValueError("No hi ha cap permís obert")
    if return_choice not in ("now", "earlier"):
        return {"ok": False, "return_choice_required": True,
                "leave": context["open_leave"]}
    if return_choice == "now":
        if punch_type != "entrada":
            return {"ok": False, "return_entry_required": True,
                    "error": "Cal registrar primer l'entrada de retorn"}
        result = finish_employee_leave(
            employee_id, confirm_incident=confirm_incident, now=now
        )
        if not result["ok"]:
            return result
        return {**result, "ordinary_punch_required": False,
                "punch_reused_as_return": True}

    # Retorn anterior: validació del fitxatge i regularització en una
    # única transacció, sense inventar cap hora de finalització.
    now = now or datetime.now(LOCAL_TIMEZONE)
    timestamp = now.astimezone(LOCAL_TIMEZONE).isoformat(timespec="seconds")
    today = now.astimezone(LOCAL_TIMEZONE).date()
    with get_connection() as db:
        leave = db.execute("""
            SELECT id FROM employee_leave
            WHERE employee_id = ? AND record_state = 'open'
            ORDER BY id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        if leave is None:
            raise ValueError("No hi ha cap permís obert")
        last = db.execute("""
            SELECT type, timestamp FROM punch WHERE employee_id = ?
            ORDER BY utc_timestamp_sort_key(timestamp) DESC, id DESC LIMIT 1
        """, (employee_id,)).fetchone()
        previous_day_entry = (
            last is not None and last["type"] == "entrada"
            and parse_local_timestamp(last["timestamp"]).astimezone(LOCAL_TIMEZONE).date() < today
        )
        unexpected = (
            (last is None and punch_type == "sortida")
            or (last is not None and last["type"] == punch_type)
        )
        note = ""
        if unexpected:
            if last is None:
                note = "Primera acció del dia: sortida confirmada pel treballador"
            elif previous_day_entry and punch_type == "entrada":
                note = "Nova entrada amb una entrada anterior sense sortida confirmada pel treballador"
            elif punch_type == "entrada":
                note = "Entrada consecutiva confirmada pel treballador"
            else:
                note = "Sortida consecutiva confirmada pel treballador"
            if not confirm_incident:
                return {"ok": False, "confirmation_required": True,
                        "error": note, "requested_punch_type": punch_type}
        punch = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method, incident, note)
            VALUES (?, ?, ?, 'pin', ?, ?)
        """, (employee_id, timestamp, punch_type, int(unexpected), note))
        db.execute("""
            UPDATE employee_leave
            SET record_state = 'needs_regularization',
                requires_supervisor = 1, status = 'pending'
            WHERE id = ?
        """, (leave["id"],))
        return {
            "ok": True, "leave_id": leave["id"],
            "record_state": "needs_regularization", "status": "pending",
            "punch_id": punch.lastrowid, "punch_type": punch_type,
            "incident": int(unexpected), "timestamp": timestamp,
            "ordinary_punch_required": False,
        }


def _leave_duration_seconds(leave):
    if leave["regularization_kind"] == "late_arrival":
        start_value = leave["expected_started_at"]
        end_value = leave["started_at"]
    elif leave["regularization_kind"] == "early_departure":
        start_value = leave["started_at"]
        end_value = leave["expected_ended_at"]
    else:
        start_value = leave["started_at"]
        end_value = leave["ended_at"]
    start = parse_local_timestamp(start_value).astimezone(timezone.utc)
    end = parse_local_timestamp(end_value).astimezone(timezone.utc)
    return max(0, round((end - start).total_seconds()))


def _refresh_daily_leave_decision(db, leave_id):
    leave = db.execute("""
        SELECT el.*, lt.approval_policy, lt.auto_approve_minutes,
               lt.guaranteed_daily_minutes
        FROM employee_leave el
        JOIN leave_type lt ON lt.id = el.leave_type_id
        WHERE el.id = ? AND el.record_state = 'finished' AND el.ended_at IS NOT NULL
    """, (leave_id,)).fetchone()
    if leave is None:
        return None

    local_date = local_timestamp_date(leave["started_at"])
    interval_end = (
        leave["expected_started_at"]
        if leave["regularization_kind"] == "late_arrival"
        else leave["expected_ended_at"]
        if leave["regularization_kind"] == "early_departure"
        else leave["ended_at"]
    )
    if local_timestamp_date(interval_end) != local_date:
        db.execute("""
            UPDATE employee_leave SET daily_decision_id = NULL, status = 'pending',
                requires_supervisor = 1 WHERE id = ?
        """, (leave_id,))
        return None

    decision = db.execute("""
        SELECT id, status, decision_source, total_seconds, approval_policy,
               auto_approve_minutes, guaranteed_daily_minutes
        FROM daily_leave_decision
        WHERE employee_id = ? AND leave_type_id = ? AND local_date = ?
    """, (leave["employee_id"], leave["leave_type_id"], local_date)).fetchone()
    created = decision is None
    if created:
        decision_id = db.execute("""
            INSERT INTO daily_leave_decision
                (employee_id, leave_type_id, local_date, status,
                 decision_source, total_seconds, approval_policy,
                 auto_approve_minutes, guaranteed_daily_minutes, updated_at)
            VALUES (?, ?, ?, 'pending', 'system', 0, ?, ?, ?, ?)
        """, (
            leave["employee_id"], leave["leave_type_id"], local_date,
            leave["approval_policy"], leave["auto_approve_minutes"],
            leave["guaranteed_daily_minutes"],
            datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        )).lastrowid
    else:
        decision_id = decision["id"]
    db.execute(
        "UPDATE employee_leave SET daily_decision_id = ? WHERE id = ?",
        (decision_id, leave_id),
    )

    members = db.execute("""
        SELECT * FROM employee_leave
        WHERE daily_decision_id = ? AND record_state = 'finished'
          AND ended_at IS NOT NULL
    """, (decision_id,)).fetchall()
    total_seconds = sum(_leave_duration_seconds(member) for member in members)
    requires_supervisor = any(member["requires_supervisor"] for member in members)
    total_changed = created or total_seconds != decision["total_seconds"]
    policy_changed = (
        not created and (
            decision["approval_policy"] != leave["approval_policy"]
            or decision["auto_approve_minutes"] != leave["auto_approve_minutes"]
            or decision["guaranteed_daily_minutes"] != leave["guaranteed_daily_minutes"]
        )
    )
    invalidated = (
        not created and (total_changed or policy_changed)
        and decision["status"] != "pending"
        and decision["decision_source"] == "supervisor"
    )

    no_excess = total_seconds <= leave["guaranteed_daily_minutes"] * 60
    if invalidated or requires_supervisor:
        status, source = "pending", "system"
    elif leave["approval_policy"] == "automatic" or (
        leave["approval_policy"] == "threshold"
        and total_seconds <= leave["auto_approve_minutes"] * 60
    ):
        status, source = "approved", "automatic"
    elif no_excess:
        status, source = "approved", "system"
    else:
        status, source = "pending", "system"

    if created:
        action = "created"
    elif invalidated:
        action = "invalidated"
    elif status == "approved" and source == "automatic" and (
        decision["status"] != "approved"
        or decision["decision_source"] != "automatic"
    ):
        action = "automatic_approval"
    else:
        action = "total_changed"

    if total_changed or policy_changed:
        changed_at = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            UPDATE daily_leave_decision
            SET status = ?, decision_source = ?, total_seconds = ?,
                approval_policy = ?, auto_approve_minutes = ?,
                guaranteed_daily_minutes = ?, updated_at = ?
            WHERE id = ?
        """, (
            status, source, total_seconds, leave["approval_policy"],
            leave["auto_approve_minutes"], leave["guaranteed_daily_minutes"],
            changed_at, decision_id,
        ))
        db.execute("""
            INSERT INTO daily_leave_decision_history
                (decision_id, changed_at, action, previous_status,
                 new_status, total_seconds, approval_policy,
                 auto_approve_minutes, guaranteed_daily_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision_id, changed_at, action,
            None if created else decision["status"], status, total_seconds,
            leave["approval_policy"], leave["auto_approve_minutes"],
            leave["guaranteed_daily_minutes"],
        ))
        db.execute(
            "UPDATE employee_leave SET status = ? WHERE daily_decision_id = ?",
            (status, decision_id),
        )
    elif decision["status"] != status or decision["decision_source"] != source:
        changed_at = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            UPDATE daily_leave_decision
            SET status = ?, decision_source = ?, updated_at = ?
            WHERE id = ?
        """, (status, source, changed_at, decision_id))
        db.execute("""
            INSERT INTO daily_leave_decision_history
                (decision_id, changed_at, action, previous_status,
                 new_status, total_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision_id, changed_at,
            "automatic_approval" if source == "automatic" else "total_changed",
            decision["status"], status, total_seconds, leave["approval_policy"],
            leave["auto_approve_minutes"], leave["guaranteed_daily_minutes"],
        ))
        db.execute(
            "UPDATE employee_leave SET status = ? WHERE daily_decision_id = ?",
            (status, decision_id),
        )

    guaranteed_seconds = min(
        total_seconds, leave["guaranteed_daily_minutes"] * 60
    )
    recognized_seconds = (
        total_seconds if status == "approved" else guaranteed_seconds
    )
    return {
        "id": decision_id, "local_date": local_date, "status": status,
        "decision_source": source, "total_seconds": total_seconds,
        "guaranteed_seconds": guaranteed_seconds,
        "recognized_seconds": recognized_seconds,
    }


def list_employee_leaves_for_supervision(filter_by="all"):
    """Consulta de permisos per al supervisor, sense modificar-ne l'estat."""
    if filter_by not in ("all", "regularization", "approval", "history"):
        raise ValueError("Filtre de permisos no vàlid")
    conditions = {
        "all": "el.daily_decision_id IS NULL",
        "regularization": "el.daily_decision_id IS NULL AND el.record_state = 'needs_regularization'",
        "approval": "el.daily_decision_id IS NULL AND el.status = 'pending' AND el.record_state = 'finished'",
        "history": "el.daily_decision_id IS NULL AND el.status IN ('approved', 'rejected')",
    }
    with get_connection() as db:
        rows = db.execute(f"""
            SELECT el.id, el.employee_id, e.name AS employee_name,
                   el.leave_type_id, lt.name AS leave_type_name,
                   el.started_at, el.ended_at, el.status, el.record_state,
                   el.requires_supervisor, el.start_punch_id, el.end_punch_id,
                   el.regularized_at, el.regularized_by, el.daily_decision_id
            FROM employee_leave el
            JOIN employee e ON e.id = el.employee_id
            JOIN leave_type lt ON lt.id = el.leave_type_id
            WHERE {conditions[filter_by]}
            ORDER BY utc_timestamp_sort_key(el.started_at) DESC, el.id DESC
        """).fetchall()
    return [dict(row) for row in rows]


def list_daily_leave_decisions_for_supervision(filter_by="all"):
    if filter_by not in ("all", "approval", "history"):
        raise ValueError("Filtre de decisions diàries no vàlid")
    condition = {
        "all": "1 = 1",
        "approval": "d.status = 'pending'",
        "history": "d.status IN ('approved', 'rejected')",
    }[filter_by]
    with get_connection() as db:
        rows = db.execute(f"""
            SELECT d.id, d.employee_id, e.name AS employee_name,
                   d.leave_type_id, lt.name AS leave_type_name,
                   d.local_date, d.status, d.decision_source, d.total_seconds,
                   d.guaranteed_daily_minutes,
                   MIN(d.total_seconds, d.guaranteed_daily_minutes * 60)
                       AS guaranteed_seconds,
                   CASE WHEN d.status = 'approved' THEN d.total_seconds
                        ELSE MIN(d.total_seconds, d.guaranteed_daily_minutes * 60)
                   END AS recognized_seconds,
                   (SELECT COUNT(*) FROM employee_leave el
                    WHERE el.daily_decision_id = d.id) AS leave_count,
                   EXISTS(
                       SELECT 1 FROM employee_leave el
                       WHERE el.daily_decision_id = d.id AND el.requires_supervisor = 1
                   ) AS requires_supervisor,
                   d.updated_at
            FROM daily_leave_decision d
            JOIN employee e ON e.id = d.employee_id
            JOIN leave_type lt ON lt.id = d.leave_type_id
            WHERE {condition}
            ORDER BY d.local_date DESC, e.name COLLATE NOCASE, lt.name COLLATE NOCASE
        """).fetchall()
    return [dict(row) for row in rows]


def get_daily_leave_decision_for_supervision(decision_id):
    with get_connection() as db:
        decision = db.execute("""
            SELECT d.*, e.name AS employee_name, lt.name AS leave_type_name,
                   d.guaranteed_daily_minutes,
                   MIN(d.total_seconds, d.guaranteed_daily_minutes * 60)
                       AS guaranteed_seconds,
                   CASE WHEN d.status = 'approved' THEN d.total_seconds
                    ELSE MIN(d.total_seconds, d.guaranteed_daily_minutes * 60)
                   END AS recognized_seconds,
                   MAX(0, d.total_seconds - d.guaranteed_daily_minutes * 60)
                       AS excess_seconds
            FROM daily_leave_decision d
            JOIN employee e ON e.id = d.employee_id
            JOIN leave_type lt ON lt.id = d.leave_type_id
            WHERE d.id = ?
        """, (decision_id,)).fetchone()
        if decision is None:
            return None
        leaves = db.execute("""
            SELECT id, started_at, ended_at, status, requires_supervisor,
                   regularization_kind, regularization_reason
            FROM employee_leave
            WHERE daily_decision_id = ?
            ORDER BY utc_timestamp_sort_key(started_at), id
        """, (decision_id,)).fetchall()
        history = db.execute("""
            SELECT h.id, h.changed_at, h.action, h.previous_status,
                   h.new_status, h.total_seconds, h.approval_policy,
                   h.auto_approve_minutes, h.guaranteed_daily_minutes, h.reason,
                   u.username AS reviewer_name
            FROM daily_leave_decision_history h
            LEFT JOIN admin_user u ON u.id = h.admin_user_id
            WHERE h.decision_id = ?
            ORDER BY utc_timestamp_sort_key(h.changed_at), h.id
        """, (decision_id,)).fetchall()
    return {
        **dict(decision),
        "leaves": [dict(row) for row in leaves],
        "decision_history": [dict(row) for row in history],
    }


def decide_daily_leave(decision_id, new_status, admin_user_id, reason):
    if new_status not in ("approved", "rejected"):
        raise ValueError("Decisió diària no vàlida")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Cal justificar la decisió")
    with get_connection() as db:
        reviewer = db.execute("""
            SELECT id FROM admin_user
            WHERE id = ? AND active = 1 AND role IN ('admin', 'supervisor')
        """, (admin_user_id,)).fetchone()
        if reviewer is None:
            raise ValueError("Supervisor no vàlid o inactiu")
        decision = db.execute("""
            SELECT status, total_seconds, approval_policy, auto_approve_minutes,
                   guaranteed_daily_minutes
            FROM daily_leave_decision WHERE id = ?
        """, (decision_id,)).fetchone()
        if decision is None:
            raise ValueError("Decisió diària no trobada")
        if decision["status"] == new_status:
            raise ValueError("La decisió diària ja té aquest estat")
        changed_at = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            INSERT INTO daily_leave_decision_history
                (decision_id, admin_user_id, changed_at, action,
                 previous_status, new_status, total_seconds, approval_policy,
                 auto_approve_minutes, guaranteed_daily_minutes, reason)
            VALUES (?, ?, ?, 'supervisor_decision', ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision_id, admin_user_id, changed_at, decision["status"],
            new_status, decision["total_seconds"], decision["approval_policy"],
            decision["auto_approve_minutes"], decision["guaranteed_daily_minutes"],
            reason.strip(),
        ))
        db.execute("""
            UPDATE daily_leave_decision
            SET status = ?, decision_source = 'supervisor', updated_at = ?
            WHERE id = ?
        """, (new_status, changed_at, decision_id))
        db.execute("""
            UPDATE employee_leave SET status = ?
            WHERE daily_decision_id = ?
        """, (new_status, decision_id))
    return {
        "ok": True, "decision_id": decision_id,
        "previous_status": decision["status"], "status": new_status,
    }


def get_employee_leave_for_supervision(leave_id):
    """Detall de permís amb fitxatges vinculats i historial de decisions."""
    with get_connection() as db:
        leave = db.execute("""
            SELECT el.*, e.name AS employee_name, lt.name AS leave_type_name,
                   lt.approval_policy, lt.max_minutes, lt.auto_approve_minutes
            FROM employee_leave el
            JOIN employee e ON e.id = el.employee_id
            JOIN leave_type lt ON lt.id = el.leave_type_id
            WHERE el.id = ?
        """, (leave_id,)).fetchone()
        if leave is None:
            return None
        punches = db.execute("""
            SELECT id, employee_id, timestamp, type, method, incident, note
            FROM punch
            WHERE id IN (?, ?)
            ORDER BY utc_timestamp_sort_key(timestamp), id
        """, (leave["start_punch_id"], leave["end_punch_id"])).fetchall()
        history = db.execute("""
            SELECT h.id, h.admin_user_id, u.username AS reviewer_name,
                   h.changed_at, h.previous_status, h.new_status, h.reason
            FROM employee_leave_decision_history h
            JOIN admin_user u ON u.id = h.admin_user_id
            WHERE h.leave_id = ?
            ORDER BY utc_timestamp_sort_key(h.changed_at), h.id
        """, (leave_id,)).fetchall()
    return {
        **dict(leave),
        "punches": [dict(row) for row in punches],
        "decision_history": [dict(row) for row in history],
    }


def regularize_employee_leave_return(leave_id, returned_at, admin_user_id, reason):
    """Completa l'hora de retorn verificada, sense crear ni alterar fitxatges."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Cal indicar el motiu de la regularització")
    if not isinstance(returned_at, str):
        raise ValueError("Hora de retorn no vàlida")
    try:
        parsed_return = datetime.fromisoformat(returned_at)
        if parsed_return.tzinfo is None or parsed_return.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("L'hora de retorn ha d'incloure la zona horària")
    with get_connection() as db:
        reviewer = db.execute("""
            SELECT id FROM admin_user
            WHERE id = ? AND active = 1 AND role IN ('admin', 'supervisor')
        """, (admin_user_id,)).fetchone()
        if reviewer is None:
            raise ValueError("Supervisor no vàlid o inactiu")
        leave = db.execute("""
            SELECT id, started_at, record_state, status, start_punch_id,
                   regularization_kind
            FROM employee_leave WHERE id = ?
        """, (leave_id,)).fetchone()
        if leave is None:
            raise ValueError("Permís no trobat")
        if leave["record_state"] != "needs_regularization" or leave["start_punch_id"] is None:
            raise ValueError("Aquest permís no admet regularització de retorn")
        start_punch = db.execute(
            "SELECT type FROM punch WHERE id = ?", (leave["start_punch_id"],)
        ).fetchone()
        if start_punch is None or start_punch["type"] != "sortida":
            raise ValueError("Aquest permís no és una sortida temporal")
        if leave["regularization_kind"] != "return":
            raise ValueError("Cal classificar el permís com a retorn oblidat")
        start = parse_local_timestamp(leave["started_at"]).astimezone(timezone.utc)
        end = parsed_return.astimezone(timezone.utc)
        if end < start or end > datetime.now(timezone.utc):
            raise ValueError("Hora de retorn fora de l'interval vàlid")
        # Un retorn declarat no pot ser posterior al primer fitxatge
        # efectuat després de l'inici del permís.
        subsequent = db.execute("""
            SELECT timestamp FROM punch
            WHERE employee_id = (
                SELECT employee_id FROM employee_leave WHERE id = ?
            ) AND id != ?
              AND utc_timestamp_sort_key(timestamp) > ?
            ORDER BY utc_timestamp_sort_key(timestamp), id
            LIMIT 1
        """, (leave_id, leave["start_punch_id"], utc_timestamp_sort_key(leave["started_at"]))).fetchone()
        if subsequent is not None and end > parse_local_timestamp(
            subsequent["timestamp"]
        ).astimezone(timezone.utc):
            raise ValueError("El retorn no pot ser posterior al següent fitxatge")
        if leave["status"] != "pending":
            raise ValueError("No es pot regularitzar un permís ja resolt")
        now = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            UPDATE employee_leave
            SET ended_at = ?, record_state = 'finished',
                requires_supervisor = 1, status = 'pending',
                regularized_at = ?, regularized_by = ?,
                regularization_reason = ?, regularization_kind = 'return'
            WHERE id = ?
        """, (returned_at, now, admin_user_id, reason.strip(), leave_id))
        _refresh_daily_leave_decision(db, leave_id)
    return {"ok": True, "leave_id": leave_id, "record_state": "finished",
            "status": "pending"}


def regularize_employee_leave_late_arrival(leave_id, expected_started_at, admin_user_id, reason):
    """Registra l'hora prevista d'entrada sense modificar l'entrada real."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Cal indicar el motiu de la regularització")
    if not isinstance(expected_started_at, str):
        raise ValueError("Hora prevista no vàlida")
    try:
        expected = datetime.fromisoformat(expected_started_at)
        if expected.tzinfo is None or expected.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("L'hora prevista ha d'incloure la zona horària")

    with get_connection() as db:
        reviewer = db.execute("""
            SELECT id FROM admin_user
            WHERE id = ? AND active = 1 AND role IN ('admin', 'supervisor')
        """, (admin_user_id,)).fetchone()
        if reviewer is None:
            raise ValueError("Supervisor no vàlid o inactiu")
        leave = db.execute("""
            SELECT id, started_at, record_state, status, start_punch_id
            FROM employee_leave WHERE id = ?
        """, (leave_id,)).fetchone()
        if leave is None:
            raise ValueError("Permís no trobat")
        if leave["record_state"] != "needs_regularization" or leave["start_punch_id"] is None:
            raise ValueError("Aquest permís no admet regularització d'arribada")
        punch = db.execute("""
            SELECT type, timestamp FROM punch WHERE id = ?
        """, (leave["start_punch_id"],)).fetchone()
        if punch is None or punch["type"] != "entrada":
            raise ValueError("Aquest permís no correspon a una arribada")
        actual = parse_local_timestamp(leave["started_at"]).astimezone(timezone.utc)
        if expected.astimezone(timezone.utc) > actual:
            raise ValueError("L'hora prevista no pot ser posterior a l'entrada real")
        if leave["status"] != "pending":
            raise ValueError("No es pot regularitzar un permís ja resolt")
        now = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            UPDATE employee_leave
            SET expected_started_at = ?, ended_at = started_at,
                regularization_kind = 'late_arrival',
                record_state = 'finished', requires_supervisor = 1,
                status = 'pending', regularized_at = ?, regularized_by = ?,
                regularization_reason = ?
            WHERE id = ?
        """, (expected_started_at, now, admin_user_id, reason.strip(), leave_id))
        _refresh_daily_leave_decision(db, leave_id)
    return {"ok": True, "leave_id": leave_id, "record_state": "finished",
            "status": "pending"}


def regularize_employee_leave_early_departure(leave_id, expected_ended_at, admin_user_id, reason):
    """Registra la sortida prevista sense alterar el fitxatge de sortida real."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Cal indicar el motiu de la regularització")
    if not isinstance(expected_ended_at, str):
        raise ValueError("Hora prevista no vàlida")
    try:
        expected = datetime.fromisoformat(expected_ended_at)
        if expected.tzinfo is None or expected.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("L'hora prevista ha d'incloure la zona horària")

    with get_connection() as db:
        reviewer = db.execute("""
            SELECT id FROM admin_user
            WHERE id = ? AND active = 1 AND role IN ('admin', 'supervisor')
        """, (admin_user_id,)).fetchone()
        if reviewer is None:
            raise ValueError("Supervisor no vàlid o inactiu")
        leave = db.execute("""
            SELECT id, employee_id, started_at, record_state, status, start_punch_id,
                   regularization_kind
            FROM employee_leave WHERE id = ?
        """, (leave_id,)).fetchone()
        if leave is None:
            raise ValueError("Permís no trobat")
        if leave["record_state"] != "needs_regularization" or leave["start_punch_id"] is None:
            raise ValueError("Aquest permís no admet regularització de sortida anticipada")
        punch = db.execute(
            "SELECT type FROM punch WHERE id = ?", (leave["start_punch_id"],)
        ).fetchone()
        if punch is None or punch["type"] != "sortida":
            raise ValueError("Aquest permís no correspon a una sortida")
        if leave["regularization_kind"] != "early_departure":
            raise ValueError("Cal classificar el permís com a sortida anticipada")
        start = parse_local_timestamp(leave["started_at"]).astimezone(timezone.utc)
        end = expected.astimezone(timezone.utc)
        if end <= start:
            raise ValueError("L'hora prevista ha de ser posterior a la sortida real")
        if leave["status"] != "pending":
            raise ValueError("No es pot regularitzar un permís ja resolt")
        next_punch = db.execute("""
            SELECT timestamp FROM punch
            WHERE employee_id = ? AND id != ?
              AND utc_timestamp_sort_key(timestamp) > ?
            ORDER BY utc_timestamp_sort_key(timestamp), id LIMIT 1
        """, (leave["employee_id"], leave["start_punch_id"],
              utc_timestamp_sort_key(leave["started_at"]))).fetchone()
        if next_punch is not None and end > parse_local_timestamp(
            next_punch["timestamp"]
        ).astimezone(timezone.utc):
            raise ValueError("L'hora prevista no pot superar el següent fitxatge")
        now = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            UPDATE employee_leave
            SET expected_ended_at = ?, ended_at = ?, regularization_kind = 'early_departure',
                record_state = 'finished',
                requires_supervisor = 1, status = 'pending',
                regularized_at = ?, regularized_by = ?, regularization_reason = ?
            WHERE id = ?
        """, (expected_ended_at, expected_ended_at, now,
              admin_user_id, reason.strip(), leave_id))
        _refresh_daily_leave_decision(db, leave_id)
    return {"ok": True, "leave_id": leave_id, "record_state": "finished",
            "status": "pending"}


def classify_employee_leave_departure(leave_id, kind, admin_user_id):
    """Classifica una sortida pendent abans de regularitzar-ne les hores."""
    if kind not in ("return", "early_departure"):
        raise ValueError("Tipus de regularització no vàlid")
    with get_connection() as db:
        reviewer = db.execute("""
            SELECT id FROM admin_user
            WHERE id = ? AND active = 1 AND role IN ('admin', 'supervisor')
        """, (admin_user_id,)).fetchone()
        if reviewer is None:
            raise ValueError("Supervisor no vàlid o inactiu")
        leave = db.execute("""
            SELECT el.record_state, el.status, el.regularization_kind,
                   p.type AS punch_type
            FROM employee_leave el
            LEFT JOIN punch p ON p.id = el.start_punch_id
            WHERE el.id = ?
        """, (leave_id,)).fetchone()
        if leave is None:
            raise ValueError("Permís no trobat")
        if (leave["record_state"] != "needs_regularization"
                or leave["status"] != "pending"
                or leave["punch_type"] != "sortida"):
            raise ValueError("El permís no és una sortida pendent de regularització")
        if leave["regularization_kind"] is not None:
            raise ValueError("El permís ja està classificat")
        db.execute("""
            UPDATE employee_leave SET regularization_kind = ?
            WHERE id = ?
        """, (kind, leave_id))
    return {"ok": True, "leave_id": leave_id, "regularization_kind": kind}


def decide_employee_leave(leave_id, new_status, admin_user_id, reason):
    """Canvia una decisió i en conserva l'historial dins una transacció."""
    if new_status not in ("approved", "rejected"):
        raise ValueError("Decisió de permís no vàlida")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Cal justificar la decisió")
    with get_connection() as db:
        reviewer = db.execute("""
            SELECT id FROM admin_user
            WHERE id = ? AND active = 1 AND role IN ('admin', 'supervisor')
        """, (admin_user_id,)).fetchone()
        if reviewer is None:
            raise ValueError("Supervisor no vàlid o inactiu")
        leave = db.execute("""
            SELECT status, record_state, daily_decision_id
            FROM employee_leave WHERE id = ?
        """, (leave_id,)).fetchone()
        if leave is None:
            raise ValueError("Permís no trobat")
        if leave["daily_decision_id"] is not None:
            raise ValueError("Aquest permís forma part d'una decisió diària")
        if leave["record_state"] != "finished":
            raise ValueError("Cal finalitzar o regularitzar el permís abans de decidir")
        previous_status = leave["status"]
        if previous_status == new_status:
            raise ValueError("El permís ja té aquesta decisió")
        now = datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")
        db.execute("""
            INSERT INTO employee_leave_decision_history
                (leave_id, admin_user_id, changed_at,
                 previous_status, new_status, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (leave_id, admin_user_id, now, previous_status,
              new_status, reason.strip()))
        db.execute("""
            UPDATE employee_leave SET status = ? WHERE id = ?
        """, (new_status, leave_id))
    return {"ok": True, "leave_id": leave_id, "previous_status": previous_status,
            "status": new_status}
