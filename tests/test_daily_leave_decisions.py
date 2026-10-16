from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from timeclock import database


TZ = ZoneInfo("Europe/Madrid")


def _record_intervals(
    employee_id, durations, *, policy="threshold", guaranteed=30, threshold=30,
    first_start=None, leave_type_id=None, leave_type_name="Esmorzar",
):
    if leave_type_id is None:
        leave_type_id = database.create_leave_type(
            leave_type_name, approval_policy=policy, auto_approve_minutes=threshold,
            guaranteed_daily_minutes=guaranteed,
        )
    first_start = first_start or datetime(2026, 10, 11, 10, 0, tzinfo=TZ)
    with database.get_connection() as db:
        existing_punch = db.execute(
            "SELECT 1 FROM punch WHERE employee_id = ? LIMIT 1", (employee_id,)
        ).fetchone()
        if existing_punch is None:
            earlier_punch = (first_start - timedelta(hours=1)).isoformat()
            db.execute("""
                INSERT INTO punch (employee_id, timestamp, type, method)
                VALUES (?, ?, 'entrada', 'pin')
            """, (employee_id, earlier_punch))

    start = first_start
    results = []
    for minutes in durations:
        opened = database.start_employee_leave(
            employee_id, leave_type_id, "sortida", now=start
        )
        result = database.finish_employee_leave(
            employee_id, now=start + timedelta(minutes=minutes)
        )
        results.append((opened["leave_id"], result))
        start += timedelta(minutes=minutes + 5)
    return leave_type_id, results


def _daily_decision(leave_id):
    with database.get_connection() as db:
        row = db.execute(
            "SELECT daily_decision_id FROM employee_leave WHERE id = ?",
            (leave_id,),
        ).fetchone()
    return database.get_daily_leave_decision_for_supervision(
        row["daily_decision_id"]
    )


def _admin_id():
    with database.get_connection() as db:
        return db.execute(
            "SELECT id FROM admin_user WHERE username = 'admin'"
        ).fetchone()["id"]


def test_daily_total_guarantee_and_single_supervisor_decision(client, employee):
    worker = employee()
    _, intervals = _record_intervals(worker["id"], [10, 12, 8, 7])
    decision = _daily_decision(intervals[0][0])

    assert len({result["daily_decision"]["id"] for _, result in intervals}) == 1
    assert decision["total_seconds"] == 37 * 60
    assert decision["status"] == "pending"
    assert decision["guaranteed_seconds"] == 30 * 60
    assert decision["excess_seconds"] == 7 * 60
    assert decision["recognized_seconds"] == 30 * 60
    assert len(decision["leaves"]) == 4
    assert len(database.list_daily_leave_decisions_for_supervision("approval")) == 1

    database.decide_daily_leave(
        decision["id"], "rejected", _admin_id(), "Excés no autoritzat"
    )
    rejected = database.get_daily_leave_decision_for_supervision(decision["id"])
    assert rejected["status"] == "rejected"
    assert rejected["recognized_seconds"] == 30 * 60

    database.decide_daily_leave(
        decision["id"], "approved", _admin_id(), "Excés justificat"
    )
    approved = database.get_daily_leave_decision_for_supervision(decision["id"])
    assert approved["status"] == "approved"
    assert approved["recognized_seconds"] == 37 * 60
    assert [item["action"] for item in approved["decision_history"]][-2:] == [
        "supervisor_decision", "supervisor_decision",
    ]


def test_daily_threshold_uses_total_across_intervals(client, employee):
    worker = employee()
    _, intervals = _record_intervals(worker["id"], [10, 15])
    assert intervals[-1][1]["status"] == "approved"
    assert _daily_decision(intervals[0][0])["total_seconds"] == 25 * 60

    worker = employee(name="Altres", pin="5678")
    _, intervals = _record_intervals(
        worker["id"], [10, 12, 8, 7], leave_type_name="Pausa llarga"
    )
    assert intervals[-1][1]["status"] == "pending"
    assert _daily_decision(intervals[0][0])["total_seconds"] == 37 * 60


def test_new_interval_invalidates_supervisor_approval_and_keeps_history(client, employee):
    worker = employee()
    _, intervals = _record_intervals(worker["id"], [10, 12, 8, 7])
    decision_id = intervals[0][1]["daily_decision"]["id"]
    database.decide_daily_leave(
        decision_id, "approved", _admin_id(), "Excés justificat"
    )

    with database.get_connection() as db:
        leave_type_id = db.execute(
            "SELECT leave_type_id FROM employee_leave WHERE id = ?",
            (intervals[0][0],),
        ).fetchone()["leave_type_id"]
    _, more_intervals = _record_intervals(
        worker["id"], [5], first_start=datetime(2026, 10, 11, 11, 7, tzinfo=TZ),
        leave_type_id=leave_type_id,
    )

    current = database.get_daily_leave_decision_for_supervision(decision_id)
    assert more_intervals[0][1]["daily_decision"]["id"] == decision_id
    assert current["status"] == "pending"
    assert current["total_seconds"] == 42 * 60
    assert current["recognized_seconds"] == 30 * 60
    assert [item["action"] for item in current["decision_history"]][-2:] == [
        "supervisor_decision", "invalidated",
    ]


