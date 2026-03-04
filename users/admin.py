from django.contrib import admin
from django.utils import timezone
from .models import (
    User,
    SpecialPrivilege,
    RoleDefaultPrivilege,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """
    Admin configuration for User (django-tenant-users UserProfile)
    
    Note: User inherits from UserProfile which doesn't have the same fields
    as Django's default User model. We use ModelAdmin instead of UserAdmin.
    """
    
    list_display = ('email', 'username', 'id_number', 'first_name', 'last_name', 'account_type', 'role', 'is_active')
    list_filter = ('is_active', 'account_type', 'role')
    search_fields = ('email', 'username', 'id_number', 'first_name', 'last_name')
    
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'id_number', 'gender', 'account_type', 'photo')}),
        ('Permissions', {
            'fields': ('is_active', 'role', 'is_default_password', 'last_password_updated')
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'id_number', 'first_name', 'last_name', 'account_type', 'role', 'password'),
        }),
    )
    
    readonly_fields = ('last_password_updated',)
    ordering = ('email',)
    filter_horizontal = ()


@admin.register(SpecialPrivilege)
class SpecialPrivilegeAdmin(admin.ModelAdmin):
    """
    Admin for granting/revoking special privileges to users.
    
    Allows:
    - Granting temporary elevated access
    - Setting expiration dates for automatic revocation
    - Tracking who granted what privilege and when
    """
    list_display = ('user', 'code', 'granted_by', 'granted_at', 'expires_at', 'is_active')
    list_filter = ('code', 'granted_at', 'expires_at')
    search_fields = ('user__email', 'user__id_number', 'code')
    readonly_fields = ('id', 'granted_at')
    date_hierarchy = 'granted_at'
    
    fieldsets = (
        (None, {'fields': ('user', 'code')}),
        ('Grant Info', {
            'fields': ('granted_by', 'granted_at'),
            'classes': ('wide',),
        }),
        ('Expiration', {
            'fields': ('expires_at',),
            'description': 'Leave blank for permanent grant. Otherwise, privilege auto-revokes after date.',
        }),
        ('Notes', {'fields': ('notes',), 'classes': ('wide',)}),
    )
    
    def is_active(self, obj):
        """Show if privilege is currently active (not expired)"""
        if obj.expires_at is None:
            return True
        return obj.expires_at > timezone.now()
    is_active.boolean = True
    is_active.short_description = "Currently Active"
    
    def save_model(self, request, obj, form, change):
        """Auto-fill granted_by on creation"""
        if not change:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(RoleDefaultPrivilege)
class RoleDefaultPrivilegeAdmin(admin.ModelAdmin):
    """
    Admin for defining default privileges per role.
    
    Read-mostly - populated via migration. Allows manual adjustments
    for role privilege configuration.
    """
    list_display = ('role', 'privilege_code', 'account_types_display')
    list_filter = ('role', 'privilege_code')
    search_fields = ('role', 'privilege_code', 'notes')
    readonly_fields = ('id',)
    
    fieldsets = (
        (None, {'fields': ('role', 'privilege_code')}),
        ('Scope', {
            'fields': ('applies_to_account_types',),
            'description': 'Which account types this privilege applies to (empty = all)',
        }),
        ('Notes', {'fields': ('notes',), 'classes': ('wide',)}),
    )
    
    def account_types_display(self, obj):
        """Display account types in readable format"""
        if not obj.applies_to_account_types:
            return "All account types"
        return ", ".join(obj.applies_to_account_types)
    account_types_display.short_description = "Applies To"