# Railway Environment Variables Reference

Complete guide to all environment variables needed for v2 SaaS backend deployment on Railway.

## 📋 Quick Reference

| Phase | Variables | Auto-Provided |
|-------|-----------|---------------|
| **BUILD** | None required | - |
| **RELEASE** | Setup-specific vars | `RAILWAY_PUBLIC_DOMAIN` |
| **WEB** | Django & app config | `DATABASE_URL`, `REDIS_URL`, `PORT` |

---

## 🛠️ BUILD Phase

**Script**: `scripts/build-railway.sh`

No environment variables required. Build phase:
- Installs dependencies
- Collects static files
- Verifies imports

---

## 📦 RELEASE Phase

**Script**: `auto-setup-railway.sh` → `setup-railway-environment.sh`

### Tenant Setup Variables

```bash
# Public Tenant Configuration
PUBLIC_DOMAIN=public.ezyschool.net
# If not set, defaults to: public.${RAILWAY_PUBLIC_DOMAIN} or public.ezyschool.net
# RAILWAY_PUBLIC_DOMAIN is auto-provided by Railway
```

### Superuser Creation (First-Time Only)

**Required if `CREATE_SUPERUSER=true`:**

```bash
CREATE_SUPERUSER=true              # Enable auto-creation (def: false)
DJANGO_SUPERUSER_EMAIL=admin@ezyschool.app
DJANGO_SUPERUSER_USERNAME=superadmin
DJANGO_SUPERUSER_ID_NUMBER=admin001
DJANGO_SUPERUSER_PASSWORD=<strong-password>  # Required if CREATE_SUPERUSER=true
DJANGO_SUPERUSER_NAME=System Administrator   # Optional
```

---

## 🌐 WEB Phase

**Script**: `start-railway.sh` → Gunicorn

### Core Django Settings

```bash
# Required (Set in Railway dashboard)
DEBUG=False
ENV=production
DJANGO_SETTINGS_MODULE=api.settings
SECRET_KEY=<generate-random-64-char-string>

# Security
ALLOWED_HOSTS=api.ezyschool.net,.ezyschool.net
CSRF_TRUSTED_ORIGINS=https://api.ezyschool.net,https://*.ezyschool.net
CORS_ALLOWED_ORIGINS=https://api.ezyschool.net
CORS_ALLOWED_ORIGIN_REGEXES=^https://[a-z0-9-]+\.ezyschool\.net$
```

### SSL & Security

```bash
# Production security (conditional on DEBUG=False)
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
```

### Database (Auto-Provided by Railway PostgreSQL Service)

```bash
# Railway auto-injects this from PostgreSQL service
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Configuration
DB_CONN_MAX_AGE=30
DB_SSL_REQUIRE=True
```

### Redis (Auto-Provided by Railway Redis Service)

```bash
# Railway auto-injects this from Redis service
REDIS_URL=redis://host:port

# Configuration
USE_REDIS=True
DISABLE_REDIS=False
```

### File Storage - Cloudflare R2

```bash
# Enable S3-compatible storage
USE_S3_STORAGE=True

# Cloudflare R2 Credentials
R2_BUCKET=ezyschool-media
R2_ACCESS_KEY_ID=<your-r2-access-key-id>
R2_SECRET_ACCESS_KEY=<your-r2-secret-access-key>
R2_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_CUSTOM_DOMAIN=<your-custom-domain-for-media>
```

### Encryption & Security Keys

```bash
# Generate with: python generate_aes_key.py
SECRET_AES_KEY=<32-byte-base64-encoded-key>

# JWT Configuration
ACCESS_TOKEN_LIFETIME_MINUTES=60
REFRESH_TOKEN_LIFETIME_DAYS=7
JWT_SIGNING_KEY=<your-jwt-secret-key>
```

### Localization

```bash
LANGUAGE_CODE=en-us
TIME_ZONE=UTC
```

### Logging & Monitoring

```bash
AUTH_DEBUG_LOGGING=False  # Set to False in production

# Optional: Sentry Error Tracking
# SENTRY_DSN=<your-sentry-dsn>
```

