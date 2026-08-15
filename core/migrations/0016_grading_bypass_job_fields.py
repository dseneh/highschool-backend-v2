from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0015_grading_bypass_operation")]

    operations = [
        migrations.AddField(
            model_name="gradingbypassoperation",
            name="request_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="gradingbypassoperation",
            name="stage",
            field=models.CharField(blank=True, default="Queued", max_length=80),
        ),
        migrations.AddField(
            model_name="gradingbypassoperation",
            name="total_students",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="gradingbypassoperation",
            name="students_processed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="gradingbypassoperation",
            name="progress_percent",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]