from django.db import models


class DisbursementSourceType(models.TextChoices):
    PAYROLL = "payroll", "Payroll"
    BENEFIT = "benefit", "Benefit"


class DisbursementRecordStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVERTED = "reverted", "Reverted"
