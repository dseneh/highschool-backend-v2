import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0008_academic_year_type_and_optional_dates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("students", "0007_enrollment_year_end_outcome"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalGradeRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("meta", models.JSONField(blank=True, default=dict)),
                ("institution_name", models.CharField(max_length=255)),
                ("academic_year_label", models.CharField(help_text='Display label, e.g. "2024-2025".', max_length=50)),
                ("subject_name", models.CharField(max_length=255)),
                ("final_percentage", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("final_letter", models.CharField(blank=True, max_length=10, null=True)),
                ("credits", models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ("include_in_rankings", models.BooleanField(default=False)),
                ("include_in_honor_roll", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True, null=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("verified", "Verified")], db_index=True, default="draft", max_length=16)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("academic_year", models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="historical_grade_records", to="academics.academicyear")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("grade_level", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="historical_grade_records", to="academics.gradelevel")),
                ("marking_period", models.ForeignKey(blank=True, default=None, help_text="Only for mid-year transfer credit on regular years.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="historical_grade_records", to="academics.markingperiod")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="historical_grade_records", to="students.student")),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="historical_grade_records", to="academics.subject")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("verified_by", models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="verified_historical_grades", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "historical_grade_record",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="historicalgraderecord",
            index=models.Index(fields=["student", "status"], name="historical__student_6f1a2b_idx"),
        ),
        migrations.AddIndex(
            model_name="historicalgraderecord",
            index=models.Index(fields=["academic_year"], name="historical__academi_7c3d4e_idx"),
        ),
        migrations.AddIndex(
            model_name="historicalgraderecord",
            index=models.Index(fields=["grade_level", "subject"], name="historical__grade_l_8e5f6a_idx"),
        ),
        migrations.AddConstraint(
            model_name="historicalgraderecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(("marking_period__isnull", True)),
                fields=("student", "institution_name", "academic_year_label", "grade_level", "subject"),
                name="unique_historical_grade_full_year",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicalgraderecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(("marking_period__isnull", False)),
                fields=("student", "institution_name", "academic_year_label", "grade_level", "subject", "marking_period"),
                name="unique_historical_grade_with_period",
            ),
        ),
    ]
