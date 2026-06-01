"""Tests for JSON serialization helpers."""

import json
import uuid
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.json_utils import make_json_safe


class MakeJsonSafeTests(SimpleTestCase):
    def test_converts_uuid_decimal_and_date(self):
        sample_id = uuid.uuid4()
        payload = {
            "id": sample_id,
            "amount": Decimal("12.50"),
            "payment_date": date(2026, 5, 31),
            "rows": [{"request": sample_id, "employee_benefit": None}],
        }

        safe = make_json_safe(payload)

        json.dumps(safe)
        self.assertEqual(safe["id"], str(sample_id))
        self.assertEqual(safe["amount"], "12.50")
        self.assertEqual(safe["payment_date"], "2026-05-31")
        self.assertEqual(safe["rows"][0]["request"], str(sample_id))
