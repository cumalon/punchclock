from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
