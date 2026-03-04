## Documentation Overview

Welcome to the grading system documentation. Everything you need is consolidated into three comprehensive guides.

### 📚 Complete Documentation (3 Files)

1. **[Grading Guide](GRADING_GUIDE.md)** - User & Administrator Guide
   - System overview and core concepts
   - Both grading modes (single_entry and multiple_entry)
   - Complete model reference
   - Quick start guide
   - Configuration instructions
   - Step-by-step workflows
   - Management commands (including `initialize_gradebooks`)
   - Troubleshooting guide
   - Best practices

2. **[API Reference](API_REFERENCE.md)** - Complete API Documentation
   - All endpoints with examples
   - Request/response formats
   - Pagination and filtering
   - Error handling
   - Role-based permissions
   - Complete workflow examples

3. **[Developer Guide](DEVELOPER_GUIDE.md)** - Technical Implementation
   - Architecture overview
   - Settings integration
   - Assessment generation engine
   - Calculation algorithms
   - Template system internals
   - Serializer patterns
   - Performance optimization
   - Testing strategies
   - Database schema

---

### 👥 For Teachers & Administrators

**Start Here**: [Grading Guide](GRADING_GUIDE.md)
- Read "Overview" to understand the system
- Check "Grading Modes" to see your school's configuration
- Follow "Quick Start" for your first gradebook
- Use "Management Commands" for setup (including `initialize_gradebooks`)
- Reference "Workflows" for day-to-day tasks

**API Integration**: [API Reference](API_REFERENCE.md)
- Find endpoints for your needs
- Copy request/response examples
- Check role-based permissions

### 👨‍💻 For Developers

**Start Here**: [Grading Guide](GRADING_GUIDE.md)
- Understand business requirements and workflows
- Learn both grading modes
- Review model relationships

**Deep Dive**: [Developer Guide](DEVELOPER_GUIDE.md)
- Architecture and design patterns
- Assessment generation algorithms
- Template system internals
- Calculation engine
- Testing strategies
- Performance optimization

**API Reference**: [API Reference](API_REFERENCE.md)
- Complete endpoint documentation
- Request/response schemas
- Error handling patterns

---

## Quick Reference

### Key Features

- ✅ **Two Grading Modes**: Single entry (simple final grades) or multiple entry (detailed assessments)
- ✅ **Auto-Generation**: Assessments created automatically based on school settings
- ✅ **Template System**: Reusable assessment templates for multiple entry mode
- ✅ **One-Command Setup**: `initialize_gradebooks` command handles complete initialization
- ✅ **Multiple Calculations**: Average, weighted, or cumulative methods
- ✅ **Role-Based Access**: Flexible permission system
- ✅ **Grade Workflow**: Draft → Pending → Reviewed → Approved
- ✅ **Real-Time Calculations**: Final grades with letter grades

### Quick Start

**Complete Setup (Recommended)**:
```bash
# Initialize everything: types → templates → gradebooks → grades
python manage.py initialize_gradebooks \
  --school-id <UUID> \
  --academic-year-id <UUID>
```

**Create Gradebook with Auto-Generation**:
```bash
POST /api/v1/grading/academic-years/{year_id}/gradebooks/
{
  "section_subject": "uuid",
  "name": "Math - Grade 10A",
  "calculation_method": "weighted",
  "auto_generate_assessments": true
}
```

**Enter Grade**:
```bash
POST /api/v1/grading/assessments/{assessment_id}/grades/
{
  "student": "uuid",
  "score": 85.5,
  "status": "draft"
}
```

**Get Final Grade**:
```bash
GET /api/v1/grading/final-grade/?student_id={uuid}&gradebook_id={uuid}
```

### System Requirements

- Django 4.2.16+
- Django REST Framework 3.15.2+
- PostgreSQL 12+ (recommended for production)
- Python 3.10+

### Common Tasks

| Task | Documentation Section |
|------|----------------------|
| **Initial setup** | [Grading Guide - Management Commands](GRADING_GUIDE.md#management-commands) |
| Set up first gradebook | [Grading Guide - Quick Start](GRADING_GUIDE.md#quick-start) |
| Configure school settings | [Grading Guide - Configuration](GRADING_GUIDE.md#configuration) |
| Create assessment templates | [Grading Guide - Multiple Entry Mode](GRADING_GUIDE.md#multiple-entry-mode) |
| Enter and approve grades | [Grading Guide - Workflows](GRADING_GUIDE.md#workflows) |
| Calculate final grades | [API Reference - Final Grades](API_REFERENCE.md#final-grades) |
| Bulk operations | [API Reference - Bulk Operations](API_REFERENCE.md) |
| Understand generation logic | [Developer Guide - Assessment Generation](DEVELOPER_GUIDE.md#assessment-generation) |
| Performance tuning | [Developer Guide - Performance](DEVELOPER_GUIDE.md#performance) |
| Write tests | [Developer Guide - Testing](DEVELOPER_GUIDE.md#testing) |

---

## Documentation Structure

All documentation is consolidated into **3 comprehensive files**:

```
grading/docs/
├── README.md              # This file - Navigation hub
├── GRADING_GUIDE.md       # Complete user guide (579 lines)
├── API_REFERENCE.md       # API documentation (587 lines)
└── DEVELOPER_GUIDE.md     # Technical details (1,038+ lines)
```

**Total**: 2,200+ lines of comprehensive documentation in 3 focused files.

---

## Support & Contributing

### Getting Help

- **Setup & Usage**: [Grading Guide](GRADING_GUIDE.md) troubleshooting section
- **API Questions**: [API Reference](API_REFERENCE.md)
- **Implementation Details**: [Developer Guide](DEVELOPER_GUIDE.md)

### Contributing

When contributing to the grading system:

1. Read all three documentation files
2. Follow existing patterns (see Developer Guide)
3. Add tests for new features
4. Update relevant documentation sections
5. Ensure all tests pass

---

## Version History

- **v2.1** (Current) - Complete initialization command, settings-aware auto-generation
- **v2.0** - Multiple entry mode with template system
- **v1.0** - Initial single entry implementation

---

## License

This project is proprietary. All rights reserved.
