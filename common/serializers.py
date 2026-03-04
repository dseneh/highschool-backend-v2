"""
Common serializer mixins and utilities for reusable serializer functionality.
"""


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
