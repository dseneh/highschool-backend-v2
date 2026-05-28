from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0010_alter_employee_pay_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="leavetype",
            name="include_on_paystub",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, this leave type appears on employee paystubs.",
            ),
        ),
    ]
