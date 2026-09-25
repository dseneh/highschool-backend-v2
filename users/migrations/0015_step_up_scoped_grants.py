from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0014_step_up_mfa")]

    operations = [
        migrations.AddField(
            model_name="stepupauthorization",
            name="session_binding",
            field=models.CharField(db_index=True, default="legacy", max_length=128),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="stepupauthorization",
            name="security_version",
            field=models.PositiveBigIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="stepupauthorization",
            name="reusable",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="stepupauthorization",
            name="last_used_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stepupauthorization",
            name="use_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
