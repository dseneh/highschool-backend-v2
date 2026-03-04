# API Quick Reference Guide

## Authentication Flow

### 1. Login
```bash
POST /api/v1/auth/login/
Content-Type: application/json

{
  "username": "user@example.com",
  "password": "your_password"
}
```

**Response:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "id": "uuid",
    "username": "user@example.com",
    "email": "user@example.com"
  }
}
```

### 2. Use Access Token
```bash
GET /api/v1/students/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
x-tenant: school-slug
```

### 3. Refresh Token
```bash
POST /api/v1/auth/token/refresh/
Content-Type: application/json

{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

## Common Operations

### Student Management

#### List All Students
```bash
GET /api/v1/students/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Create Student
```bash
POST /api/v1/students/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
Content-Type: application/json

{
  "first_name": "John",
  "last_name": "Doe",
  "date_of_birth": "2010-05-15",
  "gender": "M",
  "email": "john.doe@example.com"
}
```

#### Get Student Details
```bash
GET /api/v1/students/{student_id}/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Search Students
```bash
GET /api/v1/students/?search=john
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Filter Students by Grade Level
```bash
GET /api/v1/students/?grade_level=5
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

### Transaction Management

#### List Transactions
```bash
GET /api/v1/transactions/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Filter by Date Range
```bash
GET /api/v1/transactions/?start_date=2024-01-01&end_date=2024-12-31
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Create Transaction
```bash
POST /api/v1/transactions/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
Content-Type: application/json

{
  "student": "student_id",
  "transaction_type": "payment",
  "amount": 500.00,
  "payment_method": "cash",
  "reference_number": "REF-12345",
  "notes": "Tuition payment for Q1"
}
```

#### Bulk Create Transactions
```bash
POST /api/v1/transactions/bulk/{transaction_type_id}/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
Content-Type: application/json

{
  "transactions": [
    {
      "student": "student_id_1",
      "amount": 500.00,
      "reference_number": "REF-001"
    },
    {
      "student": "student_id_2",
      "amount": 550.00,
      "reference_number": "REF-002"
    }
  ]
}
```

### Grading Operations

#### Create Gradebook
```bash
POST /api/v1/grading/academic-years/{academic_year_id}/gradebooks/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
Content-Type: application/json

{
  "section": "section_id",
  "subject": "subject_id",
  "marking_period": "marking_period_id",
  "teacher": "teacher_id"
}
```

#### Create Assessment
```bash
POST /api/v1/grading/gradebooks/{gradebook_id}/assessments/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
Content-Type: application/json

{
  "name": "Midterm Exam",
  "assessment_type": "exam",
  "max_score": 100,
  "date": "2024-03-15",
  "weight": 30
}
```

#### Enter Grades
```bash
POST /api/v1/grading/assessments/{assessment_id}/grades/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
Content-Type: application/json

{
  "student": "student_id",
  "score": 85,
  "comments": "Excellent work"
}
```

#### Get Student Report Card
```bash
GET /api/v1/grading/students/{student_id}/final-grades/academic-years/{academic_year_id}/report-card/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

### Bill Management

#### Get Student Bills
```bash
GET /api/v1/students/{student_id}/bills/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Download Bill PDF
```bash
GET /api/v1/students/{student_id}/bills/download-pdf/
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Bill Summary
```bash
GET /api/v1/bill-summary/?grade_level=5&section=A&payment_status=unpaid
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

### Report Generation

#### Transaction Report
```bash
GET /api/v1/reports/transactions/?start_date=2024-01-01&end_date=2024-12-31&format=excel
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

#### Finance Report
```bash
GET /api/v1/reports/finance/?report_type=revenue_summary&academic_year=2024
Authorization: Bearer <token>
x-tenant: <tenant-slug>
```

## Filtering & Pagination

### Pagination
```bash
# First page (20 items)
GET /api/v1/students/?page=1&page_size=20

# Second page
GET /api/v1/students/?page=2&page_size=20
```

### Filtering
```bash
# Multiple filters
GET /api/v1/students/?grade_level=5&section=A&status=active

# Date range
GET /api/v1/transactions/?start_date=2024-01-01&end_date=2024-03-31

# Search
GET /api/v1/students/?search=john
```

### Sorting
```bash
# Ascending
GET /api/v1/students/?ordering=last_name

# Descending (prefix with -)
GET /api/v1/students/?ordering=-created_at

# Multiple fields
GET /api/v1/students/?ordering=grade_level,last_name
```

## Error Handling

### Common HTTP Status Codes

- **200 OK** - Successful GET, PUT, PATCH
- **201 Created** - Successful POST
- **204 No Content** - Successful DELETE
- **400 Bad Request** - Invalid data or parameters
- **401 Unauthorized** - Authentication required or invalid token
- **403 Forbidden** - Insufficient permissions
- **404 Not Found** - Resource not found
- **500 Internal Server Error** - Server error

### Error Response Format
```json
{
  "success": false,
  "error": {
    "detail": "Student not found",
    "code": "NOT_FOUND"
  }
}
```

### Validation Error
```json
{
  "success": false,
  "error": {
    "email": ["Enter a valid email address."],
    "date_of_birth": ["This field is required."]
  }
}
```

## Best Practices

### 1. Always Include Headers
```bash
Authorization: Bearer <your_token>
x-tenant: <tenant_slug>
Content-Type: application/json
```

### 2. Handle Token Expiration
- Access tokens expire after 60 minutes
- Use refresh token to get new access token
- Implement automatic token refresh in your client

### 3. Use Pagination for Large Lists
- Always specify `page_size` for list endpoints
- Default is usually 10-20 items
- Maximum is typically 100 items per page

### 4. Implement Error Handling
```javascript
try {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response.json();
    console.error('API Error:', error);
  }
  const data = await response.json();
} catch (error) {
  console.error('Network Error:', error);
}
```

### 5. Use Appropriate HTTP Methods
- GET - Retrieve data (no side effects)
- POST - Create new resources
- PUT - Replace entire resource
- PATCH - Update specific fields
- DELETE - Remove resource

### 6. Validate Data Before Sending
- Check required fields
- Validate formats (email, date, etc.)
- Handle file uploads properly

## cURL Examples

### Login
```bash
curl -X POST https://api.example.com/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin@example.com",
    "password": "password123"
  }'
