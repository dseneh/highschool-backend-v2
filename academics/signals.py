from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
import logging

from common.images import delete_old_file, set_default_image
from core.models import Tenant
from academics.services import (
    purge_schedule_projections_for_class_schedule,
    sync_schedule_projections_for_class_schedule,
)

logger = logging.getLogger(__name__)

# Simple upload function for tenant logo
def tenant_logo_upload(instance, filename):
    """Generate upload path for tenant logo"""
    return f"logo/{filename}"

# Signal to handle default logo upload and replacement
@receiver(post_save, sender=Tenant)
def upload_default_logo(sender, instance, created, **kwargs):
    set_default_image(
        instance,
        created,
        tenant_logo_upload,
        field_name="logo",
        default_img_path="images/logo.png",
        id_field="id_number",
        extension="png",
    )


@receiver(pre_save, sender=Tenant)
def replace_logo(sender, instance, **kwargs):
    delete_old_file(
        instance,
        Tenant,
        field_name="logo",
    )
    # if not instance.pk:
    #     return  # Skip if the instance is being created
    # try:
    #     old_instance = Tenant.objects.get(pk=instance.pk)
    #     if old_instance.logo and old_instance.logo != instance.logo:
    #         # Delete the old logo file
    #         if os.path.isfile(old_instance.logo.path):
    #             os.remove(old_instance.logo.path)
    # except School.DoesNotExist:
    #     pass


@receiver(post_save, sender=Tenant)
def setup_tenant_defaults(sender, instance, created, **kwargs):
    """
    Signal handler to set up default data for a newly created tenant.
    This is triggered after a Tenant is created and saved.
    
    Note: The tenant creation itself is already committed when this runs.
    However, the default data creation is wrapped in a transaction, so
    either ALL defaults are created or NONE are (atomic rollback).
    
    If default data creation fails, the tenant will exist but be empty.
    This is intentional - it's better to have an empty tenant than to
    fail tenant creation entirely (which could leave orphaned schemas).
    """
    if not created:
        return
    
    # Skip default data creation for public tenant
    if instance.schema_name == 'public':
        logger.info("Skipping default data creation for public tenant")
        return
    
    # Import here to avoid circular imports
    from django_tenants.utils import schema_context
    from defaults import setup_tenant_defaults as create_defaults
    from users.models import User
    from common.status import UserAccountType
    
    logger.info(f"Tenant created: {instance.name} (schema: {instance.schema_name})")
    
    # We need to work within the tenant's schema to create default data
    try:
        with schema_context(instance.schema_name):
            logger.info(f"Setting up defaults for tenant: {instance.name}")
            
            # Find a superuser or system admin to use as creator
            # Try to find GLOBAL users (admin users that can access all tenants)
            creator = User.objects.filter(
                account_type=UserAccountType.GLOBAL
            ).first()
            
            if not creator:
                # Fallback: try to find the owner
                if hasattr(instance, 'owner'):
                    creator = instance.owner
            
            if not creator:
                # Fallback: try to find any superuser
                creator = User.objects.filter(is_superuser=True).first()
            
            if not creator:
                logger.warning(
                    f"No user found for tenant {instance.name}. "
                    "Skipping default data creation. "
                    "You'll need to create defaults manually."
                )
                return
            
            # Create default data using the Tenant instance
            # This is wrapped in @transaction.atomic in setup_tenant_defaults
            # so either ALL defaults are created or NONE are
            create_defaults(instance, creator)
            
            logger.info(f"Default data successfully created for tenant: {instance.name}")
            
    except Exception as e:
        logger.error(
            f"Failed to create default data for tenant {instance.name}: {e}",
            exc_info=True
        )
        # Don't re-raise - we don't want to prevent tenant creation
        # The tenant exists but will be empty (no default data)
        # You can manually run setup_tenant_defaults(tenant, user) later


# DISABLED: Gradebook creation now happens in bulk_create_section_subjects (supporting_adapter.py)
# This ensures atomic transaction - if gradebook creation fails, SectionSubject creation is rolled back
# Signal approach was problematic because:
# 1. Transaction boundaries unclear - SectionSubject could be saved even if gradebook fails
# 2. Harder to debug - signal runs in separate context
# 3. No transaction rollback - leads to inconsistent state
#
# @receiver(post_save, sender='academics.SectionSubject')
# def auto_create_gradebook_for_section_subject(sender, instance, created, **kwargs):
#     """[DISABLED] Gradebook creation moved to view for atomic transaction handling"""
#     pass


@receiver(post_save, sender="academics.SectionSchedule")
def sync_schedule_projections_on_schedule_save(sender, instance, **kwargs):
    sync_schedule_projections_for_class_schedule(instance)


@receiver(post_delete, sender="academics.SectionSchedule")
def purge_schedule_projections_on_schedule_delete(sender, instance, **kwargs):
    purge_schedule_projections_for_class_schedule(str(instance.id))


@receiver(post_save, sender="staff.TeacherSubject")
@receiver(post_delete, sender="staff.TeacherSubject")
def sync_schedule_projections_on_teacher_assignment_change(sender, instance, **kwargs):
    section_subject_id = getattr(instance, "section_subject_id", None)
    if not section_subject_id:
        return

    from academics.models import SectionSchedule

    schedules = SectionSchedule.objects.filter(subject_id=section_subject_id, active=True)
    for schedule in schedules:
        sync_schedule_projections_for_class_schedule(schedule)


@receiver(post_save, sender="students.Enrollment")
@receiver(post_delete, sender="students.Enrollment")
def sync_schedule_projections_on_enrollment_change(sender, instance, **kwargs):
    section_id = getattr(instance, "section_id", None)
    if not section_id:
        return

    from academics.models import SectionSchedule

    schedules = SectionSchedule.objects.filter(section_id=section_id, active=True)
    for schedule in schedules:
        sync_schedule_projections_for_class_schedule(schedule)
