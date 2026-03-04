# Scripts Directory

This directory contains utility scripts for deployment, database operations, and system maintenance.

## 🚀 Deployment Scripts

- **`build.sh`** - Main build script for production deployment
- **`build-railway.sh`** - Railway-specific build script
- **`build_fresh_db.sh`** - Fresh database build script
- **`build_python.py`** - Python environment build script
- **`deploy-fly.sh`** - Fly.io deployment script
- **`migrate_to_railway.sh`** - Railway migration script
- **`setup-fly.sh`** - Fly.io setup script
- **`setup_fresh_db.sh`** - Fresh database setup

## 📊 Database & Migration Scripts

- **`migrate_data.py`** - Main data migration script
- **`migrate_data_template.py`** - Template for data migration (safe for repo)
- **`create_cache_table.py`** - Cache table creation script
- **`fix_sequence_sync.py`** - Database sequence synchronization
- **`fix_student_sequences.py`** - Student sequence number fixes

## 🔧 Optimization & Performance

- **`memory_optimization.py`** - Memory optimization utilities
- **`query_optimization_guide.py`** - Database query optimization
- **`monitor_system_memory.sh`** - System memory monitoring

## 🧪 Testing Scripts

- **`test_memory.sh`** - Memory testing script
- **`test_memory_fixes.py`** - Memory fix testing
- **`test_memory_local.py`** - Local memory testing
- **`test_memory_middleware.py`** - Memory middleware testing
- **`test_compression_memory.py`** - Compression memory testing
- **`test_comprehensive_memory.py`** - Comprehensive memory testing
- **`test_url_sanitization.py`** - URL sanitization testing

## 📤 Upload & Export Scripts

- **`upload.sh`** - File upload script
- **`upload_remote.sh`** - Remote upload script
- **`export_data.sh`** - Data export script

## ⚠️ Important Notes

- Some scripts contain platform-specific configurations
- Always review scripts before running in production
- Database scripts should be tested in staging first
- Memory optimization scripts require careful monitoring

## 🔐 Security

- Migration scripts with real credentials are excluded from git
- Only template scripts are committed to version control
- Always use environment variables for sensitive data
