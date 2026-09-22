#!/usr/bin/env bash
set -euo pipefail

echo "Validating tenant restore worker runtime..."
python manage.py check_backup_runtime --mode restore --require-object-storage

echo "Starting tenant restore worker..."
exec python -u manage.py process_tenant_restores --poll-seconds "${TENANT_RESTORE_POLL_SECONDS:-10}"
