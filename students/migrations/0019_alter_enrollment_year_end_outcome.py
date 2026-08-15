from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("students", "0018_enrollment_completion_date")]

    operations = [
        migrations.AlterField(
            model_name="enrollment",
            name="year_end_outcome",
            field=models.CharField(
                blank=True,
                choices=[
                    ("promoted", "Promoted"),
                    ("double_promoted", "Double_promoted"),
                    ("repeated", "Repeated"),
                    ("graduated", "Graduated"),
                    ("withdrawn", "Withdrawn"),
                    ("transferred", "Transferred"),
                ],
                default=None,
                max_length=20,
                null=True,
            ),
        ),
    ]