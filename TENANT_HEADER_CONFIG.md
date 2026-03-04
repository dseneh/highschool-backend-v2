# Tenant Header Configuration

## Overview

The backend uses the `X-Tenant` or `X-Workspace` header to identify which tenant schema to use for database queries. This allows for multi-tenant functionality where different organizations (schools) have isolated data.

## Header Usage

### Standard Tenant Access

To access a specific tenant's data, send the tenant's schema name in the header:

```http
GET /api/v1/students/
X-Tenant: school1
```

This will query the `school1` PostgreSQL schema for student data.

### Admin/Public Schema Access

The public schema (where global users are stored) can be accessed using the **"admin"** alias:

```http
GET /api/v1/users/
X-Tenant: admin
```

This translates to the `public` PostgreSQL schema but uses "admin" for better semantic clarity.

## Schema Translation

The middleware automatically handles the following:

1. **"admin"** → translates to `public` schema (PostgreSQL standard)
2. **Any other value** → looks up the exact schema name in the database
3. **No header** → falls back to `public` schema for auth/tenant management endpoints

## Why Keep PostgreSQL "public" Schema?

- **PostgreSQL Convention**: The `public` schema is the default in PostgreSQL
- **Less Risky**: No database migration or recreation needed
- **Backward Compatible**: Works with existing PostgreSQL tools and conventions
- **Flexible**: Can accept both "admin" and "public" as values (though "admin" is preferred)

## Search Endpoint Exception

The search endpoint (`/api/v1/search/`) is public and does **not** require any tenant header. It automatically searches across all tenants.

## Examples

### Accessing Global Users (Admin Schema)

```bash
# Using "admin" (recommended)
curl -H "X-Tenant: admin" http://localhost:8000/api/v1/users/

# Using "public" (also works)
curl -H "X-Tenant: public" http://localhost:8000/api/v1/users/
```

### Accessing Tenant-Specific Data

```bash
# Access school1's students
curl -H "X-Tenant: school1" http://localhost:8000/api/v1/students/

# Access school2's staff
curl -H "X-Tenant: school2" http://localhost:8000/api/v1/staff/
```

### No Header Required

```bash
# Authentication endpoints work without tenant header
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -d '{"username": "admin", "password": "pass"}'

# Search endpoint works without tenant header
curl http://localhost:8000/api/v1/search/?email=test@example.com
```

## Implementation Details

The translation happens in `api/middleware.py` in the `HeaderBasedTenantMiddleware.get_tenant()` method:

```python
# Special case: "admin" is an alias for the public schema
if tenant_header.lower() == 'admin':
    try:
        public_schema = get_public_schema_name()
        return Tenant.objects.get(schema_name=public_schema)
    except Tenant.DoesNotExist:
        raise NotFound(detail="Public schema (admin) not found.")
```

## API Response Consistency

All search results return tenant information in a consistent format:

- **Users**: `"schema_name": "admin"` (displayed as admin, stored as public)
- **Students/Staff**: `"schema_name": "school1"` (actual tenant schema name)

This provides semantic clarity while maintaining PostgreSQL conventions under the hood.
