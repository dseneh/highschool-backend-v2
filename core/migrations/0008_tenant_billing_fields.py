from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_platform_banner"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="billing_employee_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="tenant",
            name="billing_enrollment_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="tenant",
            name="billing_interval",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Stripe subscription interval: month or year.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="complimentary_note",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Internal note for complimentary access (e.g. pilot partner thank-you period).",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="complimentary_until",
            field=models.DateTimeField(
                blank=True,
                help_text="Pilot/partner grace: full access without Stripe billing until this datetime (UTC).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="current_period_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="enabled_addons",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Active paid add-ons, e.g. ["payroll", "sms"].',
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="past_due_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="promotion_code_redeemed",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="tenant",
            name="stripe_customer_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="tenant",
            name="stripe_subscription_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="tenant",
            name="subscription_status",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
