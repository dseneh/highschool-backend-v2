# Generated migration for tenant restore execution lifecycle phase

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backups', '0003_tenant_restore_runtime_snapshot'),
    ]

    operations = [
        # Add execution_pending to the status choices
        migrations.AlterField(
            model_name='tenantrestorerequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('requested', 'Requested'),
                    ('safety_backup_pending', 'Safety backup pending'),
                    ('ready_for_approval', 'Ready for approval'),
                    ('approved', 'Approved'),
                    ('execution_pending', 'Execution pending'),
                    ('restoring', 'Restoring'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('rejected', 'Rejected'),
                    ('cancelled', 'Cancelled'),
                ],
                db_index=True,
                default='requested',
                max_length=30
            ),
        ),
    ]

