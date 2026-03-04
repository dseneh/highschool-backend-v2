# Access Policy Implementation Summary

## Overview
Implemented comprehensive role-based access control using `drf-access-policy` integrated with custom privilege system (`User.has_privilege` + `RoleDefaultPrivilege` + `SpecialPrivilege`).

## Key Changes

### 1. Base Policy Engine Fixed (`users/access_policies/access.py`)
**Changes:**
- Added `_normalize_code()` method to ensure consistent uppercase privilege codes
- Updated `has_privilege()` to delegate to `user.has_privilege()` (single source of truth)
- Updated `has_any_privilege()` to use `user.get_privileges()` and check role defaults + special grants
- **Result:** Now checks RoleDefaultPrivilege AND SpecialPrivilege (previously only checked SpecialPrivilege)

**Before:**
```python
def has_privilege(self, request, view, action, privilege_code: str) -> bool:
    # Only checked special_privileges, bypassed role defaults
    return user.special_privileges.filter(code=privilege_code).exists()
```

**After:**
```python
def has_privilege(self, request, view, action, privilege_code: str) -> bool:
    return user.has_privilege(self._normalize_code(privilege_code))
```

### 2. New Access Policy Files Created
Created comprehensive policies for all modules:

| Module | File | Coverage |
|--------|------|----------|
| **Academics** | `academics/access_policies.py` | AcademicYear, GradeLevel, Section, Subject, MarkingPeriod, etc. |
| **Finance** | `finance/access_policies/finance.py` | BankAccount, Currency, Fees, PaymentMethod, etc. |
| **Finance Transactions** | `finance/access_policies/transaction.py` | Transaction CRUD + approve/cancel/delete |
| **Reports** | `reports/access_policies.py` | Student reports, finance reports, exports |
| **Settings** | `settings/access_policies.py` | GradingSettings, fixtures, regeneration |
| **Students** | `students/access_policies.py` | Student CRUD, enrollment, attendance |
| **Grading** | `grading/access_policies.py` | Gradebook, grades, assessments |
| **Staff** | `staff/access_policies.py` | Staff, departments, positions, schedules |

### 3. Privilege Code Normalization
Updated all existing policy files to use **uppercase privilege codes** matching migration data:

**Before (mixed case):**
```python
"condition": "has_privilege:student_enroll"
"condition": "has_privilege:grading_enter"
"condition": "has_privilege:transaction_delete"
```

**After (uppercase):**
```python
"condition": "has_privilege:STUDENT_ENROLL"
"condition": "has_privilege:GRADING_ENTER"
"condition": "has_privilege:TRANSACTION_DELETE"
```

## Policy Patterns

### Standard CRUD Pattern
```python
statements = [
    # 1) SUPERADMIN/ADMIN: full access
    {
        "action": ["*"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "is_role_in:admin,superadmin",
    },
    
    # 2) Role-based default access (REGISTRAR, ACCOUNTANT, etc.)
    {
        "action": ["list", "retrieve", "create", "update", "partial_update"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "is_role_in:registrar,accountant",
    },
    
    # 3) Privilege-based granular control
    {
        "action": ["destroy"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "has_privilege:DOMAIN_DELETE",
    },
    
    # 4) Read-only for VIEWER role
    {
        "action": ["list", "retrieve"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "is_role_in:viewer",
    },
]
```

### Custom Action Pattern (grade approval, transaction cancel, etc.)
```python
{
    "action": ["approve"],
    "principal": "authenticated",
    "effect": "allow",
    "condition": "has_privilege:GRADING_APPROVE",
},
{
    "action": ["cancel", "set_status"],
    "principal": "authenticated",
    "effect": "allow",
    "condition": "has_privilege:TRANSACTION_CANCEL",
},
```

## Privilege Codes Hierarchy

### Domain-Level Privileges (Broad)
- `CORE_VIEW`, `CORE_MANAGE` → All academic configuration
- `FINANCE_VIEW`, `FINANCE_MANAGE` → All finance configuration
- `GRADING_VIEW`, `GRADING_MANAGE` → All grading configuration
- `STUDENTS_VIEW`, `STUDENTS_MANAGE` → All student records