def test_regularization_updates_daily_total_and_invalidates_decision(client, employee):
    worker = employee()
    leave_type_id, intervals = _record_intervals(
        worker["id"], [37], policy="manual", guaranteed=30, threshold=None
    )
    decision_id = intervals[0][1]["daily_decision"]["id"]
    database.decide_daily_leave(
        decision_id, "approved", _admin_id(), "Excés revisat"
    )

    start = "2026-10-11T11:00:00+02:00"
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'sortida', 'pin')
        """, (worker["id"], start)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, status, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'pending', 'needs_regularization', 1, ?)
        """, (worker["id"], leave_type_id, start, punch_id)).lastrowid

    database.classify_employee_leave_departure(
        leave_id, "return", _admin_id()
    )
    database.regularize_employee_leave_return(
        leave_id, "2026-10-11T11:10:00+02:00", _admin_id(),
        "Retorn confirmat",
    )

    current = database.get_daily_leave_decision_for_supervision(decision_id)
    assert current["total_seconds"] == 47 * 60
    assert current["status"] == "pending"
    assert current["recognized_seconds"] == 30 * 60
    assert current["decision_history"][-1]["action"] == "invalidated"


def test_zero_duration_supervised_regularization_updates_status_without_total_change(
    client, employee
):
    worker = employee()
    leave_type_id, intervals = _record_intervals(
        worker["id"], [10], policy="manual", guaranteed=30, threshold=None
    )
    decision_id = intervals[0][1]["daily_decision"]["id"]
    assert database.get_daily_leave_decision_for_supervision(
        decision_id
    )["status"] == "approved"

    actual = "2026-10-11T10:30:00+02:00"
    with database.get_connection() as db:
        punch_id = db.execute("""
            INSERT INTO punch (employee_id, timestamp, type, method)
            VALUES (?, ?, 'entrada', 'pin')
        """, (worker["id"], actual)).lastrowid
        leave_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, status, record_state,
                 requires_supervisor, start_punch_id)
            VALUES (?, ?, ?, 'pending', 'needs_regularization', 1, ?)
        """, (worker["id"], leave_type_id, actual, punch_id)).lastrowid

    database.regularize_employee_leave_late_arrival(
        leave_id, actual, _admin_id(), "Entrada verificada"
    )
    decision = database.get_daily_leave_decision_for_supervision(decision_id)
    assert decision["total_seconds"] == 10 * 60
    assert decision["status"] == "pending"
    history_entry = decision["decision_history"][-1]
    assert history_entry["action"] == "total_changed"
    assert history_entry["total_seconds"] == 10 * 60
    assert history_entry["approval_policy"] == "manual"
    assert history_entry["auto_approve_minutes"] is None
    assert history_entry["guaranteed_daily_minutes"] == 30


def test_existing_daily_group_keeps_original_type_configuration(client, employee):
    worker = employee()
    leave_type_id, intervals = _record_intervals(worker["id"], [10, 12, 8, 7])
    decision_id = intervals[0][1]["daily_decision"]["id"]
    database.decide_daily_leave(
        decision_id, "approved", _admin_id(), "Excés revisat"
    )

    database.update_leave_type(
        leave_type_id, "Esmorzar", "manual", None, None, True,
        guaranteed_daily_minutes=5,
    )
    _record_intervals(
        worker["id"], [1], policy="manual", guaranteed=5, threshold=None,
        leave_type_id=leave_type_id,
        first_start=datetime(2026, 10, 11, 11, 0, tzinfo=TZ),
    )

    decision = database.get_daily_leave_decision_for_supervision(decision_id)
    assert decision["total_seconds"] == 38 * 60
    assert decision["approval_policy"] == "threshold"
    assert decision["auto_approve_minutes"] == 30
    assert decision["guaranteed_daily_minutes"] == 30
    assert decision["status"] == "pending"
    assert decision["recognized_seconds"] == 30 * 60
    invalidation = decision["decision_history"][-1]
    assert invalidation["action"] == "invalidated"
    assert invalidation["approval_policy"] == "threshold"
    assert invalidation["auto_approve_minutes"] == 30
    assert invalidation["guaranteed_daily_minutes"] == 30

    _, next_day_intervals = _record_intervals(
        worker["id"], [1], leave_type_id=leave_type_id,
        first_start=datetime(2026, 10, 12, 10, 0, tzinfo=TZ),
    )
    next_day = _daily_decision(next_day_intervals[0][0])
    assert next_day["approval_policy"] == "manual"
    assert next_day["auto_approve_minutes"] is None
    assert next_day["guaranteed_daily_minutes"] == 5


def test_manual_zero_guarantee_recognizes_time_only_after_approval(client, employee):
    worker = employee()
    _, intervals = _record_intervals(
        worker["id"], [15], policy="manual", guaranteed=0, threshold=None
    )
    decision = _daily_decision(intervals[0][0])
    assert decision["status"] == "pending"
    assert decision["recognized_seconds"] == 0

    database.decide_daily_leave(
        decision["id"], "approved", _admin_id(), "Permís justificat"
    )
    assert database.get_daily_leave_decision_for_supervision(
        decision["id"]
    )["recognized_seconds"] == 15 * 60


def test_manual_guarantee_covers_short_day_without_excess_review(client, employee):
    worker = employee()
    _, intervals = _record_intervals(
        worker["id"], [10], policy="manual", guaranteed=30, threshold=None
    )
    decision = _daily_decision(intervals[0][0])
    assert decision["status"] == "approved"
    assert decision["decision_source"] == "system"
    assert decision["total_seconds"] == 10 * 60
    assert decision["recognized_seconds"] == 10 * 60
    assert database.list_daily_leave_decisions_for_supervision("approval") == []


def test_daily_grouping_uses_madrid_local_date(client, employee):
    worker = employee()
    first_start = datetime(2026, 10, 10, 23, 50, tzinfo=timezone.utc)
    _, intervals = _record_intervals(
        worker["id"], [10], first_start=first_start
    )
    decision = _daily_decision(intervals[0][0])
    assert decision["local_date"] == "2026-10-11"


def test_cross_midnight_leave_is_not_silently_added_to_a_daily_group(client, employee):
    worker = employee()
    start = datetime(2026, 10, 11, 23, 55, tzinfo=TZ)
    _, intervals = _record_intervals(worker["id"], [10], first_start=start)
    leave_id, result = intervals[0]
    assert result["crosses_local_day"]
    assert result["daily_decision"] is None
    with database.get_connection() as db:
        leave = db.execute(
            "SELECT status, requires_supervisor, daily_decision_id "
            "FROM employee_leave WHERE id = ?", (leave_id,)
        ).fetchone()
    assert leave["status"] == "pending"
    assert leave["requires_supervisor"] == 1
    assert leave["daily_decision_id"] is None


def test_new_daily_groups_do_not_reinterpret_legacy_individual_decisions(client, employee):
    worker = employee()
    leave_type_id = database.create_leave_type(
        "Esmorzar", guaranteed_daily_minutes=30
    )
    with database.get_connection() as db:
        legacy_id = db.execute("""
            INSERT INTO employee_leave
                (employee_id, leave_type_id, started_at, ended_at,
                 record_state, status)
            VALUES (?, ?, '2026-10-11T09:00:00+02:00',
                    '2026-10-11T09:20:00+02:00', 'finished', 'approved')
        """, (worker["id"], leave_type_id)).lastrowid
        admin_id = db.execute(
            "SELECT id FROM admin_user WHERE username = 'admin'"
        ).fetchone()["id"]
        db.execute("""
            INSERT INTO employee_leave_decision_history
                (leave_id, admin_user_id, changed_at, previous_status,
                 new_status, reason)
            VALUES (?, ?, '2026-10-11T09:21:00+02:00', 'pending',
                    'approved', 'Legacy approval')
        """, (legacy_id, admin_id))
    _, intervals = _record_intervals(
        worker["id"], [10], leave_type_id=leave_type_id
    )

    decision = _daily_decision(intervals[0][0])
    with database.get_connection() as db:
        legacy = db.execute(
            "SELECT status, daily_decision_id FROM employee_leave WHERE id = ?",
            (legacy_id,),
        ).fetchone()
        legacy_history = db.execute("""
            SELECT previous_status, new_status, reason
            FROM employee_leave_decision_history WHERE leave_id = ?
        """, (legacy_id,)).fetchall()
    assert decision["total_seconds"] == 10 * 60
    assert decision["guaranteed_seconds"] == 10 * 60
    assert decision["recognized_seconds"] == 10 * 60
    assert [leave["id"] for leave in decision["leaves"]] == [intervals[0][0]]
    assert legacy["status"] == "approved"
    assert legacy["daily_decision_id"] is None
    assert [tuple(row) for row in legacy_history] == [
        ("pending", "approved", "Legacy approval")
    ]
    assert len(database.list_employee_leaves_for_supervision("all")) == 1


def test_daily_decision_api_requires_authentication_and_csrf(client):
    assert client.get("/api/admin/daily-leave-decisions").status_code == 401
    login = client.post("/api/admin/login", json={
        "username": "admin", "password": "test-administrator-password",
    })
    assert login.status_code == 200
    response = client.post(
        "/api/admin/daily-leave-decisions/1/decision",
        json={"status": "approved", "reason": "Revisat"},
    )
    assert response.status_code == 403


def test_daily_decision_api_lists_details_and_persists_history(
    admin_client, employee
):
    worker = employee()
    _, intervals = _record_intervals(worker["id"], [10, 12, 8, 7])
    decision_id = intervals[0][1]["daily_decision"]["id"]

    listing = admin_client.get(
        "/api/admin/daily-leave-decisions?filter=approval"
    )
    assert listing.status_code == 200
    assert [row["id"] for row in listing.get_json()["daily_decisions"]] == [
        decision_id
    ]
    invalid_filter = admin_client.get(
        "/api/admin/daily-leave-decisions?filter=invalid"
    )
    assert invalid_filter.status_code == 400
    assert invalid_filter.get_json()["error"] == "Filtre de decisions diàries no vàlid"
    detail = admin_client.get(
        f"/api/admin/daily-leave-decisions/{decision_id}"
    )
    assert detail.status_code == 200
    assert len(detail.get_json()["daily_decision"]["leaves"]) == 4

    invalid_decision = admin_client.post(
        f"/api/admin/daily-leave-decisions/{decision_id}/decision",
        json={"status": "partial", "reason": "No parcial"},
    )
    assert invalid_decision.status_code == 400
    assert invalid_decision.get_json()["error"] == (
        "No s'ha pogut registrar la decisió diària. Revisa les dades i l'estat del còmput."
    )
    response = admin_client.post(
        f"/api/admin/daily-leave-decisions/{decision_id}/decision",
        json={"status": "approved", "reason": "Excés revisat"},
    )
    assert response.status_code == 200
    detail = admin_client.get(
        f"/api/admin/daily-leave-decisions/{decision_id}"
    ).get_json()["daily_decision"]
    assert detail["status"] == "approved"
    assert detail["decision_history"][-1]["reviewer_name"] == "admin"
    assert detail["decision_history"][-1]["reason"] == "Excés revisat"

    legacy_action = admin_client.post(
        f"/api/admin/leaves/{intervals[0][0]}/decision",
        json={"status": "rejected", "reason": "No"},
    )
    assert legacy_action.status_code == 400


def test_supervisor_can_access_daily_decision_review(client, employee):
    worker = employee()
    _, intervals = _record_intervals(worker["id"], [10, 12, 8, 7])
    decision_id = intervals[0][1]["daily_decision"]["id"]
    database.create_admin_user(
        "daily-supervisor", "supervisor-password-123", role="supervisor"
    )
    login = client.post("/api/admin/login", json={
        "username": "daily-supervisor",
        "password": "supervisor-password-123",
    })
    assert login.status_code == 200
    csrf_token = login.get_json()["csrf_token"]

    listing = client.get("/api/admin/daily-leave-decisions?filter=approval")
    assert listing.status_code == 200
    response = client.post(
        f"/api/admin/daily-leave-decisions/{decision_id}/decision",
        headers={"X-CSRF-Token": csrf_token},
        json={"status": "rejected", "reason": "No autoritzat"},
    )
    assert response.status_code == 200


def test_daily_decision_migration_is_idempotent_and_auditable(client):
    database.init_database()
    database.init_database()
    with database.get_connection() as db:
        leave_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(employee_leave)")
        }
        decision_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(daily_leave_decision)")
        }
        history_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(daily_leave_decision_history)")
        }
    assert "daily_decision_id" in leave_columns
    assert {
        "employee_id", "leave_type_id", "local_date", "status",
        "total_seconds", "approval_policy", "auto_approve_minutes",
        "guaranteed_daily_minutes",
    } <= decision_columns
    assert {
        "decision_id", "admin_user_id", "action", "previous_status",
        "new_status", "total_seconds", "reason",
    } <= history_columns


def test_daily_decision_rejects_partial_and_invalid_decisions(client, employee):
    worker = employee()
    _, intervals = _record_intervals(worker["id"], [10, 12, 8, 7])
    decision_id = intervals[0][1]["daily_decision"]["id"]
    with pytest.raises(ValueError, match="no vàlida"):
        database.decide_daily_leave(
            decision_id, "partially_approved", _admin_id(), "Parcial"
        )


def test_daily_supervision_ui_exposes_group_review_and_current_cache_version(
    admin_client,
):
    page = admin_client.get("/admin").get_data(as_text=True)
    script = (
        Path(__file__).resolve().parents[1] / "static" / "admin.js"
    ).read_text()
    assert "admin.js?v=7.14" in page
    assert "/api/admin/daily-leave-decisions" in script
    assert "Aprovar tot l’excés" in script
    assert "Rebutjar tot l’excés" in script
    assert "Historial auditable de la decisió diària" in script
