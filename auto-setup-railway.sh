#!/usr/bin/env bash
# auto-setup-railway.sh - Automatically set up Railway environment only when needed

set -ex  # Added -x for verbose output

echo "🔍 Checking if Railway environment setup is needed..."
echo "DATABASE_URL is set: $([ -z "$DATABASE_URL" ] && echo 'NO' || echo 'YES')"
echo "SECRET_KEY is set: $([ -z "$SECRET_KEY" ] && echo 'NO' || echo 'YES')"
echo ""

# Check if superuser exists
echo "Attempting Django setup to check for existing superuser..."
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
echo "Checking if permissions exist..."
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
    echo "✅ Environment already set up - running migrations only"
    python manage.py migrate_schemas
    python manage.py collectstatic --noinput --clear
    echo "✅ Migrations and static files updated"
else
    echo "🚀 First-time setup detected - running full environment setup"
    bash -x ./setup-railway-environment.sh
fi