### Action-Level Privileges (Granular)
**Students:**
- `STUDENT_ENROLL` → Create enrollments
- `STUDENT_EDIT` → Update student records
- `STUDENT_DELETE` → Delete student records

**Grading:**
- `GRADING_ENTER` → Create/update grades
- `GRADING_REVIEW` → Review grades
- `GRADING_APPROVE` → Approve grades
- `GRADING_REJECT` → Reject grades

**Transactions:**
- `TRANSACTION_CREATE` → Create transactions
- `TRANSACTION_UPDATE` → Update transactions
- `TRANSACTION_DELETE` → Delete transactions
- `TRANSACTION_APPROVE` → Approve transactions
- `TRANSACTION_CANCEL` → Cancel transactions

**Settings:**
- `SETTINGS_GRADING_MANAGE` → Manage grading settings

## Views Requiring Permission Class Wiring

### ✅ Already Wired (Using AccessPolicy)
- `staff/*` → All staff ViewSets (7 views) → `StaffAccessPolicy`
- `finance/views/transaction.py` → TransactionViewSet → `TransactionAccessPolicy`

### 🔲 Need Wiring (APIView classes without permission_classes)

#### Academics (11 views)
- `AcademicYearListView`, `AcademicYearDetailView`
- `SectionListView`, `SectionDetailView`
- `SubjectListView`, `SubjectDetailView`
- `GradeLevelListView`, `GradeLevelDetailView`
- `MarkingPeriodListView`, `MarkingPeriodDetailView`
- `PeriodListView`, `PeriodDetailView`, `PeriodTimeListView`, `PeriodTimeDetailView`
- `SectionScheduleListView`, `SectionScheduleDetailView`
- `SectionSubjectListView`, `SectionSubjectDetailView`
- `DivisionListView`, `DivisionDetailView`
- `SemesterListView`, `SemesterDetailView`
- `GradeLevelTuitionFeesDetailView`

#### Finance (14 views)
- `BankAccountListView`, `BankAccountDetailView`
- `CurrencyListView`, `CurrencyDetailView`
- `GeneralFeeListView`, `GeneralFeeDetailView`
- `PaymentMethodListView`, `PaymentMethodDetailView`
- `PaymentInstallmentListView`, `PaymentInstallmentDetailView`
- `SectionFeeListView`, `SectionFeeDetailView`
- `TransactionTypeListView`, `TransactionTypeDetailView`
- `StudentPaymentStatusListView`

#### Grading (16 views)
- `GradeBookListCreateView`, `GradeBookDetailView`
- `AssessmentListCreateView`, `AssessmentDetailView`
- `AssessmentTypeListCreateView`, `AssessmentTypeDetailView`
- `AssessmentsListCreateView`, `AssessmentsDetailView`
- `GradeListCreateView`, `GradeDetailView`
- `GradeLetterListCreateView`, `GradeLetterDetailView`
- `DefaultAssessmentTemplateListCreateView`, `DefaultAssessmentTemplateDetailView`
- `StudentFinalGradeView`, `StudentFinalGradesView`, `SectionFinalGradesView`
- `GradeStatusTransitionView`, `SectionGradeStatusTransitionView`, `StudentMarkingPeriodGradeStatusTransitionView`
- `FinalGradeView`, `GradeHistoryView`, `GradeCorrectionView`, `GradeMarkForCorrectionView`
- `BulkGradeUploadView`, `RankingView`
- `GenerateAssessmentsForGradebookView`, `GenerateAssessmentsForAcademicYearView`, `PreviewAssessmentsForGradebookView`
- `StudentReportCardPDFView`

