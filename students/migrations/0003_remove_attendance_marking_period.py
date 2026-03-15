from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0002_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="attendance",
            name="marking_period",
        ),
    ]
