# Railway Production Deployment Guide - v2 Backend

## Overview

Your backend is now fully configured for Railway production deployment with:

✅ **Auto-superuser creation** via environment variables  
✅ **Cloudflare R2 storage** for multi-tenant media files  
✅ **Default data loading** for new tenants (academic years, semesters, subjects, etc.)  
✅ **Redis caching** for performance  
✅ **Automatic tenant isolation** with schema-per-tenant  
✅ **Production security** (SSL, HSTS, secure cookies)  

---

## 🚀 Deployment Checklist

### Step 1: Railway Project Setup

1. **Create Railway Project**
   ```bash
   # In Railway Dashboard
   - Create new project: "ezyschool-backend-v2"
   - Add PostgreSQL service
   - Add Redis service
   ```

2. **Connect GitHub Repository**
   - Link this repository to Railway
   - Set branch: `main`

3. **Configure Custom Domain**
   - Add domain: `api.ezyschool.net`
   - Update DNS: CNAME → Railway-provided domain

### Step 2: Environment Variables

Copy the `.env.railway.template` contents and set these variables in Railway:

#### Required Variables

```bash
# Core Django
SECRET_KEY=<generate-random-64-char-string>
DEBUG=False
ENV=production
DJANGO_SETTINGS_MODULE=api.settings
ALLOWED_HOSTS=api.ezyschool.net,.ezyschool.net

# Security
CSRF_TRUSTED_ORIGINS=https://api.ezyschool.net,https://*.ezyschool.net
CORS_ALLOWED_ORIGINS=https://api.ezyschool.net
CORS_ALLOWED_ORIGIN_REGEXES=^https://[a-z0-9-]+\.ezyschool\.net$
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# Database (Railway auto-provides)
DB_CONN_MAX_AGE=30
DB_SSL_REQUIRE=True

# Redis
DISABLE_REDIS=False
USE_REDIS=True

# Superuser (First-time deployment)
CREATE_SUPERUSER=true
DJANGO_SUPERUSER_EMAIL=admin@ezyschool.app
DJANGO_SUPERUSER_USERNAME=superadmin
DJANGO_SUPERUSER_ID_NUMBER=admin001
DJANGO_SUPERUSER_PASSWORD=<strong-password-here>

# Cloudflare R2 Storage
USE_S3_STORAGE=True
R2_BUCKET=ezyschool-media
R2_ACCESS_KEY_ID=0684afda8075102564e2c
R2_SECRET_ACCESS_KEY=358bbbbc85e99ed4b3b87d1126691ab9436e3c660d9cde60
R2_S3_ENDPOINT=https://add-restorage.com
R2_CUSTOM_DOMAIN=ezyschoolia.com

# Encryption
SECRET_AES_KEY=OIKkE8ST35EFNMxI1VgxQDq0HLA=
```

#### Optional Variables

```bash
# JWT Configuration (defaults shown)
ACCESS_TOKEN_LIFETIME_MINUTES=60
REFRESH_TOKEN_LIFETIME_DAYS=7

# Localization
LANGUAGE_CODE=en-us
TIME_ZONE=UTC

# Monitoring
AUTH_DEBUG_LOGGING=False
# SENTRY_DSN=<your-sentry-dsn>
```

### Step 3: Verify Deployment Configuration

Railway automatically uses these files:

- **`Procfile`**: Defines deployment commands
  ```
  release: ./auto-setup-railway.sh
  web: ./start-railway.sh
  ```

- **`railway.json`**: Platform configuration
  ```json
  {
    "build": {
      "builder": "NIXPACKS"
    },
    "deploy": {
      "healthcheckPath": "/health/",
      "healthcheckTimeout": 300,
      "restartPolicyType": "ON_FAILURE",
      "restartPolicyMaxRetries": 10
    }
  }
  ```

### Step 4: Deploy

```bash
# Push to GitHub (Railway auto-deploys)
git add .
git commit -m "feat: production-ready v2 backend"
git push origin main
```

Railway will:
1. ✅ Build the application
2. ✅ Run `auto-setup-railway.sh` (release phase)
   - Detect first-time deployment
   - Run shared schema migrations (`migrate_schemas --shared`)
   - Create public tenant
   - Create superuser (if `CREATE_SUPERUSER=true`)
   - Load permissions
   - Run tenant schema migrations (`migrate_schemas`)
   - Collect static files
   - Run deployment checks
3. ✅ Start web server via `start-railway.sh`
4. ✅ Run health checks on `/health/`

---

## 🔧 How It Works

### First-Time Deployment

`auto-setup-railway.sh` detects first deployment and runs `setup-railway-environment.sh`:

