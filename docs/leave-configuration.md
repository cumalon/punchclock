# Leave configuration design

## Sprint A

Leave-type configuration is stored in `leave_type`. The existing `name`,
`active`, `sort_order`, `approval_policy`, `max_minutes`, and
`auto_approve_minutes` fields retain their current meanings. In particular,
`max_minutes` is an indicative duration and does not limit a recorded leave.
`auto_approve_minutes` is the threshold for the `threshold` approval policy.
It is evaluated against the accumulated daily total. The independent
`guaranteed_daily_minutes` value accepts zero or a positive integer.

The admin API at `/api/admin/leave-types` creates and updates this
configuration. The same fields are returned by the active leave-type API used
by the terminal.

The SQLite migration adds `guaranteed_daily_minutes` with a default of zero.
It is idempotent and does not change existing leave records, their statuses,
individual decision history, configured order, or indicative durations.
Existing permission durations and decisions are not retrospectively
reinterpreted or automatically recognized as computable time.

## Sprint B: daily aggregation and decisions

Individual `employee_leave` records remain the source of the actual leave
intervals. A `daily_leave_decision` is keyed by employee, leave type, and local
calendar date in `Europe/Madrid`, with append-only
`daily_leave_decision_history`. The decision applies to the complete daily
excess, never an individual interval or a partial number of minutes.

For total duration `D` and guaranteed allowance `G`, pending or rejected groups
recognize `min(D, G)`; approved groups recognize all of `D`. A threshold policy
automatically approves the daily total when it does not exceed the configured
threshold. If an excess remains and the total exceeds that threshold, the group
stays pending unless a supervisor approves or rejects the entire excess.
Automatic policies approve the full total, unless a record requires supervisor
review. A group with no excess and no unresolved incident needs no supervisor
decision. Manual decisions require a reason and record the reviewer.

If the total changes after a supervisor decision, that decision remains in the
history and the group returns to pending review. Automatic approvals, total
changes, invalidations, and supervisor decisions are also recorded with the
total and configuration snapshot used at the time.

Each daily group keeps the approval policy, automatic threshold, and guaranteed
minutes that were configured when its first interval was added. Later edits to
the leave type apply only to daily groups created afterward; they do not alter
an existing group's snapshot or recognition rules. Additional intervals and
regularizations for an existing group continue to use its original snapshot.

### Migration and historical compatibility

The idempotent migration adds nullable `employee_leave.daily_decision_id` and
the daily decision and history tables. Existing employee leave rows and
individual decision histories are left untouched and unlinked. They continue
to use the legacy individual-review workflow and are not silently imported
into a daily total or reinterpreted under the new guarantee and threshold
rules. New completed same-day records are linked to the daily group; their
individual statuses mirror the group status for compatibility, while the
daily history is authoritative for grouped decisions.

If historical and new records of the same type occur on the same local date,
only records explicitly linked to the new daily group contribute to its total
and guaranteed-minute allowance. Historical records remain separately
individually approved/rejected and are never assigned a share of the new daily
guarantee. Future hour reports must keep the two sets distinct: they must not
apply the group guarantee to legacy records or allow a legacy status to alter
the new group's decision. No hourly-report engine is added in Sprint B.

Intervals that cross a local calendar date are not assigned to a daily group.
They remain pending and require supervisor attention rather than being
silently attributed to one day. Same-day regularizations are added to the
daily group when completed; if they change a previously reviewed total, the
decision is invalidated as above.

The supervisor API exposes daily groups through
`/api/admin/daily-leave-decisions`, with detail and decision endpoints below
that path. Linked intervals cannot be decided through the legacy individual
decision endpoint. Admin and supervisor authentication, roles, and CSRF
protection use the existing web-admin controls.

### STOP B manual validation

1. Configure an `Esmorzar` type with 30 guaranteed minutes and a 30-minute
   automatic threshold.
2. Register intervals of 10, 12, 8, and 7 minutes on one local day. The
   supervisor approval filter should show one daily row with 37 total minutes
   and 30 guaranteed minutes.
3. Reject the excess and verify 30 recognized minutes; change the decision to
   approved and verify all 37 minutes are recognized, with both decisions in
   the audit history.
4. Add another interval after approval. Verify the daily row returns to pending
   and the previous decision remains in history.
5. Configure a manual type with zero guaranteed minutes. Verify a pending
   group recognizes zero until the supervisor approves it.

Targeted automated tests:

```sh
python -m pytest tests/test_daily_leave_decisions.py tests/test_leave_*.py -q
```

Sprint B review-correction result:
`python -m pytest tests/test_daily_leave_decisions.py tests/test_leave_*.py -q`
— **135 passed**.

## Sprint C: hours reports

The `/api/admin/hours-report` JSON view and `/api/admin/hours-report.xlsx`
export use the same report engine. Both accept required `date_from` and
`date_to` values in `YYYY-MM-DD` format (inclusive) and an optional
`employee_id`. The report UI is available to administrators and supervisors,
consistent with their existing access to punch records. The existing CSV
exports remain unchanged.

The XLSX workbook contains three sheets: `Resum` (employee totals),
`Detall diari` (daily work, recognized leave, total, and leave status/details),
and `Incidències` (incomplete or excluded records and punch incidents). Hours
are represented as decimal hours in the workbook; the web view displays
`hours:minutes:seconds`.

Punches are paired as an `entrada` followed by a `sortida` on the same
`Europe/Madrid` calendar date. Unmatched punches, non-positive pairs, and
pairs containing an unresolved punch incident do not contribute work time.
Reviewed incident punches can contribute when they form a valid pair, and
reviewed incidents remain visible in the report. The report never pairs
overnight shifts; the unmatched endpoints appear as incidents instead.

For new daily groups, an approved group may recognize its full eligible
interval duration; a pending or rejected group recognizes at most its
creation-time guaranteed minutes. Legacy individual leave records contribute
only when individually approved; pending or rejected historical records are
not retroactively recognized. Incomplete, malformed, and cross-midnight leave
records do not contribute time and are listed as incidents. Overlapping leave
intervals are deduplicated, with pending/rejected guaranteed time allocated
chronologically within the group; overlap between leave and work time is
assigned to leave so no interval is counted twice. These reporting rules do
not modify punch, leave, or decision-history records.

Targeted Sprint C tests:

```sh
python -m pytest tests/test_hours_report.py -q
```

The XLSX dependency is pinned to `openpyxl==3.1.5`.

The functional design left the precise XLSX columns and treatment of
incomplete/incidence cases open. Sprint C uses the conservative rules above:
uncertain work time is excluded rather than estimated, while valid guaranteed
leave remains computable under the daily decision rules.

Whether a justification is required or optional, and its format and behavior,
remain pending functional definition. The current implementation has no
justification configuration or field; this item is explicitly excluded from
Sprints A, B, and C.
