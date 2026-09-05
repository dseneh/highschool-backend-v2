import io
import struct
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from admissions.scanning import ClamAVScanner, DocumentScanError


class FakeClamAVConnection:
    def __init__(self, response):
        self.response = response
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, _size):
        response, self.response = self.response, b""
        return response


class DocumentScanningTests(SimpleTestCase):
    def scan_with_response(self, response, content=b"school document"):
        connection = FakeClamAVConnection(response)
        scanner = ClamAVScanner(host="scanner", port=3310, timeout=10)
        with patch("admissions.scanning.socket.create_connection", return_value=connection):
            verdict = scanner.scan(io.BytesIO(content))
        return verdict, connection

    def test_clean_clamav_verdict(self):
        verdict, connection = self.scan_with_response(b"stream: OK\0")

        self.assertTrue(verdict.clean)
        self.assertEqual(connection.sent[:10], b"zINSTREAM\0")
        self.assertIn(struct.pack("!I", len(b"school document")), connection.sent)
        self.assertEqual(connection.sent[-4:], b"\0\0\0\0")

    def test_detected_file_returns_threat_name(self):
        verdict, _connection = self.scan_with_response(
            b"stream: Eicar-Test-Signature FOUND\0"
        )

        self.assertFalse(verdict.clean)
        self.assertEqual(verdict.threat_name, "Eicar-Test-Signature")

    def test_invalid_scanner_response_fails_closed(self):
        with self.assertRaises(DocumentScanError):
            self.scan_with_response(b"unexpected response\0")

    @override_settings(ADMISSIONS_DOCUMENT_SCAN_HOST="")
    def test_scanner_requires_configured_host(self):
        with self.assertRaises(DocumentScanError):
            ClamAVScanner(host="", port=3310, timeout=10)

    @override_settings(ADMISSIONS_DOCUMENT_SCAN_HOST="")
    def test_worker_refuses_to_run_without_scanner(self):
        with self.assertRaisesMessage(
            CommandError, "ADMISSIONS_DOCUMENT_SCAN_HOST must be configured."
        ):
            call_command("scan_admission_documents")
