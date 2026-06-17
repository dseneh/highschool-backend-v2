# Generated manually for historical grade period dates

from django.db import migrations, models


def backfill_period_end_dates(apps, schema_editor):
    HistoricalGradeRecord = apps.get_model("students", "HistoricalGradeRecord")
    for record in HistoricalGradeRecord.objects.select_related("academic_year").iterator():
        if record.period_end_date:
            continue
        end_date = None
        if record.academic_year_id and record.academic_year.end_date:
            end_date = record.academic_year.end_date
        elif record.created_at:
            end_date = record.created_at.date()
        if end_date:
            HistoricalGradeRecord.objects.filter(pk=record.pk).update(
                period_end_date=end_date
            )


class Migration(migrations.Migration):
    dependencies = [
        (
            "students",
            "0009_rename_historical__student_6f1a2b_idx_historical__student_df688f_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalgraderecord",
            name="period_start_date",
            field=models.DateField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="historicalgraderecord",
            name="period_end_date",
            field=models.DateField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(backfill_period_end_dates, migrations.RunPython.noop),
    ]
