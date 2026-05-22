import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_signup_request"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformBanner",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField(blank=True, default="")),
                ("action_url", models.CharField(blank=True, default="", max_length=500)),
                (
                    "variant",
                    models.CharField(
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
                ("dismissible", models.BooleanField(default=True)),
                (
                    "starts_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the banner becomes visible. Null = visible immediately.",
                        null=True,
                    ),
                ),
                (
                    "ends_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text="When the banner stops showing. Null = no auto-expiration.",
                        null=True,
                    ),
                ),
                (
                    "target_tenants",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="List of tenant schema_names to target. Empty = all tenants.",
                    ),
                ),
                (
                    "target_roles",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text='List of role names to target, e.g. ["admin"]. Empty = all roles.',
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_platform_banners",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "platform_banner",
                "verbose_name": "Platform Banner",
                "verbose_name_plural": "Platform Banners",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["active", "ends_at"],
                        name="platform_ba_active_8dd4f2_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PlatformBannerDismissal",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "banner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dismissals",
                        to="core.platformbanner",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="platform_banner_dismissals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "platform_banner_dismissal",
                "indexes": [
                    models.Index(
                        fields=["user", "banner"],
                        name="platform_ba_user_id_d87495_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("banner", "user"),
                        name="uniq_platform_banner_dismissal",
                    )
                ],
            },
        ),
    ]
