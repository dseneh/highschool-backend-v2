"""Query-count regression tests for the student list endpoint.

The list endpoint must stay O(1) in queries per page: adding more students to a
page must not add queries. See the ceilings asserted below.
"""

from datetime import date

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from academics.models import AcademicYear, Division, GradeLevel, Section
from common.status import EnrollmentStatus, StudentStatus
from students.models import Enrollment, Student
from students.views.student import StudentListView
from users.models import User


class StudentListQueryCountTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Student List Perf Test School"
        tenant.id_number = "SLP001"
        tenant.owner, _ = User.objects.get_or_create(
            email="student-list-perf@example.com",
            defaults={
                "username": "student-list-perf",
                "id_number": "STUDENT-LIST-PERF-001",
                "account_type": "staff",
                "first_name": "Perf",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = User.objects.get(email="student-list-perf@example.com")
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

    def _create_students(self, count, start=90000):
        for offset in range(count):
            student = Student.objects.create(
                first_name=f"Student{offset}",
                last_name="Test",
                id_number=str(start + offset),
                grade_level=self.grade,
                status=StudentStatus.ACTIVE,
            )
            Enrollment.objects.create(
                student=student,
                academic_year=self.current_year,
                grade_level=self.grade,
                section=self.section,
                status=EnrollmentStatus.ENROLLED,
            )

    def _list_params(self, **overrides):
        params = {
            "page": 1,
            "page_size": 20,
            "show_balance": "1",
            "show_paid": "1",
            "status": "enrolled",
        }
        params.update(overrides)
        return params

    def _capture_list(self, **params):
        request = self.factory.get("/students/", self._list_params(**params))
        force_authenticate(request, user=self.admin)
        view = StudentListView.as_view()
        with CaptureQueriesContext(connection) as captured:
            response = view(request)
            # Force full serialization inside the capture window.
            self.assertEqual(response.status_code, 200)
            _ = response.data["results"]
        return response, len(captured)

    def _warmup(self):
        """First request pays one-time setup (solo settings row, auth lookups)."""
        self._capture_list(page_size=1)

    def test_query_count_does_not_grow_with_page_size(self):
        """Adding rows to a page must not add queries."""
        self._create_students(5, start=90000)
        self._warmup()
        _, queries_for_five = self._capture_list(page_size=5)

        self._create_students(15, start=91000)
        _, queries_for_twenty = self._capture_list(page_size=20)

        self.assertEqual(
            queries_for_five,
            queries_for_twenty,
            f"Query count scales with rows: {queries_for_five} for 5 rows vs "
            f"{queries_for_twenty} for 20 rows. There is an N+1 in the list path.",
        )

    def test_page_of_twenty_stays_under_query_ceiling(self):
        self._create_students(20)
        self._warmup()
        _, query_count = self._capture_list(page_size=20)
        self.assertLessEqual(
            query_count,
            20,
            f"Student list used {query_count} queries for a 20-row page.",
        )

    def test_stats_cost_is_fixed_not_per_row(self):
        """include_stats is a fixed set of aggregate passes; it must not scale with rows."""
        self._create_students(5, start=90000)
        self._warmup()
        _, five_plain = self._capture_list(page_size=5)
        _, five_stats = self._capture_list(page_size=5, include_stats="1")

        self._create_students(15, start=91000)
        _, twenty_plain = self._capture_list(page_size=20)
        _, twenty_stats = self._capture_list(page_size=20, include_stats="1")

        self.assertEqual(
            five_stats - five_plain,
            twenty_stats - twenty_plain,
            "include_stats overhead grows with row count.",
        )

    def test_payment_plan_is_excluded_from_billing_summary_by_default(self):
        self._create_students(3)
        response, _ = self._capture_list(page_size=3, include_billing="1")
        summaries = [
            row["current_enrollment"]["billing_summary"]
            for row in response.data["results"]
        ]
        self.assertTrue(summaries, "Expected billing summaries in the response.")
        for summary in summaries:
            self.assertEqual(summary.get("payment_plan"), [])

    def test_payment_plan_can_be_requested_explicitly(self):
        self._create_students(3)
        response, _ = self._capture_list(
            page_size=3, include_billing="1", include_payment_plan="1"
        )
        for row in response.data["results"]:
            self.assertIn(
                "payment_plan", row["current_enrollment"]["billing_summary"]
            )

    def test_billing_summary_still_carries_the_columns_the_list_renders(self):
        """include_billing must keep the fields the balance/paid columns read."""
        self._create_students(3)
        response, _ = self._capture_list(page_size=3, include_billing="1")
        summary = response.data["results"][0]["current_enrollment"]["billing_summary"]
        for field in ("total_bill", "paid", "balance", "payment_status"):
            self.assertIn(field, summary)
        self.assertIn("is_on_time", summary["payment_status"])
