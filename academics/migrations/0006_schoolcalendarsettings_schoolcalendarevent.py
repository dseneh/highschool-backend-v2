import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0005_sectionschedule_section_time_slot_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SchoolCalendarSettings",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("operating_days", models.JSONField(default=list)),
                ("timezone", models.CharField(default="UTC", max_length=100)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_schoolcalendarsettings_set", to="users.user"),
                ),
                (
                    "updated_by",
                    models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_schoolcalendarsettings_set", to="users.user"),
                ),
            ],
            options={
                "verbose_name": "School Calendar Settings",
                "verbose_name_plural": "School Calendar Settings",
                "db_table": "school_calendar_settings",
            },
        ),
        migrations.CreateModel(
            name="SchoolCalendarEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True, default=None, null=True)),
                ("event_type", models.CharField(choices=[("holiday", "Holiday"), ("non_school_day", "Non-school Day"), ("special_day", "Special Day"), ("schedule_override", "Schedule Override")], default="holiday", max_length=30)),
                ("recurrence_type", models.CharField(choices=[("none", "None"), ("yearly", "Yearly")], default="none", max_length=20)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("all_day", models.BooleanField(default=True)),
                ("applies_to_all_sections", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_schoolcalendarevent_set", to="users.user"),
                ),
                (
                    "updated_by",
                    models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_schoolcalendarevent_set", to="users.user"),
                ),
            ],
            options={
                "db_table": "school_calendar_event",
                "ordering": ["start_date", "name"],
            },
        ),
        migrations.AddField(
            model_name="schoolcalendarevent",
            name="sections",
            field=models.ManyToManyField(blank=True, related_name="calendar_events", to="academics.section"),
        ),
        migrations.AddIndex(
            model_name="schoolcalendarevent",
            index=models.Index(fields=["event_type", "start_date", "end_date"], name="school_cale_event_t_d0bc87_idx"),
        ),
        migrations.AddIndex(
            model_name="schoolcalendarevent",
            index=models.Index(fields=["recurrence_type", "start_date"], name="school_cale_recurre_7378fb_idx"),
        ),
    ]