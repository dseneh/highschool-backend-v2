# Mobile AI Agent Tool-Calling Guide

This file is designed for autonomous mobile/API agents.

## Files

- `mobile-ai-agent-endpoints.json`: Human+machine endpoint catalog (one entry per endpoint path).
- `mobile-ai-agent-tools.json`: Tool-calling catalog (one entry per METHOD+PATH operation).

## Runtime Rules For Agents

1. Inject `Authorization: Bearer {{ACCESS_TOKEN}}` for authenticated operations.
2. Inject `x-tenant: {{TENANT_SLUG}}` for tenant-scoped operations.
3. On `401`, call refresh endpoint once, retry once, then fail clearly.
4. Treat GET list responses as potentially paginated (`count/next/previous/results`).
5. Log and surface `detail` + `error_code` from error responses.

## Critical Auth Endpoints

- `POST /api/v1/auth/login/`
	- Input: `username/email/staff_id`, `password`
	- Output: `access`, `refresh`
- `POST /api/v1/auth/token/refresh/`
	- Input: `refresh`
	- Output: new `access` (and possibly rotated `refresh`)
- `POST /api/v1/auth/verify/`
	- Validates token state
- `GET /api/v1/auth/user/current/`
	- Returns authenticated user profile
- `GET|POST /api/v1/auth/users/`
- `GET|PUT|PATCH|DELETE /api/v1/auth/users/{id_number}/`
- `POST /api/v1/auth/users/{id_number}/password/change/`
- `POST /api/v1/auth/password/forgot/`
- `POST /api/v1/auth/password/reset/`

## Recommended Mobile Auth Flow

1. Login via `/api/v1/auth/login/` and store `access` + `refresh` securely.
2. Send `Authorization: Bearer <access>` on authenticated requests.
3. On `401`, call `/api/v1/auth/token/refresh/` once and retry once.
4. Keep `x-tenant` header on tenant-scoped endpoints.

## Suggested Intent Mapping

- `read`: GET operations
- `create`: POST operations
- `update`: PUT/PATCH operations
- `delete`: DELETE operations

## Stats

- Modules: 9
- Endpoint paths: 115
- Operations (method+path): 263