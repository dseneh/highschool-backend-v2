from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="subject",
            name="code",
            field=models.CharField(
                blank=True,
                db_index=True,
                default=None,
                max_length=30,
                null=True,
            ),
        ),
    ]