1. **Run Shared Schema Migrations**: `python manage.py migrate_schemas --shared`
   - Creates public schema tables (User, Tenant, Domain, Permission, etc.)
2. **Create Public Tenant**: Required for django-tenant-users
   ```bash
   python manage.py create_public_tenant \
       --domain_url public.ezyschool.net \
       --owner_email admin@ezyschool.app
   ```
3. **Create Superuser** (if enabled):
   ```bash
   python manage.py create_superadmin \
       --email admin@ezyschool.app \
       --password <from-env> \
       --id-number admin001
   ```
4. **Load Permissions**: From `users/access_policies/permissions.json`
5. **Run Tenant Schema Migrations**: `python manage.py migrate_schemas`
   - Creates tenant-specific tables in all tenant schemas
6. **Collect Static Files**: `collectstatic --noinput --clear`
7. **Run Deployment Checks**: `check --deploy`

### Subsequent Deployments

`auto-setup-railway.sh` detects existing setup and only runs:
- ✅ All schema migrations: `migrate_schemas`
- ✅ Static file collection

---

## 🗄️ Cloudflare R2 Storage

### How It Works

**Tenant-Aware Paths**:
- Public schema: `public/users/<user_id>.jpg`
- Tenant schemas: `tenants/<schema_name>/students/<student_id>.jpg`

**Configuration**: `core.storage.TenantAwareS3Storage`
- Automatically prefixes all file paths with tenant schema
- Uses R2 environment variables (falls back to AWS_ variables)
- Public-read ACL for media files
- Custom domain support via `R2_CUSTOM_DOMAIN`

**File Upload Example**:
```python
# Model with file field
class Student(models.Model):
    photo = models.ImageField(upload_to="students/")

# Saved path in R2: tenants/school1/students/photo.jpg
```

### R2 Bucket Setup (Cloudflare Dashboard)

1. Create bucket: `ezyschool-media`
2. Generate API token with R2 read/write permissions
3. Get credentials:
   - Access Key ID: `R2_ACCESS_KEY_ID`
   - Secret Access Key: `R2_SECRET_ACCESS_KEY`
   - Endpoint URL: `https://<account-id>.r2.cloudflarestorage.com`
4. (Optional) Configure custom domain via Cloudflare Workers

---

## 👤 Superuser Access

### First Login

```bash
# API Login Endpoint
POST https://api.ezyschool.net/api/v1/auth/login/

# Request Body
{
  "credential": "admin001",  # or "admin@ezyschool.app"
  "password": "<your-password>"
}

# Response
{
  "access": "<jwt-access-token>",
  "refresh": "<jwt-refresh-token>",
  "user": {
    "id": 1,
    "email": "admin@ezyschool.app",
    "id_number": "admin001",
    "role": "SUPERADMIN"
  }
}
```

### Admin Panel Access

```
URL: https://api.ezyschool.net/admin/
Username: admin@ezyschool.app (or admin001)
Password: <your-password>
```

---

## 📊 Default Data

**Default data is automatically created when you create a new tenant** via the API or admin panel.

When a tenant is created through `POST /api/v1/tenants/`, the `CreateTenantSerializer` automatically calls `setup_tenant_defaults()` which creates:

- ✅ Academic year (current year cycle)
- ✅ Semesters (Fall/Spring with dates)
- ✅ Marking periods within semesters
- ✅ Grade levels (Pre-K through Grade 12)
- ✅ Divisions (Elementary, Middle, High School)
- ✅ Sections for each grade level
- ✅ Subjects (Math, English, Science, etc.)
- ✅ Periods (daily schedule)
- ✅ Period times
- ✅ Assessment types (Homework, Quiz, Test, etc.)
- ✅ Assessment templates
- ✅ Grade letters (A+, A, B+, etc.)
- ✅ Grading settings
- ✅ Currency (USD by default)
- ✅ Payment methods (Cash, Check, Credit Card, etc.)
- ✅ Transaction types (Fee, Payment, Refund, etc.)
- ✅ Fee types (Tuition, Registration, etc.)
- ✅ Departments (Admin, Academic, Finance, etc.)
- ✅ Position categories and positions

**Implementation**: `core/serializers.py` → `CreateTenantSerializer.create()` → `defaults/utils.py` → `setup_tenant_defaults()`

**No manual step required** - data is created automatically during tenant creation.

---

## 🔑 Environment-Driven Superuser

The system supports auto-creation via these env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `CREATE_SUPERUSER` | `false` | Enable auto-creation |
| `DJANGO_SUPERUSER_EMAIL` | `admin@ezyschool.app` | Superuser email |
| `DJANGO_SUPERUSER_USERNAME` | `superadmin` | Username |
| `DJANGO_SUPERUSER_ID_NUMBER` | `admin001` | ID number (login field) |
| `DJANGO_SUPERUSER_PASSWORD` | - | Password (required) |

