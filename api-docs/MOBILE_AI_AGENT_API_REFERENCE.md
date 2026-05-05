# Mobile AI Agent API Reference

Auto-generated from `api-docs/api-endpoints.json`.

## Quick Rules

- Base URL: https://your-domain.com/api/v1/
- Auth: JWT via Authorization: Bearer <token>
- Tenant header: x-tenant: <tenant_slug> (required for tenant-scoped endpoints)
- Total endpoints documented: 115

## Critical Auth Endpoints

- POST /api/v1/auth/login/
  - Purpose: Authenticate user and return JWT access/refresh tokens.
  - Body: username/email/staff_id, password
- POST /api/v1/auth/token/refresh/
  - Purpose: Exchange refresh token for a new access token.
  - Body: refresh
- POST /api/v1/auth/verify/
  - Purpose: Validate the current JWT token.
- GET /api/v1/auth/user/current/
  - Purpose: Return the currently authenticated user profile.
- GET|POST /api/v1/auth/users/
  - Purpose: List tenant users or create/attach a user in tenant scope.
- GET|PUT|PATCH|DELETE /api/v1/auth/users/{id_number}/
  - Purpose: Retrieve or manage a specific user.
- POST /api/v1/auth/users/{id_number}/password/change/
  - Purpose: Change password for a specific user.
- POST /api/v1/auth/password/forgot/
  - Purpose: Start password reset flow.
- POST /api/v1/auth/password/reset/
  - Purpose: Complete password reset.

## Endpoint Catalog

### Academics
- Academic structure management including years, semesters, subjects, and schedules

#### Academic Years

- GET|POST /api/v1/academic-years/
  - Name: List/Create Academic Years
  - Description: Get all academic years or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/academic-years/{id}/
  - Name: Academic Year Details
  - Description: Get, update, or delete specific academic year
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/academic-years/current/
  - Name: Get Current Academic Year
  - Description: Retrieve the currently active academic year
  - Auth: Required
  - Tenant Header: Required

#### Periods & Schedules

- GET|PUT|PATCH|DELETE /api/v1/class-schedules/{id}/
  - Name: Class Schedule Details
  - Description: Get, update, or delete specific class schedule
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/period-times/{id}/
  - Name: Period Time Details
  - Description: Get, update, or delete period time configuration
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/periods/
  - Name: List/Create Periods
  - Description: Get all periods or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/periods/{id}/
  - Name: Period Details
  - Description: Get, update, or delete specific period
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/periods/{period_id}/period-times/
  - Name: List/Create Period Times
  - Description: Get or configure time slots for period
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/sections/{section_id}/class-schedules/
  - Name: List/Create Section Schedules
  - Description: Get or create class schedules for section
  - Auth: Required
  - Tenant Header: Required

#### Divisions

- GET|POST /api/v1/divisions/
  - Name: List/Create Divisions
  - Description: Get all divisions or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/divisions/{id}/
  - Name: Division Details
  - Description: Get, update, or delete specific division
  - Auth: Required
  - Tenant Header: Required

#### Grade Levels

- GET|POST /api/v1/grade-levels/
  - Name: List/Create Grade Levels
  - Description: Get all grade levels or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grade-levels/{id}/
  - Name: Grade Level Details
  - Description: Get, update, or delete specific grade level
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/grade-levels/{id}/tuition/
  - Name: Get Grade Level Tuition
  - Description: Retrieve tuition fee information for grade level
  - Auth: Required
  - Tenant Header: Required

#### Sections

- GET|POST /api/v1/grade-levels/{grade_level_id}/sections/
  - Name: List/Create Sections
  - Description: Get or create sections for grade level
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/sections/{id}/
  - Name: Section Details
  - Description: Get, update, or delete specific section
  - Auth: Required
  - Tenant Header: Required

#### Marking Periods

- GET /api/v1/marking-periods/
  - Name: List All Marking Periods
  - Description: Get all marking periods across all semesters
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/marking-periods/{id}/
  - Name: Marking Period Details
  - Description: Get, update, or delete specific marking period
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/semesters/{semester_id}/marking-periods/
  - Name: List/Create Semester Marking Periods
  - Description: Get or create marking periods for specific semester
  - Auth: Required
  - Tenant Header: Required

#### Section Subjects

- GET|PUT|PATCH|DELETE /api/v1/section-subjects/{id}/
  - Name: Section Subject Details
  - Description: Get, update, or delete section-subject assignment
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/sections/{section_id}/section-subjects/
  - Name: List/Assign Section Subjects
  - Description: Get or assign subjects to section
  - Auth: Required
  - Tenant Header: Required

#### Semesters

- GET|POST /api/v1/semesters/
  - Name: List/Create Semesters
  - Description: Get all semesters or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/semesters/{id}/
  - Name: Semester Details
  - Description: Get, update, or delete specific semester
  - Auth: Required
  - Tenant Header: Required