### Gunicorn (Web Server)

```bash
# Railway auto-provides PORT (usually 8080)
PORT=8080

# Auto-calculated based on dyno type, or set manually
WEB_CONCURRENCY=3

# Not typically needed, but available:
# PYTHONUNBUFFERED=1
# PYTHONDONTWRITEBYTECODE=1
```

---

## 🔄 Variable Precedence & Defaults

### Public Domain
```bash
# Tries in order:
1. PUBLIC_DOMAIN (if set)
2. RAILWAY_PUBLIC_DOMAIN (auto-provided by Railway)
3. Default: ezyschool.net
# Result: public.${resolved_domain}
```

### Superuser Credentials
```bash
# All have fallback defaults (shown below)
DJANGO_SUPERUSER_EMAIL=${DJANGO_SUPERUSER_EMAIL:-admin@ezyschool.app}
DJANGO_SUPERUSER_USERNAME=${DJANGO_SUPERUSER_USERNAME:-superadmin}
DJANGO_SUPERUSER_ID_NUMBER=${DJANGO_SUPERUSER_ID_NUMBER:-admin001}
DJANGO_SUPERUSER_PASSWORD=${DJANGO_SUPERUSER_PASSWORD:-REQUIRED if CREATE_SUPERUSER=true}
DJANGO_SUPERUSER_NAME=${DJANGO_SUPERUSER_NAME:-System Administrator}
```

### Gunicorn Workers
```bash
# Calculated based on dyno type, but can be overridden:
WEB_CONCURRENCY=${WEB_CONCURRENCY:-3}
PORT=${PORT:-8080}
```

---

## 🚀 Deployment Steps

### 1. Create Railway Project & Services

```bash
# In Railway Dashboard
- New Project
- Add PostgreSQL service
- Add Redis service (optional but recommended)
```

### 2. Set Environment Variables

Copy all required variables from this guide into Railway environment:

```bash
# Category: Core Django
DEBUG=False
ENV=production
DJANGO_SETTINGS_MODULE=api.settings
SECRET_KEY=<generate-random-64-chars>

# Category: Domains & Security
ALLOWED_HOSTS=api.ezyschool.net,.ezyschool.net
CSRF_TRUSTED_ORIGINS=https://api.ezyschool.net,https://*.ezyschool.net
CORS_ALLOWED_ORIGINS=https://api.ezyschool.net
CORS_ALLOWED_ORIGIN_REGEXES=^https://[a-z0-9-]+\.ezyschool\.net$
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# Category: Database (auto-provided)
# DATABASE_URL will be auto-injected by Railway PostgreSQL service
DB_CONN_MAX_AGE=30
DB_SSL_REQUIRE=True

# Category: Redis (auto-provided)
# REDIS_URL will be auto-injected by Railway Redis service
USE_REDIS=True
DISABLE_REDIS=False

# Category: File Storage
USE_S3_STORAGE=True
R2_BUCKET=ezyschool-media
R2_ACCESS_KEY_ID=<your-key>
R2_SECRET_ACCESS_KEY=<your-secret>
R2_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_CUSTOM_DOMAIN=<your-media-domain>

# Category: Encryption
SECRET_AES_KEY=<generate-with-generate_aes_key.py>

# Category: JWT
ACCESS_TOKEN_LIFETIME_MINUTES=60
REFRESH_TOKEN_LIFETIME_DAYS=7
JWT_SIGNING_KEY=<your-jwt-secret>

# Category: Superuser (First Deploy Only)
CREATE_SUPERUSER=true
DJANGO_SUPERUSER_EMAIL=admin@ezyschool.app
DJANGO_SUPERUSER_USERNAME=superadmin
DJANGO_SUPERUSER_ID_NUMBER=admin001
DJANGO_SUPERUSER_PASSWORD=<strong-password>

# Category: Localization
LANGUAGE_CODE=en-us
TIME_ZONE=UTC

# Category: Monitoring (Optional)
AUTH_DEBUG_LOGGING=False
# SENTRY_DSN=<optional>
```

