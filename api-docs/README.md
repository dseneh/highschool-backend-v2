# High School Management System - API Documentation

## Overview

This directory contains comprehensive API documentation for the High School Management System.

## Files

- **`index.html`** - Interactive HTML documentation with search and navigation
- **`api-endpoints.json`** - Machine-readable JSON format of all API endpoints
- **`README.md`** - This file

## Viewing the Documentation

### Option 1: Open Directly in Browser
Simply open `index.html` in any modern web browser:
```bash
open index.html
# or
firefox index.html
# or
chrome index.html
```

### Option 2: Serve with Python HTTP Server
```bash
# Python 3
python3 -m http.server 8000

# Then visit: http://localhost:8000
```

### Option 3: Serve with Node.js
```bash
npx http-server . -p 8000

# Then visit: http://localhost:8000
```

## Features

### Interactive HTML Documentation

- **🔍 Search**: Real-time search across all endpoints
- **📱 Responsive Design**: Works on desktop, tablet, and mobile
- **🎨 Styled Interface**: Clean, professional design
- **📋 Copy on Click**: Click any endpoint path to copy it to clipboard
- **🧭 Smooth Navigation**: Jump to any section with smooth scrolling
- **📊 Statistics Dashboard**: Overview of total endpoints and modules

### Navigation

Use the sidebar to quickly jump to any API module:
- Authentication
- Core / Tenants
- Users & Auth
- Academics
- Students
- Finance
- Staff
- Grading
- Settings
- Reports

### Search Functionality

Type in the search box to filter endpoints by:
- Endpoint path
- HTTP method
- Description
- Module name

## API Structure

### Base URL
```
https://your-domain.com/api/v1/
```

### Authentication
All endpoints (except login) require JWT authentication:
```
Authorization: Bearer <your_jwt_token>
```

### Multi-Tenancy
Most endpoints require a tenant header:
```
x-tenant: <tenant_slug>
```

## API Modules

1. **Authentication** - User login and token management
2. **Core / Tenants** - Multi-tenant school management
3. **Users & Auth** - User management and authentication
4. **Academics** - Academic structure (years, semesters, subjects, sections)
5. **Students** - Student management, enrollment, attendance, billing
6. **Finance** - Financial transactions, fees, payments
7. **Staff** - Staff, teachers, departments, positions
8. **Grading** - Grades, assessments, gradebooks, report cards
9. **Settings** - School configuration and grading settings
10. **Reports** - Generate and export various reports

## HTTP Methods

- **GET** - Retrieve resources
- **POST** - Create new resources
- **PUT** - Update entire resource
- **PATCH** - Partial update of resource
- **DELETE** - Delete resource

## Response Format

All responses are in JSON format:

```json
{
  "success": true,
  "data": { ... },
  "message": "Operation successful"
}
```

Error responses:
```json
{
  "success": false,
  "error": {
    "detail": "Error message",
    "code": "ERROR_CODE"
  }
}
```

## Pagination

List endpoints support pagination:
```
GET /api/v1/students/?page=1&page_size=20
```

Response includes:
```json
{
  "count": 150,
  "next": "http://api.example.com/students/?page=2",
  "previous": null,
  "results": [ ... ]
}
```

## Filtering

Most list endpoints support filtering:
```
GET /api/v1/students/?grade_level=5&section=A&status=active
```

## Sorting

Use the `ordering` parameter:
```
GET /api/v1/students/?ordering=-created_at
GET /api/v1/students/?ordering=last_name,first_name
```

## Common Query Parameters

- `page` - Page number for pagination
- `page_size` - Number of items per page
- `search` - Search term
- `ordering` - Sort field(s)
- `limit` - Maximum results to return
- Various filter parameters specific to each endpoint

## Development Notes

### Adding New Endpoints

When adding new endpoints to the API:
1. Update the corresponding `urls.py` file
2. Add appropriate view documentation
3. Re-generate this documentation

### Versioning

Current API version: **v1**

The API follows semantic versioning. Breaking changes will be introduced in new major versions.

## Support

For questions or issues:
- Contact your system administrator
- Check the inline code documentation
- Review the Django REST Framework documentation

## Last Updated

February 10, 2026

---

**Note**: This documentation is auto-generated from the API codebase. Always refer to the latest version for accurate endpoint information.
