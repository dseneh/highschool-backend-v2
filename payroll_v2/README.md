# Payroll v2

Tenant payroll engine using `hr.Employee` and `payroll_v2` models.

## Install

1. Add `payroll_v2` to `INSTALLED_APPS`.
2. Include URLs:

```py
path("api/v1/payroll-v2/", include("payroll_v2.urls")),
path("api/v1/payroll/settings/", PayrollSettingsView.as_view()),
```

3. Run migrations:

```bash
python manage.py migrate payroll_v2
python manage.py migrate hr
python manage.py migrate accounting
```

## Main design

```txt
PaySchedule / PayrollPeriod = cadence and periods
EmployeeCompensation = salary/hourly/daily source of truth
PayrollCatalogItem = allowance, deduction, tax definitions
PayrollCatalogItemRule = bracket/formula rules on catalog items
EmployeePayrollItem = employee-specific overrides
PayrollRunRecord = payroll run for a period
PayrollEmployeeItem = employee row inside a run
PayrollLineItem = generated immutable result lines
PayrollTableView = saved run review table layout
PayrollPayslipTemplate = saved paystub layout
PayrollSettings = tenant accounting + paystub options
```

## API endpoints

```txt
/api/v1/payroll-v2/pay-schedules/
/api/v1/payroll-v2/payroll-periods/
/api/v1/payroll-v2/compensations/
/api/v1/payroll-v2/items/
/api/v1/payroll-v2/item-rules/
/api/v1/payroll-v2/employee-items/
/api/v1/payroll-v2/runs/
/api/v1/payroll-v2/employee-run-items/
/api/v1/payroll-v2/table-views/
/api/v1/payroll-v2/payslip-templates/
/api/v1/payroll-v2/settings/
/api/v1/payroll/settings/          # legacy alias
```
