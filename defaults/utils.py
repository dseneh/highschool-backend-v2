"""
Utility functions for the defaults app.

This module provides easy-to-use functions for setting up default tenant data.
"""

import os
import shutil
from django.conf import settings
from .run import run_data_creation


def copy_default_media_files(tenant):
    """
    Copy default media files (like default profile images) to the tenant's media folder.
    
    Args:
        tenant: Tenant model instance
        
    Returns:
        bool: True if successful
    """
    try:
        # Source directory for default files (in the main media folder or a templates folder)
        source_base = os.path.join(settings.MEDIA_ROOT, 'defaults')
        
        # Tenant's media directory
        tenant_media = os.path.join(settings.MEDIA_ROOT, tenant.schema_name)
        
        # Create tenant media directory if it doesn't exist
        os.makedirs(tenant_media, exist_ok=True)
        
        # Copy default images if source exists
        if os.path.exists(source_base):
            # Copy the entire defaults directory structure
            for root, dirs, files in os.walk(source_base):
                # Get relative path from source_base
                rel_path = os.path.relpath(root, source_base)
                
                # Create corresponding directory in tenant media
                if rel_path != '.':
                    dest_dir = os.path.join(tenant_media, rel_path)
                else:
                    dest_dir = tenant_media
                    
                os.makedirs(dest_dir, exist_ok=True)
                
                # Copy all files
                for file in files:
                    src_file = os.path.join(root, file)
                    dest_file = os.path.join(dest_dir, file)
                    shutil.copy2(src_file, dest_file)
                    
            print(f"Copied default media files to {tenant.schema_name}")
        else:
            # If no defaults folder exists, create default images directory
            images_dir = os.path.join(tenant_media, 'images')
            os.makedirs(images_dir, exist_ok=True)
            print(f"Created media directories for {tenant.schema_name}")
            
        return True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to copy default media files for tenant {tenant.schema_name}: {e}")
        # Don't fail tenant creation if this fails
        return False


def setup_tenant_defaults(tenant, user):
    """
    Set up default data for a newly created tenant.

    This is a wrapper around run_data_creation that provides a cleaner API
    for other parts of the application to use.

    Args:
        tenant: Tenant model instance
        user: User model instance (the creator/admin)

    Returns:
        bool: True if successful

    Raises:
        Exception: If any default data creation fails

    Example:
        from defaults.utils import setup_tenant_defaults

        # After creating a tenant
        try:
            success = setup_tenant_defaults(new_tenant, admin_user)
            print("Default data created successfully")
        except Exception as e:
            print(f"Failed to create default data: {e}")
    """
    try:
        # First, copy default media files
        copy_default_media_files(tenant)
        
        # Then run data creation
        run_data_creation(tenant, user)
        return True
    except Exception as e:
        # Re-raise with more context to ensure proper rollback
        raise Exception(f"Failed to create default data: {str(e)}")


def get_default_data_info():
    """
    Get information about what default data will be created.

    Returns:
        dict: Dictionary containing information about default data
    """
    return {
        "academic_year": "Current academic year with start/end dates",
        "semesters": "Two semesters with appropriate date ranges",
        "marking_periods": "Grading periods within semesters",
        "divisions": "School divisions (Preschool, Elementary, etc.)",
        "grade_levels": "Grade levels from Nursery 1 to Grade 12",
        "sections": "Class sections for each grade level",
        "subjects": "Academic subjects for different grade levels",
        "section_subjects": "Links between sections and subjects",
        "periods": "Daily school periods",
        "period_times": "Time slots for each period",
        # Finance models (TODO: Add when finance app is migrated)
        # "currency": "Default currency (Liberian Dollar)",
        # "payment_methods": "Various payment methods (Cash, Mobile Money, etc.)",
        # "transaction_types": "Income and expense transaction types",
        # "fees": "Standard school fees (Registration, Library, Lab, etc.)",
        # "section_fees": "Fee assignments to sections",
    }
