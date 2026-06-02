from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0004_school_calendar_recurrence_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="schedule_visibility",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("students", "Students"),
                    ("teachers", "Teachers"),
                    ("both", "Students and Teachers"),
                ],
                default="both",
                max_length=20,
            ),
        ),
    ]
