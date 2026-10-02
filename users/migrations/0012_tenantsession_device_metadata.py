from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0011_email_mfa_challenge")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                    ALTER TABLE auth_tenant_session
                    ADD COLUMN IF NOT EXISTS device_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
                """,
                reverse_sql=migrations.RunSQL.noop,
            )],
            state_operations=[migrations.AddField(
                model_name="tenantsession",
                name="device_metadata",
                field=models.JSONField(blank=True, default=dict),
            )],
        ),
    ]
