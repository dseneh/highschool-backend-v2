from datetime import date

from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from academics.models import AcademicYear, Division, GradeLevel, Section, SectionSubject, Subject
from core.models import Tenant
from grading.models import GradeBook
from hr.models import Employee, EmployeeTeacherSubject
from hr.views import EmployeeTeacherSubjectViewSet
from users.models import User


class EmployeeTeacherSubjectAssignmentTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Teacher Assignment Test School"
        tenant.id_number = "TAS001"
        tenant.owner, _ = User.objects.get_or_create(
            email="tenant-owner@example.com",
            defaults={
                "username": "tenant-owner",
                "id_number": "TENANT-OWNER-001",
                "role": "admin",
                "first_name": "Tenant",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin, _ = User.objects.get_or_create(
            email="assignment-admin@example.com",
            defaults={
                "username": "assignment-admin",
                "id_number": "ADMIN-001",
                "role": "admin",
                "first_name": "Assignment",
                "last_name": "Admin",
            },
        )
        self.teacher = Employee.objects.create(
            employee_number="EMP-001",
            id_number="TEACHER-001",
            first_name="Ada",
            last_name="Lovelace",
            is_teacher=True,
        )
        self.replacement_teacher = Employee.objects.create(
            employee_number="EMP-002",
            id_number="TEACHER-002",
            first_name="Grace",
            last_name="Hopper",
            is_teacher=True,
        )
        self.academic_year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            current=True,
        )
        division = Division.objects.create(name="Secondary")
        grade_level = GradeLevel.objects.create(name="Grade 10", level=10, division=division)
        self.section = Section.objects.create(name="A", grade_level=grade_level)
        self.subject = Subject.objects.create(name="Mathematics", code="MATH10")
        self.section_subject = SectionSubject.objects.create(
            section=self.section,
            subject=self.subject,
        )
        self.gradebook = GradeBook.objects.create(
            name="Mathematics Grade 10 A",
            section_subject=self.section_subject,
            section=self.section,
            subject=self.subject,
            academic_year=self.academic_year,
        )

    def _request(self, method, payload=None):
        request = getattr(self.factory, method)(
            "/api/v1/employee-teacher-subjects/",
            payload or {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        return request

    def test_create_retrieve_update_and_delete_gradebook_teacher_assignment(self):
        create_response = EmployeeTeacherSubjectViewSet.as_view({"post": "create"})(
            self._request("post", {"teacher": str(self.teacher.id), "section_subject": str(self.section_subject.id)})
        )

        self.assertEqual(create_response.status_code, 201, create_response.data)
        assignment = EmployeeTeacherSubject.objects.get(section_subject=self.section_subject)
        self.assertEqual(assignment.teacher_id, self.teacher.id)
        self.assertEqual(assignment.subject_id, self.subject.id)

        retrieve_request = self._request("get")
        retrieve_response = EmployeeTeacherSubjectViewSet.as_view({"get": "retrieve"})(
            retrieve_request,
            pk=str(assignment.id),
        )
        self.assertEqual(retrieve_response.status_code, 200)
        self.assertEqual(retrieve_response.data["teacher"]["id"], str(self.teacher.id))
        self.assertEqual(retrieve_response.data["section_subject"]["id"], str(self.section_subject.id))

        update_request = self._request("patch", {"teacher": str(self.replacement_teacher.id)})
        update_response = EmployeeTeacherSubjectViewSet.as_view({"patch": "partial_update"})(
            update_request,
            pk=str(assignment.id),
        )
        self.assertEqual(update_response.status_code, 200, update_response.data)
        assignment.refresh_from_db()
        self.assertEqual(assignment.teacher_id, self.replacement_teacher.id)

        delete_request = self._request("delete")
        delete_response = EmployeeTeacherSubjectViewSet.as_view({"delete": "destroy"})(
            delete_request,
            pk=str(assignment.id),
        )
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(EmployeeTeacherSubject.objects.filter(pk=assignment.id).exists())

    def test_invalid_teacher_uuid_returns_clear_validation_error(self):
        response = EmployeeTeacherSubjectViewSet.as_view({"post": "create"})(
            self._request(
                "post",
                {
                    "teacher": "0e222b04-03ca-47f1-9ccd-20bce1926bb4",
                    "section_subject": str(self.section_subject.id),
                },
            )
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("teacher", str(response.data.get("detail", response.data)).lower())
        self.assertIn("does not exist", str(response.data).lower())

    def test_employee_from_another_tenant_is_rejected(self):
        other_tenant = Tenant(schema_name="teacher_assignment_other", name="Other School", id_number="TAS002")
        other_tenant.owner = self.admin
        try:
            from django_tenants.utils import get_public_schema_name

            with schema_context(get_public_schema_name()):
                other_tenant.save(verbosity=0)
            with schema_context(other_tenant.schema_name):
                other_teacher = Employee.objects.create(
                    employee_number="EMP-OTHER",
                    id_number="TEACHER-OTHER",
                    first_name="Other",
                    last_name="School",
                    is_teacher=True,
                )
                foreign_teacher_id = str(other_teacher.id)

            response = EmployeeTeacherSubjectViewSet.as_view({"post": "create"})(
                self._request(
                    "post",
                    {
                        "teacher": foreign_teacher_id,
                        "section_subject": str(self.section_subject.id),
                    },
                )
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("teacher", str(response.data.get("detail", response.data)).lower())
        finally:
            with schema_context("public"):
                other_tenant.delete(force_drop=True)

    def test_non_teacher_employee_is_rejected(self):
        employee = Employee.objects.create(
            employee_number="EMP-003",
            id_number="STAFF-003",
            first_name="Not",
            last_name="Teacher",
            is_teacher=False,
        )

        response = EmployeeTeacherSubjectViewSet.as_view({"post": "create"})(
            self._request(
                "post",
                {"teacher": str(employee.id), "section_subject": str(self.section_subject.id)},
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "not marked as a teacher",
            str(response.data).lower(),
        )
