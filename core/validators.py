"""
Validators for core app
"""

import os
from django.core.exceptions import ValidationError
from PIL import Image


class ValidateImageFile:
    """
    Validator for image file uploads.
    Checks file extension, MIME type, and file size.
    """
    allowed_extensions = ["jpg", "jpeg", "png"]
    allowed_mime_types = ["image/jpeg", "image/png"]
    max_size = 5 * 1024 * 1024  # 5 MB in bytes

    def __call__(self, file):
        ext = os.path.splitext(file.name)[1].lower().lstrip(".")
        if ext not in self.allowed_extensions:
            raise ValidationError(f"Unsupported file extension: .{ext}")

        try:
            img = Image.open(file)
            mime_type = Image.MIME.get(img.format)
            if mime_type not in self.allowed_mime_types:
                raise ValidationError(f"Invalid image MIME type: {mime_type}")
        except Exception:
            raise ValidationError("Uploaded file is not a valid image.")

        if file.size > self.max_size:
            raise ValidationError("Image file too large (max 5MB).")

