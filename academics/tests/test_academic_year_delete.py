from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.db.models.deletion import ProtectedError

from academics.views.academic_year import (
    AcademicYearDetailView,
    _force_delete_instance,
)


class _StubModelMeta:
    app_label = "academics"
    model_name = "stub"


class _StubObject:
    _meta = _StubModelMeta()

    def __init__(self, pk="1", protected_objects=None, current=False):
        self.pk = pk
        self.current = current
        self._protected_objects = protected_objects or []
        self.delete_calls = 0

    def delete(self):
        self.delete_calls += 1
        if self._protected_objects:
            protected = self._protected_objects
            self._protected_objects = []
            raise ProtectedError("blocked", protected)


class ForceDeleteInstanceTests(SimpleTestCase):
    def test_force_delete_instance_deletes_plain_object(self):
        obj = _StubObject(pk="root")
        _force_delete_instance(obj, visited=set())
        self.assertEqual(obj.delete_calls, 1)

    def test_force_delete_instance_deletes_blocking_children_first(self):
        child = _StubObject(pk="child")
        root = _StubObject(pk="root", protected_objects=[child])

        _force_delete_instance(root, visited=set())

        self.assertEqual(child.delete_calls, 1)
        self.assertEqual(root.delete_calls, 2)

    def test_force_delete_instance_handles_nested_protected_chain(self):
        grandchild = _StubObject(pk="grandchild")
        child = _StubObject(pk="child", protected_objects=[grandchild])
        root = _StubObject(pk="root", protected_objects=[child])

        _force_delete_instance(root, visited=set())

        self.assertEqual(grandchild.delete_calls, 1)
        self.assertEqual(child.delete_calls, 2)
        self.assertEqual(root.delete_calls, 2)


class AcademicYearDeleteViewTests(SimpleTestCase):
    databases = {"default"}

    def _make_request(self, force=False):
        return SimpleNamespace(
            query_params={"force": "true"} if force else {},
            headers={},
            META={},
        )

    def test_delete_is_allowed_for_the_current_academic_year(self):
        view = AcademicYearDetailView()
        year = _StubObject(pk="year", current=True)
        view.get_object = MagicMock(return_value=year)

        response = view.delete(self._make_request(), id="year")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(year.delete_calls, 1)

    def test_delete_is_allowed_for_a_past_academic_year(self):
        view = AcademicYearDetailView()
        year = _StubObject(pk="year", current=False)
        view.get_object = MagicMock(return_value=year)

        response = view.delete(self._make_request(), id="year")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(year.delete_calls, 1)

    def test_delete_without_force_returns_400_when_protected(self):
        view = AcademicYearDetailView()
        blocked_child = _StubObject(pk="child")
        year = _StubObject(pk="year", protected_objects=[blocked_child])
        view.get_object = MagicMock(return_value=year)

        response = view.delete(self._make_request(force=False), id="year")

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.data.get("can_force_delete"))

    @patch("academics.views.academic_year._force_delete_instance")
    def test_delete_with_force_uses_recursive_force_delete(self, mock_force_delete):
        view = AcademicYearDetailView()
        year = _StubObject(pk="year", current=False)
        view.get_object = MagicMock(return_value=year)

        response = view.delete(self._make_request(force=True), id="year")

        self.assertEqual(response.status_code, 204)
        mock_force_delete.assert_called_once()

    @patch("academics.views.academic_year._force_delete_instance")
    def test_force_delete_is_allowed_for_the_current_academic_year(self, mock_force_delete):
        view = AcademicYearDetailView()
        year = _StubObject(pk="year", current=True)
        view.get_object = MagicMock(return_value=year)

        response = view.delete(self._make_request(force=True), id="year")

        self.assertEqual(response.status_code, 204)
        mock_force_delete.assert_called_once()
