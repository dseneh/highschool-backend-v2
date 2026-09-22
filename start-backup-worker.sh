#!/usr/bin/env bash
set -euo pipefail

echo "Validating tenant backup worker runtime..."
python manage.py check_backup_runtime --mode backup --require-object-storage

echo "Starting tenant backup worker..."
exec python -u manage.py process_tenant_backups --poll-seconds "${TENANT_BACKUP_POLL_SECONDS:-10}"
