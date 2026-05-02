from django.contrib import admin

from .models import (
    PayrollItem,
    PayrollItemType,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PaySchedule,
    TaxRule,
)

admin.site.register(PaySchedule)
admin.site.register(PayrollPeriod)
admin.site.register(PayrollRun)
admin.site.register(Payslip)
admin.site.register(PayrollItem)
admin.site.register(PayrollItemType)
admin.site.register(TaxRule)
