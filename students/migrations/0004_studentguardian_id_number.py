from django.core.validators import RegexValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0003_student_id_number_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="studentguardian",
            name="id_number",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=20,
                null=True,
                unique=True,
                validators=[RegexValidator("^\\d+$")],
            ),
        ),
    ]
