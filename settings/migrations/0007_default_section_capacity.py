from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings", "0006_transcript_signatory_positions"),
    ]

    operations = [
        migrations.AddField(
            model_name="gradingsettings",
            name="default_section_capacity",
            field=models.PositiveIntegerField(
                default=25,
                help_text="Default maximum number of students in a section when no capacity is set",
            ),
        ),
    ]