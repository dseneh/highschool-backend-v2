from django.contrib import admin
from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """
    Admin configuration for User (django-tenant-users UserProfile)
    
    Note: User inherits from UserProfile which doesn't have the same fields
    as Django's default User model. We use ModelAdmin instead of UserAdmin.
    """
    
    list_display = ('email', 'username', 'id_number', 'first_name', 'last_name', 'account_type', 'is_active')
    list_filter = ('is_active', 'account_type')
    search_fields = ('email', 'username', 'id_number', 'first_name', 'last_name')
    
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'id_number', 'gender', 'account_type', 'photo')}),
        ('Permissions', {
            'fields': ('is_active', 'is_default_password', 'last_password_updated')
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'id_number', 'first_name', 'last_name', 'account_type', 'password'),
        }),
    )
    
    readonly_fields = ('last_password_updated',)
    ordering = ('email',)
    filter_horizontal = ()


# RBAC roles and permissions are administered by the authorization app.
