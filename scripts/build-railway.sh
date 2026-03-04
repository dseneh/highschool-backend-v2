#!/usr/bin/env bash
# build-railway.sh - Railway Build Script

set -o errexit  # exit on error

echo "🚀 Starting Railway build process..."

# Print Python version for debugging
echo "🐍 Python version:"
python --version

# Detect Python version and choose appropriate requirements
PYTHON_VERSION=$(python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "🔍 Detected Python version: $PYTHON_VERSION"

# Install Python dependencies
echo "📦 Installing dependencies..."
# Upgrade pip and install essential build tools first
pip install --upgrade pip setuptools wheel

# Choose requirements file based on Python version
if [[ "$PYTHON_VERSION" == "3.13" ]]; then
    echo "📦 Using Python 3.13 compatible requirements..."
    REQUIREMENTS_FILE="requirements-py313.txt"
else
    echo "📦 Using standard requirements..."
    REQUIREMENTS_FILE="requirements.txt"
fi

# Install requirements with verbose output for debugging
echo "📦 Installing project requirements from $REQUIREMENTS_FILE..."
pip install -r $REQUIREMENTS_FILE --verbose || {
    echo "⚠️  Installation failed with $REQUIREMENTS_FILE, trying fallback..."
    if [[ "$REQUIREMENTS_FILE" == "requirements.txt" ]]; then
        echo "📦 Trying Python 3.13 compatible requirements..."
        pip install -r requirements-py313.txt --verbose
    else
        echo "📦 Trying standard requirements..."
        pip install -r requirements.txt --verbose
    fi
}

# Verify critical imports work
echo "🔍 Verifying critical imports..."
python -c "import django; print(f'Django {django.get_version()} imported successfully')"

# Railway-specific optimizations
echo "🛤️ Railway-specific setup..."

# Collect static files for Railway
echo "📂 Collecting static files..."
python manage.py collectstatic --noinput --clear

# Run database migrations
echo "🗄️ Running database migrations..."
python manage.py migrate --noinput

# Create superuser if configured
if [[ "$CREATE_SUPERUSER" == "true" ]]; then
    echo "👤 Creating superuser..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
import os

User = get_user_model()

# Get superuser details from environment
id_number = os.environ.get('DJANGO_SUPERUSER_ID_NUMBER', 'admin001')
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin')

# Check if superuser already exists
if not User.objects.filter(username=username).exists():
    print(f'Creating superuser: {username}')
    User.objects.create_superuser(
        id_number=id_number,
        username=username,
        email=email,
        password=password
    )
    print('✅ Superuser created successfully')
else:
    print('ℹ️ Superuser already exists')
"
fi

# Load default data if configured
if [[ "$LOAD_DEFAULT_DATA" == "true" ]]; then
    echo "📊 Loading default data..."
    python defaults/run.py || echo "⚠️ Default data loading failed (this is usually okay)"
fi

echo "✅ Railway build completed successfully!"
