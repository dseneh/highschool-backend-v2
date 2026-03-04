#!/usr/bin/env bash
# auto-setup-railway.sh - Automatically set up Railway environment only when needed

# CRITICAL: Write to both stdout and stderr to ensure output is visible
exec 1> >(tee -a /tmp/release.log)
exec 2>&1
set -ex  # Added -x for verbose output

echo "==============================================="
echo "RELEASE PHASE STARTED"
echo "==============================================="
env | grep -E "DATABASE_URL|SECRET_KEY|DJANGO|RAILWAY" || true
echo ""

# CRITICAL: Run shared schema migrations FIRST (creates public schema and tables)
echo "📦 Step 1: Running shared schema migrations..."
python manage.py migrate_schemas --shared --noinput
echo "✅ Shared schema migrations complete"
echo ""

# Check if superuser exists (now that migrations are done)
echo "Checking if superuser and permissions exist..."
SUPERUSER_EXISTS=$(python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
print('true' if User.objects.filter(is_superuser=True).exists() else 'false')
" 2>&1 || echo "false")

# Check if permissions exist
PERMISSIONS_EXIST=$(python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()
from users.models import Permission
print('true' if Permission.objects.exists() else 'false')
" 2>&1 || echo "false")

echo "Superuser exists: $SUPERUSER_EXISTS"
echo "Permissions exist: $PERMISSIONS_EXIST"
echo ""

if [ "$SUPERUSER_EXISTS" = "true" ] && [ "$PERMISSIONS_EXIST" = "true" ]; then
    echo "✅ Superuser and permissions already exist - running tenant migrations only"
    python manage.py migrate_schemas --noinput
    python manage.py collectstatic --noinput --clear
    echo "✅ Migration and static files complete"
else
    echo "🚀 First-time setup detected - running full environment setup"
    bash -x ./setup-railway-environment.sh
fi

echo "🎉 Auto-setup complete!"