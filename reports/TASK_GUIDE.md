# Enhanced Reports API with Automatic Background Processing

## 🚀 New Features

### ✅ Automatic Background Processing
- **Smart detection**: Automatically triggers background processing for large datasets
- **Configurable threshold**: Default 5,000 records (configurable via settings)
- **Export detection**: Any export format automatically uses background processing

### ✅ Intelligent Caching
- **Request caching**: Identical requests return cached results instantly
- **Cache invalidation**: Configurable timeout (default 5 minutes)
- **Cache bypass**: Use `?force_refresh=true` to bypass cache

### ✅ Enhanced Task Management
- **Progress tracking**: Real-time progress updates
- **Task cancellation**: Cancel running background tasks
- **Download management**: Download completed results

## 📊 Usage Examples

### 1. Small Dataset (Synchronous Processing)
```bash
# Returns immediately for datasets < 5,000 records
GET /api/v1/reports/transactions/school123/?target=student&page_size=100

Response:
{
    "count": 1200,
    "processing_mode": "sync",
    "cached": false,
    "results": [...]
}
```

### 2. Large Dataset (Automatic Background Processing)
```bash
# Automatically triggers background processing for datasets > 5,000 records
GET /api/v1/reports/transactions/school123/?target=student&paginate=false

Response:
{
    "task_id": "abc-123-def",
    "status": "pending",
    "processing_mode": "background",
    "message": "Large dataset detected. Processing in background.",
    "estimated_records": 25000,
    "check_status_url": "/api/v1/reports/export-status/abc-123-def/",
    "auto_background": true
}
```

### 3. Force Background Processing
```bash
# Force background processing even for small datasets
GET /api/v1/reports/transactions/school123/?force_background=true

Response:
{
    "task_id": "def-456-ghi",
    "processing_mode": "background",
    "auto_background": false
}
```

### 4. Export Formats (Always Background)
```bash
# Any export format automatically uses background processing
GET /api/v1/reports/transactions/school123/?export_format=csv

Response:
{
    "task_id": "ghi-789-jkl",
    "processing_mode": "background",
    "export_format": "csv"
}
```

### 5. Cached Results
```bash
# Second identical request returns cached results
GET /api/v1/reports/transactions/school123/?target=student&status=approved

Response:
{
    "count": 850,
    "processing_mode": "sync",
    "cached": true,
    "from_cache": true,
    "results": [...]
}
```

### 6. Check Task Status
```bash
GET /api/v1/reports/export-status/abc-123-def/

Response:
{
    "id": "abc-123-def",
    "status": "processing",
    "progress": 65,
    "estimated_completion_seconds": 70,
    "estimated_count": 25000,
    "total_processed": 16250
}
```

### 7. Download Completed Results
```bash
GET /api/v1/reports/download/abc-123-def/

Response:
{
    "download_ready": true,
    "format": "json",
    "data": {...},
    "message": "In production, this would be a file download"
}
```

### 8. Cancel Background Task
```bash
DELETE /api/v1/reports/export-status/abc-123-def/

Response:
{
    "message": "Task cancelled successfully",
    "task_id": "abc-123-def"
}
```

## ⚙️ Configuration

### Settings Options
Add to your Django settings:

```python
# Background processing threshold (number of records)
REPORTS_BACKGROUND_THRESHOLD = 5000

# Cache timeout (seconds)
REPORTS_CACHE_TIMEOUT = 300  # 5 minutes

# Task data retention (seconds)  
REPORTS_TASK_CACHE_TIMEOUT = 3600  # 1 hour

# Maximum records for synchronous processing
REPORTS_MAX_SYNC_RECORDS = 5000

# Processing chunk size for background tasks
REPORTS_CHUNK_SIZE = 1000
```

## 🔄 Processing Flow

```
Request → Cache Check → Count Query → Decision
                ↓              ↓
            Return Cache   Large Dataset?
                              ↓
                         Yes → Background Task
                         No  → Sync Processing
                              ↓
                         Cache Result → Return
```

## 📈 Performance Benefits

### Caching
- **Identical requests**: Instant response from cache
- **Reduced database load**: Fewer redundant queries
- **Better user experience**: Faster response times

### Background Processing
- **Non-blocking**: Server remains responsive
- **Scalable**: Handle any dataset size
- **Progress tracking**: Users know processing status
- **Cancellable**: Users can stop long-running tasks

### Smart Routing
- **Automatic decision**: No manual configuration needed
- **Optimal performance**: Best method for each request
- **Transparent**: Clear indication of processing mode

## 🛠️ Production Deployment

### With Celery (Recommended)
1. Install Celery: `pip install celery redis`
2. Uncomment Celery tasks in `reports/tasks.py`
3. Start Celery worker: `celery -A api worker -l info`
4. Start Celery beat (if using scheduled tasks)

### Task Queue Alternatives
- **Django-RQ**: Simpler setup, good for smaller projects
- **Dramatiq**: Modern alternative to Celery
- **Kubernetes Jobs**: For containerized deployments

## 🔍 Monitoring

### Task Status Tracking
- Real-time progress updates
- Error handling and reporting
- Completion notifications
- Resource usage monitoring

### Cache Monitoring
- Hit/miss ratios
- Memory usage
- Expiration tracking
- Performance metrics
