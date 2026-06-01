"""Build grouped employee list export rows."""

from __future__ import annotations

from collections import defaultdict


EMPLOYEE_EXPORT_HEADERS = [
    "Employee ID",
    "Name",
    "Email",
    "Phone",
    "Gender",
    "Department",
    "Position",
    "Manager",
    "Status",
    "Role",
    "Payroll Ready",
    "Hire Date",
    "Job Title",
]


def employee_to_export_row(record: dict) -> list[str]:
    return [
        record.get("employee_id") or "",
        record.get("full_name") or "",
        record.get("email") or "",
        record.get("phone") or "",
        record.get("gender") or "",
        record.get("department") or "",
        record.get("position") or "",
        record.get("manager") or "",
        record.get("employment_status") or "",
        record.get("role") or "",
        record.get("payroll_ready") or "",
        record.get("hire_date") or "",
        record.get("job_title") or "",
    ]


def _group_key(record: dict, group_by: str) -> str:
    if group_by == "department":
        return (record.get("department") or "").strip() or "Unassigned"
    if group_by == "position":
        return (record.get("position") or "").strip() or "Unassigned"
    return ""


def _sort_group_labels(labels: list[str]) -> list[str]:
    return sorted(labels, key=lambda label: (label == "Unassigned", label.lower()))


def build_grouped_employee_export_rows(
    results: list[dict],
    *,
    group_by: str | None,
) -> list[list[str]]:
    normalized_group_by = (group_by or "none").strip().lower()
    if normalized_group_by in {"", "none"}:
        return [employee_to_export_row(record) for record in results]

    buckets: dict[str, list[dict]] = defaultdict(list)
    for record in results:
        buckets[_group_key(record, normalized_group_by)].append(record)

    rows: list[list[str]] = []
    column_count = len(EMPLOYEE_EXPORT_HEADERS)

    for label in _sort_group_labels(list(buckets.keys())):
        group_rows = buckets[label]
        header_row = [f"{label} ({len(group_rows)} employee{'s' if len(group_rows) != 1 else ''})"]
        header_row.extend([""] * (column_count - 1))
        rows.append(header_row)

        for record in group_rows:
            rows.append(employee_to_export_row(record))

        subtotal_row = [f"Subtotal — {len(group_rows)} employee{'s' if len(group_rows) != 1 else ''}"]
        subtotal_row.extend([""] * (column_count - 1))
        rows.append(subtotal_row)

    return rows
