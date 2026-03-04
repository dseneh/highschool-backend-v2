# Gradebook System Documentation

## 📚 Documentation Index

This directory contains the complete gradebook system for the high school backend.

### Quick Start Guides

1. **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)** - Fast lookup for common tasks
2. **[API_GUIDE.md](./API_GUIDE.md)** - Complete API usage guide
3. **[GRADINGTASKSTATUSVIEW_GUIDE.md](./GRADINGTASKSTATUSVIEW_GUIDE.md)** - Visual guide for GradingTaskStatusView ⭐
4. **[STANDARD_RESPONSE_FORMAT.md](./STANDARD_RESPONSE_FORMAT.md)** - API response format reference 🆕

### Core Documentation

4. **[GRADEBOOK_INITIALIZER_GUIDE.md](./GRADEBOOK_INITIALIZER_GUIDE.md)** - Detailed initialization guide
5. **[GRADEBOOK_INITIALIZER_SUMMARY.md](./GRADEBOOK_INITIALIZER_SUMMARY.md)** - Function reference
6. **[IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)** - Complete implementation details

### Performance & Optimization

7. **[PERFORMANCE_ANALYSIS.md](./PERFORMANCE_ANALYSIS.md)** - Performance analysis & recommendations
8. **[CHANGELOG.md](./CHANGELOG.md)** - Version history and changes

---

## 🚀 What's New - Optimization Features

### Bulk Create (10-20x faster)
- Changed from individual creates to `bulk_create()`
- **Performance**: 50-70% faster for large schools
- **Impact**: No code changes needed, automatic

### Background Tasks (No timeouts)
- Automatic sync/async based on school size
- **Small schools (<50 sections)**: Synchronous (2-5 seconds)
- **Large schools (50+ sections)**: Background task (15-30 seconds)
- **API**: New task status endpoint for polling

---

## 🎯 Common Use Cases

### Initialize Gradebooks for a New Academic Year
```python
from grading.gradebook_initializer import initialize_gradebooks_for_academic_year

result = initialize_gradebooks_for_academic_year(
    school=school,
    academic_year=academic_year,
    grading_style='multiple_entry',
    created_by=user
)
```

### Change Grading Style (via API)
```bash
# Small school - synchronous response
PATCH /api/v1/settings/{school_id}/grading/
{
  "grading_style": "single_entry",
  "force": true
}

# Large school - async response with task_id
# Poll: GET /api/v1/settings/{school_id}/grading/tasks/{task_id}/
```

### Check Background Task Status
```bash
GET /api/v1/settings/{school_id}/grading/tasks/{task_id}/
```

**See [API_GUIDE.md](./API_GUIDE.md) for complete examples**

---

## 📊 Performance Characteristics

| School Size | Sections | Students | Processing Time | Mode |
|-------------|----------|----------|----------------|------|
| Small | 10-30 | 300-900 | 2-5 seconds | Sync ✅ |
| Medium | 30-80 | 900-2,400 | 8-12 seconds | Async ⚡ |
| Large | 80+ | 2,400+ | 15-30 seconds | Async ⚡ |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  API Request                                 │
│  PATCH /api/v1/settings/{school_id}/grading/                │
└────────────────────────┬────────────────────────────────────┘
                         ↓
              ┌──────────────────────┐
              │ Check Section Count   │
              └──────────┬───────────┘
                         ↓
              ┌──────────────────────┐
              │   < 50 sections?     │
              └──────────┬───────────┘
                         ↓
              ┌──────────┴──────────┐
              ↓                     ↓
    ┌─────────────────┐   ┌─────────────────┐
    │  Synchronous    │   │  Asynchronous   │
    │  Processing     │   │  Task Queue     │
    └────────┬────────┘   └────────┬────────┘
             ↓                     ↓
    ┌─────────────────┐   ┌─────────────────┐
    │ Return Result   │   │ Return task_id  │
    │ HTTP 200        │   │ HTTP 202        │
    └─────────────────┘   └────────┬────────┘
                                   ↓
                          ┌─────────────────┐
                          │ Poll Status URL │
                          │ for completion  │
                          └─────────────────┘
```

---

## 🔧 Key Files

| File | Purpose |
|------|---------|
| `gradebook_initializer.py` | Core initialization logic |
| `tasks.py` | Background task management |
| `models.py` | Database models |
| `management/commands/initialize_gradebooks.py` | CLI command |

---

## 📖 Detailed Documentation

- **For API Users**: See [API_GUIDE.md](./API_GUIDE.md) or [GRADINGTASKSTATUSVIEW_GUIDE.md](./GRADINGTASKSTATUSVIEW_GUIDE.md) ⭐
- **For Developers**: Start with [GRADEBOOK_INITIALIZER_GUIDE.md](./GRADEBOOK_INITIALIZER_GUIDE.md)
- **For Implementation Details**: Check [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)
- **For Performance**: Check [PERFORMANCE_ANALYSIS.md](./PERFORMANCE_ANALYSIS.md)
- **For History**: Review [CHANGELOG.md](./CHANGELOG.md)

---

## 🆘 Need Help?

1. Check [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) for common tasks
2. See [API_GUIDE.md](./API_GUIDE.md) for API examples
3. Review error messages in task status responses
4. Check logs for detailed error information

---

## 🎉 Features

- ✅ Automatic gradebook initialization
- ✅ Support for single_entry and multiple_entry grading styles
- ✅ Assessment type filtering by grading style
- ✅ Template-based assessment creation
- ✅ Bulk grade entry creation (10-20x faster)
- ✅ Background task support for large schools
- ✅ Progress tracking and status monitoring
- ✅ Transaction safety with rollback
- ✅ Comprehensive error handling
- ✅ CLI and API interfaces
