# Users App

## Overview

The `users` app manages global user authentication and user management in a multi-tenant system. Users are global (stored in the public schema) and can belong to multiple tenants with tenant-specific roles and permissions.

## Base URL

All endpoints are prefixed with: `/api/v1/auth/`

**Note:** URLs are not yet configured. These endpoints need to be added to `users/urls.py` and included in the main `api/urls.py`.

## Authentication

Most endpoints require authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

## Headers

For tenant-specific requests, include the tenant identifier:

```
X-Tenant: <schema_name>
```

User data is global (public schema), but tenant-specific permissions are managed per tenant.

---

## Authentication Endpoints

### 1. Login / Obtain Token

Authenticate user and receive JWT access and refresh tokens.

**Endpoint:** `POST /api/v1/auth/token/`

**Request Body:**

```json
{
  "username": "admin01",
  "password": "your_password"
}
```

**Note:** Users can login with `username`, `id_number`, or `email`.

**Response (200 OK):**

```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "admin",
    "email": "admin@example.com",
    "id_number": "admin01",
    "name": "Super Admin",
    "photo": "http://localhost:8000/media/users/photo.jpg",
    "is_active": true,
    "last_login": "2026-01-03T09:00:00Z",
    "date_joined": "2026-01-01T00:00:00Z"
  }
}
```

**Error Responses:**

- `401 Unauthorized`: Invalid credentials

**Example cURL:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin01",
    "password": "your_password"
  }'
```

---

### 2. Refresh Token

Get a new access token using a refresh token.

**Endpoint:** `POST /api/v1/auth/token/refresh/`

**Request Body:**

```json
{
  "refresh": "your_refresh_token"
}
```

**Response (200 OK):**

```json
{
  "access": "new_access_token"
}
```

---

### 3. Password Reset Request

Request a password reset email.

**Endpoint:** `POST /api/v1/auth/password-reset/`

**Request Body:**

```json
{
  "email": "user@example.com"
}
```

**Response (200 OK):**

```json
{
  "detail": "Password reset email has been sent."
}
```

---

### 4. Password Reset Confirm

Confirm password reset with token.

**Endpoint:** `POST /api/v1/auth/password-reset/confirm/`

**Request Body:**

```json
{
  "token": "reset_token",
  "uidb64": "user_id_base64",
  "new_password": "new_secure_password",
  "confirm_password": "new_secure_password"
}
```

**Alternative URL Format:**
`POST /api/v1/auth/password-reset/confirm/<uidb64>/<token>/`

**Response (200 OK):**

```json
{
  "detail": "Password has been reset successfully."
}
```

---

## User Management Endpoints

### 1. List Users

Get a list of all users (tenant-scoped based on permissions).

**Endpoint:** `GET /api/v1/auth/users/`

**Query Parameters:**

- `search` (string, optional): Search by name, username, email, or id_number
- `role` (string, optional): Filter by role
- `status` (string, optional): Filter by status
- `is_active` (boolean, optional): Filter by active status
- `page` (integer, optional): Page number for pagination
- `page_size` (integer, optional): Number of results per page

**Response (200 OK):**

```json
{
  "count": 100,
  "next": "http://localhost:8000/api/v1/auth/users/?page=2",
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "id_number": "admin01",
      "username": "admin",
      "email": "admin@example.com",
      "name": "Super Admin",
      "photo": "http://localhost:8000/media/users/photo.jpg",
      "is_active": true,
      "date_joined": "2024-01-01T00:00:00Z"
    }
  ]
}
```

---

### 2. Create User

Create a new user.

**Endpoint:** `POST /api/v1/auth/users/`

**Request Body:**

```json
{
  "id_number": "user001",
  "username": "newuser",
  "email": "user@example.com",
  "name": "New User",
  "password": "secure_password"
}
```

**Response (201 Created):**

```json
{
  "id": "uuid",
  "id_number": "user001",
  "username": "newuser",
  "email": "user@example.com",
  "name": "New User",
  "is_active": true
}
```

---

### 3. Get User Details

Get details of a specific user.

**Endpoint:** `GET /api/v1/auth/users/<pk>/`

**Path Parameters:**

- `pk` (string): User ID (UUID), id_number, username, or `current` to get current user

**Response (200 OK):**

```json
{
  "id": "uuid",
  "id_number": "admin01",
  "username": "admin",
  "email": "admin@example.com",
  "name": "Super Admin",
  "photo": "http://localhost:8000/media/users/photo.jpg",
  "is_active": true,
  "date_joined": "2024-01-01T00:00:00Z"
}
```

---

### 4. Update User

Update user details.

**Endpoint:** `PUT /api/v1/auth/users/<pk>/` or `PATCH /api/v1/auth/users/<pk>/`

**Path Parameters:**

- `pk` (string): User ID, id_number, username, or `current`

**Request Body (all fields optional for PATCH):**

```json
{
  "name": "Updated Name",
  "email": "newemail@example.com",
  "username": "newusername"
}
```

**Response (200 OK):** Returns updated user object

---

### 5. Delete User

Delete a user.

**Endpoint:** `DELETE /api/v1/auth/users/<pk>/`

**Path Parameters:**

- `pk` (string): User ID, id_number, or username

**Response (204 No Content)**

---

### 6. Get Current User

Get the currently authenticated user.

**Endpoint:** `GET /api/v1/auth/users/current/`

**Response (200 OK):** Returns current user object

**Example cURL:**

```bash
curl -X GET http://localhost:8000/api/v1/auth/users/current/ \
  -H "Authorization: Bearer <token>"
