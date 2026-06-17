from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings", "0005_transcript_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="gradingsettings",
            name="transcript_primary_signatory_position",
            field=models.CharField(
                default="Principal",
                help_text="Employee position title used for the first transcript signatory",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="gradingsettings",
            name="transcript_secondary_signatory_position",
            field=models.CharField(
                default="Registrar",
                help_text="Employee position title used for the second transcript signatory",
                max_length=100,
            ),
        ),
    ]
