"""Custom managers and querysets for Staff model"""

from django.db.models import QuerySet, Q
from django.db.models.manager import Manager


class StaffQuerySet(QuerySet):
    """Custom queryset with optimized queries and filters"""

    def with_relations(self):
        """Optimized queryset with all related objects"""
        return self.select_related(
            "position", "primary_department"
        ).prefetch_related("classes__section", "subjects__subject")

    def with_full_relations(self):
        """Even more optimized queryset with all relations for detail views"""
        return self.select_related(
            "position", "primary_department"
        ).prefetch_related(
            "classes__section", "subjects__subject", "schedules__class_schedule"
        )

    def active(self):
        """Filter active staff"""
        return self.filter(status="active")

    def by_status(self, status_list):
        """Filter by status list"""
        if isinstance(status_list, str):
            status_list = [s.strip() for s in status_list.split(",")]
        return self.filter(status__in=status_list)

    def by_position(self, position_id):
        """Filter by position"""
        return self.filter(position_id=position_id)

    def search(self, query):
        """Search staff by name, email, or ID number"""
        if not query:
            return self

        return self.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(middle_name__icontains=query)
            | Q(user_account_id_number__icontains=query)
            | Q(email__icontains=query)
            | Q(id_number__icontains=query)
        )

    def order_by_default(self, ordering=None):
        """Apply default or custom ordering"""
        if ordering:
            return self.order_by(ordering)
        return self.order_by("-created_at")


# Use Manager.from_queryset to automatically make all queryset methods available on manager
# This creates a manager class that has all methods from StaffQuerySet
StaffManager = Manager.from_queryset(StaffQuerySet)

