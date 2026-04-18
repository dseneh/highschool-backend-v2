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
if bash ./auto-setup-railway.sh; then
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

# Check GeoIP database availability
GEOIP_DB="geoip/GeoLite2-City.mmdb"
if [ -f "$GEOIP_DB" ]; then
    echo "✅ GeoIP database found ($(du -h "$GEOIP_DB" | cut -f1))"
elif [ -n "${MAXMIND_LICENSE_KEY:-}" ]; then
    echo "⚠️ GeoIP database not found — downloading at startup..."
    python manage.py download_geoip_db --license-key "$MAXMIND_LICENSE_KEY" || echo "⚠️ GeoIP download failed (non-fatal)"
    if [ -f "$GEOIP_DB" ]; then
        echo "✅ GeoIP database downloaded successfully ($(du -h "$GEOIP_DB" | cut -f1))"
    fi
else
    echo "⚠️ GeoIP database not found at $GEOIP_DB — location data will be unavailable"
    echo "   Set MAXMIND_LICENSE_KEY env var and redeploy to enable geo logging"
fi
echo ""

# Test database connection
echo "Testing database connection..."
if python check_setup.py superuser >/dev/null 2>&1; then
    echo "✅ Database connection OK"
else
    echo "❌ Database connection failed!"
    exit 1
fi
echo ""

# Ensure staticfiles directory exists (for WhiteNoise)
mkdir -p staticfiles

echo "Starting Gunicorn on port ${PORT:-8080} with ${WEB_CONCURRENCY:-3} workers..."
exec gunicorn api.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --timeout 120
