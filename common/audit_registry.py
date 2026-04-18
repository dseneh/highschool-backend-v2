"""
Central audit trail registration for django-auditlog.

All models that should be tracked for changes are registered here.
This file is imported in CommonConfig.ready() to ensure registration
happens after all apps are loaded.

django-auditlog automatically captures:
- CREATE / UPDATE / DELETE actions
- Field-level change diffs (old → new values as JSON)
- Actor (user who made the change) via AuditlogMiddleware
- Remote IP address via AuditlogMiddleware
- Timestamp
- Object representation (str of instance)
"""

from auditlog.registry import auditlog

# Fields to exclude globally (noisy auto-set fields)
COMMON_EXCLUDE = ["updated_at"]


def register_all_models():
    """Register all models with django-auditlog for change tracking."""

    # ── Academics ──────────────────────────────────────────────────────
    from academics.models import (
        AcademicYear,
        SchoolCalendarSettings,
        SchoolCalendarEvent,
        Semester,
        MarkingPeriod,
        Division,
        GradeLevel,
        GradeLevelTuitionFee,
        Section,
        Subject,
        SectionSubject,
        Period,
        PeriodTime,
        SectionSchedule,
    )

    auditlog.register(AcademicYear, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(SchoolCalendarSettings, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(SchoolCalendarEvent, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Semester, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(MarkingPeriod, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Division, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(GradeLevel, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(GradeLevelTuitionFee, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Section, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Subject, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(SectionSubject, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Period, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(PeriodTime, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(SectionSchedule, exclude_fields=COMMON_EXCLUDE)

    # ── Students ───────────────────────────────────────────────────────
    from students.models import (
        Student,
        Enrollment,
        Attendance,
        StudentEnrollmentBill,
        StudentConcession,
        StudentPaymentSummary,
        StudentContact,
        StudentGuardian,
    )

    auditlog.register(Student, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Enrollment, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Attendance, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(StudentEnrollmentBill, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(StudentConcession, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(StudentPaymentSummary, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(StudentContact, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(StudentGuardian, exclude_fields=COMMON_EXCLUDE)

    # ── Staff ──────────────────────────────────────────────────────────
    from staff.models import (
        Department,
        PositionCategory,
        Position,
        Staff,
        TeacherSection,
        TeacherSubject,
        TeacherSchedule,
    )

    auditlog.register(Department, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(PositionCategory, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Position, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Staff, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(TeacherSection, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(TeacherSubject, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(TeacherSchedule, exclude_fields=COMMON_EXCLUDE)

    # ── Finance ────────────────────────────────────────────────────────
    from finance.models import (
        BankAccount,
        PaymentMethod,
        Currency,
        GeneralFeeList,
        SectionFee,
        TransactionType,
        Transaction,
        PaymentInstallment,
    )

    auditlog.register(BankAccount, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(PaymentMethod, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Currency, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(GeneralFeeList, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(SectionFee, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(TransactionType, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Transaction, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(PaymentInstallment, exclude_fields=COMMON_EXCLUDE)

    # ── Grading ────────────────────────────────────────────────────────
    from grading.models import (
        GradeLetter,
        AssessmentType,
        GradeBook,
        Assessment,
        Grade,
    )

    auditlog.register(GradeLetter, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AssessmentType, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(GradeBook, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Assessment, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Grade, exclude_fields=COMMON_EXCLUDE)
    # Note: GradeHistory is the audit itself — not registered

    # ── Accounting ─────────────────────────────────────────────────────
    from accounting.models import (
        AccountingCurrency,
        AccountingExchangeRate,
        AccountingLedgerAccount,
        AccountingJournalEntry,
        AccountingJournalLine,
        AccountingBankAccount,
        AccountingPaymentMethod,
        AccountingTransactionType,
        AccountingCashTransaction,
        AccountingAccountTransfer,
        AccountingFeeItem,
        AccountingFeeRate,
        AccountingStudentBill,
        AccountingStudentBillLine,
        AccountingConcession,
        AccountingInstallmentPlan,
        AccountingInstallmentLine,
        AccountingStudentPaymentAllocation,
        AccountingTaxCode,
        AccountingTaxRemittance,
        AccountingExpenseRecord,
        AccountingPayrollPostingBatch,
        AccountingPayrollPostingLine,
    )

    auditlog.register(AccountingCurrency, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingExchangeRate, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingLedgerAccount, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingJournalEntry, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingJournalLine, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingBankAccount, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingPaymentMethod, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingTransactionType, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingCashTransaction, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingAccountTransfer, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingFeeItem, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingFeeRate, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingStudentBill, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingStudentBillLine, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingConcession, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingInstallmentPlan, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingInstallmentLine, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingStudentPaymentAllocation, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingTaxCode, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingTaxRemittance, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingExpenseRecord, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingPayrollPostingBatch, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(AccountingPayrollPostingLine, exclude_fields=COMMON_EXCLUDE)

    # ── HR ─────────────────────────────────────────────────────────────
    from hr.models import (
        EmployeeDepartment,
        EmployeePosition,
        Employee,
        EmployeeContact,
        EmployeeDependent,
        EmployeeDocument,
        LeaveType,
        LeaveRequest,
        EmployeeAttendance,
        EmployeePerformanceReview,
        EmployeeWorkflowTask,
        PayrollComponent,
        EmployeeCompensation,
        EmployeeCompensationItem,
        PayrollRun,
    )

    auditlog.register(EmployeeDepartment, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeePosition, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(Employee, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeContact, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeDependent, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeDocument, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(LeaveType, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(LeaveRequest, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeAttendance, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeePerformanceReview, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeWorkflowTask, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(PayrollComponent, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeCompensation, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(EmployeeCompensationItem, exclude_fields=COMMON_EXCLUDE)
    auditlog.register(PayrollRun, exclude_fields=COMMON_EXCLUDE)

    # ── Settings ───────────────────────────────────────────────────────
    from settings.models import GradingSettings

    auditlog.register(GradingSettings, exclude_fields=COMMON_EXCLUDE)
