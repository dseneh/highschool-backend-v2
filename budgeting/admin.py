from django.contrib import admin

from .models import (
    Budget, BudgetEnrollmentAssumption, BudgetLifecycleEvent, BudgetLine,
    BudgetLinePeriod, BudgetRevision, BudgetRevisionLineDelta, BudgetSection,
)

admin.site.register([
    Budget, BudgetSection, BudgetLine, BudgetLinePeriod,
    BudgetEnrollmentAssumption, BudgetRevision, BudgetRevisionLineDelta,
    BudgetLifecycleEvent,
])