#### Subjects

- GET|POST /api/v1/subjects/
  - Name: List/Create Subjects
  - Description: Get all subjects or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/subjects/{id}/
  - Name: Subject Details
  - Description: Get, update, or delete specific subject
  - Auth: Required
  - Tenant Header: Required

### Finance
- Financial management including fees, transactions, payments, and accounting

#### Installments

- GET|POST /api/v1/academic-years/{academic_year_id}/installments/
  - Name: List/Create Installments
  - Description: Get or create payment installment plans
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/installments/{pk}/
  - Name: Installment Details
  - Description: Get, update, or delete installment
  - Auth: Required
  - Tenant Header: Required

#### Bank Accounts

- GET|POST /api/v1/bankaccounts/
  - Name: List/Create Bank Accounts
  - Description: Get all bank accounts or add new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/bankaccounts/{id}/
  - Name: Bank Account Details
  - Description: Get, update, or delete bank account
  - Auth: Required
  - Tenant Header: Required

#### Currency

- GET|POST /api/v1/currencies/
  - Name: List/Create Currencies
  - Description: Get all currencies or add new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/currencies/{pk}/
  - Name: Currency Details
  - Description: Get, update, or delete currency
  - Auth: Required
  - Tenant Header: Required

#### Fees

- GET|POST /api/v1/general-fees/
  - Name: List/Create General Fees
  - Description: Get all general fees or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/general-fees/{id}/
  - Name: General Fee Details
  - Description: Get, update, or delete general fee
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/section-fees/{id}/
  - Name: Section Fee Details
  - Description: Get, update, or delete section fee
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/sections/{section_id}/section-fees/
  - Name: List/Create Section Fees
  - Description: Get or create fees for section
  - Auth: Required
  - Tenant Header: Required

#### Payment Methods

- GET|POST /api/v1/payment-methods/
  - Name: List/Create Payment Methods
  - Description: Get all payment methods or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/payment-methods/{pk}/
  - Name: Payment Method Details
  - Description: Get, update, or delete payment method
  - Auth: Required
  - Tenant Header: Required

#### Payment Status

- GET /api/v1/students/payment-status/
  - Name: List Student Payment Status
  - Description: Get payment status overview for all students
  - Auth: Required
  - Tenant Header: Required

#### Transaction Types

- GET|POST /api/v1/transaction-types/
  - Name: List/Create Transaction Types
  - Description: Get all transaction types or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/transaction-types/{pk}/
  - Name: Transaction Type Details
  - Description: Get, update, or delete transaction type
  - Auth: Required
  - Tenant Header: Required

#### Transactions

- GET|POST /api/v1/transactions/
  - Name: List/Create Transactions
  - Description: Get all transactions or record new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/transactions/{id}/
  - Name: Transaction Details
  - Description: Get, update, or delete specific transaction
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/transactions/bulk/{transaction_type_id}/
  - Name: Bulk Create Transactions
  - Description: Create multiple transactions in single request
  - Auth: Required
  - Tenant Header: Required

### Students
- Student management, enrollment, attendance, and billing

#### Attendance

- GET|PUT|PATCH|DELETE /api/v1/attendance/{id}/
  - Name: Attendance Details
  - Description: Get, update, or delete attendance record
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/students/{student_id}/attendance/
  - Name: List/Record Attendance
  - Description: Get or record student attendance
  - Auth: Required
  - Tenant Header: Required

#### Bill Summary

- GET /api/v1/bill-summary/
  - Name: Get Bill Summary
  - Description: Get comprehensive billing summary with analytics
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/bill-summary/download/
  - Name: Download Bill Summary
  - Description: Export bill summary to Excel/CSV
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/bill-summary/metadata/
  - Name: Get Bill Summary Metadata
  - Description: Get metadata including available filters
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/bill-summary/quick-stats/
  - Name: Get Quick Stats
  - Description: Get quick billing statistics
  - Auth: Required
  - Tenant Header: Required

#### Enrollment

- GET|PUT|PATCH|DELETE /api/v1/enrollments/{id}/
  - Name: Enrollment Details
  - Description: Get, update, or delete specific enrollment
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/students/{student_id}/enrollments/
  - Name: List/Create Enrollments
  - Description: Get or create student enrollments
  - Auth: Required
  - Tenant Header: Required

#### Student Management

- POST /api/v1/grade-levels/{grade_level_id}/student-uploads/
  - Name: Bulk Import Students
  - Description: Import multiple students from CSV/Excel
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/students/
  - Name: List/Create Students
  - Description: Get all students or register new student
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/students/{id}/
  - Name: Student Details
  - Description: Get, update, or delete specific student
  - Auth: Required
  - Tenant Header: Required

