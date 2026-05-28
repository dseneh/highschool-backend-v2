from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Legacy bridge migration — pay schedule FKs are added in 0005."""

    dependencies = [
        ("payroll_v2", "0003_employeepayrollitem_calculation_overridden"),
    ]

    operations = []
