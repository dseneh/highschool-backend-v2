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
    STORAGES = {
        "default": {
            "BACKEND": "core.storage.TenantAwareS3Storage",
            "OPTIONS": {
                "bucket_name": config("AWS_STORAGE_BUCKET_NAME", default=""),
                "access_key": config("AWS_ACCESS_KEY_ID", default=""),
                "secret_key": config("AWS_SECRET_ACCESS_KEY", default=""),
                "endpoint_url": config("AWS_S3_ENDPOINT_URL", default=None),
                "region_name": config("AWS_S3_REGION_NAME", default="auto"),
                "file_overwrite": False,
                "default_acl": "public-read",
                "custom_domain": config("AWS_S3_CUSTOM_DOMAIN", default=None),
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    
    # AWS Settings (used by django-storages)
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="")
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
    AWS_S3_ENDPOINT_URL = config("AWS_S3_ENDPOINT_URL", default=None)
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="auto")
    AWS_S3_CUSTOM_DOMAIN = config("AWS_S3_CUSTOM_DOMAIN", default=None)
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

