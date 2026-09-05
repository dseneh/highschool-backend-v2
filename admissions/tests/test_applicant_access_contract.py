from django.test import SimpleTestCase

from admissions.security import hash_session_token
from admissions.serializers import ApplicantVerificationSerializer


class ApplicantAccessContractTests(SimpleTestCase):
    def test_session_tokens_are_stored_as_fixed_length_hashes(self):
        raw_token = "applicant-session-secret"

        digest = hash_session_token(raw_token)

        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, raw_token)
        self.assertEqual(digest, hash_session_token(raw_token))

    def test_verification_requires_exactly_one_reference(self):
        neither = ApplicantVerificationSerializer(data={"code": "123456"})
        both = ApplicantVerificationSerializer(
            data={
                "challenge_id": "b9d076e3-da1a-49a4-a437-4e1f6e8521db",
                "request_id": "EZY-ABCDEF-123456",
                "code": "123456",
            }
        )

        self.assertFalse(neither.is_valid())
        self.assertFalse(both.is_valid())

    def test_verification_code_must_have_six_digits(self):
        serializer = ApplicantVerificationSerializer(
            data={
                "challenge_id": "b9d076e3-da1a-49a4-a437-4e1f6e8521db",
                "code": "12345a",
            }
        )

        self.assertFalse(serializer.is_valid())
