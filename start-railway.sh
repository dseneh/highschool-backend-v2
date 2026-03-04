#!/usr/bin/env bash
set -euo pipefail

echo "==============================================="
echo "WEB PHASE STARTING - $(date)"
echo "==============================================="
echo "DATABASE_URL set: $([ -n "${DATABASE_URL:-}" ] && echo 'YES' || echo 'NO')"
echo "SECRET_KEY set: $([ -n "${SECRET_KEY:-}" ] && echo 'YES' || echo 'NO')"
echo ""

# CRITICAL: Run setup before starting web server
echo "EXECUTING SETUP SCRIPT..."
if bash -x ./auto-setup-railway.sh; then
    echo "✅ Setup script completed successfully"
else
    SETUP_EXIT_CODE=$?
    echo "❌ Setup script failed with exit code: $SETUP_EXIT_CODE"
    exit $SETUP_EXIT_CODE
fi
echo ""

# Quick sanity check that Django can load
echo "Verifying Django configuration..."
python manage.py check --deploy 2>&1 || {
    echo "❌ Django configuration check failed!"
    exit 1
}
echo "✅ Django configuration OK"
echo ""

# Test database connection
echo "Testing database connection..."
python -c "from django.db import connection; connection.ensure_connection(); print('✅ Database connection OK')" || {
    echo "❌ Database connection failed!"
    exit 1
}
echo ""

# Ensure staticfiles directory exists (for WhiteNoise)
mkdir -p staticfiles

echo "Starting Gunicorn on port ${PORT:-8080} with ${WEB_CONCURRENCY:-3} workers..."
exec gunicorn api.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --timeout 120
