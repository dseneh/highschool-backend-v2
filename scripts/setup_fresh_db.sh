#!/bin/bash

# Fresh Database Setup Script for Production
# This script automates the process of setting up a fresh database in production

set -e  # Exit on any error

echo "🚀 Starting Fresh Database Setup for Production"
echo "================================================"

# Check if we're in the right directory
if [ ! -f "manage.py" ]; then
    echo "❌ Error: manage.py not found. Please run this script from the Django project root."
    exit 1
fi

# Confirmation prompt
echo "⚠️  WARNING: This will completely remove all existing data!"
echo "⚠️  Make sure you have backed up any important data."
echo ""
read -p "Are you sure you want to proceed? (type 'YES' to continue): " confirmation

if [ "$confirmation" != "YES" ]; then
    echo "❌ Operation cancelled."
    exit 1
fi

echo ""
echo "🗑️  Step 1: Removing existing database..."
if [ -f "db.sqlite3" ]; then
    rm -f db.sqlite3
    echo "✅ SQLite database removed"
else
    echo "ℹ️  No SQLite database found"
fi

echo ""
echo "🔄 Step 2: Applying migrations..."
python manage.py migrate
echo "✅ Migrations applied successfully"

echo ""
echo "👤 Step 3: Creating superuser..."
echo "Please provide superuser details:"
python manage.py createsuperuser

echo ""
echo "📊 Step 4: Loading default data (if available)..."
if [ -f "defaults/data/default_data.json" ]; then
    python manage.py loaddata defaults/data/default_data.json
    echo "✅ Default data loaded"
else
    echo "ℹ️  No default data file found, skipping..."
fi

echo ""
echo "🏗️  Step 5: Collecting static files..."
python manage.py collectstatic --noinput
echo "✅ Static files collected"

echo ""
echo "🧪 Step 6: Running system checks..."
python manage.py check
echo "✅ System checks passed"

echo ""
echo "🎉 Fresh database setup completed successfully!"
echo ""
echo "📋 Next Steps:"
echo "1. Test student creation with new ID system"
echo "2. Verify CSV import functionality"
echo "3. Check admin interfaces at /admin/"
echo "4. Test authentication flows"
echo "5. Verify all API endpoints"
echo ""
echo "🔗 Useful URLs:"
echo "- Admin: https://your-domain.com/admin/"
echo "- API Docs: https://your-domain.com/api/docs/"
echo ""
echo "✨ Your application is ready to use!"
