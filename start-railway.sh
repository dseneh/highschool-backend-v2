#!/usr/bin/env bash
set -euo pipefail

# Write to both stdout and stderr to ensure visibility
exec 1> >(tee -a /tmp/web.log)
exec 2>&1

echo "==============================================="
echo "WEB PHASE STARTING - $(date)"
echo "==============================================="
echo "DATABASE_URL: $([ -z "${DATABASE_URL:-}" ] && echo 'NOT SET' || echo 'SET')"
echo "SECRET_KEY: $([ -z "${SECRET_KEY:-}" ] && echo 'NOT SET' || echo 'SET')"
echo ""

# CRITICAL: Run setup before starting web server
echo "Running setup/migrations..."
bash -x ./auto-setup-railway.sh
echo "Setup complete"
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

echo "Starting Gunicorn on port ${PORT:-8080}..."
exec gunicorn api.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --timeout 120
