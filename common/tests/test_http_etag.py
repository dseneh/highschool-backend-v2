from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework import status

from common.http_etag import attach_etag, build_etag, maybe_not_modified


class HttpEtagTests(SimpleTestCase):
    def test_build_etag_is_stable_for_same_parts(self):
        ts = timezone.now()
        first = build_etag("student-1", ts, "active")
        second = build_etag("student-1", ts, "active")
        self.assertEqual(first, second)

    def test_maybe_not_modified_returns_304_when_etag_matches(self):
        request = Mock(headers={"If-None-Match": '"abc123"'})
        response = maybe_not_modified(request, "abc123")
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_304_NOT_MODIFIED)
        self.assertEqual(response["ETag"], '"abc123"')

    def test_maybe_not_modified_returns_none_when_etag_differs(self):
        request = Mock(headers={"If-None-Match": '"old"'})
        self.assertIsNone(maybe_not_modified(request, "new"))

    def test_attach_etag_sets_headers(self):
        from rest_framework.response import Response

        response = attach_etag(Response({"ok": True}), "etag-value")
        self.assertEqual(response["ETag"], '"etag-value"')
        self.assertEqual(response["Cache-Control"], "private, max-age=0, must-revalidate")
