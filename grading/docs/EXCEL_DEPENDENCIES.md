# Excel Upload Dependencies

## Required Packages

The bulk grade upload feature requires the following Python packages:

### 1. pandas
**Version**: 2.3.1 or higher  
**Purpose**: Excel file parsing and data manipulation  
**Installation**: `pip install pandas>=2.3.1`

### 2. openpyxl
**Version**: 3.1.0 or higher (minimum required by pandas 2.3.1)  
**Purpose**: Reading/writing Excel 2010 xlsx/xlsm files  
**Installation**: `pip install openpyxl>=3.1.0`

### 3. bottleneck (optional)
**Version**: 1.3.6 or higher  
**Purpose**: Speeds up pandas operations  
**Installation**: `pip install bottleneck>=1.3.6`

---

## Common Issues

### Issue: "Pandas requires version '3.1.0' or newer of 'openpyxl'"

**Error**:
```
Failed to read Excel file: Pandas requires version '3.1.0' or newer of 'openpyxl' (version '3.0.10' currently installed).
```

**Cause**: Outdated openpyxl version

**Solution**:
```bash
pip install --upgrade 'openpyxl>=3.1.0'
```

**Verification**:
```bash
python -c "import openpyxl; print(openpyxl.__version__)"
```

Expected output: `3.1.5` or higher

---

### Issue: "No module named 'openpyxl'"

**Error**:
```
ModuleNotFoundError: No module named 'openpyxl'
```

**Cause**: openpyxl not installed

**Solution**:
```bash
pip install openpyxl>=3.1.0
```

---

### Issue: Excel file reading is slow

**Cause**: Missing bottleneck package

**Solution**:
```bash
pip install bottleneck>=1.3.6
```

This can speed up pandas operations by 5-10x.

---

## Version Compatibility Matrix

| pandas | openpyxl | Status |
|--------|----------|--------|
| 2.3.1  | 3.1.5    | ✅ Recommended |
| 2.3.1  | 3.1.0    | ✅ Supported |
| 2.3.1  | 3.0.10   | ❌ Not supported |
| 2.2.x  | 3.0.10   | ⚠️ May work but not tested |

---

## Installation Steps

### Development Environment

```bash
# Install all dependencies
pip install -r requirements.txt

# Or install individually
pip install pandas>=2.3.1
pip install 'openpyxl>=3.1.0'
pip install 'bottleneck>=1.3.6'
```

### Production Environment

```bash
# Using requirements.txt
pip install -r requirements.txt

# Verify installation
python -c "import pandas, openpyxl; print(f'pandas: {pandas.__version__}, openpyxl: {openpyxl.__version__}')"
```

Expected output:
```
pandas: 2.3.1, openpyxl: 3.1.5
```

---

## Testing

### Test Excel Reading
```python
import pandas as pd

# Test reading Excel file
df = pd.read_excel('path/to/file.xlsx')
print(f"Read {len(df)} rows successfully")
```

### Test Bulk Upload
```bash
# Create test Excel file
python -c "
import pandas as pd

data = {
    'id_number': ['S001', 'S002'],
    'student_name': ['Test Student 1', 'Test Student 2'],
    'grade_level': ['Grade 9', 'Grade 9'],
    'section': ['Section A', 'Section A'],
    'subject': ['Mathematics', 'Mathematics'],
    'academic_year': ['2025-2026', '2025-2026'],
    'marking_period': ['Marking Period 1', 'Marking Period 1'],
    'Quiz 1': [85, 90]
}

df = pd.DataFrame(data)
df.to_excel('test_upload.xlsx', index=False)
print('Created test_upload.xlsx')
"

# Upload via API
curl -X POST \
  'http://localhost:8000/api/grading/sections/{section_id}/grades/upload/?academic_year={year_id}&subject_id={subj_id}' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -F 'file=@test_upload.xlsx'
```

---

## Troubleshooting

### Check Installed Versions
```bash
pip list | grep -E "(pandas|openpyxl|bottleneck)"
```

### Force Reinstall
```bash
pip uninstall openpyxl -y
pip install 'openpyxl>=3.1.0'
```

### Check for Conflicts
```bash
pip check
```

### Update All Dependencies
```bash
pip install --upgrade -r requirements.txt
```

---

## Alternative Excel Libraries

If you encounter persistent issues with openpyxl, you can also use:

### 1. xlrd (for .xls files only)
```python
df = pd.read_excel('file.xls', engine='xlrd')
```

### 2. pyxlsb (for .xlsb files)
```python
df = pd.read_excel('file.xlsb', engine='pyxlsb')
```

**Note**: The bulk upload currently only supports `.xlsx` and `.xls` files with openpyxl as the primary engine.

---

## Requirements.txt Entry

```
# Excel file processing
pandas==2.3.1
openpyxl>=3.1.0
bottleneck>=1.3.6
```

---

## Docker/Container Setup

If deploying with Docker, ensure your Dockerfile includes:

```dockerfile
# Install dependencies
RUN pip install --no-cache-dir pandas==2.3.1 openpyxl>=3.1.0 bottleneck>=1.3.6

# Or use requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

---

## Last Updated
October 28, 2025

**Verified Versions**:
- pandas: 2.3.1
- openpyxl: 3.1.5
- bottleneck: 1.3.6+
