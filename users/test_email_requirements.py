from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework import status

from common.status import UserAccountType
from users.viewsets import UserViewSet


class UserViewSetEmailRequirementTests(SimpleTestCase):
    def _request_payload(self):
        return {
            "account_type": UserAccountType.STUDENT,
            "id_number": "S0001",
            "date_of_birth": "2012-05-14",
        }

    def _lookup_serializer(self):
        serializer = MagicMock()
        serializer.is_valid.return_value = True
        serializer.validated_data = {
            "account_type": UserAccountType.STUDENT,
            "id_number": "S0001",
            "date_of_birth": "2012-05-14",
            "notify_user": False,
        }
        return serializer

    def _student_filter_result(self, source_record):
        queryset = MagicMock()
        queryset.first.return_value = source_record
        return queryset

    def _build_request(self):
        return SimpleNamespace(data=self._request_payload())

    def test_create_returns_400_when_source_email_missing(self):
        request = self._build_request()
        viewset = UserViewSet()
        viewset.request = request

        source = SimpleNamespace(
            first_name="Jane",
            last_name="Student",
            gender="female",
            email="",
        )

        with patch("users.viewsets.connection", SimpleNamespace(schema_name="tenant1")):
            with patch("users.viewsets.schema_context", side_effect=lambda _schema: nullcontext()):
                with patch("users.viewsets.UserRecreateSerializer", return_value=self._lookup_serializer()):
                    with patch("students.models.Student.objects.filter", return_value=self._student_filter_result(source)):
                        response = viewset.create(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        self.assertNotIn("errors", response.data)
        self.assertIn("valid email address", response.data["detail"])

    def test_create_returns_400_when_source_email_invalid(self):
        request = self._build_request()
        viewset = UserViewSet()
        viewset.request = request

        source = SimpleNamespace(
            first_name="Jane",
            last_name="Student",
            gender="female",
            email="invalid",
        )

        with patch("users.viewsets.connection", SimpleNamespace(schema_name="tenant1")):
            with patch("users.viewsets.schema_context", side_effect=lambda _schema: nullcontext()):
                with patch("users.viewsets.UserRecreateSerializer", return_value=self._lookup_serializer()):
                    with patch("students.models.Student.objects.filter", return_value=self._student_filter_result(source)):
                        response = viewset.create(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        self.assertNotIn("errors", response.data)
        self.assertIn("valid email address", response.data["detail"])

    def test_create_allows_valid_email_flow_for_existing_user(self):
        request = self._build_request()
        viewset = UserViewSet()
        viewset.request = request

        source = SimpleNamespace(
            first_name="Jane",
            last_name="Student",
            gender="female",
            email="jane.student@example.org",
        )
        existing_user = SimpleNamespace(
            id=101,
            username="janestudent",
            email="jane.student@example.org",
            id_number="S0001",
        )

        user_filter_qs = MagicMock()
        user_filter_qs.first.return_value = existing_user
        tenant = MagicMock()
        serializer = SimpleNamespace(data={"id_number": "S0001"})

        with patch("users.viewsets.connection", SimpleNamespace(schema_name="tenant1")):
            with patch("users.viewsets.schema_context", side_effect=lambda _schema: nullcontext()):
                with patch("users.viewsets.UserRecreateSerializer", return_value=self._lookup_serializer()):
                    with patch("students.models.Student.objects.filter", return_value=self._student_filter_result(source)):
                        with patch("users.viewsets.User.objects.filter", return_value=user_filter_qs):
                            with patch("core.models.Tenant.objects.get", return_value=tenant):
                                with patch("users.viewsets.UserSerializer", return_value=serializer):
                                    response = viewset.create(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "User account already exists")
        tenant.add_user.assert_called_once()
