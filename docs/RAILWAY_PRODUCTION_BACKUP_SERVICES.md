# Railway production backup and restore services

Backup and restore processing must run separately from the web service. Create
the following services in the **production** Railway environment from the same
repository and branch as the production API.

| Railway service | Start command | Runtime |
| --- | --- | --- |
| `backup-worker` | `./start-backup-worker.sh` | Always running |
| `restore-worker` | `./start-restore-worker.sh` | Always running |
| `backup-maintenance` | `./run-backup-maintenance.sh` | Cron: `0 * * * *` |

Do not point production services at staging resources. All three services must
reference the production PostgreSQL service. Use a production-only R2 backup
bucket and production-only R2 credentials.

## Required production variables

Set these variables on the three services through a Railway shared variable
group or references to the production API variables:

```text
DATABASE_URL=<reference to production PostgreSQL DATABASE_URL>
SECRET_KEY=<reference to production API SECRET_KEY>
DEBUG=False
USE_S3_STORAGE=True

R2_BUCKET=<production media bucket>
R2_ACCESS_KEY_ID=<production media credential>
R2_SECRET_ACCESS_KEY=<production media credential>
R2_S3_ENDPOINT=https://<cloudflare-account-id>.r2.cloudflarestorage.com

R2_BACKUP_BUCKET=<production-only backup bucket>
R2_BACKUP_ACCESS_KEY_ID=<production backup credential>
R2_BACKUP_SECRET_ACCESS_KEY=<production backup credential>
R2_BACKUP_S3_ENDPOINT=https://<cloudflare-account-id>.r2.cloudflarestorage.com

TENANT_BACKUP_SCHEDULE_ENABLED=True
TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS=24
TENANT_BACKUP_RETENTION_MANUAL_DAYS=30
TENANT_BACKUP_RETENTION_SCHEDULED_DAYS=30
TENANT_BACKUP_RETENTION_PRE_RESTORE_DAYS=90
TENANT_BACKUP_RETENTION_SYSTEM_DAYS=30
```

Optional polling variables:

```text
TENANT_BACKUP_POLL_SECONDS=10
TENANT_RESTORE_POLL_SECONDS=10
```

The worker startup scripts deliberately fail when PostgreSQL archive tools,
database access, or object storage are missing. This prevents a deployment from
appearing healthy while queued backups or restores cannot be processed.

## Production activation checklist

1. Deploy the API and run migrations.
2. Deploy `backup-worker` and confirm runtime validation passes.
3. Deploy `restore-worker` and confirm runtime validation passes.
4. Configure `backup-maintenance` with the hourly cron schedule.
5. Request a manual backup for a noncritical tenant and confirm it becomes
   `available` in the production R2 backup bucket.
6. Restore that archive into an approved noncritical tenant and verify the
   tenant is unlocked after completion.
7. Confirm a scheduled backup is queued and processed within 24 hours.
