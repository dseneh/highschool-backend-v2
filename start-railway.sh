#!/usr/bin/env bash
set -euo pipefail

echo "🚀 Starting Django on Railway"

# Ensure staticfiles directory exists (for WhiteNoise)
mkdir -p staticfiles

exec gunicorn api.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --timeout 120
