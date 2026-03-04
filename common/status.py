from enum import Enum


class Roles:
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"
    VIEWER = "viewer"
    REGISTRAR = "registrar"
    DATA_ENTRY = "data_entry"
    PARENT = "parent"
    ACCOUNTANT = "accountant"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class PersonStatus:
    RESET = "reset"
    CREATED = "created"
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class SchoolFundingType:
    PRIVATE = "private"
    PUBLIC = "public"
    CHARTER = "charter"
    INTERNATIONAL = "international"
    ONLINE = "online"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]

class SchoolType:
    PRIMARY = "primary"
    SECONDARY = "secondary"
    HIGHER_EDUCATION = "higher_education"
    VOCATIONAL = "vocational"
    K12 = "k12"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class SchoolLevel:
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class UserAccountStatus:
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"
    BLOCKED = "blocked"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class StudentStatus:
    ACTIVE = "active"
    ENROLLED = "enrolled"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"
    GRADUATED = "graduated"
    TRANSFERRED = "transferred"
    WITHDRAWN = "withdrawn"
    NTR = "ntr"  # Not Returned

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class EnrollmentStatus:
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELED = "canceled"
    WITHDRAWN = "withdrawn"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class EnrollmentType:
    NEW = "new"
    TRANSFERRED = "transferred"
    RETURNING = "returning"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class GradeStatus:
    NONE = None
    CREATED = "created"
    PENDING = "pending"
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants (excludes None)."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper()
            and isinstance(value, str)
            and not callable(value)
            and value is not None
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class EmployeePosition:
    TEACHER = "teacher"
    ADMINISTRATOR = "administrator"
    PRINCIPAL = "principal"
    DEAN = "dean"
    JANITOR = "janitor"
    VICE_PRINCIPAL = "vice_principal"
    STAFF = "staff"
    DATA_ENTRY = "data_entry"

    @classmethod
    def all(cls):
        """Automatically collect all uppercase string constants."""
        return [
            value
            for key, value in vars(cls).items()
            if key.isupper() and isinstance(value, str) and not callable(value)
        ]

    @classmethod
    def choices(cls):
        return [(x.lower(), x.capitalize()) for x in cls.all()]


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"
    HOLIDAY = "holiday"

    @classmethod
    def all(cls):
        return [status.value for status in cls]

    @classmethod
    def choices(cls):
        return [(status.value, status.value.capitalize()) for status in cls]


class UserAccountType(str, Enum):
    STUDENT = "student"
    GLOBAL = "global"
    STAFF = "staff"
    PARENT = "parent"
    OTHER = "other"

    @classmethod
    def all(cls):
        return [status.value for status in cls]

    @classmethod
    def choices(cls):
        return [(status.value, status.value.capitalize()) for status in cls]


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"
    HOLIDAY = "holiday"

    @classmethod
    def all(cls):
        return [status.value for status in cls]

    @classmethod
    def choices(cls):
        return [(status.value, status.value.capitalize()) for status in cls]
