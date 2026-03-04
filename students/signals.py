from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
import logging

from users.models import User

logger = logging.getLogger(__name__)
User = get_user_model()


# ============================================================================
# Guardian → Contact Auto-Sync
# ============================================================================

# Map guardian relationship → contact relationship
GUARDIAN_TO_CONTACT_RELATIONSHIP = {
    "father": "parent",
    "mother": "parent",
    "stepfather": "parent",
    "stepmother": "parent",
    "grandfather": "relative",
    "grandmother": "relative",
    "uncle": "relative",
    "aunt": "relative",
    "legal_guardian": "guardian",
    "foster_parent": "guardian",
    "other": "guardian",
}


@receiver(post_save, sender="students.StudentGuardian")
def sync_guardian_to_contact(sender, instance, created, **kwargs):
    """
    When a guardian is created or updated, upsert a matching StudentContact.
    The contact is linked via meta.guardian_id to avoid duplicates.
    """
    from students.models import StudentContact

    contact_rel = GUARDIAN_TO_CONTACT_RELATIONSHIP.get(
        instance.relationship, "guardian"
    )

    defaults = {
        "first_name": instance.first_name,
        "last_name": instance.last_name,
        "relationship": contact_rel,
        "phone_number": instance.phone_number,
        "email": instance.email,
        "address": instance.address,
        "is_primary": instance.is_primary,
        "is_emergency": instance.is_primary,  # primary guardians are emergency contacts
        "photo": instance.photo,
        "notes": instance.notes,
    }

    try:
        # Look up by guardian_id stored in meta
        contact = StudentContact.objects.filter(
            student=instance.student,
            meta__guardian_id=str(instance.id),
        ).first()

        if contact:
            for field, value in defaults.items():
                setattr(contact, field, value)
            contact.save(update_fields=list(defaults.keys()))
            logger.info(f"Synced guardian {instance.id} → contact {contact.id}")
        else:
            contact = StudentContact.objects.create(
                student=instance.student,
                meta={"guardian_id": str(instance.id)},
                **defaults,
            )
            logger.info(f"Created contact {contact.id} from guardian {instance.id}")
    except Exception as e:
        logger.error(f"Error syncing guardian {instance.id} to contact: {e}", exc_info=True)


@receiver(post_delete, sender="students.StudentGuardian")
def delete_synced_contact(sender, instance, **kwargs):
    """When a guardian is deleted, also delete its synced contact."""
    from students.models import StudentContact

    try:
        deleted_count, _ = StudentContact.objects.filter(
            student=instance.student,
            meta__guardian_id=str(instance.id),
        ).delete()
        if deleted_count:
            logger.info(f"Deleted synced contact for guardian {instance.id}")
    except Exception as e:
        logger.error(f"Error deleting synced contact for guardian {instance.id}: {e}")


# Signal to handle default photo upload and replacement
@receiver(post_save, sender=User)
def upload_default_photo(sender, instance, created, **kwargs):
    img = instance.photo.url if instance.photo else None

    if not instance.photo:
        print("No photo found, setting default image.")
        img = (
            f"images/default_{instance.gender}.jpg"
            if instance.gender
            else "images/default.jpg"
        )

    # set_default_image(
    #     instance,
    #     created,
    #     user_photo_upload,
    #     field_name="photo",
    #     default_img_path=img,
    #     id_field="id_number",
    #     extension="jpg",
    # )


# @receiver(pre_save, sender=School)
# def replace_photo(sender, instance, **kwargs):
#     delete_old_file(
#         instance,
#         CustomUser,
#         field_name="photo",
#     )


# ============================================================================
# Student-User Account Cascade Management
# ============================================================================


@receiver(pre_delete, sender="students.Student")
def delete_student_user_account(sender, instance, **kwargs):
    """
    When a Student is deleted, also delete the associated user account.
    This ensures that when students are removed, their login accounts are also cleaned up.

    Direction: Student deletion → User account deletion
    Note: Now uses user_account_id_number to look up user in public schema
    """
    if instance.user_account_id_number:
        from users.models import User
        
        try:
            # Look up user account by id_number (cross-schema lookup)
            user_account = User.objects.filter(id_number=instance.user_account_id_number).first()
            
            if user_account:
                logger.info(
                    f"Student {instance.id_number} being deleted - also deleting user account {user_account.username}"
                )

                # Clear the reference
                sender.objects.filter(id=instance.id).update(user_account_id_number=None)

                # Now delete the user account
                user_account.delete()

                logger.info(
                    f"Successfully deleted user account {user_account.username} for student {instance.id_number}"
                )

        except Exception as e:
            logger.error(
                f"Error deleting user account for student {instance.id_number}: {str(e)}",
                exc_info=True,
            )
            # Don't raise the exception to avoid blocking student deletion
            # The student will still be deleted even if user deletion fails


@receiver(post_delete, sender=User)
def log_user_deletion_impact(sender, instance, **kwargs):
    """
    Log when a user is deleted to track the impact on students.
    Since we store user_account_id_number (not FK), students will keep the reference
    but the user account will be gone.

    Direction: User deletion → Student keeps stale user_account_id_number
    Note: This is cross-schema, so we need to check in tenant schemas
    """
    try:
        from django_tenants.utils import schema_context
        from core.models import Tenant
        from students.models import Student
        
        # Search across all tenant schemas for students with this user's id_number
        found_students = False
        for tenant in Tenant.objects.all():
            with schema_context(tenant.schema_name):
                students = Student.objects.filter(user_account_id_number=instance.id_number)
                if students.exists():
                    found_students = True
                    for student in students:
                        logger.info(
                            f"User {instance.username} deleted - Student {student.id_number} in schema {tenant.schema_name} now has stale user reference"
                        )
        
        if not found_students:
            logger.info(
                f"User {instance.username} deleted - No associated student records found in any tenant"
            )

    except Exception as e:
        logger.error(
            f"Error logging user deletion impact for {instance.username}: {str(e)}"
        )


@receiver(pre_delete, sender=User)
def protect_critical_users(sender, instance, **kwargs):
    """
    Add protection for critical users like superusers.
    This is a safety net to prevent accidental deletion of important accounts.
    """
    if instance.is_superuser:
        logger.warning(
            f"Superuser {instance.username} is being deleted - this may impact system access"
        )

    if instance.is_staff and not instance.is_superuser:
        logger.warning(f"Staff user {instance.username} is being deleted")

    # You could add additional protection here if needed
    # For example, raise an exception to prevent deletion of certain users:
    # if instance.username == 'admin' and not getattr(instance, '_force_delete', False):
    #     raise ValueError("Cannot delete admin user without _force_delete flag")
