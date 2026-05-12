from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0002_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="student",
            name="id_number",
            field=models.CharField(
                db_index=True,
                editable=False,
                max_length=20,
                unique=True,
                validators=[django.core.validators.RegexValidator(r"^\d+$")],
            ),
        ),
    ]
