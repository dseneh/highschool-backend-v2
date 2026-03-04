import os

import requests
from django.conf import settings
from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from rest_framework.response import Response



def delete_old_file(instance, model, field_name="logo"):
    """
    Delete the old file for a given field if it has changed.
    Works with both local filesystem and cloud storage backends (S3, etc.)
    """
    if not instance.pk:
        return  # Skip if the instance is being created
    try:
        old_instance = model.objects.get(pk=instance.pk)
        old_file = getattr(old_instance, field_name)
        new_file = getattr(instance, field_name)
        
        if old_file and old_file != new_file:
            # Use storage backend's delete method (works with cloud storage)
            # This is storage-agnostic and works with local, S3, Railway Storage, etc.
            if old_file.name:
                try:
                    old_file.delete(save=False)
                except Exception as e:
                    # Log but don't fail if deletion fails
                    # File might already be deleted or not exist
                    pass
    except model.DoesNotExist:
        pass


def set_default_image(
    instance,
    created,
    instance_upload,
    field_name="logo",
    default_img_path="/images/logo.png",
    id_field="id_number",
    extension="png",
):
    """
    Set a default image for an instance if none is provided.
    """
    if created and not getattr(instance, field_name):
        store_default_image(
            instance, instance_upload, field_name, default_img_path, id_field, extension
        )


def store_default_image(
    instance, instance_upload, field_name, default_img_path, id_field, extension
):
    """
    Store a default image for an instance.
    Works with both local filesystem and cloud storage backends.
    """
    from django.core.files.storage import default_storage
    
    # Try to get the default image from storage
    # This works with both local and cloud storage
    if default_storage.exists(default_img_path):
        img_path = instance_upload(
            instance, f"{getattr(instance, id_field)}.{extension}"
        )
        with default_storage.open(default_img_path, "rb") as default_logo_file:
            getattr(instance, field_name).save(
                img_path, File(default_logo_file), save=True
            )


# def update_model_image(instance, field_name, uploaded_file, tenant_upload_func, default_image_path="images/default.jpg"):
#     """
#     Sets an image field on a model instance.
#     If uploaded_file is provided, saves it to the field using the tenant upload function.
#     Otherwise, uploads the default image to the tenant's location and saves it to the field.
#     The image name will be based on the instance's id or id_number if available.
#     Args:
#         instance: The model instance to update.
#         field_name: The name of the image field.
#         uploaded_file: The file provided by the user (or None).
#         tenant_upload_func: A function that returns the upload path for the file.
#         default_image_path: Path to the default image (relative to MEDIA_ROOT).
#     """

#     # Determine the image name (prefer id_number, fallback to id, fallback to 'new')
#     image_name = getattr(instance, 'id_number', None) or getattr(instance, 'id', None) or 'new'
#     if uploaded_file:
#         filename = tenant_upload_func(instance, f"{image_name}{os.path.splitext(uploaded_file.name)[-1]}")
#         getattr(instance, field_name).save(filename, uploaded_file, save=False)
#     else:
#         default_path = os.path.join(settings.MEDIA_ROOT, default_image_path)
#         with open(default_path, "rb") as f:
#             django_file = File(f)
#             filename = tenant_upload_func(instance, f"{image_name}.png")
#             getattr(instance, field_name).save(filename, django_file, save=False)
#     instance.save(update_fields=[field_name])
def update_model_image(
    instance,
    field_name,
    uploaded_file,
    default_image_path="images/default.jpg",
):
    """
    Update a model's image field with uploaded file or default image.
    Uses the model field's upload_to callable for tenant-aware storage.
    
    Args:
        instance: Model instance to update
        field_name: Name of the image field (e.g., "photo")
        uploaded_file: File to upload (can be File object, UploadedFile, or URL string)
        default_image_path: Path to default image if uploaded_file is None
    """
    media_root = str(settings.MEDIA_ROOT)
    image_name = (
        f"{getattr(instance, 'id_number', getattr(instance, 'id', 'unknown'))}.jpg"
    )
    
    # Get the field's upload_to callable from the model
    field = instance._meta.get_field(field_name)
    if hasattr(field, 'upload_to') and callable(field.upload_to):
        image_path = field.upload_to(instance, image_name)
    else:
        # Fallback to simple path if no upload_to callable
        image_path = image_name

    file_saved = False
    # Handle file upload from URL or file
    if uploaded_file:
        if isinstance(uploaded_file, str) and uploaded_file.startswith(
            ("http://", "https://")
        ):
            # Download image from URL
            try:
                response = requests.get(uploaded_file, stream=True, timeout=10)
                response.raise_for_status()
                temp_img = NamedTemporaryFile(delete=True)
                for chunk in response.iter_content(1024):
                    temp_img.write(chunk)
                temp_img.flush()
                temp_img.seek(0)
                django_file = File(temp_img, name=image_name)
                getattr(instance, field_name).save(image_path, django_file, save=False)
                file_saved = True
            except Exception:
                file_saved = False
        else:
            # Assume it's a file-like object (UploadedFile, etc.)
            getattr(instance, field_name).save(image_path, uploaded_file, save=False)
            file_saved = True
    if not file_saved:
        # Use storage backend to handle default images (works with cloud storage)
        from django.core.files.storage import default_storage
        
        # Ensure default_image_path is always relative (no leading slash or backslash)
        default_image_path = default_image_path.lstrip("/\\")
        
        if not default_storage.exists(default_image_path):
            raise FileNotFoundError(
                f"Default image not found at {default_image_path}. Check that the file exists in storage."
            )
        
        with default_storage.open(default_image_path, "rb") as f:
            django_file = File(f)
            getattr(instance, field_name).save(image_path, django_file, save=False)
    
    instance.save(update_fields=[field_name])
