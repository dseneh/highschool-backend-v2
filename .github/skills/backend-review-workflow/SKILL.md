---
name: backend-review-workflow
description: "Review High School SaaS Django and DRF changes for tenant isolation, authorization, serializer/API regressions, transaction safety, duplicate side effects, query performance, migration drift, and missing tests. Use for backend code reviews."
argument-hint: "Provide the backend files, diff, endpoint, or behavior to review"
user-invocable: true
---
# Backend Review Workflow

Review as a correctness and security review. Findings come before summary.

## Procedure
1. Inspect the diff and the nearest owning route, view, queryset, serializer, permission policy, model, and tests.
2. Check DRY: identify duplicated validation, permissions, query logic, service behavior, or test setup that should use an established shared abstraction.
3. Verify every tenant-owned list, retrieve, create, update, delete, export, and background operation uses the established tenant context.
4. Verify authentication, object-level authorization, role boundaries, and serializer field exposure.
5. Check transaction boundaries, status transitions, retries, signals, notifications, audit records, and duplicate side effects.
6. Check query counts and related-object loading for list and detail endpoints.
7. Check migrations, backward compatibility, validation errors, status codes, and frontend contract impact.
8. Run a focused test or Django check. For schema changes, run the migration drift check.

## Output
List findings first by severity with clickable file references and concise evidence. Then list open questions, commands/tests run, and a short summary. If there are no findings, say so clearly and identify residual test or deployment risk.
