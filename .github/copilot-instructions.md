# High School SaaS Backend AI Instructions

## Project context
- Django 5.2+, Django REST Framework, PostgreSQL, JWT authentication, and `django-tenants`.
- This is a multi-tenant school management API. Tenant context must be explicit and must never be inferred from untrusted request data without the existing middleware and validation path.
- Major domains include students, academics, grading, accounting, finance, HR, payroll, staff, billing, notifications, and audit logging.
- The frontend is the sibling `ezyschool-ui` repository and expects versioned REST endpoints, JSON responses, JWT behavior, and the `X-Tenant` header contract.

## Engineering rules
- Apply DRY consistently: search for an existing model helper, serializer, permission, query utility, service, or test factory before adding a parallel implementation. Improve a shared abstraction centrally when the behavior is broadly reusable.
- Inspect the owning model, serializer, view/viewset, URL route, permission policy, tenant middleware, and neighboring tests before editing.
- Preserve existing public API shapes and trailing-slash conventions unless the task explicitly changes the contract.
- Scope every tenant-owned query and mutation through the established tenant context. Check object-level permissions as well as authentication.
- Prefer serializers for validation and representation, service/query helpers for reusable domain logic, and transactions for multi-model mutations.
- Avoid N+1 queries; use `select_related` and `prefetch_related` when the response shape requires related objects.
- Treat money and grades with appropriate decimal precision. Do not silently convert financial values to binary floats.
- Add migrations for model changes and keep migration files deterministic. Never edit an applied migration casually.
- Add focused regression tests for permission boundaries, tenant isolation, validation, status transitions, and side effects.
- Do not expose secrets, tokens, tenant data, or full production payloads in logs or test output.

## Validation
- Prefer targeted Django tests first, then `python manage.py check`, migration checks, and the relevant broader suite.
- When migrations are involved, run `python manage.py makemigrations --check --dry-run` and verify the intended migration is present.
- Report environment-dependent failures separately from regressions introduced by the change.