#### Students (15 views)
- `StudentListView`, `StudentDetailView`
- `EnrollmentListView`, `EnrollmentDetailView`
- `AttendanceListView`, `AttendanceDetailView`
- `StudentGuardianListView`, `StudentGuardianDetailView`
- `StudentContactListView`, `StudentContactDetailView`
- `StudentConcessionListCreateView`, `StudentConcessionDetailView`, `StudentConcessionStatsView`
- `StudentWithdrawView`, `StudentReinstateView`, `StudentImportView`
- `StudentBillSummaryView`, `StudentBillSummaryDownloadView`
- `StudentEnrollmentBillListView`, `StudentEnrollmentBillDetailView`, `StudentBillingPDFView`
- `BillRecreationView`, `BillRecreationPreviewView`, `BillRecreationStatusView`
- `BillSummaryMetadataView`, `BillSummaryQuickStatsView`

#### Reports (4 views)
- `StudentReportView`
- `TransactionReportView`, `TransactionExportStatusView`, `TransactionReportDownloadView`
- `FinanceReportView`

#### Settings (5 views)
- `GradingSettingsView`
- `SchoolGradingStyleView`
- `GradingFixturesView`
- `GradebookRegenerateView`
- `GradingTaskStatusView`

## Implementation Template

### For ViewSets (like staff, transactions)
```python
from staff.access_policies import StaffAccessPolicy

class StaffViewSet(viewsets.ModelViewSet):
    permission_classes = [StaffAccessPolicy]
    # ... rest of implementation
```

### For APIView classes (most views)
```python
from academics.access_policies import AcademicsAccessPolicy

class AcademicYearListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    
    def get(self, request):
        # ... implementation
```

## Testing Recommendations

### 1. Verify Privilege Resolution
```python
# In Django shell
from users.models import User, RoleDefaultPrivilege

teacher = User.objects.get(role='teacher')
teacher.has_privilege("GRADING_ENTER")  # Should be True (from role defaults)
teacher.has_privilege("GRADING_APPROVE")  # Should be False (not in role defaults)

# Grant special privilege
from users.models import SpecialPrivilege
SpecialPrivilege.objects.create(user=teacher, code="GRADING_APPROVE", granted_by=admin)
teacher.has_privilege("GRADING_APPROVE")  # Should be True (from special grant)
```

### 2. Verify Case Normalization
```python
# All these should work (case-insensitive):
teacher.has_privilege("grading_enter")
teacher.has_privilege("GRADING_ENTER")
teacher.has_privilege("Grading_Enter")
```

### 3. Test Policy Conditions
```python
# In test client
response = client.get('/api/v1/academics/academic-years/', headers={'x-tenant': 'school1'})
# Teacher should get 200
# Unauthenticated should get 403
```

## Migration Status

### Completed
✅ Migration 0002: Add SpecialPrivilege + RoleDefaultPrivilege models
✅ Migration 0003: Populate 40+ role-privilege mappings

### To Run
```bash
cd /path/to/backend-2
source .venv/bin/activate
python manage.py migrate users
```

## Next Steps

1. **Wire policies to views** (see "Need Wiring" section above)
   - Add `permission_classes = [PolicyClass]` to each APIView
   - Import appropriate policy at top of view file

2. **Add custom conditions** (if needed)
   - `is_own_profile` (users view own data)
   - `is_section_teacher` (teachers view only their sections)
   - `is_student_parent` (parents view only their children)

3. **Add queryset filtering** (complement policy checks)
   - Teachers see only their sections
   - Students see only their own data
   - Parents see only their children's data

4. **Test coverage**
   - Unit tests for each policy condition
   - Integration tests for view access
   - Test role defaults + special privileges

## Benefits

✅ **Single source of truth**: `User.has_privilege()` checks both role defaults AND special grants
✅ **Case-insensitive**: Privilege codes normalized to uppercase
✅ **Centralized policies**: All modules have dedicated policy files
✅ **Granular control**: Role-based defaults + per-user special privileges
✅ **Expiring privileges**: SpecialPrivilege.expires_at for temporary access
✅ **Audit trail**: SpecialPrivilege tracks granted_by and granted_at
✅ **Flexible roles**: Multi-role users supported (staff + parent, etc.)
