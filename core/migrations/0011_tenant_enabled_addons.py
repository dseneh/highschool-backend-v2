from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_tenant_complimentary_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS enabled_addons jsonb NOT NULL DEFAULT '[]'::jsonb;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS enabled_addons;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenant",
                    name="enabled_addons",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Enabled tenant add-ons stored as a JSON array.",
                    ),
                ),
            ],
        )
    ]