# users/permission_constants.py

"""
Central definition of all application-level special privilege codes.

These are stored in the SpecialPrivilege model (users.SpecialPrivilege)
and can be assigned/revoked per user.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class PrivilegeDef:
    code: str
    label: str
    description: str


# ---- Core domain-level privileges -----------------------------------------
# Note: these are broad permissions for app areas, not per-table codenames.


PRIVILEGES: Dict[str, PrivilegeDef] = {
    # CORE app (AcademicYear, Division, GradeLevel, etc.)
    "CORE_VIEW": PrivilegeDef(
        code="CORE_VIEW",
        label="View core configuration",
        description=(
            "Can view core setup data: AcademicYear, GradeLevel, Sections, Subjects, "
            "Periods, MarkingPeriods, etc."
        ),
    ),
    "CORE_MANAGE": PrivilegeDef(
        code="CORE_MANAGE",
        label="Manage core configuration",
        description=(
            "Can create/update/delete core setup data: AcademicYear, GradeLevel, "
            "Sections, Subjects, tuition fees, schedules, etc."
        ),
    ),


    # FINANCE app (BankAccount, Currency, GeneralFeeList, PaymentInstallment,
    # PaymentMethod, SectionFee, Transaction, TransactionType)
    "FINANCE_VIEW": PrivilegeDef(
        code="FINANCE_VIEW",
        label="View finance data",
        description=(
            "Can view finance-related information, including transactions and fee setup."
        ),
    ),
    "FINANCE_MANAGE": PrivilegeDef(
        code="FINANCE_MANAGE",
        label="Manage finance configuration",
        description=(
            "Can manage finance configuration: fee lists, payment methods, section fees, "
            "transaction types, etc."
        ),
    ),

    # GRADING app (Assessment, AssessmentType, CalculationMethod, DefaultAssessmentTemplate,
    # Grade, GradeBook, GradeLetter)
    "GRADING_VIEW": PrivilegeDef(
        code="GRADING_VIEW",
        label="View grading data",
        description=(
            "Can view grading setup and gradebooks: assessments, grade letters, etc."
        ),
    ),
    "GRADING_MANAGE": PrivilegeDef(
        code="GRADING_MANAGE",
        label="Manage grading configuration",
        description=(
            "Can manage grading configuration: assessment types, calculation methods, "
            "default templates, grade letters."
        ),
    ),

    # SETTINGS app (GradingSettings)
    "SETTINGS_GRADING_MANAGE": PrivilegeDef(
        code="SETTINGS_GRADING_MANAGE",
        label="Manage grading settings",
        description="Can manage grading settings for the tenant/school.",
    ),

    # STUDENTS app (Attendance, Enrollment, Student GradeBook, Student, StudentEnrollmentBill,
    # StudentPaymentSummary)
    "STUDENTS_VIEW": PrivilegeDef(
        code="STUDENTS_VIEW",
        label="View students",
        description="Can view student profiles, enrollments, attendance, and related data.",
    ),
    "STUDENTS_MANAGE": PrivilegeDef(
        code="STUDENTS_MANAGE",
        label="Manage students",
        description=(
            "Can create/update/delete basic student and enrollment records, "
            "subject to specific special privileges."
        ),
    ),

    # ---- Special action-level privileges (what you explicitly asked for) ----

    # STUDENTS: enroll, edit, delete
    "STUDENT_ENROLL": PrivilegeDef(
        code="STUDENT_ENROLL",
        label="Enroll students",
        description="Can enroll students into schools/sections (students_enrollment).",
    ),
    "STUDENT_EDIT": PrivilegeDef(
        code="STUDENT_EDIT",
        label="Edit student records",
        description="Can edit core student profile and enrollment records.",
    ),
    "STUDENT_DELETE": PrivilegeDef(
        code="STUDENT_DELETE",
        label="Delete student records",
        description="Can delete student/enrollment records when allowed.",
    ),

    # GRADING: enter, review, approve, reject
    "GRADING_ENTER": PrivilegeDef(
        code="GRADING_ENTER",
        label="Enter grades",
        description="Can enter grades into gradebooks (grading_grade, grading_gradebook).",
    ),
    "GRADING_REVIEW": PrivilegeDef(
        code="GRADING_REVIEW",
        label="Review grades",
        description="Can mark grades as reviewed.",
    ),
    "GRADING_APPROVE": PrivilegeDef(
        code="GRADING_APPROVE",
        label="Approve grades",
        description="Can approve grades in gradebooks.",
    ),
    "GRADING_REJECT": PrivilegeDef(
        code="GRADING_REJECT",
        label="Reject grades",
        description="Can reject grades and send them back for correction.",
    ),

    # TRANSACTION: create, delete, update, approve, cancel
    "TRANSACTION_CREATE": PrivilegeDef(
        code="TRANSACTION_CREATE",
        label="Create transactions",
        description="Can create finance transactions (finance_transaction).",
    ),
    "TRANSACTION_UPDATE": PrivilegeDef(
        code="TRANSACTION_UPDATE",
        label="Update transactions",
        description="Can update existing finance transactions.",
    ),
    "TRANSACTION_DELETE": PrivilegeDef(
        code="TRANSACTION_DELETE",
        label="Delete transactions",
        description="Can delete finance transactions.",
    ),
    "TRANSACTION_APPROVE": PrivilegeDef(
        code="TRANSACTION_APPROVE",
        label="Approve transactions",
        description="Can approve finance transactions.",
    ),
    "TRANSACTION_CANCEL": PrivilegeDef(
        code="TRANSACTION_CANCEL",
        label="Cancel transactions",
        description="Can cancel finance transactions.",
    ),
}


# Conveniences

ALL_PRIVILEGE_CODES: List[str] = list(PRIVILEGES.keys())

ALL_PRIVILEGE_DEFS: List[PrivilegeDef] = list(PRIVILEGES.values())
