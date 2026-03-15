# Generated manually for table rename alignment.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0009_gradebookscheduleprojection_and_more"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="schoolcalendarsettings",
            table="calendar_settings",
        ),
        migrations.AlterModelTable(
            name="schoolcalendarevent",
            table="calendar_event",
        ),
        migrations.AlterModelTable(
            name="schoolcalendareventoccurrence",
            table="calendar_event_occurrence",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE IF EXISTS school_calendar_event_sections RENAME TO calendar_event_sections;",
            reverse_sql="ALTER TABLE IF EXISTS calendar_event_sections RENAME TO school_calendar_event_sections;",
        ),
        migrations.AlterField(
            model_name="schoolcalendarevent",
            name="sections",
            field=models.ManyToManyField(
                blank=True,
                db_table="calendar_event_sections",
                related_name="calendar_events",
                to="academics.section",
            ),
        ),
    ]
