"""
Multi-tenant aware storage backends
Supports S3-compatible storage (Cloudflare R2, AWS S3) with tenant-aware paths
"""

from django.conf import settings
from django.db import connection
from storages.backends.s3 import S3Storage


class TenantAwareS3Storage(S3Storage):
    """
    S3/R2 Storage backend that automatically prefixes paths with schema name.
    
    File paths in S3/R2:
    - Public schema: public/users/<user_id>.jpg
    - Tenant schemas: tenants/<schema_name>/students/<student_id>.jpg
    
    Reference: https://github.com/andyjud/tenants
    """
    
    def _get_schema_prefix(self):
        """Get prefix based on current schema"""
        schema_name = connection.schema_name
        
        if schema_name == 'public':
            return 'public'
        
        return f'tenants/{schema_name}'
    
    def _normalize_name(self, name):
        """
        Override to add schema prefix to all file paths.
        This ensures tenant isolation in S3/R2 storage.
        """
        # Get base path from storage
        prefix = self._get_schema_prefix()
        
        # If name already has prefix, don't double-add
        if name.startswith('tenants/') or name.startswith('public/'):
            return name
        
        # Add schema prefix
        return f"{prefix}/{name}" if prefix else name

