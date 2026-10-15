from collections import defaultdict
from datetime import date, timedelta, timezone

from timeclock import database


def _parse_report_date(value, field):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Data {field} no vàlida")
    if parsed.isoformat() != value:
        raise ValueError(f"Data {field} no vàlida")
    return parsed


def _timestamp(value):
    parsed = database.parse_local_timestamp(value)
    return parsed.astimezone(database.LOCAL_TIMEZONE)


def _issue(employee_id, employee_name, local_date, category, description):
    return {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "date": local_date or "",
        "category": category,
        "description": description,
    }


def _union_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [(start, end) for start, end in merged]


def _duration(intervals):
    return sum(round((end - start).total_seconds()) for start, end in intervals)


def _limit_intervals(intervals, limit_seconds):
    limited = []
    remaining = limit_seconds
    for start, end in _union_intervals(intervals):
        if remaining <= 0:
            break
        duration = round((end - start).total_seconds())
        included = min(duration, remaining)
        limited.append((start, start + timedelta(seconds=included)))
        remaining -= included
    return limited


def _subtract_intervals(interval, occupied):
    start, end = interval
    available = [(start, end)]
    for used_start, used_end in occupied:
        remaining = []
        for part_start, part_end in available:
            if used_end <= part_start or used_start >= part_end:
                remaining.append((part_start, part_end))
                continue
            if used_start > part_start:
                remaining.append((part_start, used_start))
            if used_end < part_end:
                remaining.append((used_end, part_end))
        available = remaining
    return available


def _safe_local_date(value):
    try:
        return database.local_timestamp_date(value)
    except (TypeError, ValueError, OverflowError):
        return None