### 3. Connect GitHub Repository

```bash
- Add GitHub account
- Select this repository
- Set branch: main
- Enable automatic deployments
```

### 4. Deploy

```bash
# Push to GitHub (Railway will auto-deploy)
git add .
git commit -m "Production deployment v2"
git push origin main
```

Railway will automatically:
1. **BUILD** (`scripts/build-railway.sh`):
   - Install dependencies
   - Collect static files
   
2. **RELEASE** (`auto-setup-railway.sh`):
   - Detect first-time vs. subsequent deploy
   - First deploy: Run full setup (migrations, public tenant, superuser)
   - Subsequent: Run just migrations
   
3. **WEB** (`start-railway.sh`):
   - Start Gunicorn server
   - Run health checks

---

## 📝 v1 → v2 Migration Notes

| Aspect | v1 | v2 |
|--------|----|----|
| **Setup** | Manual commands | Auto via scripts |
| **Superuser** | `createsuperuser` prompt | Env vars + auto-create |
| **Migrations** | `migrate --noinput` | `migrate_schemas --shared`, then `migrate_schemas` |
| **Public Schema** | Created manually | Auto-created in release phase |
| **Default Data** | Via `LOAD_DEFAULT_DATA` env | Auto via `CreateTenantSerializer` |
| **File Storage** | S3 only | S3/R2 + local fallback |

---

## 🔧 Troubleshooting

### "DATABASE_URL not found"
**Cause**: PostgreSQL service not provisioned  
**Fix**: Add PostgreSQL service to Railway project and wait for it to be ready

### "Invalid HTTP_HOST header: 'healthcheck.railway.app'"
**Cause**: ALLOWED_HOSTS doesn't include Railway's internal health check domain  
**Fix**: This is now automatically added to ALLOWED_HOSTS in settings. No action needed.  
**Note**: Both `api/settings/base.py` and `railway.json` now support Railway's health checks

### "REDIS_URL not found"
**Cause**: Redis service not provisioned  
**Fix**: Add Redis service to Railway project (optional but recommended)

### "Superuser not created"
**Cause**: `CREATE_SUPERUSER != "true"`  
**Fix**: Set `CREATE_SUPERUSER=true` and `DJANGO_SUPERUSER_PASSWORD` in Railway env vars

### Public tenant creation fails
**Cause**: Migrations haven't run  
**Fix**: Check that `migrate_schemas --shared` completed successfully in logs

### "SECRET_KEY not set" or "SECRET_AES_KEY not set"
**Cause**: Missing security keys  
**Fix**: Generate with:
```bash
# Generate SECRET_KEY (64 random chars)
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Generate SECRET_AES_KEY (32-byte base64)
python generate_aes_key.py
```

---

## ✅ Verification Checklist

- [ ] All required env vars set in Railway dashboard
- [ ] PostgreSQL service added and running
- [ ] Redis service added and running (optional)
- [ ] Domain DNS configured (`api.ezyschool.net` → Railway domain)
- [ ] Cloudflare R2 bucket created (if using)
- [ ] R2 credentials valid and set
- [ ] Repository connected to Railway
- [ ] First deploy completed successfully
- [ ] Health check passes: `https://api.ezyschool.net/health/`
- [ ] Admin panel accessible: `https://api.ezyschool.net/admin/`
- [ ] Superuser can log in with provided credentials

---

## 🔐 Security Best Practices

1. **Never commit `.env` files** - Always set vars in Railway dashboard
2. **Use strong passwords** for `DJANGO_SUPERUSER_PASSWORD`
3. **Rotate `SECRET_KEY`** periodically (requires restart)
4. **Enable HSTS preloading**: Add your domain to https://hstspreload.org/
5. **Monitor logs** for errors and suspicious activity
6. **Use separate R2 keys** for production vs. staging
7. **Enable 2FA** on Cloudflare account (for R2 access)
8. **Set `DEBUG=False`** in production (default checked)

---

**Last Updated**: March 4, 2026  
**Version**: 2.0 (SaaS Multi-Tenant)
