from users.access_policies import BaseSchoolAccessPolicy


class GradebookAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for grading operations:
      - grading.enter  -> create/update/bulk_enter
      - grading.review -> review
      - grading.approve-> approve
      - grading.reject -> reject
    Applies to grading_assessment, grading_gradebook, grading_grade, etc.

        Note:
            Many grading endpoints are APIView-based and expose HTTP-method actions
            (post/put/patch/delete) instead of ViewSet actions
            (create/update/partial_update/destroy). Include both forms.
    """

    statements = [
        # Read access requires a registered grades.view grant at any valid scope.
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_grading_permission:grades.view",
        },

        # 4) RBAC permissions (all normal users, regardless of role)
        # GRADING_ENTER -> create/update/bulk
        {
            "action": ["create", "update", "partial_update", "post", "put", "patch", "bulk_enter"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_grading_permission:grades.enter",
        },

        # GRADING_REVIEW -> review action
        {
            "action": ["review", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_grading_permission:grades.review",
        },

        # GRADING_APPROVE -> approve
        {
            "action": ["approve", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_grading_permission:grades.approve",
        },

        # GRADING_REJECT -> reject
        {
            "action": ["reject", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_grading_permission:grades.reject",
        },

        {
            "action": ["put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_grading_permission:grades.unlock",
        },
    ]

    def has_grading_permission(self, request, view, action, permission_code):
        user = self._get_user(request)
        if not user:
            return False

        from authorization.runtime import initialize_request_authorization

        return initialize_request_authorization(
            request,
            user,
        ).permission_scope(permission_code) is not None
