# Student status contract

Two tables, two purposes. Do not overload `student.status` with per-year attendance state.

## `student.status` (lifecycle)

| Status | Meaning |
|--------|---------|
| `active` | **Default.** Person record is operational. Use with `enrollment.status = enrolled`. |
| `inactive` | Not operational. |
| `suspended` | Temporarily blocked. |
| `withdrawn` | Left the school (formal). |
| `transferred` | Left for another school. |
| `graduated` | Finished program (school-wide). |
| `deleted` | Soft-deleted. |
| `enrolled` | **Deprecated** on student — migrate to `active`. Still accepted in reads/filters until data is cleaned. |
| `ntr` | Legacy (not returned). |

**Deferred:** `archived` (reporting-only), when archive feature ships.

Formal exits use **`withdrawn`** on both tables (sync on withdraw). **`dropped`** is not a separate enum yet; use `withdrawn` + notes for informal exits until needed.

## `enrollment.status` (per academic year)

| Status | Meaning |
|--------|---------|
| `pending` | Process started, not finalized. |
| `enrolled` | **Active seat** this year (`is_enrolled = true`). |
| `completed` | **Year-end closure** — not an active seat. |
| `withdrawn` | Withdrawal for this year. |
| `canceled` | Enrollment voided. |

**Deferred (rollover workflow):** `promoted`, `repeated`.

**Intake type (not status):** `enrollment.enrolled_as` = `new` | `returning` | `transferred` (replaces a `transferred_in` status).

## API fields

| Field | Source |
|-------|--------|
| `lifecycle_status` | Raw `student.status` |
| `enrollment_status` | Current-year `enrollment.status` |
| `is_enrolled` | `enrollment.status == enrolled` and non-terminal lifecycle |
| `status` (display) | Terminal lifecycle, else `enrollment_status`, else `not enrolled` |

## List filters (`?status=`)

| Value | Meaning |
|-------|---------|
| `enrolled` | `enrollment.status = enrolled` |
| `pending` | `enrollment.status = pending` |
| `completed` | `enrollment.status = completed` (year ended) |
| `not_enrolled` | No `pending`/`enrolled` seat this year |
| `withdrawn`, `graduated`, … | `student.status` |

## Writes

| Action | `student.status` | `enrollment.status` |
|--------|------------------|---------------------|
| Enroll | `active` | `enrolled` |
| Withdraw | `withdrawn` | `withdrawn` |
| Reinstate | `active` | `enrolled` |
| End year (future) | unchanged or `graduated` | `completed` |
