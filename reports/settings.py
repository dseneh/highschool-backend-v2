"""
Reports app configuration and settings
"""

from django.conf import settings

# Default settings for reports app
REPORTS_SETTINGS = {
    # Background processing threshold
    'BACKGROUND_THRESHOLD': 5000,  # Records count to trigger background processing
    
    # Cache settings
    'CACHE_TIMEOUT': 300,  # 5 minutes default cache timeout
    'TASK_CACHE_TIMEOUT': 3600,  # 1 hour for task data
    
    # Task processing
    'MAX_SYNC_RECORDS': 5000,  # Maximum records for synchronous processing
    'CHUNK_SIZE': 1000,  # Processing chunk size for background tasks
    
    # Export settings
    'EXPORT_FORMATS': ['json', 'csv', 'excel'],
    'MAX_EXPORT_RECORDS': 100000,  # Maximum records for exports
    
    # File storage (for future file exports)
    'EXPORT_STORAGE_PATH': 'reports/exports/',
    'EXPORT_FILE_RETENTION_HOURS': 24,
}

def get_reports_setting(key: str, default=None):
    """Get a reports setting with fallback to defaults"""
    # Check Django settings first
    if hasattr(settings, f'REPORTS_{key}'):
        return getattr(settings, f'REPORTS_{key}')
    
    # Fallback to app defaults
    return REPORTS_SETTINGS.get(key, default)


# Export to be used by other modules
REPORT_BACKGROUND_THRESHOLD = get_reports_setting('BACKGROUND_THRESHOLD')
REPORT_CACHE_TIMEOUT = get_reports_setting('CACHE_TIMEOUT')
REPORT_TASK_CACHE_TIMEOUT = get_reports_setting('TASK_CACHE_TIMEOUT')
MAX_SYNC_RECORDS = get_reports_setting('MAX_SYNC_RECORDS')
CHUNK_SIZE = get_reports_setting('CHUNK_SIZE')
