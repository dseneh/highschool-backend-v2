# Core App - Tenant Management

## Overview

The `core` app manages multi-tenant functionality using `django-tenants`. It handles tenant (school) creation, management, and domain configuration. All data is isolated per tenant using PostgreSQL schemas.

## Base URL

All endpoints are prefixed with: `/api/v1/`

## Authentication

**Public Endpoints (No Authentication Required):**
- `GET /api/v1/tenants/` - List all active tenants (for tenant discovery/routing)
- `GET /api/v1/tenants/{schema_name}/` - Get tenant details (for branding/routing)

**Protected Endpoints (Authentication Required):**
- `POST /api/v1/tenants/` - Create tenant (admin only)
- `PUT /api/v1/tenants/{schema_name}/` - Update tenant (admin only)
- `PATCH /api/v1/tenants/{schema_name}/` - Partial update tenant (admin only)
- `DELETE /api/v1/tenants/{schema_name}/` - Delete tenant (admin only)

For protected endpoints, include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

## Headers

For tenant-specific requests, include the tenant identifier:

```
X-Tenant: <schema_name>
```

For tenant management endpoints (create/list tenants), these must be called from the public schema context (no X-Tenant header or use `public`).

## Endpoints

All endpoints are provided by the `TenantViewSet` (ModelViewSet) which provides standard REST CRUD operations.

### 1. Create Tenant

Create a new tenant (school) in the system.

**Endpoint:** `POST /api/v1/tenants/`

**Permissions:** Requires admin/superuser authentication

**Request Body:**

```json
{
  "name": "My School",
  "short_name": "MS",
  "schema_name": "my_school", // Optional, auto-generated from name if not provided
  "domain": "my-school.localhost", // Optional, auto-generated if not provided
  "owner_email": "admin@school.com", // Optional, uses request user if not provided
  "is_active": true
}
```

**Response (201 Created):**

```json
{
  "id": "uuid-here",
  "name": "My School",
  "short_name": "MS",
  "schema_name": "my_school",
  "logo": null,
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "domain": "my-school.localhost",
  "domain_id": 1
}
```

**Error Responses:**

- `400 Bad Request`: Validation errors or tenant already exists
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: User is not an admin/superuser

**Example cURL:**

```bash
curl -X POST http://localhost:8000/api/v1/tenants/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My School",
    "short_name": "MS"
  }'
```

---

### 2. List All Tenants

Get a list of all tenants in the system.

**Endpoint:** `GET /api/v1/tenants/`

**Permissions:** Requires admin/superuser authentication

**Response (200 OK):**

```json
[
  {
    "id": "uuid-here",
    "name": "My School",
    "short_name": "MS",
    "schema_name": "my_school",
    "logo": "http://localhost:8000/media/logo.png",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

**Error Responses:**

- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: User is not an admin/superuser

**Example cURL:**

```bash
curl -X GET http://localhost:8000/api/v1/tenants/ \
  -H "Authorization: Bearer <token>"