**Security Note**: After first deployment, consider:
- Setting `CREATE_SUPERUSER=false`
- Removing `DJANGO_SUPERUSER_PASSWORD` from env
- Changing superuser password via Django admin

---

## 🧪 Health Check

Railway monitors this endpoint:

```bash
GET https://api.ezyschool.net/health/

# Response (healthy)
{
  "status": "healthy",
  "database": "connected"
}
```

Location: `api/urls.py` → `core.views.health_check`

---

## 🔒 Multi-Tenant Security

### Tenant Isolation

- **Database**: Schema-per-tenant (PostgreSQL schemas)
- **Storage**: Path-prefixed per tenant in R2
- **Routing**: Via `x-tenant` HTTP header (subdomain-based)

### Frontend Integration

```javascript
// Next.js API client
const subdomain = window.location.hostname.split('.')[0];

fetch('https://api.ezyschool.net/api/v1/students/', {
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'x-tenant': subdomain  // e.g., "school1"
  }
});
```

---

## 🚨 Troubleshooting

### Deployment Fails at Migration

**Symptom**: `auto-setup-railway.sh` fails during migrations

**Solution**:
1. Check Railway logs for specific error
2. Verify `DATABASE_URL` is set (auto-provided by PostgreSQL service)
3. Ensure PostgreSQL service is running

### Superuser Not Created

**Symptom**: Can't log in with superuser credentials

**Check**:
1. `CREATE_SUPERUSER=true` set?
2. `DJANGO_SUPERUSER_PASSWORD` provided?
3. Check Railway logs for creation output
4. Verify public tenant exists first

**Manual Creation**:
```bash
# Railway CLI
railway run python manage.py create_public_tenant \
    --domain_url public.ezyschool.net \
    --owner_email admin@ezyschool.app

railway run python manage.py create_superadmin \
    --email admin@ezyschool.app \
    --password <password>
```

### File Uploads Not Working

**Check**:
1. `USE_S3_STORAGE=True`
2. R2 credentials valid
3. R2 bucket exists and is accessible
4. Check Railway logs for boto3 errors

**Test R2 Connection**:
```python
# In Django shell (railway run python manage.py shell)
from django.core.files.storage import default_storage
default_storage.bucket_name  # Should show: ezyschool-media
default_storage.connection  # Should not error
```

### Health Check Failing

**Symptom**: Railway shows "Unhealthy" status

**Check**:
1. `/health/` endpoint returns 200
2. Database connection successful
3. Healthcheck timeout (300s) sufficient for cold starts
4. Railway logs show web server started

---

## 📝 Migration Notes from v1

### Key Differences

| Feature | v1 | v2 |
|---------|----|----|
| **Django** | 4.x | 5.2+ |
| **Python** | 3.10 | 3.10+ |
| **Tenant Library** | django-tenants | django-tenants 3.9+ |
| **Storage** | Direct S3 | TenantAwareS3Storage |
| **Superuser** | Manual creation | Auto-creation via env |
| **Setup Script** | Manual | Automated release phase |

### Data Migration

Since this is a fresh v2 deployment, no automatic v1 → v2 migration exists.

**Options**:
1. **Clean Start**: Use v2 as fresh system (recommended if v1 is test/dev)
2. **Manual Migration**: Export v1 data → Import to v2 (custom scripts needed)

---

## 🎉 Post-Deployment

### Verify Deployment

```bash
# Health check
curl https://api.ezyschool.net/health/

# API docs
open https://api.ezyschool.net/api/docs/

# Admin panel
open https://api.ezyschool.net/admin/

# Login test
curl -X POST https://api.ezyschool.net/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"credential": "admin001", "password": "<password>"}'
```

### Next Steps

1. ✅ Configure frontend (`NEXT_PUBLIC_API_BASE_URL=https://api.ezyschool.net/api/v1`)
2. ✅ Create first school tenant via admin panel
3. ✅ Test student creation, file uploads, authentication flows
4. ✅ Set up monitoring (Sentry, Railway metrics)
5. ✅ Configure email backend for notifications
6. ✅ Set up automated backups (Railway PostgreSQL backups)

---

## 📚 Additional Resources

- **Django Tenants**: https://django-tenants.readthedocs.io/
- **Django Tenant Users**: https://django-tenant-users.readthedocs.io/
- **Railway Docs**: https://docs.railway.app/
- **Cloudflare R2**: https://developers.cloudflare.com/r2/

---

**🎊 Your backend is production-ready!**

For questions or issues, check Railway logs or Django admin panel.
