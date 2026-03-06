# Dashboard Functionality Implementation Guide

## Overview
This guide documents the complete dashboard functionality implementation across frontend v2 (ezyschool-ui) and backend v2 (backend-2), mirroring the patterns from the v1 projects.

## Architecture

### Backend (backend-2)
The backend provides three key endpoints for dashboard functionality:

#### 1. **GET `/students/summary/`**
**Purpose**: Returns aggregated student and academic statistics for the dashboard overview

**Location**: `/backend-2/students/views/student.py` → `StudentSummaryView`

**Response Format**:
```json
{
  "total_students": 150,
  "total_staff": 25,
  "academic_year": "2024-2025",
  "total_enrolled": 120,
  "pending_bills": 45000.50,
  "total_courses": 24,
  "active_sections": 12,
  "avg_attendance": 85.5
}
```

**Key Implementation Details**:
- **Section Filtering**: Uses `enrollments__academic_year` to properly traverse relationships (Section has no direct academic_year field)
- **Course Counting**: Uses `SectionSubject` model to count unique subjects across active sections
- **Attendance**: Returns placeholder (0) - requires implementation from Attendance records
- **Bills**: Sums active `StudentEnrollmentBill` records

**Recent Fixes** (Applied in this session):
- Fixed academic_year filtering using proper relationship traversal
- Fixed course counting to use SectionSubject model
- Removed invalid AVG aggregation on ForeignKey attendance field

#### 2. **GET `/students/`**
**Purpose**: Returns paginated list of students for the recent activity feed

**Location**: `/backend-2/students/views/student.py` → `StudentListView`

**Response Format**:
```json
{
  "count": 150,
  "next": "http://...",
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "first_name": "John",
      "last_name": "Doe",
      "id_number": "STU001",
      "gender": "M",
      "date_of_birth": "2010-05-15",
      "grade_level": { ... },
      ...
    },
    ...
  ]
}
```

**Query Parameters**:
- `limit`: Number of results (default: paginator limit)
- `offset`: Pagination offset
- `ordering`: Sort field (default: "id_number")
- `status`: Filter by status
- `first_name`, `last_name`, `gender`: Additional filters

**Implementation**:
- Uses `StudentPageNumberPagination` for pagination
- Returns `StudentSerializer` data

#### 3. **GET `/finance/billing/summary/`**
**Purpose**: Returns monthly financial data for chart visualization

**Location**: `/backend-2/finance/views/billing_summary.py` → `get_billing_summary()`

**Response Format**:
```json
[
  {
    "month": "2024-12",
    "moneyIn": 50000.00,
    "moneyOut": 25000.00,
    "moneyInChange": 5.2,
    "moneyOutChange": -3.1
  },
  ...
]
```

**Implementation**:
- Aggregates Transaction records by month and type (income/expense)
- Calculates percentage changes month-over-month
- Returns last 12 months of data
- Only counts approved transactions
- Filters by current academic year (if exists)

**New in This Session**:
- Created new endpoint at `/finance/views/billing_summary.py`
- Added to imports in `/finance/views/__init__.py`
- Registered URL route in `/finance/urls.py`

---

### Frontend (ezyschool-ui)
The frontend implements a complete dashboard experience using React Query for data management.

#### 1. **API Integration Layer**
**Location**: `/ezyschool-ui/lib/api2/dashboard/`

**Structure**:
```
api2/dashboard/
├── api.ts       (Axios API calls)
├── index.ts     (React Query hooks)
└── types.ts     (TypeScript types)
```

**Key Components**:

**api.ts** - Raw API functions:
```typescript
export const useDashboardApi = () => {
  const { get } = useAxiosAuth()
  
  const getDashboardSummary = async () => {
    return get(`/students/summary/`)
  }
  
  const getRecentStudents = async (params?: any) => {
    return get(`/students/`, { params: { limit: 5, ...params } })
  }
  
  const getFinancialSummary = async () => {
    return get(`/finance/billing/summary/`)
  }
  
  return { getDashboardSummary, getRecentStudents, getFinancialSummary }
}
```

**index.ts** - React Query hooks:
```typescript
export function useDashboard() {
  const api = useDashboardApi()
  
  // Each hook automatically manages caching, loading states, errors
  const getDashboardSummary = (options = {}) =>
    useApiQuery(
      ['dashboard', 'summary'],
      () => api.getDashboardSummary(),
      options
    )
  
  const getRecentStudents = (params?: any, options = {}) =>
    useApiQuery(
      ['dashboard', 'recentStudents', params],
      () => api.getRecentStudents(params),
      options
    )
  
  const getFinancialSummary = (options = {}) =>
    useApiQuery(
      ['dashboard', 'financialSummary'],
      () => api.getFinancialSummary().catch(() => null),
      options
    )
  
  return { getDashboardSummary, getRecentStudents, getFinancialSummary }
}
```

