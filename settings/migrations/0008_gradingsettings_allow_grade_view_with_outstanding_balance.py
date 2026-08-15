from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("settings", "0007_default_section_capacity")]

    operations = [
        migrations.AddField(
            model_name="gradingsettings",
            name="allow_grade_view_with_outstanding_balance",
            field=models.BooleanField(
                default=True,
                help_text="Allow students and non-privileged viewers to access grades when the current-year balance is outstanding.",
            ),
        ),
    ]