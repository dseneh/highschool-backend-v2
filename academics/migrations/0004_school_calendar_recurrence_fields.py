from django.db import migrations, models


def backfill_recurrence_pattern(apps, schema_editor):
    SchoolCalendarEvent = apps.get_model("academics", "SchoolCalendarEvent")
    for event in SchoolCalendarEvent.objects.all().iterator():
        if event.recurrence_type == "yearly":
            event.recurrence_pattern = "yearly"
        else:
            event.recurrence_pattern = "none"
        event.save(update_fields=["recurrence_pattern"])


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0003_subject_code_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="recurrence_pattern",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("yearly", "Yearly"),
                    ("weekly", "Weekly"),
                    ("monthly_day", "Monthly Day"),
                    ("monthly_first_weekday", "Monthly First Weekday"),
                    ("monthly_last_weekday", "Monthly Last Weekday"),
                ],
                default="none",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="recurrence_interval",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="recurrence_until",
            field=models.DateField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(backfill_recurrence_pattern, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="schoolcalendarevent",
            index=models.Index(
                fields=["recurrence_pattern", "start_date"],
                name="calendar_ev_recurre_6a8b0d_idx",
            ),
        ),
    ]
