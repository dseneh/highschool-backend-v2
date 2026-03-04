"""
Multi-tenant storage configuration
Supports both local file storage and S3-compatible storage (e.g., Cloudflare R2)

Both storage backends automatically handle tenant-aware path prefixing,
so models can use simple upload_to paths like "logo.jpg" or "users/{id}.jpg"
"""

from decouple import config

# Storage Backend Selection
USE_S3_STORAGE = config("USE_S3_STORAGE", default=False, cast=bool)

if USE_S3_STORAGE:
    # S3-compatible storage (Cloudflare R2, AWS S3, etc.)
    # TenantAwareS3Storage automatically prefixes paths with tenant schema
    
    # Support both R2_* (Cloudflare R2) and AWS_* (generic S3) env vars
    # R2_* variables take precedence if present
    bucket_name = config("R2_BUCKET", default=config("AWS_STORAGE_BUCKET_NAME", default=""))
    access_key = config("R2_ACCESS_KEY_ID", default=config("AWS_ACCESS_KEY_ID", default=""))
    secret_key = config("R2_SECRET_ACCESS_KEY", default=config("AWS_SECRET_ACCESS_KEY", default=""))
    endpoint_url = config("R2_S3_ENDPOINT", default=config("AWS_S3_ENDPOINT_URL", default=None))
    custom_domain = config("R2_CUSTOM_DOMAIN", default=config("AWS_S3_CUSTOM_DOMAIN", default=None))
    region_name = config("AWS_S3_REGION_NAME", default="auto")
    
    STORAGES = {
        "default": {
            "BACKEND": "core.storage.TenantAwareS3Storage",
            "OPTIONS": {
                "bucket_name": bucket_name,
                "access_key": access_key,
                "secret_key": secret_key,
                "endpoint_url": endpoint_url,
                "region_name": region_name,
                "file_overwrite": False,
                "default_acl": "public-read",
                "custom_domain": custom_domain,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    
    # AWS Settings (used by django-storages)
    # Map R2 variables to AWS variables for compatibility
    AWS_STORAGE_BUCKET_NAME = bucket_name
    AWS_ACCESS_KEY_ID = access_key
    AWS_SECRET_ACCESS_KEY = secret_key
    AWS_S3_ENDPOINT_URL = endpoint_url
    AWS_S3_REGION_NAME = region_name
    AWS_S3_CUSTOM_DOMAIN = custom_domain
    AWS_DEFAULT_ACL = "public-read"
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False
else:
    # Local file storage with tenant-aware prefixing
    # TenantFileSystemStorage automatically prefixes paths with tenant schema
    STORAGES = {
        "default": {
            "BACKEND": "django_tenants.files.storage.TenantFileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

