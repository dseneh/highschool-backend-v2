from types import SimpleNamespace

from django.test import SimpleTestCase

from users.serializers import UserSerializer


class UserAuditSerializationTests(SimpleTestCase):
    def test_user_serializer_exposes_detail_and_audit_fields(self):
        fields = set(UserSerializer.Meta.fields)

        self.assertTrue(
            {
                "status",
                "created_at",
                "profile_updated_at",
                "profile_updated_by",
                "last_password_updated",
                "last_login",
            }.issubset(fields)
        )

    def test_profile_update_actor_uses_compact_public_identity(self):
        actor = SimpleNamespace(
            pk="actor-1",
            id_number="ADMIN-1",
            first_name="Ada",
            last_name="Admin",
            username="ada.admin",
            email="ada@example.com",
        )
        target = SimpleNamespace(profile_updated_by=actor)

        payload = UserSerializer().get_profile_updated_by(target)

        self.assertEqual(
            payload,
            {
                "id": "actor-1",
                "id_number": "ADMIN-1",
                "full_name": "Ada Admin",
                "email": "ada@example.com",
            },
        )

    def test_missing_profile_update_actor_serializes_as_null(self):
        target = SimpleNamespace(profile_updated_by=None)

        self.assertIsNone(UserSerializer().get_profile_updated_by(target))
