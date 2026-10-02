from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_platformauthappearance"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformauthappearance",
            name="background_settings",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