#### 2. **Dashboard Page**
**Location**: `/ezyschool-ui/app/[subdomain]/(with-shell)/page.tsx`

**Features**:
- Uses React Query hooks with 5-minute cache
- Automatically routes students to their student portal
- Shows loading skeleton while data fetches
- Transforms API data into dashboard layout format
- Provides refresh functionality

**Implementation**:
```typescript
export default function DashboardPage() {
  const { user: currentUser } = useAuth()
  const isStudent = currentUser?.account_type?.toLowerCase() === "student"
  const dashboard = useDashboard()
  
  // Fetch all three data sources
  const summaryQuery = dashboard.getDashboardSummary({
    staleTime: 5 * 60 * 1000,
    enabled: !isStudent
  })
  const recentStudentsQuery = dashboard.getRecentStudents(undefined, {
    staleTime: 5 * 60 * 1000,
    enabled: !isStudent
  })
  const financialSummaryQuery = dashboard.getFinancialSummary({
    staleTime: 5 * 60 * 1000,
    enabled: !isStudent
  })
  
  // Transform to DashboardData format
  const dashboardData = useMemo(() => ({
    alert: { pendingLeaves: 0, overtimeApprovals: 0 },
    stats: [
      { title: "Total Students", value: String(summary.total_students || 0), ... },
      { title: "Pending Bills", value: String(summary.pending_bills || 0), ... },
      { title: "Attendance", value: `${summary.avg_attendance || 0}%`, ... },
      { title: "Active Classes", value: String(summary.active_sections || 0), ... }
    ],
    chart: financialSummaryQuery.data || [],
    employees: recentStudentsQuery.data || []
  }), [isLoading, summaryQuery.data, ...])
  
  return <DashboardContent data={dashboardData!} ... />
}
```

#### 3. **Dashboard Components**
**Location**: `/ezyschool-ui/components/dashboard/`

**Key Components**:
- `DashboardContent.tsx` - Main layout container
- `StatsCards.tsx` - Four stat cards (Total Students, Pending Bills, Attendance, Active Classes)
- `FinancialOverview.tsx` - Chart showing monthly income/expense trends
- `RecentActivity.tsx` - Table of recent students
- `QuickActions.tsx` - Quick action buttons
- `DashboardSkeleton.tsx` - Loading state

**Layout Structure**:
```
Dashboard
├── Alert Banner (conditionally shown)
├── Stats Cards (4 columns or responsive grid)
├── Main Grid
│   ├── Financial Overview Chart
│   └── Quick Actions
└── Recent Activity Table
```

---

## Data Flow

```
┌─────────────────────┐
│   ezyschool-ui      │
│  (Frontend v2)      │
│                     │
│ Dashboard Page      │
│   ↓                 │
│ useDashboard()      │ (React Query hooks)
│   ├─ getDashboardSummary()
│   ├─ getRecentStudents()
│   └─ getFinancialSummary()
│   ↓                 │
│ DashboardContent    │
│   ├─ StatsCards    │
│   ├─ Chart         │
│   └─ Activity      │
└─────────────────────┘
         ↕
    HTTP Requests
         ↕
┌─────────────────────┐
│   backend-2         │
│  (Backend v2)       │
│                     │
│ /students/summary/  │ → StudentSummaryView
│ /students/          │ → StudentListView
│ /finance/billing/   │
│  summary/           │ → get_billing_summary()
│                     │
│ Database responses  │
└─────────────────────┘
```

---

## Configuration & Setup

### Backend Configuration (backend-2)

1. **Ensure all imports are in place**:
   - ✅ `/finance/views/__init__.py` exports `get_billing_summary`
   - ✅ `/finance/urls.py` imports and registers the endpoint

2. **Database Models Required**:
   - `students.Student`
   - `students.Enrollment`
   - `students.StudentEnrollmentBill`
   - `academics.Section`
   - `academics.SectionSubject`
   - `academics.AcademicYear`
   - `finance.Transaction`
   - `finance.TransactionType`
   - `users.User`

3. **Permissions**:
   - `/students/summary/` → `StudentAccessPolicy`
   - `/students/` → `StudentAccessPolicy`
   - `/finance/billing/summary/` → `IsAuthenticated`

### Frontend Configuration (ezyschool-ui)

1. **API Configuration**:
   - Ensure `useAxiosAuth()` is configured with correct base URL
   - Tenant context should handle subdomain routing
   - Multi-tenant headers should be set on requests

2. **React Query Configuration**:
   - Query client configured in `/lib/query-client.ts`
   - Default cache times: 5 minutes for dashboard data
   - Automatic refetch on focus/visibility changes

