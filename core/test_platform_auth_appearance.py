from types import SimpleNamespace
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from core.models import PlatformAuthAppearance
from core.platform_auth_views import PublicAuthAppearanceView, PlatformAuthAppearanceView


class PlatformAuthAppearanceTests(TestCase):
    def request(self, method, data=None, *, admin=False, role="platform", workspace="admin", schema="public"):
        request = getattr(APIRequestFactory(), method)("/", data or {}, format="json")
        request.META["HTTP_X_TENANT"] = workspace
        request.tenant = SimpleNamespace(schema_name=schema)
        user = SimpleNamespace(is_authenticated=True, is_active=True, is_platform_superuser=admin,
                               _active_role_selection=role, pk=1)
        force_authenticate(request, user=user)
        return PlatformAuthAppearanceView.as_view()(request)

    def test_defaults_are_public_and_read_does_not_create_record(self):
        response = PublicAuthAppearanceView.as_view()(APIRequestFactory().get("/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"default_layout": "classic", "workspace_layout": "", "parent_layout": "", "background_settings": {}})
        self.assertFalse(PlatformAuthAppearance.objects.exists())

    def test_school_user_and_non_platform_role_cannot_write(self):
        self.assertEqual(self.request("patch", {"default_layout": "ambient"}).status_code, 403)
        self.assertEqual(self.request("patch", {"default_layout": "ambient"}, admin=True, role="school-role").status_code, 403)
        self.assertFalse(PlatformAuthAppearance.objects.exists())

    def test_admin_saves_and_overrides_survive_partial_updates(self):
        self.assertEqual(self.request("patch", {"default_layout": "ambient", "parent_layout": "centered"}, admin=True).status_code, 200)
        self.assertEqual(self.request("patch", {"workspace_layout": "minimal"}, admin=True).status_code, 200)
        response = PublicAuthAppearanceView.as_view()(APIRequestFactory().get("/"))
        self.assertEqual(response.data, {"default_layout": "ambient", "workspace_layout": "minimal", "parent_layout": "centered", "background_settings": {}})
        self.assertEqual(self.request("patch", {"parent_layout": ""}, admin=True).data["parent_layout"], "")

    def test_invalid_layout_and_anonymous_write_rejected(self):
        self.assertEqual(self.request("patch", {"default_layout": "unknown"}, admin=True).status_code, 400)
        response = PlatformAuthAppearanceView.as_view()(APIRequestFactory().patch("/", {"default_layout": "ambient"}, format="json"))
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(PublicAuthAppearanceView.as_view()(APIRequestFactory().patch("/", {}, format="json")).status_code, 405)

    def test_platform_admin_cannot_manage_from_school_or_parent_workspace(self):
        for method in ("get", "patch"):
            for workspace, schema in (("demo", "demo"), ("parent", "public"), ("admin", "demo")):
                response = self.request(method, {"default_layout": "ambient"}, admin=True, workspace=workspace, schema=schema)
                self.assertEqual(response.status_code, 403)
        self.assertFalse(PlatformAuthAppearance.objects.exists())

    def test_animated_layouts_round_trip_on_all_surfaces(self):
        for layout in ("aurora", "orbit", "editorial", "studio", "dusk", "water", "boxes", "particles"):
            with self.subTest(layout=layout):
                data = {field: layout for field in ("default_layout", "workspace_layout", "parent_layout")}
                self.assertEqual(self.request("patch", data, admin=True).status_code, 200)
                response = PublicAuthAppearanceView.as_view()(APIRequestFactory().get("/"))
                self.assertEqual(response.data, {**data, "background_settings": {}})

    def test_layout_backgrounds_round_trip_and_reject_invalid_blur(self):
        settings = {
            "classic": {"background": "boxes", "blur": 4},
            "water": {"background": "particles", "blur": 12},
        }
        response = self.request("patch", {"background_settings": settings}, admin=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["background_settings"], settings)
        self.assertEqual(self.request("patch", {"default_layout": "water"}, admin=True).data["background_settings"], settings)
        for invalid in (
            {"water": {"background": "untrusted", "blur": 4}},
            {"water": {"background": "boxes", "blur": -1}},
            {"water": {"background": "boxes", "blur": 25}},
            {"water": {"background": "boxes", "blur": True}},
            {"water": {"background": "boxes", "blur": "8"}},
            {"unknown": {"background": "boxes", "blur": 4}},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.request("patch", {"background_settings": invalid}, admin=True).status_code, 400)
