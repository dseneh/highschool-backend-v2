#!/usr/bin/env bash
set -euo pipefail

# Write to both stdout and stderr to ensure visibility
exec 1> >(tee -a /tmp/web.log)
exec 2>&1

echo "==============================================="
echo "WEB PHASE STARTING - $(date)"
echo "==============================================="
echo "PORT: ${PORT:-8080}"
echo "WEB_CONCURRENCY: ${WEB_CONCURRENCY:-3}"
echo ""

# Quick sanity check that Django can load
echo "Verifying Django configuration..."
python manage.py check --deploy 2>&1 || {
    echo "❌ Django configuration check failed!"
    exit 1
}
echo "✅ Django configuration OK"
echo ""

# Ensure staticfiles directory exists (for WhiteNoise)
mkdir -p staticfiles

echo "Starting Gunicorn..."
exec gunicorn api.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --timeout 120
