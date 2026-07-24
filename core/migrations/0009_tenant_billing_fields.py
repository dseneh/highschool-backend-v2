from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_tenant_onboarding"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS billing_employee_count integer NOT NULL DEFAULT 0;"
                    ),
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS billing_employee_count;",
                ),
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS billing_enrollment_count integer NOT NULL DEFAULT 0;"
                    ),
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS billing_enrollment_count;",
                ),
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS billing_interval varchar(20) NOT NULL DEFAULT '';"
                    ),
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS billing_interval;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenant",
                    name="billing_employee_count",
                    field=models.IntegerField(
                        default=0,
                        help_text="Expected employee count used for billing defaults.",
                    ),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="billing_enrollment_count",
                    field=models.IntegerField(
                        default=0,
                        help_text="Expected enrollment count used for billing defaults.",
                    ),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="billing_interval",
                    field=models.CharField(
                        max_length=20,
                        blank=True,
                        default="",
                        help_text="Billing interval label, if configured.",
                    ),
                ),
            ],
        )
    ]