# Defaults App

This Django app provides functionality to create default data for newly created schools in the high school management system.

## Overview

When a new school is created, it needs various default data structures to be functional:
- Academic years and semesters (dynamically calculated from current date)
- School divisions and grade levels  
- Subjects and periods
- Fee structures
- Transaction types
- Payment methods
- And more...

This app automates the creation of all this default data using predefined templates stored in the `data/` folder. The academic calendar is dynamically generated based on the current date to ensure relevance.

### Dynamic Date Generation

The app automatically calculates dates based on the current date:
- **Academic Year**: 12-month period starting from the first of the current month
- **Semesters**: Two 6-month periods (equal distribution)
- **Marking Periods**: 6 equally distributed periods (~7 weeks each)
- **Exam Periods**: 2 exam periods (1 week each) at the end of each semester

## Usage

### Option 1: Using the utility function (Recommended)

```python
from defaults import setup_school_defaults

# After creating a school
try:
    success = setup_school_defaults(school_instance, admin_user)
    print("Default data created successfully!")
except Exception as e:
    print(f"Error creating default data: {e}")
```

### Option 2: Using the core function directly

```python
from defaults.run import run_data_creation

# Create default data
run_data_creation(school_instance, admin_user)
```

### Option 3: Using Django management command

```bash
# Create default data for school with ID 1
python manage.py create_default_data --school-id 1

# Specify a specific user as creator
python manage.py create_default_data --school-id 1 --user-id 5
```

## Data Structure

The default data is organized in the `data/` folder:

- `academic_year.py` - Academic year information (dynamically calculated)
- `currency.py` - Default currency settings
- `division_list.py` - School divisions (Preschool, Elementary, etc.)
- `fees.py` - Standard school fees
- `gade_level.py` - Grade levels from Nursery to Grade 12
- `marking_period.py` - Grading periods within semesters (dynamically calculated)
- `payment_methods.py` - Payment method options
- `semester.py` - Semester definitions (dynamically calculated)
- `subjects.py` - Academic subjects by grade level
- `transaction_types.py` - Financial transaction types

**Note**: Files marked as "dynamically calculated" generate dates based on the current date when the school is created.

## Customization

To customize the default data:

1. Edit the relevant files in the `data/` folder
2. Modify the data structures according to your needs
3. The changes will be applied to all new schools created after the modification

## Integration

To integrate this with school creation, add this to your school creation view/serializer:

```python
from defaults import setup_school_defaults

class SchoolCreateView(CreateAPIView):
    # ... your existing code ...
    
    def perform_create(self, serializer):
        school = serializer.save()
        # Create default data for the new school
        try:
            setup_school_defaults(school, self.request.user)
        except Exception as e:
            # Handle error appropriately - could re-raise to rollback
            raise Exception(f"School created but default setup failed: {e}")
```

## Functions Available

### `setup_school_defaults(school, user)`
- **Purpose**: Main function to set up all default data
- **Args**: 
  - `school`: School model instance
  - `user`: User model instance (creator/admin)
- **Returns**: `True` if successful
- **Raises**: `Exception` if any default data creation fails

### `run_data_creation(school, user)`
- **Purpose**: Core function that creates all the default data
- **Args**: 
  - `school`: School model instance  
  - `user`: User model instance (creator/admin)
- **Returns**: None
- **Raises**: `Exception` if any default data creation fails

### `get_default_data_info()`
- **Purpose**: Get information about what data will be created
- **Returns**: Dictionary with descriptions of each data type

## Error Handling

The utility function `setup_school_defaults()` now raises exceptions on failure to ensure proper database rollback when used within transactions. For more detailed error information, you can catch and handle the exceptions as needed:

```python
from defaults import setup_school_defaults
from django.db import transaction

try:
    with transaction.atomic():
        school = create_school(...)
        setup_school_defaults(school, user)
        # Both school creation and default data setup will be rolled back on error
except Exception as e:
    print(f"Error: {e}")
    # Handle the error appropriately
```

## Dependencies

This app depends on:
- `core.models.School` 
- `users.models` (for user management)
- `python-dateutil` (for dynamic date calculations)
- Other models referenced in the creation functions

Make sure these apps are properly configured and the `python-dateutil` package is installed before using the defaults app.

### Installation

If `python-dateutil` is not installed, add it to your requirements.txt:
```
python-dateutil==2.8.2
```

Or install it directly:
```bash
pip install python-dateutil
```
