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


class SponsorshipCoverageType(models.TextChoices):
    FULL = "full", "Full"
    PERCENTAGE = "percentage", "Percentage"
    FIXED_AMOUNT = "fixed_amount", "Fixed Amount"


class EmployeeContributionType(models.TextChoices):
    NONE = "none", "None"
    PERCENTAGE = "percentage", "Percentage"
    FIXED_AMOUNT = "fixed_amount", "Fixed Amount"


class EmployeeWardRelationshipType(models.TextChoices):
    CHILD = "child", "Child"
    DEPENDENT = "dependent", "Dependent"
    LEGAL_GUARDIAN = "legal_guardian", "Legal Guardian"
    OTHER = "other", "Other"


class StaffWardSponsorshipStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    REJECTED = "rejected", "Rejected"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class DeductionSourceType(models.TextChoices):
    STAFF_WARD_SPONSORSHIP = "staff_ward_sponsorship", "Staff Ward Sponsorship"
    SALARY_ADVANCE = "salary_advance", "Salary Advance"
    LOAN = "loan", "Loan"
    OTHER = "other", "Other"


class PayrollDeductionScheduleStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    PARTIALLY_APPLIED = "partially_applied", "Partially Applied"
    APPLIED = "applied", "Applied"
    DEFERRED = "deferred", "Deferred"
    ADJUSTED = "adjusted", "Adjusted"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class PayrollDeductionInstallmentStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    APPLIED = "applied", "Applied"
    ADJUSTED = "adjusted", "Adjusted"
    DEFERRED = "deferred", "Deferred"
    CANCELLED = "cancelled", "Cancelled"


class SalaryAdvanceRepaymentMethod(models.TextChoices):
    FIXED_INSTALLMENT = "fixed_installment", "Fixed Installment"
    EQUAL_SPLIT = "equal_split", "Equal Split"


class SalaryAdvanceRepaymentStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    IN_PROGRESS = "in_progress", "In Progress"
    PAID = "paid", "Paid"


class SalaryAdvanceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
