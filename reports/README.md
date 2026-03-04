# Reports App

This Django app handles all reporting functionality for the high school management system.

## Structure

The reports app is organized with modular view files for different report types:

```
reports/
├── apps.py
├── urls.py
├── views/
│   ├── __init__.py
│   ├── transactions.py      # Transaction reports
│   ├── students.py          # Student reports (placeholder)
│   ├── finance.py          # Finance reports (placeholder)
│   └── ... (future reports)
└── README.md
```

## Available Reports

### Transaction Reports
- **URL**: `/api/v1/reports/transactions/<school_id>/`
- **Features**:
  - Large dataset support with pagination
  - Background export processing for datasets >10,000 records
  - Multiple export formats (JSON, CSV)
  - Real-time and batch processing modes

### Export Status Management
- **URL**: `/api/v1/reports/export-status/<task_id>/`
- **Features**:
  - Check export progress
  - Cancel running exports
  - Download completed files

### Future Reports (Placeholders)
- **Student Reports**: `/api/v1/reports/students/<school_id>/`
- **Finance Reports**: `/api/v1/reports/finance/<school_id>/`

## Usage Examples

### Real-time Transaction Report
```bash
GET /api/v1/reports/transactions/school123/?target=student&page_size=500
```

### Background Export
```bash
# Large dataset export
GET /api/v1/reports/transactions/school123/?target=student&large_export=true

# CSV export
GET /api/v1/reports/transactions/school123/?target=student&export_format=csv
```

### Check Export Status
```bash
GET /api/v1/reports/export-status/abc-123-def/
```

## Adding New Report Types

To add a new report type:

1. Create a new view file in `views/`:
   ```python
   # views/attendance.py
   class AttendanceReportView(APIView):
       # Implementation here
   ```

2. Add to `views/__init__.py`:
   ```python
   from .attendance import AttendanceReportView
   __all__.append('AttendanceReportView')
   ```

3. Add URL pattern in `urls.py`:
   ```python
   path('attendance/<str:school_id>/', AttendanceReportView.as_view(), name='attendance-reports'),
   ```

## Background Processing

The transaction reports support background processing for large datasets using:
- Task queues (Celery recommended)
- Progress tracking via cache
- Email notifications on completion
- File cleanup after 24 hours

See `finance/tasks.py` for the background task implementation.

## Permissions

All report views require appropriate permissions:
- `Permissions.Finance.TRANSACTION_READ` for transaction reports
- `Permissions.Student.STUDENT_READ` for student reports
- `Permissions.Finance.FINANCE_READ` for finance reports