```

### List Students with Filters
```bash
curl -X GET "https://api.example.com/api/v1/students/?grade_level=5&page=1&page_size=20" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..." \
  -H "x-tenant: my-school"
```

### Create Transaction
```bash
curl -X POST https://api.example.com/api/v1/transactions/ \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..." \
  -H "x-tenant: my-school" \
  -H "Content-Type: application/json" \
  -d '{
    "student": "student-uuid",
    "transaction_type": "payment",
    "amount": 500.00,
    "payment_method": "cash",
    "reference_number": "REF-12345"
  }'
```

### Download Report
```bash
curl -X GET "https://api.example.com/api/v1/reports/transactions/?format=excel" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..." \
  -H "x-tenant: my-school" \
  --output transaction_report.xlsx
```

## JavaScript/Fetch Examples

### Setup API Client
```javascript
const API_BASE_URL = 'https://api.example.com/api/v1';
const TENANT_SLUG = 'my-school';

let accessToken = localStorage.getItem('access_token');

const apiRequest = async (endpoint, options = {}) => {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    'x-tenant': TENANT_SLUG,
    ...options.headers,
  };

  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Handle token refresh
    await refreshToken();
    return apiRequest(endpoint, options);
  }

  return response;
};
```

### Login
```javascript
const login = async (username, password) => {
  const response = await apiRequest('/auth/login/', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });

  const data = await response.json();
  
  if (data.access) {
    localStorage.setItem('access_token', data.access);
    localStorage.setItem('refresh_token', data.refresh);
    accessToken = data.access;
  }

  return data;
};
```

### Get Students
```javascript
const getStudents = async (filters = {}) => {
  const queryParams = new URLSearchParams(filters).toString();
  const response = await apiRequest(`/students/?${queryParams}`);
  return await response.json();
};

// Usage
const students = await getStudents({
  grade_level: 5,
  section: 'A',
  page: 1,
  page_size: 20
});
```

### Create Transaction
```javascript
const createTransaction = async (transactionData) => {
  const response = await apiRequest('/transactions/', {
    method: 'POST',
    body: JSON.stringify(transactionData),
  });
  return await response.json();
};

// Usage
const transaction = await createTransaction({
  student: 'student-uuid',
  transaction_type: 'payment',
  amount: 500.00,
  payment_method: 'cash',
  reference_number: 'REF-12345'
});
```

## Python/Requests Examples

### Setup API Client
```python
import requests
from typing import Optional, Dict, Any

class SchoolAPIClient:
    def __init__(self, base_url: str, tenant_slug: str):
        self.base_url = base_url
        self.tenant_slug = tenant_slug
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            'Content-Type': 'application/json',
            'x-tenant': self.tenant_slug
        }
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        return headers

    def login(self, username: str, password: str) -> Dict[str, Any]:
        response = requests.post(
            f'{self.base_url}/auth/login/',
            json={'username': username, 'password': password}
        )
        response.raise_for_status()
        data = response.json()
        
        self.access_token = data.get('access')
        self.refresh_token = data.get('refresh')
        
        return data

    def get_students(self, **filters) -> Dict[str, Any]:
        response = requests.get(
            f'{self.base_url}/students/',
            headers=self._get_headers(),
            params=filters
        )
        response.raise_for_status()
        return response.json()

    def create_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            f'{self.base_url}/transactions/',
            headers=self._get_headers(),
            json=transaction_data
        )
        response.raise_for_status()
        return response.json()

# Usage
client = SchoolAPIClient('https://api.example.com/api/v1', 'my-school')
client.login('admin@example.com', 'password123')

students = client.get_students(grade_level=5, section='A')
transaction = client.create_transaction({
    'student': 'student-uuid',
    'transaction_type': 'payment',
    'amount': 500.00,
    'payment_method': 'cash',
    'reference_number': 'REF-12345'
})
```

## Rate Limiting

The API may implement rate limiting to prevent abuse:
- Typical limit: 100 requests per minute per user
- Check response headers for rate limit info:
  - `X-RateLimit-Limit`: Total allowed requests
  - `X-RateLimit-Remaining`: Remaining requests
  - `X-RateLimit-Reset`: Time when limit resets

## Support & Resources

- **API Documentation**: Open `index.html` in your browser
- **JSON Spec**: See `api-endpoints.json` for programmatic access
- **Issues**: Contact your system administrator
- **Updates**: Refer to the latest API documentation

---

Last updated: February 10, 2026
