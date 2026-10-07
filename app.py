import csv
import io
import os
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, send_from_directory, render_template, request, session, url_for
from timeclock.database import (
    SESSION_KEY_PATH,
    authenticate_admin,
    authenticate_admin_pin,
    change_admin_password,
    correct_punch,
    create_employee,
    create_punch,
    create_terminal_event,
    find_employee_by_pin,
    get_settings,
    get_active_admin_session_version,
    init_database,
    list_employees,
    list_punches,
    list_punch_corrections,
    list_punch_incident_reviews,
    set_punch_incident_status,
    set_admin_pin,
    list_terminal_events,
    update_employee,
    update_settings,
)
from pathlib import Path

from timeclock import branding, database
import backup as backup_module
from backup import create_backup, restore_backup, verify_backup

USB_MOUNTPOINT = Path("/mnt/timeclockpi-usb")
USB_STATE_FILE = Path("/run/timeclockpi/usb-device")
USB_RESTORE_DIR = Path("/run/timeclockpi/restore")
USB_RESTORE_STATUS = Path("/run/timeclockpi-restore/result")


def pending_branding_dir():
    return database.DATA_DIR / "branding-pending"


def pending_branding_launch_marker():
    return USB_RESTORE_DIR / "branding-launched"


def discard_pending_branding():
    shutil.rmtree(pending_branding_dir(), ignore_errors=True)
    pending_branding_launch_marker().unlink(missing_ok=True)


