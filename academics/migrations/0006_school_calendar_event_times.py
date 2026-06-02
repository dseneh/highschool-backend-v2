from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0005_school_calendar_event_schedule_visibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="end_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="start_time",
            field=models.TimeField(blank=True, null=True),
        ),
    ]
