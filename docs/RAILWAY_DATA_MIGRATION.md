# Railway Data Migration Guide

This guide provides two methods to copy PostgreSQL data from your Railway production environment to staging environment.

## Prerequisites

1. **Railway CLI installed**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

2. **Environment Access**: Ensure you have access to both production and staging Railway environments

3. **Backup First**: Always backup your data before migration operations

## Method 1: Django Export/Import (Recommended)

**Best for**: Most use cases, safer, handles Django relationships properly

```bash
./copy-data-django-method.sh
```

### What it does:
- ✅ Uses Django's `dumpdata`/`loaddata` (safer for Django apps)
- ✅ Handles foreign key relationships properly
- ✅ Excludes system tables (contenttypes, sessions, etc.)
- ✅ Creates staging-specific admin user
- ✅ Automatic backups
- ✅ Less likely to cause schema issues

### Customization:
```bash
# Use different environment names
PROD_ENV=production STAGING_ENV=staging ./copy-data-django-method.sh

# Or export environment variables
export PROD_ENV="production"
export STAGING_ENV="staging" 
./copy-data-django-method.sh
```

## Method 2: PostgreSQL Dump/Restore

**Best for**: Large databases, exact replica needed, includes PostgreSQL-specific features

```bash
./copy-production-to-staging.sh
```

### What it does:
- ✅ Complete PostgreSQL database dump/restore
- ✅ Exact replica of production database
- ✅ Faster for very large datasets
- ✅ Includes all PostgreSQL features (triggers, functions, etc.)
- ⚠️ Completely replaces staging database schema
- ⚠️ May require schema migrations afterward

## Post-Migration Steps

After running either script:

1. **Test the staging environment**:
   ```bash
   railway run --environment staging python manage.py check
   ```

2. **Access staging admin**:
   - Username: `staging-admin` 
   - Password: `staging123`
   - Email: `staging@ezyschool.app`

3. **Change staging admin password immediately**!

4. **Verify data integrity**:
   - Check user counts
   - Verify school data
   - Test login functionality

## Manual Steps (if needed)

### Export production data manually:
```bash
# Django export
railway run --environment production python manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --indent 2 > prod_data.json

# PostgreSQL export  
railway run --environment production -- pg_dump $DATABASE_URL > prod_dump.sql
```

### Import to staging manually:
```bash
# Django import
cat prod_data.json | railway run --environment staging python manage.py loaddata --format=json -

# PostgreSQL import
cat prod_dump.sql | railway run --environment staging -- psql $DATABASE_URL
```

## Troubleshooting

### Common Issues:

1. **"Railway CLI not found"**:
   ```bash
   npm install -g @railway/cli
   ```

2. **"Not logged in to Railway"**:
   ```bash
   railway login
   ```

3. **"Environment not found"**:
   - Check your environment names in Railway dashboard
   - Update PROD_ENV and STAGING_ENV variables

4. **"Foreign key constraint errors"**:
   - Use Method 1 (Django method) instead
   - Clear staging data completely first

5. **"Permission denied"**:
   - Ensure you have access to both environments
   - Check Railway project permissions

### Recovery:

If something goes wrong, restore from backup:
```bash
# Restore staging from backup (if available)
cat backup_directory/staging_backup.json | railway run --environment staging python manage.py loaddata --format=json -
```

## Security Notes

- ⚠️ **Never run these scripts against production as target**
- ⚠️ **Always backup before migration**  
- ⚠️ **Change default passwords immediately**
- ⚠️ **Review data sensitivity** (production data in staging)
- ⚠️ **Ensure staging environment is secure**

## Environment Variables

You can customize the script behavior:

```bash
export PROD_ENV="production"        # Source environment name
export STAGING_ENV="staging"        # Target environment name
```

Default values are `production` and `staging` respectively.