def fsync_path(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stage_pending_branding(prepare_dir):
    """Stage the logo change of a prepared restore.

    The pending change lives under the data directory so that it survives a
    reboot. A random nonce is also written into the staged database copy: the
    nonce only appears in the live database if the privileged restore
    succeeded, so it is a durable success marker needing no extra privileges.
    """
    discard_pending_branding()
    state_file = prepare_dir / backup_module.BRANDING_STATE_FILE
    if not state_file.is_file():
        return
    state = state_file.read_text(encoding="utf-8")
    nonce = secrets.token_hex(16)
    staged_database = prepare_dir / "data" / "timeclock.db"
    connection = sqlite3.connect(staged_database)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("CREATE TABLE IF NOT EXISTS branding_restore (nonce TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO branding_restore (nonce) VALUES (?)", (nonce,))
        connection.commit()
    finally:
        connection.close()

    pending = pending_branding_dir()
    temporary = pending.with_name(pending.name + ".tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    pending.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(mode=0o700)
    if state == "custom":
        (temporary / branding.LOGO_FILE_NAME).write_bytes(
            (prepare_dir / branding.BACKUP_LOGO_NAME).read_bytes()
        )
    (temporary / "action").write_text("set" if state == "custom" else "clear", encoding="utf-8")
    (temporary / "nonce").write_text(nonce, encoding="utf-8")
    for child in temporary.iterdir():
        fsync_path(child)
    fsync_path(temporary)
    temporary.replace(pending)
    fsync_path(pending.parent)


def mark_pending_branding_launched():
    if (pending_branding_dir() / "nonce").is_file():
        pending_branding_launch_marker().write_text("", encoding="utf-8")


def live_database_has_nonce(nonce):
    try:
        connection = sqlite3.connect(f"file:{database.DATABASE_PATH}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT 1 FROM branding_restore WHERE nonce = ?", (nonce,)
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return row is not None


def clear_database_nonce(nonce):
    connection = sqlite3.connect(database.DATABASE_PATH)
    try:
        connection.execute("DELETE FROM branding_restore WHERE nonce = ?", (nonce,))
        connection.commit()
    finally:
        connection.close()


def read_restore_state():
    try:
        return USB_RESTORE_STATUS.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def finalize_pending_branding(startup=False):
    """Apply the staged logo change once the restore is durably committed.

    The helper starts the service and runs its health check before it commits
    the transaction, and rolls the database back if that check fails, so the
    nonce in the live database alone does not prove success. While the helper
    reports "running" nothing is applied or discarded. Once it is not running
    the journal is resolved (committed or rolled back, also by the boot-time
    recovery that runs before this service), so the nonce is authoritative.
    """
    pending = pending_branding_dir()
    with branding_finalize_lock:
        try:
            nonce = (pending / "nonce").read_text(encoding="utf-8").strip()
            action = (pending / "action").read_text(encoding="utf-8")
        except OSError:
            return
        state = read_restore_state()
        if state == "running":
            return
        committed_state = state in {"success", "idle"} or (startup and state is None)
        if committed_state and live_database_has_nonce(nonce):
            try:
                if action == "set":
                    branding.save_custom_logo((pending / branding.LOGO_FILE_NAME).read_bytes())
                elif action == "clear":
                    branding.remove_custom_logo()
                clear_database_nonce(nonce)
            except (OSError, ValueError, sqlite3.Error) as error:
                app.logger.warning("No s'ha pogut aplicar el logo restaurat: %s", error)
                return
            discard_pending_branding()
            return
        if startup:
            discard_pending_branding()
            return
        try:
            launched = pending_branding_launch_marker().stat().st_mtime_ns
            status = USB_RESTORE_STATUS.stat().st_mtime_ns
        except OSError:
            return
        if status >= launched and state == "rollback":
            discard_pending_branding()


def load_or_create_session_key():
    SESSION_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SESSION_KEY_PATH.exists():
        value = SESSION_KEY_PATH.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_hex(32)
    SESSION_KEY_PATH.write_text(value + "\n", encoding="utf-8")
    SESSION_KEY_PATH.chmod(0o600)
    return value


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_or_create_session_key(),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

IDENTIFICATION_TTL_SECONDS = 60
USB_AUTHORIZATION_TTL_SECONDS = 120
identification_tokens = {}
usb_authorization_tokens = {}
usb_operation_lock = threading.Lock()
branding_finalize_lock = threading.Lock()
usb_pin_failures = {}
USB_PIN_MAX_FAILURES = 5
USB_PIN_LOCKOUT_SECONDS = 60
employee_pin_failures = []
employee_pin_lockout_until = 0
employee_pin_lockout_lock = threading.Lock()
EMPLOYEE_PIN_MAX_FAILURES = 5
EMPLOYEE_PIN_WINDOW_SECONDS = 60
EMPLOYEE_PIN_LOCKOUT_SECONDS = 60


def employee_pin_rate_limited():
    global employee_pin_failures, employee_pin_lockout_until
    now = time.monotonic()
    with employee_pin_lockout_lock:
        if now < employee_pin_lockout_until:
            return True
        employee_pin_failures = [
            attempt for attempt in employee_pin_failures
            if now - attempt < EMPLOYEE_PIN_WINDOW_SECONDS
        ]
        return False


def record_employee_pin_failure():
    global employee_pin_lockout_until
    now = time.monotonic()
    with employee_pin_lockout_lock:
        employee_pin_failures.append(now)
        employee_pin_failures[:] = [
            attempt for attempt in employee_pin_failures
            if now - attempt < EMPLOYEE_PIN_WINDOW_SECONDS
        ]
        if len(employee_pin_failures) >= EMPLOYEE_PIN_MAX_FAILURES:
            employee_pin_lockout_until = now + EMPLOYEE_PIN_LOCKOUT_SECONDS
            return True
    return False


def usb_pin_rate_limited():
    key = request.remote_addr or "local"
    now = time.monotonic()
    failures = [attempt for attempt in usb_pin_failures.get(key, []) if now - attempt < USB_PIN_LOCKOUT_SECONDS]
    usb_pin_failures[key] = failures
    return len(failures) >= USB_PIN_MAX_FAILURES


def record_usb_pin_failure():
    key = request.remote_addr or "local"
    usb_pin_failures.setdefault(key, []).append(time.monotonic())


def clear_usb_pin_failures():
    usb_pin_failures.pop(request.remote_addr or "local", None)



def create_identification_token(employee):
    token = secrets.token_urlsafe(32)
    identification_tokens[token] = {
        "employee_id": employee["id"],
        "method": "pin",
        "expires_at": time.monotonic() + IDENTIFICATION_TTL_SECONDS,
    }
    return token


def get_identification(token):
    identification = identification_tokens.get(token)
    if identification is None:
        return None
    if identification["expires_at"] < time.monotonic():
        identification_tokens.pop(token, None)
        return None
    return identification


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/branding/logo")
def branding_logo():
    finalize_pending_branding()
    custom_logo = branding.read_custom_logo()
    if custom_logo is None:
        response = send_from_directory(app.static_folder, "default-logo.svg")
    else:
        response = Response(custom_logo[0], mimetype=custom_logo[1])
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return response


@app.get("/api/admin/logo")
def admin_logo_status():
    return jsonify({"ok": True, "custom": branding.has_custom_logo()})


@app.post("/api/admin/logo")
def admin_upload_logo():
    if request.content_length is None:
        return jsonify({"ok": False, "error": "Cal indicar la mida del fitxer"}), 411
    if request.content_length > branding.MAX_LOGO_BYTES + 64 * 1024:
        return jsonify({"ok": False, "error": "El logo supera la mida màxima permesa (1 MB)"}), 413
    upload = request.files.get("logo")
    if upload is None:
        return jsonify({"ok": False, "error": "Cal seleccionar un fitxer"}), 400
    data = upload.stream.read(branding.MAX_LOGO_BYTES + 1)
    try:
        branding.save_custom_logo(data)
    except branding.LogoError as error:
        return jsonify({"ok": False, "error": error.message}), 400
    except OSError:
        return jsonify({"ok": False, "error": "No s'ha pogut desar el logo"}), 500
    return jsonify({"ok": True, "custom": True})


@app.delete("/api/admin/logo")
def admin_remove_logo():
    try:
        branding.remove_custom_logo()
    except OSError:
        return jsonify({"ok": False, "error": "No s'ha pogut eliminar el logo"}), 500
    return jsonify({"ok": True, "custom": False})


@app.route("/admin")
def admin():
    if "admin_user_id" not in session:
        return redirect(url_for("admin_login_page"))
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return render_template("admin.html", csrf_token=session["csrf_token"])


@app.get("/admin/login")
def admin_login_page():
    if "admin_user_id" in session:
        return redirect(url_for("admin"))
    return render_template("admin_login.html")


@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    admin_user = authenticate_admin(username, password)
    if admin_user is None:
        return jsonify({"ok": False, "error": "Usuari o contrasenya incorrectes"}), 401

    session.clear()
    session.permanent = True
    session["admin_user_id"] = admin_user["id"]
    session["admin_username"] = admin_user["username"]
    session["admin_session_version"] = admin_user["updated_at"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({
        "ok": True,
        "username": admin_user["username"],
        "csrf_token": session["csrf_token"],
    })


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify({"ok": True})


@app.before_request
def require_admin_authentication():
    if request.path.startswith("/api/admin/") and request.endpoint != "admin_login":
        if "admin_user_id" not in session:
            return jsonify({"ok": False, "error": "Autenticació requerida"}), 401

        current_version = get_active_admin_session_version(session["admin_user_id"])
        if (
            current_version is None
            or current_version != session.get("admin_session_version")
        ):
            session.clear()
            return jsonify({
                "ok": False,
                "error": "La sessió d'administrador ja no és vàlida. Torna a iniciar sessió",
            }), 401

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_token = request.headers.get("X-CSRF-Token", "")
            if not csrf_token or not secrets.compare_digest(
                csrf_token, session.get("csrf_token", "")
            ):
                return jsonify({"ok": False, "error": "Token CSRF no vàlid"}), 403


@app.post("/api/admin/change-pin")
def admin_change_pin():
    data = request.get_json(silent=True) or {}
    new_pin = str(data.get("new_pin", ""))
    confirmation = str(data.get("confirmation", ""))
    if new_pin != confirmation:
        return jsonify({"ok": False, "error": "Els PIN no coincideixen"}), 400
    try:
        set_admin_pin(session["admin_user_id"], new_pin)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True})


@app.post("/api/admin/change-password")
def admin_change_password():
    data = request.get_json(silent=True) or {}
    new_password = str(data.get("new_password", ""))
    confirmation = str(data.get("confirmation", ""))
    if new_password != confirmation:
        return jsonify({"ok": False, "error": "Les contrasenyes no coincideixen"}), 400
    try:
        change_admin_password(
            session["admin_user_id"],
            data.get("current_password", ""),
            new_password,
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    session.clear()
    return jsonify({"ok": True})


@app.get("/api/admin/settings")
def admin_settings():
    return jsonify({
        "ok": True,
        "settings": get_settings(),
        "system": {
            "version": "0.1.0",
            "timezone": "Europe/Madrid",
            "time": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="seconds"),
            "database": "OK",
        },
    })


@app.put("/api/admin/settings")
def admin_update_settings():
    data = request.get_json(silent=True) or {}
    try:
        settings = update_settings(
            data.get("terminal_name", ""),
            data.get("terminal_id", ""),
            data.get("sound_volume", 20),
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    return jsonify({"ok": True, "settings": settings})


@app.get("/api/admin/employees")
def admin_employees():
    return jsonify({"ok": True, "employees": list_employees()})


@app.get("/api/admin/punches")
def admin_punches():
    employee_filter = request.args.get("employee_id", "")
    terminal_only = employee_filter == "terminal"
    employee_id = None if terminal_only else request.args.get("employee_id", type=int)
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    return jsonify({
        "ok": True,
        "punches": list_punches(employee_id, date_from, date_to)
    })


@app.get("/api/admin/export.csv")
def admin_export_csv():
    employee_id = request.args.get("employee_id", type=int)
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    punches = list_punches(employee_id, date_from, date_to)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Data", "Hora", "Treballador", "Tipus", "Metode", "Incidencia"])

    for punch in punches:
        timestamp = punch["timestamp"]
        date, time = timestamp[:10], timestamp[11:19]
        writer.writerow([
            date,
            time,
            punch["employee_name"],
            "Entrada" if punch["type"] == "entrada" else "Sortida",
            punch["method"],
            punch["note"] if punch["incident"] else ""
        ])

    filename = "fitxatges.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/api/admin/timeline")
def admin_timeline():
    employee_filter = request.args.get("employee_id", "")
    terminal_only = employee_filter == "terminal"
    employee_id = None if terminal_only else request.args.get("employee_id", type=int)
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    items = [] if terminal_only else [
        {"kind": "punch", **item}
        for item in list_punches(employee_id, date_from, date_to)
    ]
    if terminal_only or not employee_id:
        items.extend(
            {"kind": "terminal_event", **item}
            for item in list_terminal_events(date_from, date_to)
        )
    items.sort(key=lambda item: (item["timestamp"], item["id"]), reverse=True)
    return jsonify({"ok": True, "items": items})


@app.get("/api/admin/terminal-events.csv")
def admin_terminal_events_csv():
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    events = list_terminal_events(date_from, date_to)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Data", "Hora", "Tipus", "Detall"])
    for event in events:
        writer.writerow([
            event["timestamp"][:10], event["timestamp"][11:19],
            event["type"], event["detail"]
        ])
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="esdeveniments-terminal.csv"'}
    )


@app.post("/api/admin/employees")
def admin_create_employee():
    data = request.get_json(silent=True) or {}
    try:
        employee_id = create_employee(str(data.get("name", "")), str(data.get("pin", "")))
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True, "employee_id": employee_id}), 201


