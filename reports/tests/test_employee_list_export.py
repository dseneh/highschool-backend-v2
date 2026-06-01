"""Tests for employee list export grouping."""

from django.test import SimpleTestCase

from reports.services.employee_list_export import build_grouped_employee_export_rows


class EmployeeListExportTests(SimpleTestCase):
    def test_build_grouped_rows_by_department(self):
        results = [
            {
                "employee_id": "E1",
                "full_name": "Alice",
                "email": "",
                "phone": "",
                "gender": "",
                "department": "Finance",
                "position": "Accountant",
                "manager": "",
                "employment_status": "Active",
                "role": "Staff",
                "payroll_ready": "Yes",
                "hire_date": "",
                "job_title": "",
            },
            {
                "employee_id": "E2",
                "full_name": "Bob",
                "email": "",
                "phone": "",
                "gender": "",
                "department": "Finance",
                "position": "Clerk",
                "manager": "",
                "employment_status": "Active",
                "role": "Staff",
                "payroll_ready": "No",
                "hire_date": "",
                "job_title": "",
            },
        ]

        rows = build_grouped_employee_export_rows(results, group_by="department")
        self.assertEqual(rows[0][0], "Finance (2 employees)")
        self.assertEqual(rows[1][0], "E1")
        self.assertEqual(rows[2][0], "E2")
        self.assertEqual(rows[3][0], "Subtotal — 2 employees")

    def test_build_flat_rows_when_not_grouped(self):
        results = [
            {
                "employee_id": "E1",
                "full_name": "Alice",
                "email": "a@example.com",
                "phone": "",
                "gender": "",
                "department": "",
                "position": "",
                "manager": "",
                "employment_status": "",
                "role": "",
                "payroll_ready": "",
                "hire_date": "",
                "job_title": "",
            }
        ]
        rows = build_grouped_employee_export_rows(results, group_by="none")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "E1")
        self.assertEqual(rows[0][1], "Alice")
