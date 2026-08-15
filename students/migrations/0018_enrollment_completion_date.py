from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("students", "0017_discipline_attendance_effects")]

    operations = [
        migrations.AddField(
            model_name="enrollment",
            name="completion_date",
            field=models.DateField(blank=True, default=None, null=True),
        ),
    ]