#### Billing

- GET /api/v1/students/{student_id}/bills/
  - Name: List Student Bills
  - Description: Get all bills for student
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/students/{student_id}/bills/download-pdf/
  - Name: Download Bill PDF
  - Description: Generate and download bill PDF
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/students/bills/recreate/
  - Name: Recreate Bills
  - Description: Bulk recreate bills (async operation)
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/students/bills/recreate/preview/
  - Name: Preview Bill Recreation
  - Description: Preview changes for bill recreation
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/students/bills/recreate/status/{task_id}/
  - Name: Check Bill Recreation Status
  - Description: Check async task status
  - Auth: Required
  - Tenant Header: Required

### Authentication
- JWT-based authentication endpoints for user login and token management

#### Authentication

- GET /api/v1/auth/
  - Name: List Tenant Users
  - Description: Get a list of all users within a specific tenant.
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/auth/login/
  - Name: User Login
  - Description: Authenticate a user using email, username, or staff ID. Returns access and refresh tokens.
  - Auth: Not required
  - Tenant Header: Not required
- POST /api/v1/auth/token/refresh/
  - Name: Refresh Access Token
  - Description: Obtain a new access token using a valid refresh token.
  - Auth: Not required
  - Tenant Header: Not required
- GET /api/v1/auth/user/current/
  - Name: Get Current User
  - Description: Retrieve detailed information about the currently authenticated user.
  - Auth: Required
  - Tenant Header: Not required
- POST /api/v1/auth/verify/
  - Name: Verify Token
  - Description: Validate a JWT token and check if it's still valid.
  - Auth: Required
  - Tenant Header: Not required

### Staff
- Staff, teacher, department, and position management

#### Staff

- GET|POST /api/v1/departments/
  - Name: List/Create Departments
  - Description: Get all departments or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/departments/{id}/
  - Name: Department Details
  - Description: Get, update, or delete department
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/position-categories/
  - Name: List/Create Position Categories
  - Description: Get all position categories or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/position-categories/{id}/
  - Name: Position Category Details
  - Description: Get, update, or delete position category
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/positions/
  - Name: List/Create Positions
  - Description: Get all positions or create new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/positions/{id}/
  - Name: Position Details
  - Description: Get, update, or delete position
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/staff/
  - Name: List/Create Staff
  - Description: Get all staff members or add new one
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/staff/{id}/
  - Name: Staff Details
  - Description: Get, update, or delete staff member
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/staff/teachers/
  - Name: List Teachers
  - Description: Get all teaching staff members
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/teacher-schedules/
  - Name: List/Create Teacher Schedules
  - Description: Get or assign teacher schedules
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/teacher-schedules/{id}/
  - Name: Teacher Schedule Details
  - Description: Get, update, or delete teacher schedule
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/teacher-sections/
  - Name: List/Create Teacher Sections
  - Description: Get or assign teacher to sections
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/teacher-sections/{id}/
  - Name: Teacher Section Details
  - Description: Get, update, or delete teacher-section assignment
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/teacher-subjects/
  - Name: List/Create Teacher Subjects
  - Description: Get or assign teacher to subjects
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/teacher-subjects/{id}/
  - Name: Teacher Subject Details
  - Description: Get, update, or delete teacher-subject assignment
  - Auth: Required
  - Tenant Header: Required

### Grading
- Grade management, assessments, gradebooks, and report cards

#### Templates

- POST /api/v1/grading/academic-years/{academic_year_id}/generate-assessments/
  - Name: Generate Assessments for Academic Year
  - Description: Bulk generate assessments for academic year
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/grading/default-templates/
  - Name: List/Create Assessment Templates
  - Description: Get or create assessment templates
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grading/default-templates/{pk}/
  - Name: Template Details
  - Description: Get, update, or delete assessment template
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/grading/gradebooks/{gradebook_id}/generate-assessments/
  - Name: Generate Assessments for Gradebook
  - Description: Auto-generate assessments for gradebook from templates
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/grading/gradebooks/{gradebook_id}/preview-assessments/
  - Name: Preview Generated Assessments
  - Description: Preview assessments before generation
  - Auth: Required
  - Tenant Header: Required

#### Gradebooks

- GET|POST /api/v1/grading/academic-years/{academic_year_id}/gradebooks/
  - Name: List/Create Gradebooks
  - Description: Get or create gradebooks for academic year
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grading/gradebooks/{pk}/
  - Name: Gradebook Details
  - Description: Get, update, or delete gradebook
  - Auth: Required
  - Tenant Header: Required

#### Assessments

- GET|POST /api/v1/grading/assessment-types/
  - Name: List/Create Assessment Types
  - Description: Get or create assessment types
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grading/assessment-types/{pk}/
  - Name: Assessment Type Details
  - Description: Get, update, or delete assessment type
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grading/assessments/{pk}/
  - Name: Assessment Details
  - Description: Get, update, or delete assessment
  - Auth: Required
  - Tenant Header: Required
