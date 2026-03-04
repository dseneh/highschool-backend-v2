# Tenant Information Search API

## Overview

The Tenant Information Search endpoint allows you to search for tenant information by email, phone number, or ID number across multiple user types (Admin Users, Students, and Staff) in a multi-tenant system.

## Endpoint

```
GET /api/v1/search/
```

**Authentication Required:** No (Public endpoint)

**Tenant Header Required:** No (Searches across all tenants automatically)

## Query Parameters

At least one of the following parameters is required:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email` | string | Optional | Email address to search for (case-insensitive) |
| `phone` | string | Optional | Phone number to search for (partial match) |
| `id_number` | string | Optional | ID number to search for (exact match) |

## Request Examples

### Search by Email

```bash
GET /api/v1/search/?email=john.doe@example.com
```

### Search by Phone Number

```bash
GET /api/v1/search/?phone=+1234567890
```

### Search by ID Number

```bash
GET /api/v1/search/?id_number=STU123456
```

### Search by Multiple Parameters

```bash
GET /api/v1/search/?email=john.doe@example.com&phone=+1234567890
```

## Response Format

```json
{
  "count": 2,
  "search_params": {
    "email": "john.doe@example.com",
    "phone": null,
    "id_number": null
  },
  "results": [
    {
      "user_type": "user",
      "tenant": {
        "id": "uuid-here",
        "schema_name": "admin",
        "name": "Public Schema",
        "short_name": "Public"
      },
      "data": {
        "id": "uuid-here",
        "id_number": "USR123456",
        "email": "john.doe@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "full_name": "John Doe",
        "username": "johndoe",
        "account_type": "admin",
        "is_active": true
      }
    },
    {
      "user_type": "student",
      "tenant": {
        "id": "uuid-here",
        "schema_name": "school1",
        "name": "Example High School",
        "short_name": "EHS"
      },
      "data": {
        "id": "uuid-here",
        "id_number": "STU123456",
        "email": "john.doe@example.com",
        "phone_number": "+1234567890",
        "first_name": "John",
        "middle_name": "",
        "last_name": "Doe",
        "full_name": "John Doe",
        "gender": "male",
        "status": "active",
        "grade_level": "Grade 10"
      }
    }
  ]
}
```

## Response Fields

### Root Response

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Total number of matching records found |
| `search_params` | object | Echo of the search parameters used |
| `results` | array | Array of matching records |

### Result Object

| Field | Type | Description |
|-------|------|-------------|
| `user_type` | string | Type of user: `"user"`, `"student"`, or `"staff"` |
| `tenant` | object | Tenant information (public schema for users, specific tenant for students/staff) |
| `data` | object | User/Student/Staff data |

### Tenant Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Tenant UUID |
| `schema_name` | string | Tenant schema/workspace name |
| `name` | string | Full tenant name |
| `short_name` | string | Short tenant name |

### Data Object (User)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | User UUID |
| `id_number` | string | User ID number |
| `email` | string | User email address |
| `first_name` | string | First name |
| `last_name` | string | Last name |
| `full_name` | string | Full name |
| `username` | string | Username |
| `account_type` | string | Account type |
| `is_active` | boolean | Whether user is active |

### Data Object (Student/Staff)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Record UUID |
| `id_number` | string | Student/Staff ID number |
| `email` | string | Email address |
| `phone_number` | string | Phone number |
| `first_name` | string | First name |
| `middle_name` | string | Middle name |
| `last_name` | string | Last name |
| `full_name` | string | Full name |
| `gender` | string | Gender |
| `status` | string | Status |
| `grade_level` | string | Grade level (students only) |
| `position` | string | Position title (staff only) |
| `is_teacher` | boolean | Whether staff is a teacher (staff only) |

## Error Responses

### 400 Bad Request - Missing Parameters

```json
{
  "error": "At least one search parameter (email, phone, or id_number) is required"
}
```



## Important Notes

1. **Public Endpoint**: This endpoint is publicly accessible without authentication. No tenant header (X-Tenant) is required as it automatically searches across all active tenants.

2. **Admin Schema Alias**: The search API displays the public schema as "admin" for clarity. When using other endpoints that require a tenant header, you can use `X-Tenant: admin` to reference the public schema (where global users are stored).

3. **Non-Unique Fields**: Email and phone number fields are NOT unique in the Student and Staff models, so a search may return multiple matching records.

4. **ID Number Uniqueness**: The `id_number` field is unique within each model type (User, Student, Staff), but the same ID number could theoretically exist across different model types.

5. **Case Sensitivity**: Email search is case-insensitive.

6. **Phone Matching**: Phone number search uses partial matching (contains), so searching for "1234" will match "+1234567890".

7. **Multi-Tenant Search**: The endpoint automatically searches across all active tenants for Student and Staff records.

8. **Public Schema**: User records exist in the public schema. The tenant field for users will show schema_name as "admin" for better clarity and consistency.

9. **Performance**: Searching across many tenants can be resource-intensive. Consider adding pagination or limiting results if performance becomes an issue.

## Future Enhancements

- **Parent Email**: Once parent models include email fields, they will be added to the search functionality.
- **Pagination**: Add pagination support for large result sets.
- **Filtering**: Add filters to search within specific tenants or user types.
- **Sorting**: Add options to sort results by different fields.

## Example Use Cases

### Finding All Records for a Person

A person might have multiple records across different roles (user account, student in one school, staff in another):

```bash
GET /api/v1/search/?email=john.doe@example.com
```

This will return all matching records regardless of user type or tenant.

### Verifying ID Number Uniqueness

Check if an ID number is already in use:

```bash
GET /api/v1/search/?id_number=STU123456
```

### Finding Contact Information

Locate all records associated with a phone number:

```bash
GET /api/v1/search/?phone=+1234567890
```
