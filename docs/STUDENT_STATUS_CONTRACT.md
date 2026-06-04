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

Formal exits use **`withdrawn`** or **`transferred`** on the student row. **`dropped`** is not a separate enum yet; use `withdrawn` + notes for informal exits until needed.

## `enrollment.status` (per academic year)

| Status | Meaning |
|--------|---------|
| `pending` | Process started, not finalized. |
| `enrolled` | **Active seat** this year (`is_enrolled = true`). |
| `completed` | **Year-end closure** — not an active seat. |
| `withdrawn` | Withdrawal for this year (mid-year or exit). |
| `canceled` | Enrollment voided. |

**Not enrollment.status values:** `promoted`, `repeated` — use `year_end_outcome` instead (see below).

**Intake type (not status):** `enrollment.enrolled_as` = `new` | `returning` | `transferred`.

## `enrollment.year_end_outcome`

Set when closing a year or marking a school exit on the enrollment row:

| Outcome | Typical `enrollment.status` | Meaning |
|---------|----------------------------|---------|
| `promoted` | `completed` | Advanced to next grade next year (`next_grade_level` set). |
| `repeated` | `completed` | Stays in same grade next year. |
| `graduated` | `completed` | Finished program; `student.status = graduated`. |
| `withdrawn` | `withdrawn` | Left school (sync with withdraw). |
| `transferred` | `withdrawn` | Transferred to another school; `student.status = transferred`. |

## API fields

| Field | Source |
|-------|--------|
| `lifecycle_status` | Raw `student.status` |
| `enrollment_status` | Current-year `enrollment.status` |
| `year_end_outcome` | Current-year `enrollment.year_end_outcome` |
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

| Action | `student.status` | `enrollment.status` | `year_end_outcome` |
|--------|------------------|---------------------|-------------------|
| Enroll | `active` | `enrolled` | cleared |
| Withdraw | `withdrawn` | `withdrawn` | `withdrawn` (optional) |
| Reinstate | `active` | `enrolled` | cleared |
| Promote & close year | `active` | `completed` | `promoted` |
| Repeat & close year | `active` | `completed` | `repeated` |
| Graduate | `graduated` | `completed` | `graduated` |
| Transfer out | `transferred` | `withdrawn` | `transferred` |

## Bulk API (registrar / admin only)

- `POST /students/enrollment-lifecycle/preview/` — body `{ action, outcome?, selection: { mode: "ids"|"filters", student_ids?, grade_level?, section?, search? } }`
- `POST /students/enrollment-lifecycle/apply/` — same body plus `expected_eligible_count`, `confirm_phrase: "APPLY"` (max 250 students per run)

UI: **Students → Year-end & enrollment** (`/students/enrollment-lifecycle`).

## Per-student API (phase 1)

- `POST /students/<id>/enrollments/current/complete-year/` — body `{ "outcome": "promoted" | "repeated" }`
- `POST /students/<id>/graduate/` — body `{ "graduation_date"?: "YYYY-MM-DD" }`
- `POST /students/<id>/transfer/` — body `{ "transfer_date"?: "YYYY-MM-DD", "reason"?: string }`

Setting `enrollment.status = completed` via PUT requires `year_end_outcome`.

## Data repair (migration 0005)

If year-end rows were migrated to `enrolled`, run (dry-run first):

`python manage.py repair_enrollment_year_end_status --dry-run`