@app.patch("/api/admin/employees/<int:employee_id>")
def admin_update_employee(employee_id):
    data = request.get_json(silent=True) or {}
    try:
        employee = update_employee(
            employee_id,
            name=data.get("name"),
            pin=data.get("pin"),
            active=data.get("active")
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    if employee is None:
        return jsonify({"ok": False, "error": "Empleat no trobat"}), 404
    return jsonify({"ok": True, "employee": employee})


@app.patch("/api/admin/punches/<int:punch_id>")
def admin_correct_punch(punch_id):
    data = request.get_json(silent=True) or {}
    try:
        employee_id = int(data.get("employee_id"))
        local_timestamp = datetime.fromisoformat(str(data.get("timestamp", "")).strip())
        if local_timestamp.tzinfo is not None:
            raise ValueError("La data i hora de la correcció han de ser locals")
        timestamp = local_timestamp.replace(
            tzinfo=ZoneInfo("Europe/Madrid")
        ).isoformat(timespec="seconds")
        punch = correct_punch(
            punch_id,
            session["admin_user_id"],
            employee_id,
            timestamp,
            data.get("type", ""),
            data.get("reason", ""),
        )
    except (TypeError, ValueError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    if punch is None:
        return jsonify({"ok": False, "error": "Fitxatge no trobat"}), 404
    return jsonify({"ok": True, "punch": punch})


@app.post("/api/admin/punches/<int:punch_id>/incident-review")
def admin_review_punch_incident(punch_id):
    data = request.get_json(silent=True) or {}
    try:
        review = set_punch_incident_status(
            punch_id,
            session["admin_user_id"],
            data.get("status", "reviewed"),
            data.get("note", ""),
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    if review is None:
        return jsonify({"ok": False, "error": "Fitxatge no trobat"}), 404
    return jsonify({"ok": True, "review": review})


@app.get("/api/admin/punches/<int:punch_id>/incident-reviews")
def admin_punch_incident_reviews(punch_id):
    return jsonify({
        "ok": True,
        "reviews": list_punch_incident_reviews(punch_id),
    })


@app.get("/api/admin/punches/<int:punch_id>/corrections")
def admin_punch_corrections(punch_id):
    return jsonify({"ok": True, "corrections": list_punch_corrections(punch_id)})


def get_usb_status():
    state_device = None
    if USB_STATE_FILE.exists():
        state_device = USB_STATE_FILE.read_text(encoding="utf-8").strip() or None

    mounted = USB_MOUNTPOINT.is_mount()

    if state_device is None and not mounted:
        return {"state": "absent", "device": None}

    if state_device is not None and mounted:
        try:
            mounted_device = subprocess.run(
                ["findmnt", "-no", "SOURCE", "--target", str(USB_MOUNTPOINT)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return {"state": "error", "device": state_device}

        if mounted_device == state_device:
            return {"state": "available", "device": state_device}

    return {"state": "error", "device": state_device}


def list_usb_backups():
    backups = []
    for archive_path in sorted(
        USB_MOUNTPOINT.glob("timeclockpi-backup-*.zip"),
        key=lambda path: path.name,
        reverse=True,
    ):
        try:
            manifest = verify_backup(archive_path)
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
        backups.append({
            "filename": archive_path.name,
            "created_at": manifest["created_at"],
        })
    return backups


@app.post("/api/admin/usb/backup")
def usb_create_backup():
    if get_usb_status()["state"] != "available":
        return jsonify({"ok": False, "error": "No hi ha cap dispositiu USB disponible"}), 409
    if not usb_operation_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Ja hi ha una operació USB en curs"}), 409

    try:
        archive_path = create_backup(USB_MOUNTPOINT)
        manifest = verify_backup(archive_path)
        create_terminal_event(
            "usb_backup_completed",
            f"Administrador ID {session['admin_user_id']}; fitxer {archive_path.name}",
        )
        return jsonify({
            "ok": True,
            "filename": archive_path.name,
            "created_at": manifest["created_at"],
        }), 201
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        create_terminal_event(
            "usb_backup_failed",
            f"Administrador ID {session['admin_user_id']}; {error}",
        )
        return jsonify({"ok": False, "error": f"No s'ha pogut crear la còpia: {error}"}), 500
    finally:
        usb_operation_lock.release()


@app.get("/api/admin/usb/backups")
def usb_backups():
    if get_usb_status()["state"] != "available":
        return jsonify({"ok": False, "error": "No hi ha cap dispositiu USB disponible"}), 409
    return jsonify({"ok": True, "backups": list_usb_backups()})


@app.post("/api/admin/usb/authorize-restore")
def usb_authorize_restore():
    if get_usb_status()["state"] != "available":
        return jsonify({"ok": False, "error": "No hi ha cap dispositiu USB disponible"}), 409

    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename", ""))

    if Path(filename).name != filename or not filename.startswith("timeclockpi-backup-") or not filename.endswith(".zip"):
        return jsonify({"ok": False, "error": "Nom de còpia no vàlid"}), 400

    archive_path = USB_MOUNTPOINT / filename
    try:
        verify_backup(archive_path)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        return jsonify({"ok": False, "error": f"Còpia no vàlida: {error}"}), 400

    token = secrets.token_urlsafe(32)
    usb_authorization_tokens[token] = {
        "admin_user_id": session["admin_user_id"],
        "operation": "restore",
        "filename": filename,
        "expires_at": time.monotonic() + USB_AUTHORIZATION_TTL_SECONDS,
    }
    return jsonify({"ok": True, "authorization_token": token})


@app.post("/api/admin/usb/prepare-restore")
def usb_prepare_restore():
    data = request.get_json(silent=True) or {}
    token = str(data.get("authorization_token", ""))
    authorization = usb_authorization_tokens.pop(token, None)

    if authorization is None:
        return jsonify({"ok": False, "error": "Autorització no vàlida"}), 401
    if authorization["expires_at"] < time.monotonic():
        return jsonify({"ok": False, "error": "Autorització caducada"}), 401
    if authorization["operation"] != "restore":
        return jsonify({"ok": False, "error": "Autorització no vàlida"}), 403
    if authorization["admin_user_id"] != session["admin_user_id"]:
        return jsonify({"ok": False, "error": "Autorització no vàlida"}), 403
    if get_usb_status()["state"] != "available":
        return jsonify({"ok": False, "error": "El dispositiu USB no està disponible"}), 409

    archive_path = USB_MOUNTPOINT / authorization["filename"]
    try:
        staging_dir = USB_RESTORE_DIR / "data"
        prepare_dir = USB_RESTORE_DIR / "prepare"
        if prepare_dir.exists():
            shutil.rmtree(prepare_dir)
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        restore_backup(archive_path, prepare_dir)
        stage_pending_branding(prepare_dir)
        (prepare_dir / "data").replace(staging_dir)
        shutil.rmtree(prepare_dir)
    except sqlite3.Error:
        app.logger.exception("Restore preparation failed")
        return jsonify({"ok": False, "error": "No s'ha pogut preparar la restauració"}), 500
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        return jsonify({"ok": False, "error": f"No s'ha pogut preparar la restauració: {error}"}), 500

    apply_token = secrets.token_urlsafe(32)
    usb_authorization_tokens[apply_token] = {
        "admin_user_id": authorization["admin_user_id"],
        "operation": "apply-restore",
        "filename": authorization["filename"],
        "expires_at": time.monotonic() + USB_AUTHORIZATION_TTL_SECONDS,
    }

    return jsonify({
        "ok": True,
        "filename": authorization["filename"],
        "prepared": True,
        "apply_token": apply_token,
    })


@app.post("/api/admin/usb/apply-restore")
def usb_apply_restore():
    data = request.get_json(silent=True) or {}
    token = str(data.get("apply_token", ""))
    confirmation = str(data.get("confirmation", ""))
    authorization = usb_authorization_tokens.pop(token, None)

    if authorization is None:
        return jsonify({"ok": False, "error": "Confirmació no vàlida"}), 401
    if authorization["expires_at"] < time.monotonic():
        return jsonify({"ok": False, "error": "Confirmació caducada"}), 401
    if authorization["operation"] != "apply-restore":
        return jsonify({"ok": False, "error": "Confirmació no vàlida"}), 403
    if authorization["admin_user_id"] != session["admin_user_id"]:
        return jsonify({"ok": False, "error": "Confirmació no vàlida"}), 403
    if confirmation != "RESTAURAR":
        return jsonify({"ok": False, "error": "Cal confirmar explícitament la restauració"}), 400

    staging_database = USB_RESTORE_DIR / "data" / "timeclock.db"
    if not staging_database.is_file():
        return jsonify({"ok": False, "error": "No hi ha cap restauració preparada"}), 409

    mark_pending_branding_launched()

    try:
        subprocess.run(
            [
                "sudo",
                "-n",
                "/usr/local/lib/timeclockpi/timeclockpi-restore-launch",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        return jsonify({
            "ok": False,
            "error": f"No s'ha pogut iniciar la restauració: {error}",
        }), 500

    return jsonify({
        "ok": True,
        "filename": authorization["filename"],
        "restore_started": True,
    }), 202


@app.get("/api/admin/usb/restore-status")
def usb_restore_status():
    result_path = USB_RESTORE_STATUS
    try:
        state = result_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        state = "idle"
    except OSError as error:
        return jsonify({"ok": False, "error": f"No s'ha pogut llegir l'estat: {error}"}), 500

    if state not in {"idle", "running", "success", "rollback"}:
        state = "unknown"
    finalize_pending_branding()
    return jsonify({"ok": True, "state": state})


@app.post("/api/usb/authorize-export")
def usb_authorize_export():
    if get_usb_status()["state"] != "available":
        return jsonify({"ok": False, "error": "No hi ha cap dispositiu USB disponible"}), 409

    if usb_pin_rate_limited():
        return jsonify({"ok": False, "error": "Massa intents incorrectes. Espera un minut i torna-ho a provar"}), 429

    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", ""))
    admin_user = authenticate_admin_pin(pin)
    if admin_user is None:
        record_usb_pin_failure()
        create_terminal_event("usb_export_auth_failed", "Intent de PIN d'administrador incorrecte")
        return jsonify({"ok": False, "error": "PIN d'administrador incorrecte"}), 401

    clear_usb_pin_failures()
    create_terminal_event("usb_export_authorized", f"Administrador: {admin_user['username']}")

    token = secrets.token_urlsafe(32)
    usb_authorization_tokens[token] = {
        "admin_user_id": admin_user["id"],
        "operation": "export",
        "expires_at": time.monotonic() + 90,
    }
    return jsonify({"ok": True, "authorization_token": token})


@app.post("/api/usb/export")
def usb_export():
    data = request.get_json(silent=True) or {}
    token = str(data.get("authorization_token", ""))
    authorization = usb_authorization_tokens.pop(token, None)

    if authorization is None:
        return jsonify({"ok": False, "error": "Autorització no vàlida"}), 401
    if authorization["expires_at"] < time.monotonic():
        return jsonify({"ok": False, "error": "Autorització caducada"}), 401
    if authorization["operation"] != "export":
        return jsonify({"ok": False, "error": "Autorització no vàlida"}), 403
    if get_usb_status()["state"] != "available":
        return jsonify({"ok": False, "error": "El dispositiu USB no està disponible"}), 409
    if not usb_operation_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Ja hi ha una operació USB en curs"}), 409

    try:
        employee_id = data.get("employee_id")
        date_from = data.get("date_from") or None
        date_to = data.get("date_to") or None
        punches = list_punches(int(employee_id) if employee_id not in (None, "", "all") else None, date_from, date_to)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Data", "Hora", "Treballador", "Tipus", "Metode", "Incidencia"])
        for punch in punches:
            writer.writerow([
                punch["timestamp"][:10],
                punch["timestamp"][11:19],
                punch["employee_name"],
                "Entrada" if punch["type"] == "entrada" else "Sortida",
                punch["method"],
                punch["note"] if punch["incident"] else "",
            ])

        timestamp = datetime.now(ZoneInfo("Europe/Madrid"))
        filename = f"fitxatges-{timestamp.strftime('%Y%m%d-%H%M%S')}.csv"
        target = USB_MOUNTPOINT / filename
        temp = USB_MOUNTPOINT / f".{filename}.partial"

        try:
            with temp.open("w", encoding="utf-8", newline="") as handle:
                handle.write("\ufeff")
                handle.write(output.getvalue())
                handle.flush()
                import os
                os.fsync(handle.fileno())
            temp.replace(target)
            expected = ("\ufeff" + output.getvalue()).encode("utf-8")
            if target.read_bytes() != expected:
                raise OSError("La verificació del fitxer exportat ha fallat")
        except OSError as error:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return jsonify({"ok": False, "error": f"No s'ha pogut escriure l'exportació: {error}"}), 500

        try:
            subprocess.run(
                ["sudo", "-n", "/usr/local/lib/timeclockpi/timeclockpi-usb-eject"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            return jsonify({
                "ok": False,
                "error": f"Fitxatges exportats i verificats, però no s'ha pogut expulsar l'USB: {detail.strip()}",
            }), 500

        create_terminal_event(
            "usb_export_completed",
            f"Administrador ID {authorization['admin_user_id']}; fitxer {filename}; {len(punches)} fitxatges",
        )
        return jsonify({
            "ok": True,
            "filename": filename,
            "count": len(punches),
            "ejected": True,
        })
    finally:
        usb_operation_lock.release()


@app.get("/api/usb/status")
def usb_status():
    return jsonify({"ok": True, "usb": get_usb_status()})


@app.get("/api/settings")
def public_settings():
    settings = get_settings()
    return jsonify({
        "ok": True,
        "settings": {
            "terminal_name": settings["terminal_name"],
            "sound_volume": settings["sound_volume"],
        },
    })


@app.post("/api/identify")
def identify():
    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", ""))

    if not pin:
        return jsonify({"ok": False, "error": "PIN requerit"}), 400

    if employee_pin_rate_limited():
        return jsonify({
            "ok": False,
            "error": "PIN incorrecte o identificació temporalment limitada",
        }), 429

    employee = find_employee_by_pin(pin)

    if employee is None:
        if record_employee_pin_failure():
            create_terminal_event(
                "employee_pin_rate_limited",
                "S'ha activat el límit d'intents de PIN d'empleat",
            )
            return jsonify({
                "ok": False,
                "error": "PIN incorrecte o identificació temporalment limitada",
            }), 429
        return jsonify({"ok": False, "error": "PIN incorrecte"}), 401

    return jsonify({
        "ok": True,
        "employee": employee,
        "identification_token": create_identification_token(employee)
    })


@app.post("/api/punch")
def punch():
    data = request.get_json(silent=True) or {}
    punch_type = data.get("type")
    token = str(data.get("identification_token", ""))
    confirm_incident = bool(data.get("confirm_incident", False))

    if punch_type not in ("entrada", "sortida"):
        return jsonify({"ok": False, "error": "Dades no vàlides"}), 400

    identification = get_identification(token)
    if identification is None:
        return jsonify({"ok": False, "error": "Identificació no vàlida o caducada"}), 401

    result = create_punch(
        identification["employee_id"], punch_type, identification["method"],
        confirm_incident=confirm_incident
    )

    if result is None:
        identification_tokens.pop(token, None)
        return jsonify({"ok": False, "error": "Empleat no vàlid"}), 404

    if not result["ok"]:
        if result.get("confirmation_required"):
            identification["expires_at"] = time.monotonic() + IDENTIFICATION_TTL_SECONDS
        else:
            identification_tokens.pop(token, None)
        return jsonify(result), 409

    identification_tokens.pop(token, None)
    return jsonify(result)


if __name__ == "__main__":
    init_database()
    app.run(host="0.0.0.0", port=8000)
