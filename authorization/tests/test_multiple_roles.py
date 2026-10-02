import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.core.cache import cache
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from authorization.models import Role, TenantMembership, TenantRoleAssignment
from authorization.multiple_roles import add_role, revoke_role, selected_assignment, user_assignments_payload
from authorization.runtime import initialize_request_authorization, resolve_authorization_context
from authorization.views import MyRolesView, UserRoleView, UserRoleRevokeView
from users.models import User


class MultipleRolesTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "multiple_roles_test"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Multiple roles school"
        tenant.id_number = "MULTI001"
        tenant.owner, _ = User.objects.get_or_create(email="multi-owner@example.com", defaults={
            "id_number": "MULTI-OWNER", "username": "multi-owner",
        })

    def setUp(self):
        cache.clear()
        self.user = User.objects.create(email="multi-user@example.com", id_number="MULTI-USER", account_type="staff")
        self.teacher = Role.objects.get(system_key="teacher")
        self.parent = Role.objects.get(system_key="parent")
        self.membership = add_role(user=self.user, role=self.teacher)
        add_role(user=self.user, role=self.parent)
        self.parent_assignment = self.membership.role_assignments.get(role_key="system:parent")

    def test_additive_idempotent_assignment(self):
        add_role(user=self.user, role=self.parent)
        self.assertEqual(self.membership.role_assignments.count(), 2)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.role_id, self.teacher.pk)

    def test_database_rejects_duplicate_role(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TenantRoleAssignment.objects.create(membership=self.membership, role=self.parent, role_key="system:parent")

    def test_selected_parent_does_not_union_teacher_permissions(self):
        self.user._active_role_selection = str(self.parent_assignment.pk)
        context = resolve_authorization_context(self.user)
        self.assertEqual(context.permission_scope("grades.view"), "own")
        self.assertIsNone(context.permission_scope("grades.enter"))

    def test_platform_user_is_restricted_in_parent_context(self):
        self.user.is_platform_superuser = True
        self.user._active_role_selection = str(self.parent_assignment.pk)
        context = resolve_authorization_context(self.user)
        self.assertFalse(context.unrestricted)
        self.assertIsNone(context.permission_scope("roles.assign_users"))

    def test_foreign_and_invalid_assignments_fail_closed(self):
        for selection in (str(uuid.uuid4()), "invalid", "platform"):
            self.user._active_role_selection = selection
            self.assertFalse(resolve_authorization_context(self.user).active)

    def test_revoked_selection_never_falls_back_to_teacher(self):
        revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)
        self.user._active_role_selection = str(self.parent_assignment.pk)
        self.assertFalse(resolve_authorization_context(self.user).active)
        self.assertIsNone(selected_assignment(self.user))

    @patch("authorization.multiple_roles.parent_removal_reason", return_value="Active guardian links")
    def test_parent_protection_enforced_by_backend(self, reason):
        with self.assertRaisesMessage(ValidationError, "Active guardian links"):
            revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)
        self.parent_assignment.refresh_from_db()
        self.assertTrue(self.parent_assignment.is_active)

    def test_legacy_parent_base_role_is_protected(self):
        self.user.account_type = "parent"
        self.user.save(update_fields=["account_type"])
        with self.assertRaisesMessage(ValidationError, "base role is protected"):
            revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)

    def test_last_admin_cannot_be_revoked(self):
        add_role(user=self.tenant.owner, role=self.teacher)
        assignment = TenantRoleAssignment.objects.get(membership__user=self.tenant.owner, role_key="system:admin")
        with self.assertRaisesMessage(ValidationError, "at least one administrator"):
            revoke_role(user=self.tenant.owner, assignment_id=assignment.pk, actor=self.user)

    def test_cannot_modify_own_assignments(self):
        with self.assertRaisesMessage(ValidationError, "own role assignments"):
            add_role(user=self.user, role=self.parent, actor=self.user)
        with self.assertRaisesMessage(ValidationError, "own role assignments"):
            revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.user)

    def test_self_service_roles_does_not_require_role_management_permission(self):
        factory = APIRequestFactory()
        request = factory.get("/authorization/me/roles/", HTTP_X_ROLE_ASSIGNMENT=str(self.parent_assignment.pk))
        request.tenant = self.tenant
        force_authenticate(request, user=self.user)
        response = MyRolesView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["assignments"]), 2)

    def test_switch_only_accepts_assigned_role(self):
        factory = APIRequestFactory()
        request = factory.post("/authorization/me/roles/", {"assignment_id": str(uuid.uuid4())}, format="json")
        request.tenant = self.tenant
        force_authenticate(request, user=self.user)
        self.assertEqual(MyRolesView.as_view()(request).status_code, 403)

    def test_default_revocation_keeps_other_role(self):
        teacher_assignment = self.membership.role_assignments.get(role_key="system:teacher")
        revoke_role(user=self.user, assignment_id=teacher_assignment.pk, actor=self.tenant.owner)
        self.assertEqual(selected_assignment(self.user).pk, self.parent_assignment.pk)

    def test_last_role_is_protected_in_payload_and_revoke_endpoint(self):
        revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)
        teacher_assignment = self.membership.role_assignments.get(role_key="system:teacher")
        payload = user_assignments_payload(self.user)["assignments"][0]
        self.assertFalse(payload["can_revoke"])
        self.assertIn("at least one active role", payload["revocation_blocked_reason"])
        response = self._tenant_role_request(self.tenant.owner, assignment=teacher_assignment.pk)
        self.assertEqual(response.status_code, 400)
        teacher_assignment.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertTrue(teacher_assignment.is_active)
        self.assertTrue(self.membership.is_active)

    def test_disabled_role_does_not_allow_removing_last_usable_role(self):
        revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)
        custom = Role.objects.create(name="Disabled alternative")
        add_role(user=self.user, role=custom)
        from authorization.services import update_role
        update_role(role=custom, changes={"is_active": False})
        teacher_assignment = self.membership.role_assignments.get(role_key="system:teacher")
        with self.assertRaisesMessage(ValidationError, "at least one active role"):
            revoke_role(user=self.user, assignment_id=teacher_assignment.pk, actor=self.tenant.owner)

    def test_shared_role_counts_as_an_alternative(self):
        from django_tenants.utils import get_public_schema_name, schema_context
        from core.models import SharedRole
        revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)
        with schema_context(get_public_schema_name()):
            shared = SharedRole.objects.create(name="Shared alternative", role_type="CUSTOM", scope="TENANT", is_active=True)
        add_role(user=self.user, role=shared)
        teacher_assignment = self.membership.role_assignments.get(role_key="system:teacher")
        revoke_role(user=self.user, assignment_id=teacher_assignment.pk, actor=self.tenant.owner)
        remaining = selected_assignment(self.user)
        self.assertEqual(remaining.shared_role_id, shared.pk)
        with self.assertRaisesMessage(ValidationError, "at least one active role"):
            revoke_role(user=self.user, assignment_id=remaining.pk, actor=self.tenant.owner)

    def test_public_role_cannot_be_assigned_in_school(self):
        role = SimpleNamespace(is_active=True, system_key=None, scope="PUBLIC", _meta=SimpleNamespace(label_lower="core.sharedrole"))
        with self.assertRaisesMessage(ValidationError, "not available in school"):
            add_role(user=self.user, role=role)

    def test_default_disabled_role_uses_other_assignment_only_without_selection(self):
        from authorization.services import replace_role_permissions, update_role
        custom = Role.objects.create(name="Temporary role")
        replace_role_permissions(custom, {"students.view": "all"})
        add_role(user=self.user, role=custom)
        self.membership.role = custom
        self.membership.save()
        assignment = self.membership.role_assignments.get(role=custom)
        update_role(role=custom, changes={"is_active": False})
        self.assertTrue(resolve_authorization_context(self.user).active)
        self.user._active_role_selection = str(assignment.pk)
        self.assertFalse(resolve_authorization_context(self.user).active)

    def test_valid_assignment_of_another_user_is_rejected(self):
        foreign = TenantRoleAssignment.objects.filter(membership__user=self.tenant.owner).first()
        self.user._active_role_selection = str(foreign.pk)
        self.assertFalse(resolve_authorization_context(self.user).active)

    def test_active_guardian_link_protects_parent_role_for_employee(self):
        from students.models import Student, StudentGuardian
        student = Student.objects.create(first_name="Mary", last_name="Doe", id_number="99001",
            entry_as="new", school_code=1, student_seq=99001)
        from users.models import ParentProfile
        from django.utils import timezone
        profile = ParentProfile.objects.create(user=self.user)
        StudentGuardian.objects.create(student=student, first_name="Jane", last_name="Doe",
            user_account_id_number=self.user.id_number, active=True, parent_profile_id=profile.pk,
            portal_state="active", portal_verified_at=timezone.now(), portal_approved_at=timezone.now())
        with self.assertRaisesMessage(ValidationError, "active guardian links"):
            revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)

    def test_shared_and_local_system_role_are_one_assignment(self):
        from django_tenants.utils import get_public_schema_name, schema_context
        from core.models import SharedRole
        with schema_context(get_public_schema_name()):
            shared, _ = SharedRole.objects.update_or_create(system_key="parent", defaults={
                "name": "Parent", "role_type": "SYSTEM", "scope": "TENANT", "permissions": [], "is_active": True})
        add_role(user=self.user, role=shared)
        self.assertEqual(self.membership.role_assignments.filter(role_key="system:parent").count(), 1)

    def test_tenant_detail_lists_all_roles_for_target_user(self):
        from users.viewsets import UserViewSet
        roles = UserViewSet._tenant_roles_for_user(self.user, self.tenant.schema_name)
        self.assertEqual([role["system_key"] for role in roles], ["parent", "teacher"])
        self.assertTrue(all(role["is_active"] for role in roles))
        owner_roles = UserViewSet._tenant_roles_for_user(self.tenant.owner, self.tenant.schema_name)
        self.assertEqual([role["system_key"] for role in owner_roles], ["admin"])

    def test_tenant_detail_excludes_revoked_role_assignments(self):
        from users.viewsets import UserViewSet
        revoke_role(user=self.user, assignment_id=self.parent_assignment.pk, actor=self.tenant.owner)
        roles = UserViewSet._tenant_roles_for_user(self.user, self.tenant.schema_name)
        self.assertEqual([role["system_key"] for role in roles], ["teacher"])

    def _tenant_role_request(self, actor, *, action='revoke_tenant_role', schema=None, assignment=None, role=None):
        from users.viewsets import UserViewSet
        if not self.user.tenants.filter(pk=self.tenant.pk).exists():
            self.tenant.add_user(self.user)
        factory = APIRequestFactory()
        method = 'delete' if action == 'revoke_tenant_role' else 'put'
        request = getattr(factory, method)('/', {'role_id': str((role or self.parent).pk)}, format='json')
        request.tenant = self.tenant
        force_authenticate(request, user=actor)
        kwargs = {'id_number': self.user.id_number, 'schema_name': schema or self.tenant.schema_name}
        if method == 'delete':
            kwargs['assignment_id'] = str(assignment or self.parent_assignment.pk)
        return UserViewSet.as_view({method: action})(request, **kwargs)

    def test_tenant_role_endpoints_require_assignment_permission(self):
        actor = User.objects.create(email='role-reader@example.com', id_number='ROLE-READER')
        role = Role.objects.create(name='User editor')
        from authorization.services import replace_role_permissions
        replace_role_permissions(role, {'users.view': 'all', 'users.update': 'all'})
        add_role(user=actor, role=role)
        for action in ['tenant_role', 'revoke_tenant_role']:
            self.assertEqual(self._tenant_role_request(actor, action=action).status_code, 403)
        self.parent_assignment.refresh_from_db()
        self.assertTrue(self.parent_assignment.is_active)

    def test_authorized_school_user_can_assign_and_revoke(self):
        actor = User.objects.create(email='role-manager@example.com', id_number='ROLE-MANAGER')
        role = Role.objects.create(name='Role manager')
        from authorization.services import replace_role_permissions
        replace_role_permissions(role, {'roles.view': 'all', 'roles.assign_users': 'all'})
        add_role(user=actor, role=role)
        self.assertEqual(self._tenant_role_request(actor).status_code, 204)
        self.parent_assignment.refresh_from_db()
        self.assertFalse(self.parent_assignment.is_active)
        self.assertEqual(self._tenant_role_request(actor, action='tenant_role').status_code, 200)
        self.parent_assignment.refresh_from_db()
        self.assertTrue(self.parent_assignment.is_active)

    def test_school_admin_cannot_manage_another_school_roles(self):
        for action in ['tenant_role', 'revoke_tenant_role']:
            self.assertEqual(self._tenant_role_request(self.tenant.owner, action=action, schema='other_school').status_code, 403)

    def test_tenant_role_removal_preserves_protected_parent(self):
        self.user.account_type = 'parent'
        self.user.save(update_fields=['account_type'])
        self.assertEqual(self._tenant_role_request(self.tenant.owner).status_code, 400)
        from users.viewsets import UserViewSet
        parent = next(role for role in UserViewSet._tenant_roles_for_user(self.user, self.tenant.schema_name) if role['system_key'] == 'parent')
        self.assertFalse(parent['can_revoke'])
        self.assertEqual(parent['assignment_id'], str(self.parent_assignment.pk))
