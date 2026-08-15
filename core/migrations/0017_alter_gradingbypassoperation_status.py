from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0016_grading_bypass_job_fields")]

    operations = [
        migrations.AlterField(
            model_name="gradingbypassoperation",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("in_progress", "In progress"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