```

---

### 7. Change Password

Change user's password.

**Endpoint:** `PATCH /api/v1/auth/users/<pk>/password/change/`

**Path Parameters:**

- `pk` (string): User ID, id_number, username, or `current`

**Request Body:**

```json
{
  "old_password": "current_password",
  "new_password": "new_secure_password",
  "confirm_password": "new_secure_password"
}
```

**Response (200 OK):**

```json
{
  "detail": "Password has been changed successfully."
}
```

---

### 8. Change User Status

Activate or deactivate a user.

**Endpoint:** `PATCH /api/v1/auth/users/<pk>/status/`

**Path Parameters:**

- `pk` (string): User ID, id_number, or username

**Request Body:**

```json
{
  "is_active": false
}
```

**Response (200 OK):** Returns updated user object

---

### 9. Reset Password to Default

Reset user's password to a default password (admin action).

**Endpoint:** `PUT /api/v1/auth/users/<pk>/password-reset/`

**Path Parameters:**

- `pk` (string): User ID, id_number, or username

**Request Body (optional):**

```json
{
  "default_password": "new_default_password"
}
```

**Response (200 OK):**

```json
{
  "detail": "Password has been reset to default.",
  "default_password": "new_default_password"
}
```

---

## User Model

### Fields

- `id` (UUID): Primary key
- `id_number` (string): Unique identifier number
- `username` (string): Username (unique, optional)
- `email` (string): Email address (unique, primary identifier)
- `name` (string): Full name
- `photo` (ImageField): User profile photo
- `is_active` (boolean): Whether the user is active
- `is_staff` (boolean): Whether the user is staff (tenant-specific)
- `is_superuser` (boolean): Whether the user is a superuser (tenant-specific)
- `date_joined` (datetime): Account creation timestamp
- `last_login` (datetime): Last login timestamp

### Multi-Tenant User Architecture

Users are **global** (stored in public schema) but have **tenant-specific permissions**:

- A user can belong to multiple tenants
- Each tenant association has its own permissions (is_staff, is_superuser, roles)
- Tenant membership and permissions are managed via `TenantUser` model (from django-tenant-users)

---

## Authentication Backend

The app uses a custom authentication backend (`MultiFieldAuthBackend`) that allows users to login with:

- `username` + password
- `id_number` + password
- `email` + password

The `username` field in the login request can contain any of these three values.

---

## Management Commands

### Create Superadmin

Create a global superadmin user:

```bash
python manage.py create_superadmin \
  --email admin@example.com \
  --id_number admin01 \
  --name "Super Admin" \
  --password secure_password
```

This creates a user in the public schema with superuser privileges.

---

## Permissions

User permissions are managed per-tenant:

- Global users exist in the public schema
- Tenant-specific permissions (is_staff, is_superuser, roles) are stored in tenant schemas
- Use `django-tenant-users` utilities to manage tenant-user relationships

---

## Related Documentation

- See `core/README.md` for tenant management
- [Django Tenant Users Documentation](https://django-tenant-users.readthedocs.io/)
- See project root README.md for architecture details
