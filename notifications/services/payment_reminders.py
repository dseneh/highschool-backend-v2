from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from django.utils import timezone

from accounting.models import AccountingInstallmentPlan
from common.status import Roles
from finance.models import get_student_payment_plan, get_student_payment_status
from notifications.models import NotificationCampaign
from notifications.services.audience import get_tenant_user_queryset
from notifications.services.campaign_send import create_and_send_campaign
from students.models import Enrollment, StudentGuardian


PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(?P<key>[a-zA-Z0-9_]+)\s*\}\}|\{(?P<legacy>[a-zA-Z0-9_]+)\}")


@dataclass
class ReminderRecipient:
    user_id: str
    recipient_name: str
    student_name: str
    student_id: str
    audience_role: str
    balance_due: Decimal
    current_installment: str
    installment_due: Decimal
    due_date: str
    academic_year: str


def render_reminder_template(template: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group("key") or match.group("legacy") or ""
        return str(context.get(key, match.group(0)))

    return PLACEHOLDER_PATTERN.sub(replace, template or "")


def _get_current_installment_meta(academic_year):
    today = timezone.now().date()
    plan = (
        AccountingInstallmentPlan.objects.filter(academic_year=academic_year, is_active=True)
        .prefetch_related("lines")
        .first()
    )
    if not plan:
        return {"name": "Current installment", "due_date": ""}

    lines = sorted(plan.lines.all(), key=lambda line: (line.sequence, line.due_date))
    current_line = None
    for line in lines:
        if line.due_date <= today:
            current_line = line
    if current_line is None and lines:
        current_line = lines[0]

    if not current_line:
        return {"name": "Current installment", "due_date": ""}

    return {
        "name": current_line.name or f"Installment {current_line.sequence}",
        "due_date": current_line.due_date.isoformat() if current_line.due_date else "",
    }


def _get_installment_due_amount(enrollment, academic_year) -> Decimal:
    today = timezone.now().date()
    payment_plan = get_student_payment_plan(enrollment, academic_year)
    if not payment_plan:
        return Decimal("0")

    cumulative_balance_due = Decimal("0")
    for item in payment_plan:
        payment_date = item.get("payment_date")
        if payment_date and payment_date <= today.isoformat():
            cumulative_balance_due = Decimal(str(item.get("cumulative_balance") or 0))

    if cumulative_balance_due <= 0:
        return Decimal("0")

    return max(Decimal("0"), cumulative_balance_due)


def _resolve_student_and_guardian_users(student_ids: list[str]):
    tenant_users = get_tenant_user_queryset()
    users_by_id_number = {
        user.id_number: user
        for user in tenant_users.only("id", "id_number", "first_name", "last_name", "role")
        if user.id_number
    }

    guardians = StudentGuardian.objects.filter(student_id__in=student_ids, active=True).only(
        "student_id",
        "first_name",
        "last_name",
        "user_account_id_number",
    )

    guardians_by_student: dict[str, list[tuple[object, StudentGuardian]]] = {}
    for guardian in guardians:
        if not guardian.user_account_id_number:
            continue
        user = users_by_id_number.get(guardian.user_account_id_number)
        if not user:
            continue
        guardians_by_student.setdefault(str(guardian.student_id), []).append((user, guardian))

    return users_by_id_number, guardians_by_student


def build_payment_reminder_recipients(*, academic_year, student_ids: list[str] | None, audience: str, basis: str):
    enrollments = (
        Enrollment.objects.filter(academic_year=academic_year, active=True)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    )
    if student_ids:
        enrollments = enrollments.filter(student_id__in=student_ids)

    enrollments_list = list(enrollments)
    users_by_id_number, guardians_by_student = _resolve_student_and_guardian_users(
        [str(enrollment.student_id) for enrollment in enrollments_list]
    )

    installment_meta = _get_current_installment_meta(academic_year)
    recipients: list[ReminderRecipient] = []
    eligible_student_ids: set[str] = set()

    for enrollment in enrollments_list:
        student = enrollment.student
        payment_status = get_student_payment_status(enrollment, academic_year)
        total_due = Decimal(str(payment_status.get("overall_balance") or 0))
        if total_due <= 0:
            continue

        installment_due = _get_installment_due_amount(enrollment, academic_year)
        balance_due = total_due if basis == "total" else min(total_due, installment_due)
        if balance_due <= 0:
            continue

        student_id = str(student.id)
        eligible_student_ids.add(student_id)
        student_name = student.get_full_name()
        due_date = installment_meta["due_date"] or (payment_status.get("next_due_date") or "")
        current_installment = installment_meta["name"]

        if audience in ("students", "both") and student.user_account_id_number:
            student_user = users_by_id_number.get(student.user_account_id_number)
            if student_user:
                recipients.append(
                    ReminderRecipient(
                        user_id=str(student_user.id),
                        recipient_name=student_user.get_full_name() or student_name,
                        student_name=student_name,
                        student_id=student_id,
                        audience_role=Roles.STUDENT,
                        balance_due=balance_due,
                        current_installment=current_installment,
                        installment_due=installment_due,
                        due_date=due_date,
                        academic_year=academic_year.name,
                    )
                )

        if audience in ("parents", "both"):
            for parent_user, guardian in guardians_by_student.get(student_id, []):
                recipients.append(
                    ReminderRecipient(
                        user_id=str(parent_user.id),
                        recipient_name=parent_user.get_full_name() or guardian.full_name,
                        student_name=student_name,
                        student_id=student_id,
                        audience_role=Roles.PARENT,
                        balance_due=balance_due,
                        current_installment=current_installment,
                        installment_due=installment_due,
                        due_date=due_date,
                        academic_year=academic_year.name,
                    )
                )

    return recipients, eligible_student_ids


def send_payment_reminders(
    *,
    created_by,
    academic_year,
    student_ids: list[str] | None,
    audience: str,
    basis: str,
    channels: list[str] | None = None,
    title_template: str = "",
    body_template: str = "",
    parent_title_template: str = "",
    parent_body_template: str = "",
    student_title_template: str = "",
    student_body_template: str = "",
):
    recipients, eligible_student_ids = build_payment_reminder_recipients(
        academic_year=academic_year,
        student_ids=student_ids,
        audience=audience,
        basis=basis,
    )
    delivery_channels = list(channels or ["in_app", "email"])

    generic_title = (title_template or "").strip()
    generic_body = (body_template or "").strip()
    parent_title = (parent_title_template or generic_title).strip()
    parent_body = (parent_body_template or generic_body).strip()
    student_title = (student_title_template or generic_title).strip()
    student_body = (student_body_template or generic_body).strip()

    campaign_count = 0
    for recipient in recipients:
        balance_str = f"{recipient.balance_due:,.2f}"
        installment_str = f"{recipient.installment_due:,.2f}"
        context = {
            "recipient_name": recipient.recipient_name,
            "student_name": recipient.student_name,
            "student_id": recipient.student_id,
            "balance_due": balance_str,
            "installment_due": installment_str,
            "current_installment": recipient.current_installment,
            "due_date": recipient.due_date,
            "academic_year": recipient.academic_year,
        }

        if recipient.audience_role == Roles.PARENT:
            resolved_title_template = parent_title
            resolved_body_template = parent_body
        else:
            resolved_title_template = student_title
            resolved_body_template = student_body

        create_and_send_campaign(
            title=render_reminder_template(resolved_title_template, context),
            body=render_reminder_template(resolved_body_template, context),
            category=NotificationCampaign.Category.FINANCE,
            channels=delivery_channels,
            audience={"scope": "user_ids", "user_ids": [recipient.user_id]},
            source=NotificationCampaign.Source.MANUAL,
            created_by=created_by,
        )
        campaign_count += 1

    return {
        "student_count": len(eligible_student_ids),
        "recipient_count": len(recipients),
        "campaign_count": campaign_count,
    }