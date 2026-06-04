from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="gradingsettings",
            name="allow_year_closure",
            field=models.BooleanField(
                default=True,
                help_text="Allow year-end closure and promotion actions from the enrollment workspace",
            ),
        ),
        migrations.AddField(
            model_name="gradingsettings",
            name="year_closure_min_overall_average",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=None,
                help_text="Minimum overall grade average (%) required to promote at year-end; blank = no minimum",
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="gradingsettings",
            name="year_closure_require_approved_grades",
            field=models.BooleanField(
                default=True,
                help_text="When checking promotion averages, only include approved grades",
            ),
        ),
        migrations.AddField(
            model_name="gradingsettings",
            name="allow_mid_year_promotion",
            field=models.BooleanField(
                default=False,
                help_text="Allow promoting students to the next grade during the school year without closing the year",
            ),
        ),
        migrations.AddField(
            model_name="gradingsettings",
            name="mid_year_promotion_min_overall_average",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=None,
                help_text="Minimum overall average (%) for mid-year promotion; blank = use year-end minimum or none",
                max_digits=5,
                null=True,
            ),
        ),
    ]
