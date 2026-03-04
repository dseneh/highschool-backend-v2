#!/usr/bin/env bash
# auto-setup-railway.sh - Automatically set up Railway environment only when needed

set -e

echo "🔍 Checking if Railway environment setup is needed..."

# Check if superuser exists
SUPERUSER_EXISTS=$(python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
print('true' if User.objects.filter(is_superuser=True).exists() else 'false')
" 2>/dev/null || echo "false")

# Check if permissions exist
PERMISSIONS_EXIST=$(python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()
from users.models import Permission
print('true' if Permission.objects.exists() else 'false')
" 2>/dev/null || echo "false")

if [ "$SUPERUSER_EXISTS" = "true" ] && [ "$PERMISSIONS_EXIST" = "true" ]; then
    echo "✅ Environment already set up - running migrations only"
    python manage.py migrate --noinput
    echo "✅ Migrations complete"
else
    echo "🚀 First-time setup detected - running full environment setup"
    ./setup-railway-environment.sh
fi