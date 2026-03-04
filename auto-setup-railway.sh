#!/usr/bin/env bash
# auto-setup-railway.sh - Automatically set up Railway environment only when needed

set -ex  # Exit on error, show commands

echo ""
echo "###############################################"
echo "RELEASE PHASE: Starting setup/migrations"
echo "###############################################"
echo ""

# Step 1: Shared schema migrations
echo "Step 1: Running migrate_schemas --shared..."
python manage.py migrate_schemas --shared --noinput
echo "✅ Step 1 complete"
echo ""

# Step 2: Check if superuser exists
echo "Step 2: Checking if already initialized..."
SUPERUSER_EXISTS=$(python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
print('true' if User.objects.filter(is_superuser=True).exists() else 'false')
" 2>&1 || echo "false")

echo "Superuser exists: $SUPERUSER_EXISTS"
echo ""

# Step 3: Tenant migrations
if [ "$SUPERUSER_EXISTS" = "true" ]; then
    echo "Step 3: Already initialized - running tenant migrations only..."
    python manage.py migrate_schemas --noinput
    python manage.py collectstatic --noinput --clear
    echo "✅ Step 3 complete"
else
    echo "Step 3: First-time setup - running full setup..."
    bash -x ./setup-railway-environment.sh
    echo "✅ Step 3 complete"
fi

echo ""
echo "###############################################"
echo "SETUP COMPLETE"
echo "###############################################"
echo ""