- GET|POST /api/v1/grading/gradebooks/{gradebook_id}/assessments/
  - Name: List/Create Assessments
  - Description: Get or create assessments for gradebook
  - Auth: Required
  - Tenant Header: Required

#### Grades

- GET|POST /api/v1/grading/assessments/{assessment_id}/grades/
  - Name: List/Create Grades
  - Description: Get or enter grades for assessment
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grading/grades/{pk}/
  - Name: Grade Details
  - Description: Get, update, or delete grade
  - Auth: Required
  - Tenant Header: Required
- PATCH /api/v1/grading/grades/{pk}/status/
  - Name: Update Grade Status
  - Description: Change grade status (draft/submitted/published)
  - Auth: Required
  - Tenant Header: Required
- PATCH /api/v1/grading/sections/{section_id}/grades-status/
  - Name: Update Section Grades Status
  - Description: Batch update status for section grades
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/grading/sections/{section_id}/grades-upload/
  - Name: Bulk Upload Grades
  - Description: Upload multiple grades via CSV/Excel
  - Auth: Required
  - Tenant Header: Required

#### Final Grades

- GET /api/v1/grading/final-grade/
  - Name: Calculate Final Grades
  - Description: Calculate and retrieve final grades
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/grading/sections/{section_id}/final-grades/
  - Name: Get Section Final Grades
  - Description: Get final grades for all students in section
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/grading/students/{student_id}/final-grades/academic-years/{academic_year_id}/
  - Name: Get Student Academic Year Grades
  - Description: Get all final grades for student for academic year
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/grading/students/{student_id}/final-grades/gradebooks/{gradebook_id}/
  - Name: Get Student Final Grade
  - Description: Get final grade for student in gradebook
  - Auth: Required
  - Tenant Header: Required

#### Grade Letters

- GET|POST /api/v1/grading/grade-letters/
  - Name: List/Create Grade Letters
  - Description: Get or configure grade letter scale
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH|DELETE /api/v1/grading/grade-letters/{pk}/
  - Name: Grade Letter Details
  - Description: Get, update, or delete grade letter configuration
  - Auth: Required
  - Tenant Header: Required

#### Rankings

- GET /api/v1/grading/rankings/
  - Name: Get Student Rankings
  - Description: Get student rankings based on grades
  - Auth: Required
  - Tenant Header: Required

#### Report Cards

- GET /api/v1/grading/students/{student_id}/final-grades/academic-years/{academic_year_id}/report-card/
  - Name: Download Report Card PDF
  - Description: Generate and download student report card PDF
  - Auth: Required
  - Tenant Header: Required

### Reports
- Generate and export various school reports

#### Reports

- GET /api/v1/reports/download/{task_id}/
  - Name: Download Report
  - Description: Download completed report file
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/reports/export-status/{task_id}/
  - Name: Check Export Status
  - Description: Check status of async report export
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/reports/finance/
  - Name: Finance Reports
  - Description: Generate financial reports
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/reports/students/
  - Name: Student Reports
  - Description: Generate student-related reports
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/reports/transactions/
  - Name: Transaction Reports
  - Description: Generate financial transaction reports
  - Auth: Required
  - Tenant Header: Required

### Settings
- School configuration and grading system settings

#### Settings

- GET|PUT|PATCH /api/v1/settings/grading-style/
  - Name: Grading Style Settings
  - Description: Configure grading style
  - Auth: Required
  - Tenant Header: Required
- GET|PUT|PATCH /api/v1/settings/grading/
  - Name: Grading Settings
  - Description: Get or update grading system settings
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/settings/grading/init/
  - Name: Initialize Grading Fixtures
  - Description: Initialize default grading configuration
  - Auth: Required
  - Tenant Header: Required
- POST /api/v1/settings/grading/regenerate/
  - Name: Regenerate Gradebooks
  - Description: Regenerate all gradebooks (async operation)
  - Auth: Required
  - Tenant Header: Required
- GET /api/v1/settings/grading/tasks/{task_id}/
  - Name: Check Grading Task Status
  - Description: Check status of async grading operations
  - Auth: Required
  - Tenant Header: Required

### Core / Tenants
- Multi-tenancy management for schools and organizations

#### Core / Tenants

- GET|POST /api/v1/tenants/
  - Name: List/Create Tenants
  - Description: Retrieve list of tenants or create new tenant
  - Auth: Required
  - Tenant Header: Not required
- GET|PUT|PATCH|DELETE /api/v1/tenants/{id}/
  - Name: Tenant Details
  - Description: Get, update, or delete a specific tenant
  - Auth: Required
  - Tenant Header: Not required
