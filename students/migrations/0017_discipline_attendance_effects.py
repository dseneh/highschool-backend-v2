import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("students", "0016_disciplinaryactiontype_action_outcome"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="disciplinaryactiontype",
            name="attendance_effect_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="disciplinaryactiontype",
            name="attendance_effect_status",
            field=models.CharField(
                choices=[
                    ("present", "Present"),
                    ("absent", "Absent"),
                    ("late", "Late"),
                    ("excused", "Excused"),
                    ("sick", "Sick"),
                    ("on_leave", "On_leave"),
                    ("holiday", "Holiday"),
                ],
                default="absent",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="DisciplinaryAttendanceImpact",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("effective_date", models.DateField()),
                (
                    "original_status",
                    models.CharField(blank=True, default=None, max_length=20, null=True),
                ),
                (
                    "applied_status",
                    models.CharField(
                        choices=[
                            ("present", "Present"),
                            ("absent", "Absent"),
                            ("late", "Late"),
                            ("excused", "Excused"),
                            ("sick", "Sick"),
                            ("on_leave", "On_leave"),
                            ("holiday", "Holiday"),
                        ],
                        max_length=20,
                    ),
                ),
                ("was_created", models.BooleanField(default=False)),
                (
                    "resolution",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("restored", "Restored"),
                            ("kept", "Kept"),
                            ("deleted", "Deleted"),
                        ],
                        default="pending",
                        max_length=12,
                    ),
                ),
                (
                    "resolved_at",
                    models.DateTimeField(blank=True, default=None, null=True),
                ),
                (
                    "attendance",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="discipline_impacts",
                        to="students.attendance",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_%(class)s_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "discipline_action",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_impacts",
                        to="students.studentdisciplinaryaction",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_%(class)s_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Disciplinary Attendance Impact",
                "verbose_name_plural": "Disciplinary Attendance Impacts",
                "db_table": "disciplinary_attendance_impact",
                "ordering": ["effective_date", "created_at"],
                "unique_together": {("discipline_action", "effective_date")},
            },
        ),
        migrations.AddIndex(
            model_name="disciplinaryattendanceimpact",
            index=models.Index(
                fields=["discipline_action", "effective_date"],
                name="disciplinar_discipl_d00623_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="disciplinaryattendanceimpact",
            index=models.Index(fields=["resolution"], name="disciplinar_resolut_d01151_idx"),
        ),
    ]
