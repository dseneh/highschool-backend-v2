from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationcampaign",
            name="deliver_banner",
            field=models.BooleanField(
                default=False,
                help_text="If true, emit this campaign as a header banner for recipients.",
            ),
        ),
        migrations.AddField(
            model_name="notificationcampaign",
            name="banner_variant",
            field=models.CharField(
                blank=True,
                choices=[
                    ("info", "Info"),
                    ("warning", "Warning"),
                    ("error", "Error"),
                    ("success", "Success"),
                ],
                default="info",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="notificationcampaign",
            name="banner_dismissible",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "If false, users cannot manually dismiss this banner "
                    "(it only goes away after banner_ends_at)."
                ),
            ),
        ),
        migrations.AddField(
            model_name="notificationcampaign",
            name="banner_starts_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When the banner becomes visible. Null = visible immediately.",
            ),
        ),
        migrations.AddField(
            model_name="notificationcampaign",
            name="banner_ends_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                help_text="When the banner stops showing. Null = no auto-expiration.",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="banner_dismissed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When this user dismissed the banner channel (if any).",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["recipient", "banner_dismissed_at"],
                name="notificatio_recipie_b7cc05_idx",
            ),
        ),
    ]
