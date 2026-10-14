# Leave configuration design

## Sprint A

Leave-type configuration is stored in `leave_type`. The existing `name`,
`active`, `sort_order`, `approval_policy`, `max_minutes`, and
`auto_approve_minutes` fields retain their current meanings. In particular,
`max_minutes` is an indicative duration and does not limit a recorded leave.
`auto_approve_minutes` is the daily accumulated threshold for the `threshold`
approval policy; it is independent of the new `guaranteed_daily_minutes`
value. Guaranteed minutes accept zero or a positive integer.

The admin API at `/api/admin/leave-types` creates and updates this
configuration. The same fields are returned by the active leave-type API used
by the terminal.

The SQLite migration adds `guaranteed_daily_minutes` with a default of zero.
It is idempotent and does not change existing leave records, their statuses,
individual decision history, configured order, or indicative durations.
Existing permission durations and decisions are not retrospectively
reinterpreted or automatically recognized as computable time.

## Daily decision design for Sprint B

Individual `employee_leave` records remain the source of the actual leave
intervals. A separate daily decision is planned for each employee, leave type,
and local calendar date in `Europe/Madrid`, with append-only decision history.
The decision applies to the complete daily excess, not an individual interval
or a partial number of minutes. The decision records the daily total it
reviewed; if that total changes, the previous decision is retained in history
and the current excess requires review again. Sprint A does not create this
entity or alter existing individual decisions.

The format and behavior of optional justifications remain to be specified;
the existing implementation has no justification field.
