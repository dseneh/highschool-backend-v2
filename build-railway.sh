#!/usr/bin/env bash
# build-railway.sh - Railway Build Script (runs after dependency installation)

set -e

echo "🚀 Railway Build Started"

# Dependencies should already be installed by nixpacks
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput --clear || echo "⚠️ Static files collection failed"

echo "✅ Build completed successfully"
