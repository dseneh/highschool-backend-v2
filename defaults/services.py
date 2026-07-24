"""
Onboarding provisioning service.

Reads a saved onboarding plan JSON and executes each step's handlers
in dependency order. Designed to be idempotent — all handlers use
get_or_create so re-running create-workspace never duplicates records.

Usage:
    from defaults.services import build_initial_plan, apply_onboarding_plan

    plan = build_initial_plan(tenant)         # generate template plan
    result = apply_onboarding_plan(tenant, user, plan)  # provision workspace
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plan template helpers
# ---------------------------------------------------------------------------

STEP_ORDER = [
    "school_profile",
    "branding",
    "academic_calendar",
    "grade_structure",
    "subjects",
    "grading",
    "finance",
    "accounting",
    "hr_staff",
    "payroll",
]

REQUIRED_STEPS = [
    "school_profile",
    "branding",
    "academic_calendar",
    "grade_structure",
    "subjects",
    "grading",
    "finance",
]

OPTIONAL_STEPS = [
    "accounting",
    "hr_staff",
    "payroll",
]

STEP_META = {
    "school_profile": {
        "label": "School Profile",
        "description": "Basic school identity, contact details, and branding.",
        "icon": "Building02Icon",
    },
    "branding": {
        "label": "Branding",
        "description": "School logo, logo presentation, and theme configuration.",
        "icon": "PaintBoardIcon",
    },
    "academic_calendar": {
        "label": "Academic Calendar",
        "description": "Academic year, semesters, marking periods, and school calendar settings.",
        "icon": "Calendar03Icon",
    },
    "grade_structure": {
        "label": "Grade Structure",
        "description": "School divisions, grade levels, and class sections.",
        "icon": "BookOpen02Icon",
    },
    "subjects": {
        "label": "Subjects",
        "description": "Course subjects offered at your school.",
        "icon": "CourseIcon",
    },
    "grading": {
        "label": "Grading",
        "description": "Grade scale, assessment types, and grading settings.",
        "icon": "ChartIcon",
    },
    "finance": {
        "label": "Finance",
        "description": "Currency, payment methods, fee types, and transaction categories.",
        "icon": "Coins01Icon",
    },
    "accounting": {
        "label": "Accounting",
        "description": "Chart of accounts, accounting payment methods, and bank accounts.",
        "icon": "Invoice01Icon",
    },
    "hr_staff": {
        "label": "HR & Staff",
        "description": "Departments, positions, and HR leave types.",
        "icon": "UserMultiple02Icon",
    },
    "payroll": {
        "label": "Payroll",
        "description": "Default pay schedule and payroll settings.",
        "icon": "CreditCardIcon",
    },
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Recursively convert values to JSON-safe primitives for JSONField storage."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _build_step_entry(status: str = "pending", payload: dict | None = None) -> dict:
    return {
        "status": status,
        "saved_at": None,
        "payload": _json_safe(payload or {}),
        "apply_result": None,
    }


def build_initial_plan(tenant) -> dict:
    """
    Generate a starter onboarding plan populated with system defaults
    so the user can modify values before applying.
    """
    from defaults.data.academic_year import get_academic_year
    from defaults.data.semester import get_semester_list
    from defaults.data.marking_period import get_marking_periods_dict
    from defaults.data.division_list import division_list
    from defaults.data.gade_level import grade_level_data
    from defaults.data.subjects import subjects
    from defaults.data.currency import currency
    from defaults.data.payment_methods import payment_method_data
    from defaults.data.transaction_types import transaction_types_data
    from defaults.data.fees import fee_list
    from defaults.data.accounting import (
        accounting_currency,
        accounting_ledger_accounts,
        accounting_payment_methods,
        accounting_transaction_types,
        accounting_fee_items,
        accounting_bank_accounts,
    )
    from defaults.data.hr import employee_departments, employee_positions, leave_types
    from defaults.data.payroll import get_default_pay_schedule

    academic_year = get_academic_year()
    semesters = get_semester_list()
    marking_periods = get_marking_periods_dict()
    pay_schedule = get_default_pay_schedule()

    steps: dict[str, dict] = {}

    # Step: school_profile — pre-filled from current tenant record
    steps["school_profile"] = _build_step_entry(
        status="pending",
        payload={
            "name": tenant.name,
            "short_name": tenant.short_name or "",
            "slogan": tenant.slogan or "",
            "school_type": tenant.school_type or "secondary",
            "funding_type": tenant.funding_type or "private",
            "emis_number": tenant.emis_number or "",
            "description": tenant.description or "",
            "date_est": str(tenant.date_est) if tenant.date_est else "",
            "address": tenant.address or "",
            "city": tenant.city or "",
            "state": tenant.state or "",
            "country": tenant.country or "",
            "postal_code": tenant.postal_code or "",
            "phone": tenant.phone or "",
            "email": tenant.email or "",
            "website": tenant.website or "",
        },
    )

    # Step: branding — pre-filled from tenant branding/theme
    steps["branding"] = _build_step_entry(
        status="pending",
        payload={
            "logo": tenant.logo.url if getattr(tenant, "logo", None) else "",
            "logo_shape": tenant.logo_shape or "square",
            "theme_config": {
                "border_radius": (tenant.theme_config or {}).get("border_radius", "medium"),
                "color_theme": (tenant.theme_config or {}).get("color_theme", "ocean"),
                "background_style": (tenant.theme_config or {}).get("background_style", "clean"),
                "font_family": (tenant.theme_config or {}).get("font_family", "sans"),
                "font_size": (tenant.theme_config or {}).get("font_size", "normal"),
                "shadow_intensity": (tenant.theme_config or {}).get("shadow_intensity", "medium"),
                "spacing_scale": (tenant.theme_config or {}).get("spacing_scale", "comfortable"),
                "animation_speed": (tenant.theme_config or {}).get("animation_speed", "normal"),
            },
        },
    )

    # Step: academic_calendar
    steps["academic_calendar"] = _build_step_entry(
        payload={
            "academic_year": {
                "name": academic_year["name"],
                "start_date": academic_year["start_date"],
                "end_date": academic_year["end_date"],
                "current": True,
            },
            "semesters": [
                {
                    "name": s["name"],
                    "start_date": s["start_date"],
                    "end_date": s["end_date"],
                }
                for s in semesters
            ],
            "marking_periods": [
                {
                    "name": mp["name"],
                    "short_name": mp["short_name"],
                    "semester_index": mp["semester"],
                    "start_date": mp["start_date"],
                    "end_date": mp["end_date"],
                }
                for mp in marking_periods
            ],
            "calendar_settings": {
                "operating_days": [1, 2, 3, 4, 5],
                "timezone": "UTC",
            },
        }
    )

    # Step: grade_structure
    steps["grade_structure"] = _build_step_entry(
        payload={
            "divisions": [
                {"name": d["name"], "description": d["description"]}
                for d in division_list
            ],
            "grade_levels": [
                {
                    "name": g["name"],
                    "short_name": g["short_name"],
                    "description": g["description"],
                    "level": g["level"],
                    "division_index": g["division"],
                }
                for g in grade_level_data
            ],
        }
    )

    # Step: subjects
    steps["subjects"] = _build_step_entry(
        payload={
            "subjects": [
                {"name": s["name"], "code": s.get("code", ""), "description": s["description"]}
                for s in subjects
            ]
        }
    )

    # Step: grading
    steps["grading"] = _build_step_entry(
        payload={
            "grade_letters": [
                {"letter": "A+", "min_percentage": 97, "max_percentage": 100, "order": 1},
                {"letter": "A",  "min_percentage": 93, "max_percentage": 96,  "order": 2},
                {"letter": "A-", "min_percentage": 90, "max_percentage": 92,  "order": 3},
                {"letter": "B+", "min_percentage": 87, "max_percentage": 89,  "order": 4},
                {"letter": "B",  "min_percentage": 83, "max_percentage": 86,  "order": 5},
                {"letter": "B-", "min_percentage": 80, "max_percentage": 82,  "order": 6},
                {"letter": "C+", "min_percentage": 77, "max_percentage": 79,  "order": 7},
                {"letter": "C",  "min_percentage": 73, "max_percentage": 76,  "order": 8},
                {"letter": "C-", "min_percentage": 70, "max_percentage": 72,  "order": 9},
                {"letter": "D+", "min_percentage": 67, "max_percentage": 69,  "order": 10},
                {"letter": "D",  "min_percentage": 63, "max_percentage": 66,  "order": 11},
                {"letter": "D-", "min_percentage": 60, "max_percentage": 62,  "order": 12},
                {"letter": "F",  "min_percentage": 0,  "max_percentage": 59,  "order": 13},
            ],
            "assessment_types": [
                {"name": "Assignment", "description": "Regular class assignment", "is_single_entry": False},
                {"name": "Quiz",       "description": "Short quiz",               "is_single_entry": False},
                {"name": "Test",       "description": "Formal test",              "is_single_entry": False},
                {"name": "Midterm",    "description": "Midterm exam",             "is_single_entry": True},
                {"name": "Final Exam", "description": "Final examination",        "is_single_entry": True},
                {"name": "Project",    "description": "Student project",          "is_single_entry": False},
                {"name": "Participation", "description": "Class participation",   "is_single_entry": False},
            ],
        }
    )

    # Step: finance
    steps["finance"] = _build_step_entry(
        payload={
            "currency": {
                "name": currency["name"],
                "code": currency["code"],
                "symbol": currency["symbol"],
            },
            "payment_methods": [
                {"name": m["name"], "description": m.get("description", "")}
                for m in payment_method_data
            ],
            "transaction_types": [
                {
                    "name": t["name"],
                    "type": t["type"],
                    "type_code": t.get("type_code", t.get("type_id", "")),
                    "description": t.get("description", ""),
                }
                for t in transaction_types_data
            ],
            "fees": [
                {"name": f["name"], "description": f.get("description", "")}
                for f in fee_list
            ],
        }
    )

    # Step: accounting
    steps["accounting"] = _build_step_entry(
        payload={
            "currency": {
                "name": accounting_currency["name"],
                "code": accounting_currency["code"],
                "symbol": accounting_currency["symbol"],
            },
            "ledger_accounts_count": len(accounting_ledger_accounts),
            "payment_methods": [m["name"] for m in accounting_payment_methods],
            "bank_accounts": [
                {"account_name": b["account_name"], "account_number": b["account_number"]}
                for b in accounting_bank_accounts
            ],
        }
    )

    # Step: hr_staff
    steps["hr_staff"] = _build_step_entry(
        payload={
            "departments": [
                {"name": d["name"], "code": d.get("code", "")}
                for d in employee_departments
            ],
            "positions": [
                {
                    "title": p["title"],
                    "code": p.get("code", ""),
                    "department_code": p.get("department_code", ""),
                    "employment_type": p.get("employment_type", "full_time"),
                }
                for p in employee_positions
            ],
            "leave_types": [
                {"name": lt["name"], "code": lt.get("code", ""), "default_days": lt.get("default_days", 1)}
                for lt in leave_types
            ],
        }
    )

    # Step: payroll
    steps["payroll"] = _build_step_entry(
        payload={
            "pay_schedule": {
                "name": pay_schedule["name"],
                "frequency": pay_schedule["frequency"],
                "payment_day_offset": pay_schedule["payment_day_offset"],
                "overtime_multiplier": pay_schedule["overtime_multiplier"],
            }
        }
    )

    return _json_safe({
        "version": "1.0",
        "current_step": "school_profile",
        "steps": steps,
        "step_order": STEP_ORDER,
        "step_meta": STEP_META,
        "required_steps": REQUIRED_STEPS,
        "optional_steps": OPTIONAL_STEPS,
        "started_at": None,
        "completed_at": None,
        "apply_result": None,
    })


def sync_plan_with_latest_template(tenant, plan: dict) -> tuple[dict, bool]:
    """Merge missing onboarding steps/meta from the latest template.

    Keeps existing payloads/statuses for known steps while injecting any newly
    introduced steps (for example when onboarding evolves after a tenant has
    already started).
    """
    template = build_initial_plan(tenant)
    changed = False

    merged_steps: dict[str, dict] = {}
    existing_steps = plan.get("steps", {}) if isinstance(plan, dict) else {}

    for key in template["step_order"]:
      template_entry = template["steps"][key]
      if key in existing_steps:
          existing_entry = existing_steps[key] or {}
          merged_steps[key] = {
              "status": existing_entry.get("status", template_entry["status"]),
              "saved_at": existing_entry.get("saved_at", template_entry["saved_at"]),
              "payload": _json_safe(existing_entry.get("payload", template_entry["payload"])),
              "apply_result": existing_entry.get("apply_result", template_entry["apply_result"]),
          }
      else:
          merged_steps[key] = template_entry
          changed = True

    merged_plan = {
        **template,
        **plan,
        "steps": merged_steps,
        "step_order": template["step_order"],
        "step_meta": template["step_meta"],
        "required_steps": template["required_steps"],
        "optional_steps": template["optional_steps"],
        "current_step": plan.get("current_step") if plan.get("current_step") in template["step_order"] else template["current_step"],
    }

    if merged_plan["step_order"] != plan.get("step_order"):
        changed = True
    if merged_plan["required_steps"] != plan.get("required_steps"):
        changed = True
    if merged_plan["optional_steps"] != plan.get("optional_steps"):
        changed = True
    if merged_plan["step_meta"] != plan.get("step_meta"):
        changed = True

    return _json_safe(merged_plan), changed


# ---------------------------------------------------------------------------
# Completion check
# ---------------------------------------------------------------------------

def get_completion_status(plan: dict) -> dict:
    """
    Return progress metadata for a given onboarding plan dict.
    """
    steps = plan.get("steps", {})
    required = plan.get("required_steps", REQUIRED_STEPS)
    optional = plan.get("optional_steps", OPTIONAL_STEPS)

    completed_required = [k for k in required if steps.get(k, {}).get("status") == "completed"]
    completed_optional = [k for k in optional if steps.get(k, {}).get("status") == "completed"]

    required_done = len(completed_required) == len(required)
    percent = int(len(completed_required) / max(len(required), 1) * 100)

    return {
        "required_done": required_done,
        "percent": percent,
        "completed_required": completed_required,
        "completed_optional": completed_optional,
        "total_required": len(required),
        "total_optional": len(optional),
    }


# ---------------------------------------------------------------------------
# Apply / provisioning engine
# ---------------------------------------------------------------------------

def apply_onboarding_plan(tenant, user, plan: dict) -> dict:
    """
    Execute the onboarding plan: apply each step's saved payload to provision
    the workspace. Returns a result dict with per-step outcomes.

    This runs in a single database transaction; any unhandled exception rolls
    back all database changes but the error is captured in the result.
    """
    from defaults import run as default_run
    from django_tenants.utils import schema_context
    from django.db import transaction

    results: dict[str, Any] = {}
    step_order = plan.get("step_order", STEP_ORDER)
    steps = plan.get("steps", {})

    try:
        with transaction.atomic():
            # Step 1: Update school profile on the tenant itself
            results["school_profile"] = _apply_school_profile(tenant, steps.get("school_profile", {}).get("payload", {}))
            results["branding"] = _apply_branding(tenant, steps.get("branding", {}).get("payload", {}))

            # All remaining steps execute inside the tenant schema
            with schema_context(tenant.schema_name):
                # Step 2: Academic calendar
                results["academic_calendar"] = _apply_academic_calendar(
                    tenant, user,
                    steps.get("academic_calendar", {}).get("payload", {})
                )
                # Step 3: Grade structure
                results["grade_structure"] = _apply_grade_structure(
                    tenant, user,
                    steps.get("grade_structure", {}).get("payload", {})
                )
                # Step 4: Subjects
                results["subjects"] = _apply_subjects(
                    tenant, user,
                    steps.get("subjects", {}).get("payload", {})
                )
                # Step 5: Grading
                results["grading"] = _apply_grading(
                    tenant, user,
                    steps.get("grading", {}).get("payload", {})
                )
                # Step 6: Finance
                results["finance"] = _apply_finance(
                    tenant, user,
                    steps.get("finance", {}).get("payload", {}),
                )
                # Step 7: Accounting (optional)
                if "accounting" in step_order:
                    results["accounting"] = _apply_accounting(
                        tenant, user,
                        steps.get("accounting", {}).get("payload", {})
                    )
                # Step 8: HR & Staff (optional)
                if "hr_staff" in step_order:
                    results["hr_staff"] = _apply_hr_staff(
                        tenant, user,
                        steps.get("hr_staff", {}).get("payload", {})
                    )
                # Step 9: Payroll (optional)
                if "payroll" in step_order:
                    results["payroll"] = _apply_payroll(
                        tenant, user,
                        steps.get("payroll", {}).get("payload", {})
                    )

        return {"success": True, "steps": results, "applied_at": _now_iso()}

    except Exception as exc:
        logger.exception("Onboarding apply failed for tenant %s", tenant.schema_name)
        return {"success": False, "error": str(exc), "steps": results, "applied_at": _now_iso()}


# ---------------------------------------------------------------------------
# Per-step apply helpers
# ---------------------------------------------------------------------------

def _ok(step: str, records_created: int = 0, records_updated: int = 0) -> dict:
    return {"step": step, "ok": True, "records_created": records_created, "records_updated": records_updated}


def _fail(step: str, error: str) -> dict:
    return {"step": step, "ok": False, "error": error}


def _apply_school_profile(tenant, payload: dict) -> dict:
    try:
        fields_to_update = [
            "name", "short_name", "slogan", "school_type", "funding_type",
            "emis_number", "description", "address", "city", "state",
            "country", "postal_code", "phone", "email", "website",
        ]
        updated = False
        for field in fields_to_update:
            if field in payload and payload[field] is not None:
                setattr(tenant, field, payload[field])
                updated = True
        if payload.get("date_est"):
            tenant.date_est = payload["date_est"]
            updated = True
        if updated:
            tenant.save(update_fields=fields_to_update + ["date_est", "updated_at"])
        return _ok("school_profile", records_updated=1 if updated else 0)
    except Exception as exc:
        return _fail("school_profile", str(exc))


def _apply_branding(tenant, payload: dict) -> dict:
    try:
        updated_fields: list[str] = []

        logo_shape = payload.get("logo_shape")
        if logo_shape:
            tenant.logo_shape = logo_shape
            updated_fields.append("logo_shape")

        theme_config = payload.get("theme_config")
        if isinstance(theme_config, dict):
            tenant.theme_config = theme_config
            updated_fields.append("theme_config")

        if updated_fields:
            tenant.save(update_fields=updated_fields + ["updated_at"])

        return _ok("branding", records_updated=1 if updated_fields else 0)
    except Exception as exc:
        return _fail("branding", str(exc))


def _apply_academic_calendar(tenant, user, payload: dict) -> dict:
    from academics.models import AcademicYear, Semester, MarkingPeriod, SchoolCalendarSettings

    created = 0
    ay_data = payload.get("academic_year", {})

    # Academic year
    ay, ay_created = AcademicYear.objects.get_or_create(
        name=ay_data.get("name", ""),
        defaults={
            "start_date": ay_data.get("start_date"),
            "end_date": ay_data.get("end_date"),
            "current": ay_data.get("current", True),
            "created_by": user,
            "updated_by": user,
        },
    )
    if ay_created:
        created += 1

    # Semesters
    semester_objs = []
    for s_data in payload.get("semesters", []):
        sem, sem_created = Semester.objects.get_or_create(
            academic_year=ay,
            name=s_data.get("name", ""),
            defaults={
                "start_date": s_data.get("start_date"),
                "end_date": s_data.get("end_date"),
                "created_by": user,
                "updated_by": user,
            },
        )
        semester_objs.append(sem)
        if sem_created:
            created += 1

    # Marking periods
    for mp_data in payload.get("marking_periods", []):
        sem_idx = mp_data.get("semester_index", 0)
        if sem_idx < len(semester_objs):
            _, mp_created = MarkingPeriod.objects.get_or_create(
                semester=semester_objs[sem_idx],
                name=mp_data.get("name", ""),
                defaults={
                    "short_name": mp_data.get("short_name", ""),
                    "start_date": mp_data.get("start_date"),
                    "end_date": mp_data.get("end_date"),
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if mp_created:
                created += 1

    # Calendar settings singleton
    cal = payload.get("calendar_settings", {})
    if not SchoolCalendarSettings.objects.exists():
        SchoolCalendarSettings.objects.create(
            operating_days=cal.get("operating_days", [1, 2, 3, 4, 5]),
            timezone=cal.get("timezone", "UTC"),
            created_by=user,
            updated_by=user,
        )
        created += 1

    return _ok("academic_calendar", records_created=created)


def _apply_grade_structure(tenant, user, payload: dict) -> dict:
    from academics.models import Division, GradeLevel, GradeLevelTuitionFee, Section

    created = 0

    # Divisions
    division_objs = []
    for div_data in payload.get("divisions", []):
        div, div_created = Division.objects.get_or_create(
            name=div_data.get("name", ""),
            defaults={
                "description": div_data.get("description", ""),
                "created_by": user,
                "updated_by": user,
            },
        )
        division_objs.append(div)
        if div_created:
            created += 1

    # Grade levels
    grade_level_objs = []
    for gl_data in payload.get("grade_levels", []):
        div_idx = gl_data.get("division_index", 0)
        div_obj = division_objs[div_idx] if div_idx < len(division_objs) else (division_objs[0] if division_objs else None)
        gl, gl_created = GradeLevel.objects.get_or_create(
            name=gl_data.get("name", ""),
            defaults={
                "short_name": gl_data.get("short_name", ""),
                "description": gl_data.get("description", ""),
                "level": gl_data.get("level", 1),
                "division": div_obj,
                "created_by": user,
                "updated_by": user,
            },
        )
        grade_level_objs.append(gl)
        if gl_created:
            created += 1
            # Tuition fee placeholders
            for t in ["new", "returning", "transferred"]:
                GradeLevelTuitionFee.objects.get_or_create(
                    grade_level=gl,
                    targeted_student_type=t,
                    defaults={"amount": 0, "created_by": user, "updated_by": user},
                )

    # Sections — one "General" per grade_level ≤ level 13, else Arts/Science
    for gl in grade_level_objs:
        if gl.level <= 13:
            _, s_created = Section.objects.get_or_create(
                grade_level=gl,
                name="General",
                defaults={
                    "description": f"General Section for {gl.name}",
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if s_created:
                created += 1
        else:
            for sname in ["Arts", "Science"]:
                _, s_created = Section.objects.get_or_create(
                    grade_level=gl,
                    name=sname,
                    defaults={
                        "description": f"{sname} Section for {gl.name}",
                        "created_by": user,
                        "updated_by": user,
                    },
                )
                if s_created:
                    created += 1

    return _ok("grade_structure", records_created=created)


def _apply_subjects(tenant, user, payload: dict) -> dict:
    from academics.models import Subject

    created = 0
    for s_data in payload.get("subjects", []):
        _, s_created = Subject.objects.get_or_create(
            name=s_data.get("name", ""),
            defaults={
                "code": s_data.get("code") or None,
                "description": s_data.get("description", ""),
                "created_by": user,
                "updated_by": user,
            },
        )
        if s_created:
            created += 1

    return _ok("subjects", records_created=created)


def _apply_grading(tenant, user, payload: dict) -> dict:
    from grading.models import GradeLetter, AssessmentType
    from settings.models import GradingSettings

    created = 0

    for gl_data in payload.get("grade_letters", []):
        _, c = GradeLetter.objects.get_or_create(
            letter=gl_data["letter"],
            defaults={
                "min_percentage": gl_data["min_percentage"],
                "max_percentage": gl_data["max_percentage"],
                "order": gl_data["order"],
                "created_by": user,
                "updated_by": user,
            },
        )
        if c:
            created += 1

    for at_data in payload.get("assessment_types", []):
        _, c = AssessmentType.objects.get_or_create(
            name=at_data["name"],
            defaults={
                "description": at_data.get("description", ""),
                "is_single_entry": at_data.get("is_single_entry", False),
                "created_by": user,
                "updated_by": user,
            },
        )
        if c:
            created += 1

    if not GradingSettings.objects.exists():
        GradingSettings.objects.create(created_by=user, updated_by=user)
        created += 1

    return _ok("grading", records_created=created)


def _apply_finance(tenant, user, payload: dict) -> dict:
    from finance.models import Currency, PaymentMethod, TransactionType, GeneralFeeList, SectionFee
    from academics.models import Section

    created = 0

    # Currency
    cur = payload.get("currency", {})
    if cur.get("code"):
        _, c = Currency.objects.get_or_create(
            code=cur["code"],
            defaults={
                "name": cur.get("name", ""),
                "symbol": cur.get("symbol", ""),
                "created_by": user,
                "updated_by": user,
            },
        )
        if c:
            created += 1

    # Payment methods
    for pm_data in payload.get("payment_methods", []):
        _, c = PaymentMethod.objects.get_or_create(
            name=pm_data["name"],
            defaults={
                "description": pm_data.get("description", ""),
                "is_editable": pm_data.get("is_editable", True),
                "created_by": user,
                "updated_by": user,
            },
        )
        if c:
            created += 1

    # Transaction types
    for tt_data in payload.get("transaction_types", []):
        type_code = tt_data.get("type_code") or tt_data.get("name", "").upper().replace(" ", "_")[:20]
        _, c = TransactionType.objects.get_or_create(
            type_code=type_code,
            defaults={
                "name": tt_data["name"],
                "description": tt_data.get("description", ""),
                "type": tt_data.get("type", "income"),
                "is_editable": tt_data.get("is_editable", True),
                "created_by": user,
                "updated_by": user,
            },
        )
        if c:
            created += 1

    # Fee list + section fees
    fee_objs = []
    for fee_data in payload.get("fees", []):
        fee_obj, c = GeneralFeeList.objects.get_or_create(
            name=fee_data["name"],
            defaults={
                "description": fee_data.get("description", ""),
                "created_by": user,
                "updated_by": user,
            },
        )
        fee_objs.append(fee_obj)
        if c:
            created += 1

    for section in Section.objects.all():
        for fee in fee_objs:
            _, c = SectionFee.objects.get_or_create(
                section=section,
                general_fee=fee,
                defaults={"amount": 0, "created_by": user, "updated_by": user},
            )
            if c:
                created += 1

    return _ok("finance", records_created=created)


def _apply_accounting(tenant, user, payload: dict) -> dict:
    from defaults.data.accounting import (
        accounting_currency,
        accounting_ledger_accounts,
        accounting_payment_methods,
        accounting_transaction_types,
        accounting_fee_items,
        accounting_bank_accounts,
    )
    from defaults import run as default_run

    try:
        currency_obj = default_run.create_accounting_currency(tenant, user)
        default_run.create_accounting_ledger_accounts(tenant, user)
        default_run.create_accounting_payment_methods(tenant, user)
        default_run.create_accounting_transaction_types(tenant, user)
        default_run.create_accounting_fee_items(tenant, user)
        default_run.create_accounting_bank_accounts(tenant, user, currency_obj)
        return _ok("accounting", records_created=len(accounting_ledger_accounts))
    except Exception as exc:
        return _fail("accounting", str(exc))


def _apply_hr_staff(tenant, user, payload: dict) -> dict:
    from defaults import run as default_run

    try:
        default_run.create_departments(tenant, user)
        default_run.create_position_categories(tenant, user)
        default_run.create_positions(tenant, user)
        default_run.create_employee_departments(tenant, user)
        default_run.create_employee_positions(tenant, user)
        default_run.create_leave_types(tenant, user)
        return _ok("hr_staff", records_created=10)
    except Exception as exc:
        return _fail("hr_staff", str(exc))


def _apply_payroll(tenant, user, payload: dict) -> dict:
    from defaults.data.accounting import accounting_currency
    from accounting.models import AccountingCurrency
    from django_tenants.utils import schema_context

    try:
        with schema_context(tenant.schema_name):
            acc_currency = AccountingCurrency.objects.filter(
                code=accounting_currency["code"]
            ).first()
        if acc_currency:
            from defaults import run as default_run
            default_run.create_default_pay_schedule(tenant, user, acc_currency)
        return _ok("payroll", records_created=1 if acc_currency else 0)
    except Exception as exc:
        return _fail("payroll", str(exc))
