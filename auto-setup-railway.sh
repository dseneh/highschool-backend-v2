#!/usr/bin/env bash
# auto-setup-railway.sh - Automatically set up Railway environment only when needed

set -ex  # Exit on error, show commands

echo ""
echo "###############################################"
echo "RELEASE PHASE: Starting setup/migrations"
echo "###############################################"
echo ""

# Step 1: Create migrations if they don't exist
echo "Step 1: Creating migrations from models..."
python manage.py makemigrations --noinput
echo "✅ Step 1 complete"
echo ""

# Step 2: Shared schema migrations
echo "Step 2: Running migrate_schemas --shared..."
python manage.py migrate_schemas --shared --noinput
echo "✅ Step 2 complete"
echo ""

# Step 3: Check if superuser exists
echo "Step 3: Checking if already initialized..."
SUPERUSER_EXISTS=$(python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
print('true' if User.objects.filter(role='superadmin').exists() else 'false')
" 2>&1 || echo "false")

echo "Superuser exists: $SUPERUSER_EXISTS"
echo ""

# Step 4: Tenant migrations
if [ "$SUPERUSER_EXISTS" = "true" ]; then
    echo "Step 4: Already initialized - running tenant migrations only..."
    python manage.py migrate_schemas --noinput
    python manage.py collectstatic --noinput --clear
    echo "✅ Step 4 complete"
else
    echo "Step 4: First-time setup - running full setup..."
    bash -x ./setup-railway-environment.sh
    echo "✅ Step 4 complete"
fi

echo ""
echo "###############################################"
echo "SETUP COMPLETE"
echo "###############################################"
echo ""