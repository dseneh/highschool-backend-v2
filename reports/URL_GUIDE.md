# Reports App URL Structure

## Available Endpoints

### Transaction Reports
- **URL**: `/api/v1/reports/transactions/<school_id>/`
- **Method**: GET
- **Permission**: `Permissions.Finance.TRANSACTION_READ`
- **Features**: Large dataset support, background processing, export capabilities

**Examples:**
```bash
# Basic transaction report
GET /api/v1/reports/transactions/school123/?target=student&page_size=500

# Large export (background processing)
GET /api/v1/reports/transactions/school123/?target=student&large_export=true

# CSV export (background processing)  
GET /api/v1/reports/transactions/school123/?target=student&export_format=csv

# Unpaginated with limit
GET /api/v1/reports/transactions/school123/?target=student&paginate=false&limit=5000
```

### Student Reports (Placeholder)
- **URL**: `/api/v1/reports/students/<school_id>/`
- **Method**: GET
- **Permission**: `Permissions.Student.STUDENT_READ`
- **Status**: Not yet implemented (returns 501)

### Finance Reports (Placeholder)
- **URL**: `/api/v1/reports/finance/<school_id>/`
- **Method**: GET
- **Permission**: `Permissions.Finance.BANK_ACCOUNT_READ`
- **Status**: Not yet implemented (returns 501)

### Export Status Management
- **URL**: `/api/v1/reports/export-status/<task_id>/`
- **Methods**: GET, DELETE
- **Permission**: `Permissions.Finance.TRANSACTION_READ`
- **Features**: Check progress, cancel exports

**Examples:**
```bash
# Check export status
GET /api/v1/reports/export-status/abc-123-def/

# Cancel export
DELETE /api/v1/reports/export-status/abc-123-def/
```

## Response Formats

### Standard Paginated Response
```json
{
    "count": 1500,
    "next": "http://api.../reports/transactions/school123/?page=2",
    "previous": null,
    "results": [...]
}
```

### Large Dataset Response (Unpaginated)
```json
{
    "count": 8500,
    "returned": 5000,
    "has_more": true,
    "limit": 5000,
    "next": null,
    "previous": null,
    "results": [...]
}
```

### Background Export Response
```json
{
    "task_id": "abc-123-def",
    "status": "pending",
    "message": "Export task has been queued. Use the task_id to check progress.",
    "check_status_url": "/api/v1/reports/export-status/abc-123-def/",
    "estimated_records": 25000
}
```

### Export Status Response
```json
{
    "status": "processing",
    "progress": 45,
    "created_at": "2025-09-16T10:30:00Z",
    "updated_at": "2025-09-16T10:32:15Z",
    "total_records": 25000,
    "export_format": "csv"
}
```
