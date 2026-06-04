from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0006_alter_enrollment_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="enrollment",
            name="year_end_outcome",
            field=models.CharField(
                blank=True,
                choices=[
                    ("promoted", "Promoted"),
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
