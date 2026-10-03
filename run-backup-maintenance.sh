#!/usr/bin/env bash
set -euo pipefail

echo "Validating tenant backup maintenance runtime..."
python manage.py check_backup_runtime --mode maintenance --require-object-storage

echo "Running tenant backup maintenance..."
exec python -u manage.py maintain_tenant_backups
