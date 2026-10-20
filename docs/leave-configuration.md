# Leave management and hours reporting

This guide explains how an administrator or supervisor can configure leave types, review absences and interpret hours reports on a PunchClock terminal. All dates and daily calculations use the terminal's configured local timezone (in the reference installation, `Europe/Madrid`).

## Configure leave types

Leave types are maintained in Web Admin. Each type has a name, an active/inactive state, a display order and an approval policy. Two duration settings have different purposes:

- **Indicative duration (`max_minutes`)**: guidance for the expected duration of a leave; it does **not** prevent longer absences from being recorded.
- **Guaranteed daily minutes (`guaranteed_daily_minutes`)**: minutes that can count toward recognized time even while a daily leave group is pending or rejected. Set to zero if no time is guaranteed.
- **Automatic approval threshold (`auto_approve_minutes`)**: for the threshold-based policy, the maximum **daily accumulated** duration eligible for automatic approval. It is not a per-interval allowance.

Available approval behaviors include automatic approval, threshold-based approval and manual review. Under a threshold policy, the daily total is approved automatically when it is within the configured threshold; otherwise any excess requires a supervisor's decision. Some records may still require review because of an incident.

**Example:** A type named `Esmorzar` has 30 guaranteed minutes and a 30-minute automatic threshold. Four intervals of 10, 12, 8 and 7 minutes on the same day total 37 minutes. The first 30 minutes are guaranteed; the additional 7 minutes count as recognized time only if the supervisor approves the daily excess.

## Review and approve leave

For newly recorded, completed same-day absences, PunchClock groups intervals by **employee, leave type and local calendar day**. Supervisors review these daily groups in Web Admin rather than deciding each interval separately.

- **Approved:** the full eligible daily leave duration is recognized.
- **Pending or rejected:** only up to the group's guaranteed daily minutes are recognized.
- **No excess and no unresolved incident:** no supervisor decision is needed.
- **Manual decision:** the supervisor approves or rejects the entire daily excess, provides a reason and leaves an auditable record. A partial approval of only some excess minutes is not supported.

A later interval or correction can change the daily total. If that happens after a supervisor's decision, the previous decision remains in the history and the group returns to pending review. The group's policy, threshold and guaranteed minutes are retained from when its first interval was created. Changing a leave type affects future daily groups, not existing ones.

The supervisor view is backed by `/api/admin/daily-leave-decisions`. Access is subject to the Web Admin roles and authentication controls.

## Understand the hours report

The hours report is available in Web Admin to administrators and supervisors. Choose an inclusive **start date** and **end date**; you can optionally restrict the results to one employee. The web report and Excel export use the same calculation rules. The Excel workbook contains:

- **Resum:** totals by employee.
- **Detall diari:** daily worked time, recognized leave, total time and leave details/status.
- **Incidències:** incomplete, excluded or problematic records and punch incidents.

The web interface displays time as hours, minutes and seconds. The Excel workbook represents hours as decimal values.

### Worked time

A valid work interval consists of an `entrada` followed by a `sortida` on the **same local date**. Unmatched punches, non-positive intervals and pairs with unresolved punch incidents are excluded from worked time and shown as incidents where applicable. A reviewed incident can contribute to worked time when its punches form a valid pair. Overnight shifts are not automatically paired.

### Recognized leave and overlaps

For grouped daily leave, approved groups can count their full eligible duration; pending or rejected groups count no more than the guaranteed daily allowance. The guaranteed allowance is applied to the day's accumulated eligible leave, **not separately to every interval**.

A valid leave interval represents an absence from work even when approval is pending or rejected. Its time is removed from worked time; only the approved or guaranteed portion is added back as recognized leave. Consequently, an unrecognized absence is not counted as work. Overlapping leave intervals are deduplicated, and overlapping leave and work are not counted twice.

Incomplete, malformed and cross-midnight leave intervals are excluded from recognized time and identified as incidents. Cross-midnight leave needs supervisor attention rather than being assigned automatically to one day.

## Older records and configuration changes

Older leave records created before daily grouping remain subject to their original **individual approval decisions**. They count as recognized leave only when individually approved. They are not silently transferred into new daily groups or granted the newer daily allowance.

If older and newer records of the same type exist on the same date, PunchClock keeps their approval and recognition rules separate. Changing the current leave-type configuration does not retroactively recalculate older decisions or existing daily groups.

## Operational checks

When checking a discrepancy in reported hours, verify the date range, the employee, the sequence of entry/exit punches, unresolved incidents, any overlapping leave intervals and the daily leave approval status. For an absence exceeding guaranteed minutes, check whether the supervisor approved the excess. Review the **Incidències** worksheet before treating a report as complete.

Web Admin currently does not provide a configurable justification requirement or a dedicated justification field for these leave decisions. Do not assume that supporting documents are collected automatically.