3. **Authentication**:
   - `useAuth()` hook from portable-auth provides user context
   - Dashboard automatically redirects unauthenticated users
   - Student users redirected to student portal

---

## Key Features Implemented

### ✅ Complete Features
1. **Student Summary Statistics**
   - Total students count
   - Total staff count
   - Current academic year name
   - Total enrolled students
   - Pending bills amount
   - Active sections count
   - Total courses count

2. **Recent Students Feed**
   - Latest 5 students added to system
   - Paginated with limit parameter
   - Includes student details (name, ID number, grade level, etc.)

3. **Financial Overview Chart**
   - Monthly income/expense trends
   - Last 12 months of data
   - Percentage change calculations
   - Properly handles missing months

4. **Dashboard Layout**
   - Responsive grid layout
   - Loading skeletons while fetching
   - Error handling with user-friendly messages
   - Refresh functionality

### ⏳ Pending/Partial Features

4. **Average Attendance**
   - Currently returns placeholder `0`
   - Implementation requires calculation from `Attendance` records
   - Would be: `COUNT(status='present') / COUNT(*)`
   - Should filter by current academic year

---

## Attendance Implementation Guide

To implement real attendance percentage calculation:

1. **Query Attendance Records**:
```python
from students.models import Attendance

if current_academic_year:
    attendance_records = Attendance.objects.filter(
        enrollment__academic_year=current_academic_year,
        status__in=['present', 'late']  # Count as present
    )
    absent_count = Attendance.objects.filter(
        enrollment__academic_year=current_academic_year,
        status='absent'
    ).count()
else:
    attendance_records = []
    absent_count = 0
```

2. **Calculate Percentage**:
```python
total_attendance = len(attendance_records) + absent_count
if total_attendance > 0:
    avg_attendance = (len(attendance_records) / total_attendance) * 100
else:
    avg_attendance = 0
```

3. **Update StudentSummaryView**:
Replace the placeholder in `/students/views/student.py`:
```python
# Calculate average attendance
avg_attendance = 0  # REPLACE THIS
```

---

## Testing Checklist

- [ ] Backend `/students/summary/` returns all 8 fields correctly
- [ ] Backend `/students/` returns paginated student list
- [ ] Backend `/finance/billing/summary/` returns monthly data
- [ ] Frontend dashboard page loads without errors
- [ ] Stats cards display correct values
- [ ] Financial chart renders with data
- [ ] Recent activity table shows students
- [ ] Loading states work correctly
- [ ] Error handling shows user-friendly messages
- [ ] Refresh button works
- [ ] Student users see student portal instead
- [ ] All endpoints require authentication

---

## Performance Notes

- **Caching**: React Query caches dashboard data for 5 minutes
- **Database**: Uses `select_related` and `prefetch_related` for optimization
- **Pagination**: Students limited to 5 for recent activity
- **Aggregation**: Uses Django ORM aggregation for efficiency
- **Query Optimization**: All views use single/minimal database queries

---

## Debugging

### If dashboard doesn't load:
1. Check browser console for API errors
2. Verify authentication token is present
3. Check backend logs for StudentSummaryView errors
4. Verify all models exist in database
5. Check finance/billing/summary endpoint exists

### If stats show 0 or wrong values:
1. Verify data exists in database
2. Check StudentEnrollmentBill records (should have `active=True`)
3. Verify academic year has `current=True`
4. Check Section relationships through Enrollment model
5. Verify Transaction status is "approved"

### If chart shows no data:
1. Verify Transaction records exist
2. Check transaction dates are within last 12 months
3. Verify TransactionType has correct `type` value
4. Check finance/billing/summary endpoint response

---

## Files Modified/Created (This Session)

### Created:
- `/backend-2/finance/views/billing_summary.py` - New billing summary endpoint

### Modified:
- `/backend-2/finance/views/__init__.py` - Added billing_summary import
- `/backend-2/finance/urls.py` - Added billing/summary/ route

### Already Existing (No Changes Needed):
- `/backend-2/students/views/student.py` - StudentSummaryView (fixed in previous session)
- `/ezyschool-ui/app/[subdomain]/(with-shell)/page.tsx` - Dashboard page
- `/ezyschool-ui/lib/api2/dashboard/` - API integration layer
- `/ezyschool-ui/components/dashboard/` - UI components

---

## Next Steps

1. **Test Integration**: Run full dashboard flow end-to-end
2. **Implement Attendance**: Add real attendance calculation
3. **Performance Monitoring**: Track query performance in production
4. **UI Polish**: Fine-tune responsive design on mobile devices
5. **Additional Charts**: Add more financial visualizations
6. **Export Functionality**: Add PDF/CSV export for dashboard data

