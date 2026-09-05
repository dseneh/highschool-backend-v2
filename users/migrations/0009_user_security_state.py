from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0008_merge_role_and_rbac_histories")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="security_version",
            field=models.PositiveBigIntegerField(default=1),
        ),
    ]
