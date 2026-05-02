#!/usr/bin/env bash
# setup-railway-environment.sh - First-time Railway deployment setup
# Creates public tenant, superuser, and loads default data

set -eo pipefail  # Exit on error, fail on pipe errors

echo "🚀 Setting up Railway environment (first-time deployment)"
echo "========================================================="

# Step 1: Run shared schema migrations (creates public schema)
echo ""
echo "📦 Step 1: Running shared schema migrations..."
python manage.py migrate_schemas --shared --fake-initial
echo "✅ Shared schema migrations complete"

# Step 2: Create public tenant (required for django-tenant-users)
echo ""
echo "🏢 Step 2: Creating public tenant..."
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-public.${RAILWAY_PUBLIC_DOMAIN:-ezyschool.net}}"
OWNER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-admin@ezyschool.app}"

# Check if public tenant already exists
PUBLIC_EXISTS=$(python check_setup.py public_tenant 2>/dev/null || echo "false")

if [ "$PUBLIC_EXISTS" = "true" ]; then
    echo "✅ Public tenant already exists"
else
    echo "Creating public tenant at: $PUBLIC_DOMAIN"
    python manage.py create_public_tenant \
        --domain_url "$PUBLIC_DOMAIN" \
        --owner_email "$OWNER_EMAIL"
    echo "✅ Public tenant created"
fi

# Step 3: Create superuser (defaults to true for first-time setup)
CREATE_SUPERUSER="${CREATE_SUPERUSER:-true}"
if [ "$CREATE_SUPERUSER" = "true" ]; then
    echo ""
    echo "👤 Step 3: Creating superuser..."
    
    # Check if superuser with this email exists
    SUPERUSER_EXISTS=$(python check_setup.py superuser 2>/dev/null || echo "false")
    
    if [ "$SUPERUSER_EXISTS" = "true" ]; then
        echo "✅ Superuser already exists"
    else
        python manage.py create_superadmin \
            --email "${DJANGO_SUPERUSER_EMAIL:-admin@ezyschool.app}" \
            --password "${DJANGO_SUPERUSER_PASSWORD:-changeme}" \
            --id-number "${DJANGO_SUPERUSER_ID_NUMBER:-admin001}" \
            --name "${DJANGO_SUPERUSER_NAME:-System Administrator}"
        echo "✅ Superuser created"
    fi
else
    echo ""
    echo "⏭️  Step 3: Skipping superuser creation (CREATE_SUPERUSER not enabled)"
fi

# Step 4: Load permissions (required for access control)
echo ""
echo "🔐 Step 4: Loading permissions..."
PERMISSIONS_EXIST=$(python check_setup.py permissions 2>/dev/null || echo "false")

if [ "$PERMISSIONS_EXIST" = "true" ]; then
    echo "✅ Permissions already loaded"
else
    # Check if permissions JSON file exists
    if [ -f "users/access_policies/permissions.json" ]; then
        python manage.py loaddata users/access_policies/permissions.json
        echo "✅ Permissions loaded"
    else
        echo "⚠️  Warning: permissions.json not found, skipping..."
    fi
fi

# Step 5: Run tenant schema migrations
echo ""
echo "📦 Step 5: Running tenant schema migrations..."
python manage.py migrate_schemas --fake-initial
echo "✅ Tenant schema migrations complete"

# Step 6: Collect static files
echo ""
echo "📦 Step 6: Collecting static files..."
python manage.py collectstatic --noinput --clear
echo "✅ Static files collected"

# Step 7: Run deployment checks
echo ""
echo "✅ Step 7: Running deployment checks..."
python manage.py check --deploy
echo "✅ Deployment checks passed"

echo ""
echo "🎉 Railway environment setup complete!"
echo ""
echo "📋 Setup Summary:"
echo "  - Shared schema migrations: ✅"
echo "  - Public tenant: ✅"
echo "  - Superuser: $([ "$CREATE_SUPERUSER" = "true" ] && echo "✅" || echo "⏭️ skipped")"
echo "  - Permissions: ✅"
echo "  - Tenant schema migrations: ✅"
echo "  - Static files: ✅"
echo "  - Deployment checks: ✅"
echo ""
echo "🔗 Superuser Credentials (if created):"
echo "  Email: ${DJANGO_SUPERUSER_EMAIL:-admin@ezyschool.app}"
echo "  ID Number: ${DJANGO_SUPERUSER_ID_NUMBER:-admin001}"
echo "  Username: ${DJANGO_SUPERUSER_USERNAME:-superadmin}"
echo ""
