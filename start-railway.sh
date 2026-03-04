#!/usr/bin/env bash
set -euo pipefail

echo "🚀 Starting Django on Railway"

# Quick sanity check that Django can load
echo "Verifying Django configuration..."
python manage.py check --deploy 2>&1 || {
    echo "❌ Django configuration check failed!"
    exit 1
}
echo "✅ Django configuration OK"

# Ensure staticfiles directory exists (for WhiteNoise)
mkdir -p staticfiles

exec gunicorn api.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --timeout 120
