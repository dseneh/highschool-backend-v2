

from users.access_policies.access import BaseSchoolAccessPolicy


class StudentRecordAccessPolicy(BaseSchoolAccessPolicy):
    """Authorization for the primary student list and detail resources."""

    statements = [
        {
            "action": ["get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.view",
        },
        {
            "action": ["post"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.create",
        },
        {
            "action": ["put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.update",
        },
        {
            "action": ["delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.delete",
        },
    ]

    def has_student_permission(self, request, view, action, permission_code) -> bool:
        user = self._get_user(request)
        if not user:
            return False

        from authorization.runtime import initialize_request_authorization

        return initialize_request_authorization(
            request,
            user,
        ).permission_scope(permission_code) is not None


class StudentAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for student-related endpoints:
      - students_student
      - students_enrollment
      - students_attendance
      - students_gradebook
      - students_studentenrollmentbill
      - students_studentpaymentsummary
    """

    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.view",
        },
        {
            "action": ["create_student"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.create",
        },
        {
            "action": ["create", "post", "update", "partial_update", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.update",
        },
        {
            "action": ["enroll"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.enroll",
        },
        {
            "action": ["promote"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.promote",
        },
        {
            "action": ["transfer"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.transfer",
        },
        {
            "action": ["withdraw"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.withdraw",
        },
        {
            "action": ["lifecycle"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_any_student_permission:students.promote,students.transfer",
        },
        {
            "action": ["destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_student_permission:students.delete",
        },
    ]

    has_student_permission = StudentRecordAccessPolicy.has_student_permission

    def has_any_student_permission(self, request, view, action, permission_codes):
        user = self._get_user(request)
        if not user:
            return False

        from authorization.runtime import initialize_request_authorization

        facade = initialize_request_authorization(request, user)
        return any(
            facade.permission_scope(code.strip()) is not None
            for code in permission_codes.split(",")
            if code.strip()
        )


class HistoricalGradeAccessPolicy(BaseSchoolAccessPolicy):
    """Permissions for historical / transferred transcript grades."""

    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:grades.view",
        },
        {
            "action": ["create", "update", "partial_update", "post", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:grades.enter",
        },
        {
            "action": ["verify"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:grades.review",
        },
        {
            "action": ["unverify", "destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:grades.unlock",
        },
    ]

    has_domain_permission = StudentRecordAccessPolicy.has_student_permission


class AttendanceAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:attendance.view",
        },
        {
            "action": ["take"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:attendance.take",
        },
        {
            "action": ["update", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:attendance.update",
        },
        {
            "action": ["correct", "destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:attendance.correct",
        },
    ]

    has_domain_permission = StudentRecordAccessPolicy.has_student_permission


class BillingAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:billing.view",
        },
        {
            "action": ["manage", "create", "update", "partial_update", "post", "put", "patch", "destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:billing.manage",
        },
    ]

    has_domain_permission = StudentRecordAccessPolicy.has_student_permission


class StudentContactAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:students.contacts.view",
        },
        {
            "action": ["manage", "create", "update", "partial_update", "post", "put", "patch", "destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:students.contacts.manage",
        },
    ]

    has_domain_permission = StudentRecordAccessPolicy.has_student_permission


class StudentGuardianAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:students.guardians.view",
        },
        {
            "action": ["manage", "create", "update", "partial_update", "post", "put", "patch", "destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:students.guardians.manage",
        },
    ]

    has_domain_permission = StudentRecordAccessPolicy.has_student_permission


class StudentDisciplineAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:students.discipline.view",
        },
        {
            "action": ["manage", "create", "update", "partial_update", "post", "put", "patch", "destroy", "delete"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_domain_permission:students.discipline.manage",
        },
    ]

    has_domain_permission = StudentRecordAccessPolicy.has_student_permission