def build_hours_report(date_from, date_to, employee_id=None):
    first_day = _parse_report_date(date_from, "inicial")
    last_day = _parse_report_date(date_to, "final")
    if last_day < first_day:
        raise ValueError("La data final no pot ser anterior a la inicial")

    with database.get_connection() as db:
        employees_query = """
            SELECT id, name FROM employee
        """
        employees_params = []
        if employee_id is not None:
            employees_query += " WHERE id = ?"
            employees_params.append(employee_id)
        employees_query += " ORDER BY name COLLATE NOCASE, id"
        employees = [dict(row) for row in db.execute(
            employees_query, employees_params
        ).fetchall()]
        if employee_id is not None and not employees:
            raise ValueError("Treballador no trobat")

        punch_params = [date_from, date_to]
        punch_filter = (
            "(local_timestamp_date(p.timestamp) BETWEEN ? AND ? "
            "OR local_timestamp_date(p.timestamp) IS NULL)"
        )
        if employee_id is not None:
            punch_filter += " AND p.employee_id = ?"
            punch_params.append(employee_id)
        punches = [dict(row) for row in db.execute(f"""
            SELECT p.id, p.employee_id, p.timestamp, p.type, p.incident, p.note,
                   COALESCE(review.status, 'pending') AS incident_status,
                   review.note AS incident_review_note
            FROM punch p
            LEFT JOIN punch_incident_review review ON review.id = (
                SELECT r.id FROM punch_incident_review r
                WHERE r.punch_id = p.id ORDER BY r.id DESC LIMIT 1
            )
            WHERE {punch_filter}
            ORDER BY p.employee_id, utc_timestamp_sort_key(p.timestamp), p.id
        """, punch_params).fetchall()]

        leave_params = [date_from, date_to, date_from, date_to]
        leave_filter = """
            (local_timestamp_date(el.started_at) BETWEEN ? AND ?
             OR local_timestamp_date(el.ended_at) BETWEEN ? AND ?
             OR local_timestamp_date(el.started_at) IS NULL
             OR (el.ended_at IS NOT NULL
                 AND local_timestamp_date(el.ended_at) IS NULL))
        """
        if employee_id is not None:
            leave_filter += " AND el.employee_id = ?"
            leave_params.append(employee_id)
        leaves = [dict(row) for row in db.execute(f"""
            SELECT el.*, lt.name AS leave_type_name,
                   d.status AS daily_status,
                   d.guaranteed_daily_minutes,
                   d.local_date AS daily_local_date,
                   e.name AS employee_name
            FROM employee_leave el
            JOIN leave_type lt ON lt.id = el.leave_type_id
            JOIN employee e ON e.id = el.employee_id
            LEFT JOIN daily_leave_decision d ON d.id = el.daily_decision_id
            WHERE {leave_filter}
            ORDER BY el.employee_id, el.started_at, el.id
        """, leave_params).fetchall()]

    employee_names = {row["id"]: row["name"] for row in employees}
    day_data = {}
    issues = []

    def get_day(worker_id, local_date):
        key = worker_id, local_date
        if key not in day_data:
            day_data[key] = {
                "employee_id": worker_id,
                "employee_name": employee_names.get(worker_id, ""),
                "date": local_date,
                "worked_seconds": 0,
                "leave_seconds": 0,
                "total_seconds": 0,
                "leave_details": [],
            }
        return day_data[key]

    punch_days = defaultdict(list)
    for punch in punches:
        local_date = _safe_local_date(punch["timestamp"])
        if local_date is None:
            issues.append(_issue(
                punch["employee_id"], employee_names.get(punch["employee_id"], ""),
                "", "Fitxatge", f"Fitxatge #{punch['id']}: data o hora no vàlida",
            ))
            continue
        punch_days[(punch["employee_id"], local_date)].append(punch)
        if punch["incident"]:
            reviewed = punch["incident_status"] == "reviewed"
            issues.append(_issue(
                punch["employee_id"], employee_names.get(punch["employee_id"], ""),
                local_date, "Incidència revisada" if reviewed else "Incidència pendent",
                f"Fitxatge #{punch['id']}: "
                f"{punch['incident_review_note'] or punch['note'] or 'sense detall'}",
            ))
            get_day(punch["employee_id"], local_date)

    work_intervals = defaultdict(list)
    for (worker_id, local_date), day_punches in punch_days.items():
        current_entry = None
        for punch in day_punches:
            if punch["type"] == "entrada":
                if current_entry is not None:
                    issues.append(_issue(
                        worker_id, employee_names.get(worker_id, ""), local_date,
                        "Fitxatge incomplet",
                        f"Entrada #{current_entry['id']} sense sortida abans de "
                        f"l'entrada #{punch['id']}; no s'han atribuït hores.",
                    ))
                current_entry = punch
                continue
            if current_entry is None:
                issues.append(_issue(
                    worker_id, employee_names.get(worker_id, ""), local_date,
                    "Fitxatge incomplet",
                    f"Sortida #{punch['id']} sense entrada anterior; no s'han "
                    "atribuït hores.",
                ))
                continue

            start = _timestamp(current_entry["timestamp"]).astimezone(timezone.utc)
            end = _timestamp(punch["timestamp"]).astimezone(timezone.utc)
            pair = current_entry, punch
            current_entry = None
            if end <= start:
                issues.append(_issue(
                    worker_id, employee_names.get(worker_id, ""), local_date,
                    "Fitxatge invàlid",
                    f"El parell d'entrada/sortida #{pair[0]['id']}/#{pair[1]['id']} "
                    "no té una durada positiva.",
                ))
                continue
            unresolved_incident = any(
                member["incident"] and member["incident_status"] != "reviewed"
                for member in pair
            )
            if unresolved_incident:
                issues.append(_issue(
                    worker_id, employee_names.get(worker_id, ""), local_date,
                    "Treball pendent de revisió",
                    f"El període entre els fitxatges #{pair[0]['id']} i "
                    f"#{pair[1]['id']} no es compta fins a revisar les incidències.",
                ))
                continue
            work_intervals[(worker_id, local_date)].append((start, end))

        if current_entry is not None:
            issues.append(_issue(
                worker_id, employee_names.get(worker_id, ""), local_date,
                "Fitxatge incomplet",
                f"Entrada #{current_entry['id']} sense sortida; no s'han atribuït hores.",
            ))

    permission_groups = defaultdict(list)
    for leave in leaves:
        worker_id = leave["employee_id"]
        employee_name = leave["employee_name"]
        start_value = leave["started_at"]
        end_value = leave["ended_at"]
        if leave["regularization_kind"] == "late_arrival":
            start_value = leave["expected_started_at"]
            end_value = leave["started_at"]
        elif leave["regularization_kind"] == "early_departure":
            end_value = leave["expected_ended_at"]

        start_date = _safe_local_date(start_value) if start_value else None
        end_date = _safe_local_date(end_value) if end_value else None
        issue_date = (
            start_date if start_date and first_day.isoformat() <= start_date <= last_day.isoformat()
            else end_date if end_date and first_day.isoformat() <= end_date <= last_day.isoformat()
            else ""
        )
        if leave["record_state"] != "finished" or not end_value:
            issues.append(_issue(
                worker_id, employee_name, issue_date, "Permís incomplet",
                f"Permís #{leave['id']} ({leave['leave_type_name']}) sense durada "
                "regularitzada; no s'han atribuït minuts.",
            ))
            if issue_date:
                get_day(worker_id, issue_date)
            continue
        if start_date is None or end_date is None:
            issues.append(_issue(
                worker_id, employee_name, issue_date, "Permís invàlid",
                f"Permís #{leave['id']} ({leave['leave_type_name']}) té una data "
                "o hora no vàlida; no s'han atribuït minuts.",
            ))
            if issue_date:
                get_day(worker_id, issue_date)
            continue
        if start_date != end_date:
            issues.append(_issue(
                worker_id, employee_name, issue_date, "Permís nocturn",
                f"Permís #{leave['id']} travessa la mitjanit i queda fora del "
                "còmput de la primera versió.",
            ))
            if issue_date:
                get_day(worker_id, issue_date)
            continue
        if not first_day.isoformat() <= start_date <= last_day.isoformat():
            continue

        start = _timestamp(start_value).astimezone(timezone.utc)
        end = _timestamp(end_value).astimezone(timezone.utc)
        if end <= start:
            issues.append(_issue(
                worker_id, employee_name, start_date, "Permís invàlid",
                f"Permís #{leave['id']} ({leave['leave_type_name']}) no té una "
                "durada positiva; no s'han atribuït minuts.",
            ))
            get_day(worker_id, start_date)
            continue
        get_day(worker_id, start_date)
        if leave["daily_decision_id"] is not None:
            if leave["daily_status"] is None:
                issues.append(_issue(
                    worker_id, employee_name, start_date, "Decisió absent",
                    f"Permís #{leave['id']} està vinculat a una decisió diària "
                    "inexistent; no s'han atribuït minuts.",
                ))
                continue
            group_key = ("daily", leave["daily_decision_id"])
            permission_groups[group_key].append({
                "employee_id": worker_id,
                "employee_name": employee_name,
                "date": start_date,
                "leave_type": leave["leave_type_name"],
                "leave_id": leave["id"],
                "status": leave["daily_status"],
                "guarantee_seconds": leave["guaranteed_daily_minutes"] * 60,
                "interval": (start, end),
            })
        elif leave["status"] == "approved":
            permission_groups[("legacy", leave["id"])].append({
                "employee_id": worker_id,
                "employee_name": employee_name,
                "date": start_date,
                "leave_type": leave["leave_type_name"],
                "leave_id": leave["id"],
                "status": "approved",
                "guarantee_seconds": 0,
                "interval": (start, end),
            })
        else:
            issues.append(_issue(
                worker_id, employee_name, start_date, "Permís no reconegut",
                f"Permís històric #{leave['id']} ({leave['leave_type_name']}) "
                f"amb estat «{leave['status']}» no genera minuts reconeguts.",
            ))

    recognized_permission_intervals = defaultdict(list)
    occupied_permission_intervals = defaultdict(list)
    for group in sorted(
        permission_groups.values(),
        key=lambda values: (
            values[0]["date"], values[0]["employee_id"],
            min(item["interval"][0] for item in values),
        ),
    ):
        intervals = [item["interval"] for item in group]
        unique_intervals = _union_intervals(intervals)
        if _duration(unique_intervals) < sum(
            _duration([item["interval"]]) for item in group
        ):
            first = group[0]
            issues.append(_issue(
                first["employee_id"], first["employee_name"], first["date"],
                "Permisos solapats",
                f"Els permisos del tipus «{first['leave_type']}» se solapen; "
                "el temps coincident només es compta una vegada.",
            ))

        status = group[0]["status"]
        if status == "approved":
            eligible = unique_intervals
        else:
            eligible = _limit_intervals(
                unique_intervals, group[0]["guarantee_seconds"]
            )
        first = group[0]
        key = first["employee_id"], first["date"]
        existing = occupied_permission_intervals[key]
        unique_eligible = [
            part for interval in eligible
            for part in _subtract_intervals(interval, existing)
        ]
        if _duration(unique_eligible) < _duration(eligible):
            issues.append(_issue(
                first["employee_id"], first["employee_name"], first["date"],
                "Intervals de permís solapats",
                "El temps coincident entre tipus o registres de permís només es "
                "compta una vegada.",
            ))
        recognized_permission_intervals[key].extend(unique_eligible)
        occupied_permission_intervals[key] = _union_intervals(
            existing + unique_eligible
        )
        get_day(first["employee_id"], first["date"])["leave_details"].append({
            "leave_type": first["leave_type"],
            "status": status,
            "record_count": len(group),
            "recognized_seconds": _duration(unique_eligible),
        })

    for key in set(work_intervals) | set(recognized_permission_intervals):
        worker_id, local_date = key
        work = _union_intervals(work_intervals[key])
        permission = _union_intervals(recognized_permission_intervals[key])
        occupied_permissions = permission
        overlap_seconds = sum(
            _duration(_subtract_intervals(interval, []))
            - _duration(_subtract_intervals(interval, occupied_permissions))
            for interval in work
        )
        if overlap_seconds:
            issues.append(_issue(
                worker_id, employee_names.get(worker_id, ""), local_date,
                "Intervals solapats",
                "El temps coincident entre fitxatge i permís s'assigna al permís "
                "i no es duplica.",
            ))
        effective_work = [
            part for interval in work
            for part in _subtract_intervals(interval, occupied_permissions)
        ]
        day = get_day(worker_id, local_date)
        day["worked_seconds"] = _duration(effective_work)
        day["leave_seconds"] = _duration(permission)
        day["total_seconds"] = day["worked_seconds"] + day["leave_seconds"]

    for issue in issues:
        if issue["date"]:
            get_day(issue["employee_id"], issue["date"])

    daily_rows = sorted(
        day_data.values(),
        key=lambda row: (row["date"], row["employee_name"].casefold(), row["employee_id"]),
    )
    summaries_by_employee = {row["id"]: {
        "employee_id": row["id"],
        "employee_name": row["name"],
        "worked_seconds": 0,
        "leave_seconds": 0,
        "total_seconds": 0,
        "incident_count": 0,
    } for row in employees}
    issue_counts = defaultdict(int)
    for issue in issues:
        issue_counts[issue["employee_id"]] += 1
    for row in daily_rows:
        summary = summaries_by_employee[row["employee_id"]]
        summary["worked_seconds"] += row["worked_seconds"]
        summary["leave_seconds"] += row["leave_seconds"]
        summary["total_seconds"] += row["total_seconds"]
    for worker_id, count in issue_counts.items():
        if worker_id in summaries_by_employee:
            summaries_by_employee[worker_id]["incident_count"] = count

    return {
        "date_from": date_from,
        "date_to": date_to,
        "employees": list(summaries_by_employee.values()),
        "days": daily_rows,
        "incidents": issues,
    }
