# Populate Grade Letters Command

## Overview
The `populate_grade_letters` management command creates standard grade letter scales for schools. This command is useful for initial setup or when adding new schools that need default grading scales.

## Usage

### Basic Usage
```bash
# Populate grade letters for all active schools using the standard scale
python manage.py populate_grade_letters

# Preview what would be created without making changes
python manage.py populate_grade_letters --dry-run

# Populate for a specific school
python manage.py populate_grade_letters --school-id <SCHOOL_ID>

# Use a different grading scale
python manage.py populate_grade_letters --scale-type simple

# Replace existing grade letters
python manage.py populate_grade_letters --overwrite
```

## Options

### `--school-id SCHOOL_ID`
Create grade letters only for a specific school by ID.
- **Example**: `--school-id 123`

### `--scale-type {standard,simple,ten_point,seven_point}`
Choose which grading scale to use (default: `standard`).
- **standard**: 13-point scale with plus/minus grades (A+ to F)
- **simple**: 5-point scale (A, B, C, D, F) with 10-point ranges
- **ten_point**: Same as simple (A, B, C, D, F) with 10-point ranges
- **seven_point**: 5-point scale (A, B, C, D, F) with 7-8 point ranges

### `--dry-run`
Preview what would be created without actually making any database changes.

### `--overwrite`
Delete all existing grade letters for the school(s) and create new ones. Use with caution!

## Grading Scales

### Standard Scale (default)
| Letter | Min % | Max % |
|--------|-------|-------|
| A+     | 97.00 | 100.00|
| A      | 93.00 | 96.99 |
| A-     | 90.00 | 92.99 |
| B+     | 87.00 | 89.99 |
| B      | 83.00 | 86.99 |
| B-     | 80.00 | 82.99 |
| C+     | 77.00 | 79.99 |
| C      | 73.00 | 76.99 |
| C-     | 70.00 | 72.99 |
| D+     | 67.00 | 69.99 |
| D      | 63.00 | 66.99 |
| D-     | 60.00 | 62.99 |
| F      | 0.00  | 59.99 |

### Simple / Ten Point Scale
| Letter | Min % | Max % |
|--------|-------|-------|
| A      | 90.00 | 100.00|
| B      | 80.00 | 89.99 |
| C      | 70.00 | 79.99 |
| D      | 60.00 | 69.99 |
| F      | 0.00  | 59.99 |

### Seven Point Scale
| Letter | Min % | Max % |
|--------|-------|-------|
| A      | 93.00 | 100.00|
| B      | 85.00 | 92.99 |
| C      | 77.00 | 84.99 |
| D      | 70.00 | 76.99 |
| F      | 0.00  | 69.99 |

## Examples

### Example 1: Initial Setup
```bash
# Preview for all schools
python manage.py populate_grade_letters --dry-run

# If the preview looks good, run it
python manage.py populate_grade_letters
```

### Example 2: Add Grade Letters to New School
```bash
# After creating a new school with ID 456
python manage.py populate_grade_letters --school-id 456
```

### Example 3: Change Grading Scale
```bash
# Switch a school to a simpler grading scale
python manage.py populate_grade_letters --school-id 123 --scale-type simple --overwrite
```

### Example 4: Test Different Scales
```bash
# Preview different scales without making changes
python manage.py populate_grade_letters --scale-type standard --dry-run
python manage.py populate_grade_letters --scale-type simple --dry-run
python manage.py populate_grade_letters --scale-type seven_point --dry-run
```

## Behavior

1. **Skipping Existing**: By default, the command will skip any grade letters that already exist for a school (based on the letter field).

2. **Overwrite Mode**: When using `--overwrite`, all existing grade letters for the school(s) will be deleted before creating new ones.

3. **Created By**: Grade letters are created with the `created_by` field set to the first superuser or staff user found in the system.

4. **Active Schools Only**: When no `--school-id` is specified, the command only processes schools where `active=True`.

## Notes

- Each school can have its own grade letter scale
- Grade letters are used to convert percentage grades into letter grades for report cards
- The `order` field determines the display order in the UI
- Schools can manually adjust grade letters through the Django admin interface after initial population

## Related Commands

- `populate_assessment_types`: Populate default assessment types for schools
- `create_gradebooks`: Create gradebooks for sections