```

---

### 3. Get Tenant Details

Get details of a specific tenant by schema name. This endpoint is **public** (no authentication required) and is designed for tenant branding and routing before login.

**Endpoint:** `GET /api/v1/tenants/<schema_name>/`

**Permissions:** Public (no authentication required)

**Note:** For unauthenticated users, returns limited fields (branding/routing info only). For authenticated admin users, returns full tenant details.

**Path Parameters:**

- `schema_name` (string, required): The schema name of the tenant

**Response (200 OK):**

```json
{
  "id": "uuid-here",
  "name": "My School",
  "short_name": "MS",
  "schema_name": "my_school",
  "logo": "http://localhost:8000/media/logo.png",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Error Responses:**

- `404 Not Found`: Tenant with schema_name not found
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: User is not an admin/superuser

**Example cURL:**

```bash
curl -X GET http://localhost:8000/api/v1/tenants/my_school/ \
  -H "Authorization: Bearer <token>"
```

---

### 4. Update Tenant

Update tenant details (full update - all fields).

**Endpoint:** `PUT /api/v1/tenants/<schema_name>/`

**Permissions:** Requires admin/superuser authentication

**Path Parameters:**

- `schema_name` (string, required): The schema name of the tenant

**Request Body (all fields optional):**

```json
{
  "name": "Updated School Name",
  "short_name": "USN",
  "is_active": false
}
```

**Response (200 OK):**

```json
{
  "id": "uuid-here",
  "name": "Updated School Name",
  "short_name": "USN",
  "schema_name": "my_school",
  "logo": "http://localhost:8000/media/logo.png",
  "is_active": false,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T01:00:00Z"
}
```

**Error Responses:**

- `400 Bad Request`: Validation errors
- `404 Not Found`: Tenant with schema_name not found
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: User is not an admin/superuser

**Example cURL:**

```bash
curl -X PUT http://localhost:8000/api/v1/tenants/my_school/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated School Name",
    "is_active": false
  }'
```

---

### 4a. Partial Update Tenant

Partially update tenant details (only send fields you want to update).

**Endpoint:** `PATCH /api/v1/tenants/<schema_name>/`

**Permissions:** Requires admin/superuser authentication

**Path Parameters:**

- `schema_name` (string, required): The schema name of the tenant

**Request Body (all fields optional, only include fields to update):**

```json
{
  "is_active": false
}
```

**Response (200 OK):**

```json
{
  "id": "uuid-here",
  "name": "My School",
  "short_name": "MS",
  "schema_name": "my_school",
  "logo": "http://localhost:8000/media/logo.png",
  "is_active": false,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T01:00:00Z"
}
```

**Error Responses:**

- `400 Bad Request`: Validation errors
- `404 Not Found`: Tenant with schema_name not found
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: User is not an admin/superuser

**Example cURL:**

```bash
curl -X PATCH http://localhost:8000/api/v1/tenants/my_school/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "is_active": false
  }'
```

---

### 5. Delete Tenant

Delete a tenant (WARNING: Schema is not automatically dropped for safety).

**Endpoint:** `DELETE /api/v1/tenants/<schema_name>/`

**Permissions:** Requires admin/superuser authentication

**Path Parameters:**

- `schema_name` (string, required): The schema name of the tenant

**Response (204 No Content):** Empty response body

**Error Responses:**

- `404 Not Found`: Tenant with schema_name not found
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: User is not an admin/superuser

**Example cURL:**

```bash
curl -X DELETE http://localhost:8000/api/v1/tenants/my_school/ \
  -H "Authorization: Bearer <token>"
```

**Note:** Deleting a tenant does not automatically drop the PostgreSQL schema. This is a safety feature. To fully remove a tenant, you may need to manually drop the schema.

---

## Models

### Tenant

The main tenant model that represents a school/organization.

**Fields:**

- `id` (UUID): Primary key
- `name` (string): Tenant name
- `short_name` (string): Short name/abbreviation
- `schema_name` (string): PostgreSQL schema name (auto-generated)
- `logo` (ImageField): Tenant logo
- `is_active` (boolean): Whether the tenant is active
- `created_at` (datetime): Creation timestamp
- `updated_at` (datetime): Last update timestamp
- `owner` (User): Owner user (from django-tenant-users)

### Domain

Domain model for tenant routing (used for subdomain-based routing, optional for header-based routing).

**Fields:**

- `domain` (string): Domain name
- `tenant` (Tenant): Associated tenant
- `is_primary` (boolean): Whether this is the primary domain

---

## Multi-Tenant Architecture

This app uses PostgreSQL schema-based multi-tenancy:

1. **Public Schema**: Contains global data (tenants, domains, global users)
2. **Tenant Schemas**: Each tenant gets its own schema (e.g., `my_school`)
3. **Data Isolation**: All tenant-specific data is stored in the tenant's schema
4. **Header-Based Routing**: Tenants are identified via `X-Tenant` or `X-Workspace` header

---

## Usage Notes

1. **Schema Names**: Must be valid PostgreSQL identifiers (letters, numbers, underscores only, max 63 characters)
2. **Auto-Generation**: If `schema_name` is not provided, it's auto-generated from the tenant name
3. **Owner User**: The owner user is automatically added as a superuser to the new tenant
4. **Public Tenant**: There's a special "public" tenant for global operations (created via management command)

---

## Management Commands

### Create Public Tenant

```bash
python manage.py create_public_tenant \
  --domain_url public.localhost \
  --owner_email admin@example.com
```

### Create Superadmin

```bash
python manage.py create_superadmin \
  --email admin@example.com \
  --id_number admin01 \
  --name "Super Admin" \
  --password secure_password
```

---

## Related Documentation

- [Django Tenants Documentation](https://django-tenants.readthedocs.io/)
- [Django Tenant Users Documentation](https://django-tenant-users.readthedocs.io/)
- See project root README.md for architecture details
