"""Regression tests for student list filtering contracts."""

from datetime import date

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from academics.models import AcademicYear, Division, GradeLevel, Section
from common.status import EnrollmentStatus, StudentStatus, YearEndOutcome
from reports.views.students import _build_students_queryset
from students.models import Enrollment, Student
from students.views.student import StudentListView
from users.models import User


class StudentListFilterTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Student List Filter Test School"
        tenant.id_number = "SLF001"
        tenant.owner, _ = User.objects.get_or_create(
            email="student-list-owner@example.com",
            defaults={
                "username": "student-list-owner",
                "id_number": "STUDENT-LIST-OWNER-001",
                "role": "admin",
                "first_name": "List",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = User.objects.get(email="student-list-owner@example.com")
        self.previous_year = AcademicYear.objects.create(
            name="2024-2025",
            start_date=date(2024, 9, 2),
            end_date=date(2025, 7, 18),
            current=False,
            status="inactive",
        )
        self.current_year = AcademicYear.objects.create(
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 17),
            current=True,
            status="active",
        )
        self.division = Division.objects.create(name="Secondary")
        self.grade = GradeLevel.objects.create(
            name="Grade 12", level=12, division=self.division
        )
        self.section = Section.objects.create(name="12A", grade_level=self.grade)

        self.new_student = self._create_student("New", "Student", "90001")
        # A current-year-only enrollment is not enrollment history.
        Enrollment.objects.create(
            student=self.new_student,
            academic_year=self.current_year,
            grade_level=self.grade,
            section=self.section,
            status=EnrollmentStatus.ENROLLED,
        )

        self.returning_student = self._create_student("Returning", "Student", "90002")
        Enrollment.objects.create(
            student=self.returning_student,
            academic_year=self.previous_year,
            grade_level=self.grade,
            section=self.section,
            status=EnrollmentStatus.COMPLETED,
            year_end_outcome=YearEndOutcome.PROMOTED,
        )

        # Prior enrollment history counts even when the year was never completed.
        self.withdrawn_returning_student = self._create_student(
            "Withdrawn", "Returner", "90004"
        )
        Enrollment.objects.create(
            student=self.withdrawn_returning_student,
            academic_year=self.previous_year,
            grade_level=self.grade,
            section=self.section,
            status=EnrollmentStatus.WITHDRAWN,
        )

        self.graduate = self._create_student(
            "Graduated",
            "Student",
            "90003",
            status=StudentStatus.GRADUATED,
            date_of_graduation=date(2025, 7, 18),
        )
        Enrollment.objects.create(
            student=self.graduate,
            academic_year=self.previous_year,
            grade_level=self.grade,
            section=self.section,
            status=EnrollmentStatus.COMPLETED,
            year_end_outcome=YearEndOutcome.GRADUATED,
        )

    def _create_student(self, first_name, last_name, id_number, **extra):
        return Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            id_number=id_number,
            grade_level=self.grade,
            status=extra.pop("status", StudentStatus.ACTIVE),
            **extra,
        )

    def _list(self, **params):
        request = self.factory.get("/students/", params)
        force_authenticate(request, user=self.admin)
        response = StudentListView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        return response.data

    def _id_numbers(self, data):
        return {row["id_number"] for row in data["results"]}

    def test_student_type_filter_returns_only_new_students(self):
        data = self._list(student_type="new")
        self.assertEqual(self._id_numbers(data), {self.new_student.id_number})

    def test_student_type_filter_returns_only_returning_students(self):
        data = self._list(student_type="returning")
        self.assertEqual(
            self._id_numbers(data),
            {
                self.returning_student.id_number,
                self.withdrawn_returning_student.id_number,
                self.graduate.id_number,
            },
        )

    def test_any_prior_year_enrollment_marks_student_returning(self):
        data = self._list(search=self.withdrawn_returning_student.id_number)
        self.assertEqual(data["results"][0]["student_type"], "returning")

    def test_current_year_only_enrollment_stays_new(self):
        data = self._list(search=self.new_student.id_number)
        self.assertEqual(data["results"][0]["student_type"], "new")

    def test_exclude_status_removes_graduates_from_results(self):
        data = self._list(exclude_status="graduated")
        self.assertNotIn(self.graduate.id_number, self._id_numbers(data))

    def test_graduated_status_filter_returns_only_graduates(self):
        data = self._list(status="graduated")
        self.assertEqual(self._id_numbers(data), {self.graduate.id_number})

    def test_graduation_year_comes_from_year_end_record(self):
        data = self._list(status="graduated")
        graduate_row = data["results"][0]
        self.assertEqual(graduate_row["graduation_year"], self.previous_year.name)

    def test_graduation_year_filter(self):
        data = self._list(status="graduated", graduation_year=self.previous_year.name)
        self.assertEqual(self._id_numbers(data), {self.graduate.id_number})

        data = self._list(status="graduated", graduation_year=self.current_year.name)
        self.assertEqual(data["count"], 0)


class StudentReportFilterTests(StudentListFilterTests):
    """The export queryset must honour the same filters as the list view."""

    def _export(self, **params):
        return _build_students_queryset(params)

    def _export_id_numbers(self, **params):
        return {student.id_number for student in self._export(**params)}

    def test_export_excludes_graduates(self):
        self.assertNotIn(
            self.graduate.id_number,
            self._export_id_numbers(exclude_status="graduated"),
        )

    def test_export_scopes_to_graduates(self):
        self.assertEqual(
            self._export_id_numbers(status="graduated"),
            {self.graduate.id_number},
        )

    def test_export_filters_by_student_type(self):
        self.assertEqual(
            self._export_id_numbers(student_type="new"),
            {self.new_student.id_number},
        )

    def test_export_filters_by_graduation_year(self):
        self.assertEqual(
            self._export_id_numbers(graduation_year=self.previous_year.name),
            {self.graduate.id_number},
        )
        self.assertEqual(
            self._export_id_numbers(graduation_year=self.current_year.name),
            set(),
        )
