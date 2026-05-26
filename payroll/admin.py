from django.contrib import admin

from .models import (
    PayrollItem,
    PayrollItemType,
    PayrollItemTypeRule,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PaySchedule,
    TaxAmountRule,
    TaxRule,
)

admin.site.register(PaySchedule)
admin.site.register(PayrollPeriod)
admin.site.register(PayrollRun)
admin.site.register(Payslip)
admin.site.register(PayrollItem)
admin.site.register(PayrollItemType)
admin.site.register(PayrollItemTypeRule)
admin.site.register(TaxRule)
admin.site.register(TaxAmountRule)
