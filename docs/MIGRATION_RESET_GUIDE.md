# Migration Reset Guide

## ✅ Completed Steps

1. ✅ Deleted all old migration files (kept `__init__.py`)
2. ✅ Cleaned up models (removed Permission, Role, UserRole, RolePermission)

## 📋 Next Steps

### Step 1: Create Fresh Initial Migration

Run this command to create a new initial migration:

```bash
python manage.py makemigrations users --name initial
```

This will create `users/migrations/0001_initial.py` with only the CustomUser model (no permission/role tables).

### Step 2: Handle Database Migration

You have two options depending on your situation:

#### Option A: Fresh Database (No Existing Data)

If you're starting fresh or can drop/recreate the database:

```bash
python manage.py migrate users
```

#### Option B: Existing Database (Has Data)

If you have existing user data that you want to keep:

1. **First, backup your database!**

   ```bash
   # PostgreSQL example
   pg_dump your_database > backup.sql

   # SQLite example
   cp db.sqlite3 db.sqlite3.backup
   ```

2. **Fake the initial migration** (tells Django the tables already exist):

   ```bash
   python manage.py migrate users --fake-initial
   ```

3. **If you have permission/role tables in your database**, you'll need to drop them manually:
   ```sql
   -- PostgreSQL
   DROP TABLE IF EXISTS auth_role_permissions CASCADE;
   DROP TABLE IF EXISTS auth_user_roles CASCADE;
   DROP TABLE IF EXISTS auth_roles CASCADE;
   DROP TABLE IF EXISTS auth_permissions CASCADE;
   ```

### Step 3: Verify

Check that everything works:

```bash
# Check migration status
python manage.py showmigrations users

# Should show:
# users
#  [X] 0001_initial
```

## ⚠️ Important Notes

1. **Foreign Keys**: All foreign keys pointing to `users.user` remain intact - no code changes needed!

2. **Database State**: Make sure your database schema matches your models before faking migrations

3. **Other Apps**: Other apps' migrations that depend on users app will need to reference the new initial migration

4. **Testing**: Test thoroughly after migration reset to ensure everything works

## 🔍 Troubleshooting

### If you get "Table already exists" errors:

- Use `--fake-initial` flag
- Or manually drop the users tables and recreate

### If foreign key constraints fail:

- Make sure all related tables exist
- Check that `core.School` table exists (CustomUser has FK to School)

### If migration dependencies fail:

- Check other apps' migrations that depend on users
- You may need to update their dependencies to point to the new initial migration
