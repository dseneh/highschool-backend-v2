"""
HR app models - Phase 6-7 implementation (payroll, contracts, workforce).
"""

from django.db import models
from common.models import BaseModel


class PayrollRun(BaseModel):
    """
    Payroll run model (stub for accounting posting bridge).
    
    Full implementation is Phase 6 work. This stub allows accounting app
    models to reference hr.PayrollRun without breaking Django's app registry.
    """

    name = models.CharField(max_length=255)
    run_date = models.DateField()

    class Meta:
        db_table = "hr_payroll_run"
        verbose_name = "Payroll Run"
        verbose_name_plural = "Payroll Runs"

    def __str__(self):
        return f"{self.name} - {self.run_date}"
