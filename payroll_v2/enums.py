from django.db import models


class PayrollStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PROCESSING = "processing", "Processing"
    PENDING_APPROVAL = "pending_approval", "Pending Approval"
    APPROVED = "approved", "Approved"
    PAID = "paid", "Paid"
    CANCELLED = "cancelled", "Cancelled"


class PayrollType(models.TextChoices):
    REGULAR = "regular", "Regular"
    BONUS = "bonus", "Bonus"
    COMMISSION = "commission", "Commission"
    OVERTIME = "overtime", "Overtime"
    ADJUSTMENT = "adjustment", "Adjustment"
    TERMINATION = "termination", "Termination"


class PayType(models.TextChoices):
    SALARY = "salary", "Salary"
    HOURLY = "hourly", "Hourly"
    DAILY = "daily", "Daily"


class LineType(models.TextChoices):
    EARNING = "earning", "Earning"
    DEDUCTION = "deduction", "Deduction"
    TAX = "tax", "Tax"
    BENEFIT = "benefit", "Benefit"
    REIMBURSEMENT = "reimbursement", "Reimbursement"


class CalculationType(models.TextChoices):
    FLAT = "flat", "Flat Amount"
    PERCENTAGE = "percentage", "Percentage"
    FORMULA = "formula", "Formula"


class TargetAmountSource(models.TextChoices):
    BASIC_SALARY = "basic_salary", "Basic Salary"
    GROSS_PAY = "gross_pay", "Gross Pay"
    TAXABLE_INCOME = "taxable_income", "Taxable Income"
    ANNUAL_SALARY = "annual_salary", "Annual Salary"


class Frequency(models.TextChoices):
    ONE_TIME = "one_time", "One Time"
    WEEKLY = "weekly", "Weekly"
    BIWEEKLY = "biweekly", "Biweekly"
    SEMIMONTHLY = "semimonthly", "Semi-Monthly"
    MONTHLY = "monthly", "Monthly"
    ANNUAL = "annual", "Annual"


class PayScheduleFrequency(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    BIWEEKLY = "biweekly", "Bi-Weekly"
    WEEKLY = "weekly", "Weekly"


class PaymentStatus(models.TextChoices):
    UNPAID = "unpaid", "Unpaid"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    CHECK = "check", "Check"
    BANK_TRANSFER = "bank_transfer", "Bank Transfer"
    MOBILE_MONEY = "mobile_money", "Mobile Money"
    OTHER = "other", "Other"
