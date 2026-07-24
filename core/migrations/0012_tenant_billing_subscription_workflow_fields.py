from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_tenant_enabled_addons"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS current_period_end timestamp with time zone NULL;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS current_period_end;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS past_due_since timestamp with time zone NULL;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS past_due_since;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS promotion_code_redeemed varchar(100) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS promotion_code_redeemed;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS stripe_customer_id varchar(255) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS stripe_customer_id;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS stripe_subscription_id varchar(255) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS stripe_subscription_id;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS subscription_status varchar(50) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS subscription_status;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS provisioning_status varchar(50) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS provisioning_status;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS provisioning_step varchar(100) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS provisioning_step;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS provisioning_progress smallint NOT NULL DEFAULT 0;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS provisioning_progress;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS provisioning_error text NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS provisioning_error;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS provisioning_completed_steps jsonb NOT NULL DEFAULT '[]'::jsonb;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS provisioning_completed_steps;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS provisioning_payload jsonb NOT NULL DEFAULT '{}'::jsonb;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS provisioning_payload;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS deletion_status varchar(50) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS deletion_status;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS deletion_mode varchar(50) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS deletion_mode;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS deletion_step varchar(100) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS deletion_step;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS deletion_progress smallint NOT NULL DEFAULT 0;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS deletion_progress;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS deletion_error text NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS deletion_error;",
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE tenant ADD COLUMN IF NOT EXISTS deletion_completed_steps jsonb NOT NULL DEFAULT '[]'::jsonb;",
                    reverse_sql="ALTER TABLE tenant DROP COLUMN IF EXISTS deletion_completed_steps;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenant",
                    name="current_period_end",
                    field=models.DateTimeField(blank=True, help_text="Current subscription period end, if applicable.", null=True),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="past_due_since",
                    field=models.DateTimeField(blank=True, help_text="When the tenant first became past due, if applicable.", null=True),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="promotion_code_redeemed",
                    field=models.CharField(blank=True, default="", help_text="Promotion code redeemed for the tenant, if any.", max_length=100),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="stripe_customer_id",
                    field=models.CharField(blank=True, default="", help_text="Stripe customer identifier.", max_length=255),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="stripe_subscription_id",
                    field=models.CharField(blank=True, default="", help_text="Stripe subscription identifier.", max_length=255),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="subscription_status",
                    field=models.CharField(blank=True, default="", help_text="Stripe subscription status.", max_length=50),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="provisioning_status",
                    field=models.CharField(blank=True, default="", help_text="Workspace provisioning status.", max_length=50),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="provisioning_step",
                    field=models.CharField(blank=True, default="", help_text="Current provisioning step.", max_length=100),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="provisioning_progress",
                    field=models.SmallIntegerField(default=0, help_text="Provisioning progress percentage."),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="provisioning_error",
                    field=models.TextField(blank=True, default="", help_text="Latest provisioning error message."),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="provisioning_completed_steps",
                    field=models.JSONField(blank=True, default=list, help_text="List of completed provisioning steps."),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="provisioning_payload",
                    field=models.JSONField(blank=True, default=dict, help_text="Payload captured for provisioning."),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="deletion_status",
                    field=models.CharField(blank=True, default="", help_text="Deletion lifecycle status.", max_length=50),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="deletion_mode",
                    field=models.CharField(blank=True, default="", help_text="Deletion mode for the tenant.", max_length=50),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="deletion_step",
                    field=models.CharField(blank=True, default="", help_text="Current deletion step.", max_length=100),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="deletion_progress",
                    field=models.SmallIntegerField(default=0, help_text="Deletion progress percentage."),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="deletion_error",
                    field=models.TextField(blank=True, default="", help_text="Latest deletion error message."),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="deletion_completed_steps",
                    field=models.JSONField(blank=True, default=list, help_text="List of completed deletion steps."),
                ),
            ],
        )
    ]