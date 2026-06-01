from decimal import Decimal

from django.db import models

from common.models import BaseModel

from .enums import DisbursementRecordStatus, DisbursementSourceType


class EmployeeDisbursementRecord(BaseModel):
    """Immutable paid disbursement snapshot for payroll and employee benefits."""

    source_type = models.CharField(max_length=20, choices=DisbursementSourceType.choices)
    source_id = models.UUIDField(db_index=True)
    payroll_employee_item = models.ForeignKey(
        "payroll_v2.PayrollEmployeeItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disbursement_records",
    )
    benefit_request_line = models.ForeignKey(
        "employee_benefits.BenefitRequestLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disbursement_records",
    )
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="disbursement_records",
    )
    journal_entry = models.ForeignKey(
        "accounting.AccountingJournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_disbursement_records",
    )
    status = models.CharField(
        max_length=20,
        choices=DisbursementRecordStatus.choices,
        default=DisbursementRecordStatus.ACTIVE,
        db_index=True,
    )
    paid_at = models.DateTimeField()
    reverted_at = models.DateTimeField(null=True, blank=True)

    payment_date = models.DateField(db_index=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    reference_number = models.CharField(max_length=80, blank=True, default="")
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="employee_disbursement_records",
        null=True,
        blank=True,
    )
    net_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    gross_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
    )
    benefit_type_name = models.CharField(max_length=120, blank=True, default="")
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "employee_disbursement_record"
        ordering = ["-payment_date", "-paid_at"]
        indexes = [
            models.Index(fields=["employee", "payment_date", "status"]),
            models.Index(fields=["source_type", "source_id", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["payroll_employee_item"],
                condition=models.Q(status=DisbursementRecordStatus.ACTIVE)
                & models.Q(payroll_employee_item__isnull=False),
                name="employee_disbursement_uniq_active_payroll_item",
            ),
            models.UniqueConstraint(
                fields=["benefit_request_line"],
                condition=models.Q(status=DisbursementRecordStatus.ACTIVE)
                & models.Q(benefit_request_line__isnull=False),
                name="employee_disbursement_uniq_active_benefit_line",
            ),
        ]

    def __str__(self):
        return f"{self.source_type}:{self.reference_number or self.id}"
