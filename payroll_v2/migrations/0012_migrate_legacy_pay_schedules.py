"""Copy v1 pay schedules into payroll_v2 and repair broken employee FKs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import migrations


LEGACY_SCHEDULE_TABLE = "pay_schedule"
LEGACY_PERIOD_TABLE = "payroll_period"
V2_SCHEDULE_TABLE = "payroll_v2_pay_schedule"
V2_PERIOD_TABLE = "payroll_v2_payroll_period"


def _table_exists(connection, table_name: str) -> bool:
    return table_name in set(connection.introspection.table_names())


def _copy_legacy_schedules(connection, PaySchedule):
    if not _table_exists(connection, LEGACY_SCHEDULE_TABLE):
        return 0

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {V2_SCHEDULE_TABLE} (
                id,
                active,
                created_at,
                created_by_id,
                updated_at,
                updated_by_id,
                name,
                frequency,
                anchor_date,
                currency_id,
                payment_day_offset,
                overtime_multiplier,
                is_default,
                is_active
            )
            SELECT
                id,
                active,
                created_at,
                created_by_id,
                updated_at,
                updated_by_id,
                name,
                frequency,
                anchor_date,
                currency_id,
                payment_day_offset,
                overtime_multiplier,
                is_default,
                is_active
            FROM {LEGACY_SCHEDULE_TABLE}
            ON CONFLICT (id) DO NOTHING
            """
        )
        return cursor.rowcount


def _copy_legacy_periods(connection):
    if not _table_exists(connection, LEGACY_PERIOD_TABLE):
        return 0
    if not _table_exists(connection, V2_PERIOD_TABLE):
        return 0

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {V2_PERIOD_TABLE} (
                id,
                active,
                created_at,
                created_by_id,
                updated_at,
                updated_by_id,
                schedule_id,
                name,
                start_date,
                end_date,
                payment_date,
                is_closed
            )
            SELECT
                id,
                active,
                created_at,
                created_by_id,
                updated_at,
                updated_by_id,
                schedule_id,
                name,
                start_date,
                end_date,
                payment_date,
                is_closed
            FROM {LEGACY_PERIOD_TABLE}
            ON CONFLICT (id) DO NOTHING
            """
        )
        return cursor.rowcount


def _ensure_default_schedule(PaySchedule, AccountingCurrency):
    existing = PaySchedule.objects.filter(is_default=True).first()
    if existing:
        return existing

    existing = PaySchedule.objects.order_by("created_at").first()
    if existing:
        return existing

    currency = AccountingCurrency.objects.order_by("created_at").first()
    if currency is None:
        return None

    today = date.today()
    return PaySchedule.objects.create(
        name="Monthly Payroll",
        frequency="monthly",
        anchor_date=date(today.year, today.month, 1),
        currency=currency,
        payment_day_offset=0,
        overtime_multiplier=Decimal("1.50"),
        is_default=True,
        is_active=True,
    )


def _repair_orphan_fks(apps, default_schedule):
    PaySchedule = apps.get_model("payroll_v2", "PaySchedule")
    Employee = apps.get_model("hr", "Employee")
    PayrollRunRecord = apps.get_model("payroll_v2", "PayrollRunRecord")

    valid_ids = set(PaySchedule.objects.values_list("id", flat=True))
    fallback_id = default_schedule.id if default_schedule else None

    for model, field_name in (
        (Employee, "pay_schedule_id"),
        (PayrollRunRecord, "pay_schedule_id"),
    ):
        orphan_qs = model.objects.filter(**{f"{field_name}__isnull": False}).exclude(
            **{f"{field_name}__in": valid_ids}
        )
        if fallback_id is None:
            orphan_qs.update(**{field_name: None})
        else:
            orphan_qs.update(**{field_name: fallback_id})


def migrate_legacy_pay_schedules(apps, schema_editor):
    connection = schema_editor.connection
    PaySchedule = apps.get_model("payroll_v2", "PaySchedule")
    AccountingCurrency = apps.get_model("accounting", "AccountingCurrency")

    _copy_legacy_schedules(connection, PaySchedule)
    _copy_legacy_periods(connection)

    default_schedule = _ensure_default_schedule(PaySchedule, AccountingCurrency)
    _repair_orphan_fks(apps, default_schedule)


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0011_alter_payrollsettings_created_by_and_more"),
        ("hr", "0012_remove_employee_tax_rules"),
        ("accounting", "0006_remove_accountingpayrollpostingbatch_payroll_run"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_pay_schedules, migrations.RunPython.noop),
    ]
