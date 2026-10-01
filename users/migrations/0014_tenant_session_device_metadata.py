from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0013_accountsetupchallenge_parentlinkrequest_and_more")]

    operations = [
        # Some existing databases already have this required column from an
        # earlier schema. Preserve its contents while bringing migration state
        # and fresh installations into agreement. The DB default also supports
        # older application processes during a rolling deployment.
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                    ALTER TABLE auth_tenant_session
                    ADD COLUMN IF NOT EXISTS device_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
                    ALTER TABLE auth_tenant_session
                    ALTER COLUMN device_metadata SET DEFAULT '{}'::jsonb;
                """,
                reverse_sql=migrations.RunSQL.noop,
            )],
            state_operations=[migrations.AddField(
                model_name="tenantsession",
                name="device_metadata",
                field=models.JSONField(default=dict, db_default={}, blank=True),
            )],
        ),
    ]
