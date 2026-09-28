"""Identity and editable fields for employee self-service."""
from django.db.models import Q
from hr.models import Employee

PERSONAL_FIELDS = {
    "first_name", "middle_name", "last_name", "gender", "date_of_birth",
    "place_of_birth", "email", "phone_number", "address", "city", "state",
    "postal_code", "country",
}


def own_employee_queryset(user):
    identifier = getattr(user, "id_number", None)
    if not identifier:
        return Employee.objects.none()
    return Employee.objects.filter(
        Q(user_account_id_number=identifier)
        | ((Q(user_account_id_number="") | Q(user_account_id_number__isnull=True)) & Q(id_number=identifier))
    )
