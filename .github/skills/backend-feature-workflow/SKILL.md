---
name: backend-feature-workflow
description: "Implement or debug High School SaaS backend features with Django, DRF, JWT, django-tenants, serializers, permissions, transactions, migrations, and focused tests. Use for API endpoints, model changes, workflow logic, and tenant-aware fixes."
argument-hint: "Describe the backend endpoint, model, workflow, or failing test"
user-invocable: true
---
# Backend Feature Workflow

Use this workflow for a focused Django or DRF change.

## Procedure
1. Locate the owning app and trace the route to the view, queryset, serializer, permission policy, and model/service that decides the behavior.
2. Read the existing tenant middleware/header implementation and a neighboring test before deciding how tenant context should flow.
3. Form one falsifiable hypothesis and choose the cheapest targeted test or check that can disprove it.
4. Apply DRY: search for an existing helper, serializer, permission, query utility, service, or test factory before creating parallel logic.
5. Preserve the established API shape, serializer conventions, status codes, trailing slashes, and permission model.
6. Scope reads and writes to the active tenant. Use serializer validation, `select_related`/`prefetch_related`, and `transaction.atomic()` where the operation requires them.
7. Add or update a focused regression test for the behavior, including authorization or tenant isolation when relevant.
8. If models change, create the migration and run `python manage.py makemigrations --check --dry-run`. Do not hide migration drift.
9. Run the narrowest relevant test immediately after the first edit, then run `python manage.py check` or a focused broader suite.

## Completion checklist
- Tenant isolation is tested and enforced for both list and detail/mutation paths.
- Authentication and object-level permissions are explicit.
- Serializer errors and HTTP status codes match existing API conventions.
- Related writes are atomic and repeated requests do not duplicate side effects.
- Query shape avoids avoidable N+1 work.
- Migrations and API documentation are updated when required.
