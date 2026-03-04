#!/usr/bin/env bash
# build-railway.sh - Railway Build Phase Script
#
# This script runs during the Railway BUILD phase:
# - Installs Python dependencies
# - Verifies critical packages
# - Collects static files (for serving via WhiteNoise)
#
# Database setup, migrations, and superuser creation happen in the RELEASE phase
# (see ../auto-setup-railway.sh and ../setup-railway-environment.sh)
#
# ENVIRONMENT VARIABLES:
# - This script does NOT require any environment variables
# - All configuration happens in RELEASE and WEB phases
# - See RAILWAY_ENV_VARIABLES.md for complete reference

set -o errexit  # exit on error

echo "🚀 Railway BUILD phase starting..."
echo ""

# Print Python version for debugging
echo "🐍 Python version:"
python --version
echo ""

# Ensure we have the right pip, setuptools, wheel
echo "📦 Upgrading pip, setuptools, and wheel..."
pip install --upgrade pip setuptools wheel
echo ""

# Install Python dependencies
echo "📦 Installing project dependencies..."
pip install -r requirements.txt --verbose
echo ""

# Verify critical imports work
echo "🔍 Verifying critical imports..."
python -c "import django; print(f'✅ Django {django.get_version()} imported successfully')"
python -c "import rest_framework; print(f'✅ Django REST Framework imported successfully')"
python -c "import django_tenants; print(f'✅ django-tenants imported successfully')"
echo ""

# Collect static files for production serving via WhiteNoise
echo "📂 Collecting static files for WhiteNoise..."

# Create staticfiles directory if it doesn't exist
mkdir -p staticfiles

# Run collectstatic with verbose output
python manage.py collectstatic --noinput --clear --verbosity=2

# Verify static files were collected
if [ -d "staticfiles" ] && [ "$(ls -A staticfiles)" ]; then
    file_count=$(find staticfiles -type f | wc -l)
    echo "✅ Static files collected: $file_count files in staticfiles/"
else
    echo "⚠️  Warning: staticfiles directory is empty or missing"
fi
echo ""

echo "✅ BUILD phase completed successfully!"
echo ""
echo "📋 Next steps (RELEASE phase):"
echo "   - auto-setup-railway.sh will run migrations"
echo "   - Public tenant will be created"
echo "   - Superuser will be created (if CREATE_SUPERUSER=true)"
echo ""
