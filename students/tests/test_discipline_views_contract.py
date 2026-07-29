from types import SimpleNamespace
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory


class _FakeDisciplineSerializer:
    def __init__(self, instance=None, data=None, partial=False):
        self.instance = instance
        self._data = data
        self.partial = partial
        self.validated_data = dict(data or {})

    def is_valid(self, raise_exception=False):
        return True

    def save(self, **kwargs):
        if self.instance is not None:
            return self.instance

        student = SimpleNamespace(id="student-1")
        return SimpleNamespace(id="record-1", student=student)

    @property
    def data(self):
        record_id = getattr(self.instance, "id", "record-1")
        return {"id": record_id}


class _FakeDisciplineUpdateSerializer:
    def __init__(self, instance=None, data=None, partial=False):
        self.instance = instance
        self.partial = partial
        self.validated_data = {
            "end_date": date(2026, 7, 1),
            "status": "inactive",
            "active": False,
        }

    def is_valid(self, raise_exception=False):
        return True

    def save(self, **kwargs):
        return self.instance

    @property
    def data(self):
        record_id = getattr(self.instance, "id", "record-1")
        return {"id": record_id}


class DisciplineViewContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_create_rejects_enrollment_status_update(self):
        import importlib

        discipline_module = importlib.import_module("students.views.discipline")
        view = discipline_module.StudentDisciplinaryActionListCreateView()

        payload = {
            "student": "student-1",
            "title": "Expulsion",
            "action_taken": "Expelled",
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
            "enrollment_status_update": "withdrawn",
        }
        request = self.factory.post("/students/discipline-actions", payload, format="json")
        request.data = payload
        request.user = SimpleNamespace(id="u1")

        response = view.post(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer supported", str(response.data.get("detail", "")))

    def test_create_rejects_student_status_update(self):
        import importlib

        discipline_module = importlib.import_module("students.views.discipline")
        view = discipline_module.StudentDisciplinaryActionListCreateView()

        payload = {
            "student": "student-1",
            "title": "Suspension",
            "action_taken": "Suspended",
            "start_date": "2026-07-01",
            "end_date": "2026-07-05",
            "student_status_update": "suspended",
        }
        request = self.factory.post("/students/discipline-actions", payload, format="json")
        request.data = payload
        request.user = SimpleNamespace(id="u1")

        response = view.post(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer supported", str(response.data.get("detail", "")))

    def test_update_rejects_student_status_update(self):
        import importlib

        discipline_module = importlib.import_module("students.views.discipline")
        view = discipline_module.StudentDisciplinaryActionDetailView()

        record = SimpleNamespace(id="record-1", student=SimpleNamespace(id="student-1"))

        payload = {
            "action_taken": "Suspended",
            "student_status_update": "suspended",
        }
        request = self.factory.put(
            "/students/discipline-actions/record-1", payload, format="json"
        )
        request.data = payload
        request.user = SimpleNamespace(id="u1")

        with patch.object(
            discipline_module.StudentDisciplinaryActionDetailView,
            "get_object",
            return_value=record,
        ):
            response = view.put(request, "record-1")

        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer supported", str(response.data.get("detail", "")))

    def test_update_requires_attendance_resolution_when_ending_early(self):
        import importlib

        discipline_module = importlib.import_module("students.views.discipline")
        view = discipline_module.StudentDisciplinaryActionDetailView()

        record = SimpleNamespace(
            id="record-1",
            student=SimpleNamespace(id="student-1"),
            end_date=date(2026, 7, 5),
            status="active",
            active=True,
            action_type=SimpleNamespace(attendance_effect_enabled=True),
        )

        payload = {
            "end_date": "2026-07-01",
            "status": "inactive",
            "active": False,
        }
        request = self.factory.put(
            "/students/discipline-actions/record-1", payload, format="json"
        )
        request.data = payload
        request.user = SimpleNamespace(id="u1")

        with patch.object(
            discipline_module.StudentDisciplinaryActionDetailView,
            "get_object",
            return_value=record,
        ), patch.object(
            discipline_module,
            "StudentDisciplinaryActionSerializer",
            _FakeDisciplineUpdateSerializer,
        ), patch.object(
            discipline_module,
            "count_unresolved_attendance_impacts_after",
            return_value=4,
        ):
            response = view.put(request, "record-1")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data.get("code"), "attendance_resolution_required")
        self.assertEqual(response.data.get("affected_attendance_rows"), 4)

    def test_update_applies_attendance_resolution_when_provided(self):
        import importlib

        discipline_module = importlib.import_module("students.views.discipline")
        view = discipline_module.StudentDisciplinaryActionDetailView()

        record = SimpleNamespace(
            id="record-1",
            student=SimpleNamespace(id="student-1"),
            end_date=date(2026, 7, 5),
            status="active",
            active=True,
            action_type=SimpleNamespace(attendance_effect_enabled=True),
        )

        payload = {
            "end_date": "2026-07-01",
            "status": "inactive",
            "active": False,
            "attendance_resolution": "restore_previous",
        }
        request = self.factory.put(
            "/students/discipline-actions/record-1", payload, format="json"
        )
        request.data = payload
        request.user = SimpleNamespace(id="u1")

        with patch.object(
            discipline_module.StudentDisciplinaryActionDetailView,
            "get_object",
            return_value=record,
        ), patch.object(
            discipline_module,
            "StudentDisciplinaryActionSerializer",
            _FakeDisciplineUpdateSerializer,
        ), patch.object(
            discipline_module,
            "count_unresolved_attendance_impacts_after",
            return_value=2,
        ), patch.object(
            discipline_module,
            "resolve_attendance_impacts_after",
            return_value=2,
        ):
            response = view.put(request, "record-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("attendance_effect_updates", {}).get("resolved_impacts"), 2)
