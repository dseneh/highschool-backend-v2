#!/usr/bin/env bash
# build-railway.sh - Railway Build Script (runs after dependency installation)

set -e

echo "🚀 Railway Build Started"

# Dependencies should already be installed by nixpacks
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput --clear || echo "⚠️ Static files collection failed"

# Download GeoIP database for location-aware audit logs
if [ -n "${MAXMIND_LICENSE_KEY:-}" ]; then
  echo "🌍 Downloading GeoIP database..."
  python manage.py download_geoip_db --license-key "$MAXMIND_LICENSE_KEY" || echo "⚠️ GeoIP download failed (non-fatal)"
else
  echo "⚠️ MAXMIND_LICENSE_KEY not set — skipping GeoIP download"
fi

echo "✅ Build completed successfully"
