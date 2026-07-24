from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_tenant_billing_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS complimentary_note text NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS complimentary_note;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS complimentary_until timestamp with time zone NULL;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS complimentary_until;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenant",
                    name="complimentary_note",
                    field=models.TextField(
                        blank=True,
                        default="",
                        help_text="Optional complimentary billing note.",
                    ),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="complimentary_until",
                    field=models.DateTimeField(
                        blank=True,
                        help_text="When complimentary billing expires, if configured.",
                        null=True,
                    ),
                ),
            ],
        )
    ]