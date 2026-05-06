"""
Common serializer mixins and utilities for reusable serializer functionality.
"""
from rest_framework import serializers

from auditlog.models import LogEntry


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for django-auditlog LogEntry records."""

    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)
    actor_username = serializers.CharField(source="actor.username", read_only=True, default=None)
    actor_id_number = serializers.CharField(source="actor.id_number", read_only=True, default=None)
    actor_name = serializers.SerializerMethodField()
    actor_photo = serializers.SerializerMethodField()
    actor_display = serializers.SerializerMethodField()
    content_type_name = serializers.SerializerMethodField()

    class Meta:
        model = LogEntry
        fields = [
            "id",
            "content_type",
            "content_type_name",
            "object_id",
            "object_repr",
            "action",
            "changes",
            "actor",
            "actor_email",
            "actor_username",
            "actor_id_number",
            "actor_name",
            "actor_photo",
            "actor_display",
            "remote_addr",
            "timestamp",
            "additional_data",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj) -> str | None:
        actor = getattr(obj, "actor", None)
        if not actor:
            return None

        full_name = f"{getattr(actor, 'first_name', '')} {getattr(actor, 'last_name', '')}".strip()
        return full_name or None

    def get_actor_photo(self, obj) -> str | None:
        actor = getattr(obj, "actor", None)
        if not actor or not getattr(actor, "photo", None):
            return None

        request = self.context.get("request")
        try:
            photo_url = actor.photo.url
        except Exception:
            return None

        if request:
            return request.build_absolute_uri(photo_url)
        return photo_url

    def get_actor_display(self, obj) -> str:
        actor = getattr(obj, "actor", None)
        if not actor:
            return "System"

        full_name = self.get_actor_name(obj)
        return (
            full_name
            or
            getattr(actor, "id_number", None)
            or getattr(actor, "email", None)
            or getattr(actor, "username", None)
            or str(getattr(actor, "id", ""))
            or "System"
        )

    def get_content_type_name(self, obj) -> str:
        ct = obj.content_type
        if ct:
            return f"{ct.app_label}.{ct.model}"
        return ""


class PhotoURLMixin:
    """
    Mixin to add photo URL building logic to serializers.
    
    Automatically converts photo paths to absolute URLs, handling:
    - Tenant-aware media paths
    - Relative vs absolute paths
    - Default fallback images
    
    Usage:
        class MySerializer(PhotoURLMixin, serializers.ModelSerializer):
            class Meta:
                model = MyModel
                fields = ['id', 'name', 'photo', ...]
    """
    
    def build_photo_url(self, photo_path, request=None):
        """
        Build an absolute URL for a photo path.
        
        Args:
            photo_path: The photo field value (can be relative or absolute)
            request: Optional request object for building absolute URIs
            
        Returns:
            str: Absolute URL for the photo
        """
        if not photo_path:
            return photo_path
            
        # If it's already a full URL, return as-is
        if photo_path.startswith(('http://', 'https://', '//')):
            return photo_path
            
        # Add leading slash if not present
        if not photo_path.startswith('/'):
            photo_path = f'/{photo_path}'
            
        # Build absolute URI if request is available
        if request:
            return request.build_absolute_uri(photo_path)
        
        # Fallback: prepend /media/ if not already there
        if not photo_path.startswith('/media/'):
            return f'/media{photo_path}'
        
        return photo_path
    
    def to_representation(self, instance):
        """
        Override to_representation to automatically handle photo URL building.
        Subclasses should call super().to_representation(instance) to get this behavior.
        """
        response = super().to_representation(instance)
        request = self.context.get("request")
        
        # Build absolute URL for photo if it exists
        if response.get("photo"):
            response["photo"] = self.build_photo_url(response["photo"], request)
            
        return response
