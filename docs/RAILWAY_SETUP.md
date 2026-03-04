# Railway Environment Setup

## ✅ Automatic Setup (Default Behavior)

Your Railway environment will be **automatically set up** on each deployment through the release phase in `Procfile`. The setup includes:

- Database migrations
- RBAC permissions and roles
- Superuser account creation
- Default groups and permissions
- Permission cache warming

**No manual action required!** Just deploy and your environment will be ready.

## Manual Setup Options

### Option 1: Full manual setup script
```bash
railway run bash setup-railway-environment.sh
```

### Option 2: Individual commands

```bash
# 1. Apply migrations
railway run python manage.py migrate --noinput

# 2. Set up permissions and roles  
railway run python manage.py sync_permissions

# 3. Create superuser
railway run python manage.py ensure_superuser

# 4. Set up default permissions
railway run python manage.py setup_default_permissions

# 5. Set up initial data
railway run python manage.py setup_initial_data --username admin --email admin@ezyschool.app --password changeme123

# 6. Warm permission cache
railway run python manage.py warm_permission_cache
```

## Setting up School Data

After the basic setup, you'll need to create a school and populate it with default data:

```bash
# Option 1: Through admin panel (recommended)
# 1. Go to https://your-app.railway.app/admin/
# 2. Create a new School
# 3. Note the School ID from the URL
# 4. Run the default data creation:
railway run python manage.py create_default_data --school-id <school_id>

# Option 2: Check available management commands
railway run python manage.py help
```

## Default Credentials (change after first login!)
- **Username:** admin
- **Email:** admin@ezyschool.app  
- **Password:** changeme123

## Environment Variables (optional, set in Railway dashboard)
You can customize the superuser by setting these environment variables in Railway:
- `DJANGO_SUPERUSER_USERNAME=your_admin_username`
- `DJANGO_SUPERUSER_EMAIL=your_admin@email.com`
- `DJANGO_SUPERUSER_PASSWORD=your_secure_password`

## Quick Start Guide
1. Run the setup script: `railway run bash setup-railway-environment.sh`
2. Access the admin panel at: `https://your-app.railway.app/admin/`
3. Log in with the default credentials
4. Create a new School in the admin panel
5. Run school data setup: `railway run python manage.py create_default_data --school-id <id>`
6. **Change the default password immediately!**