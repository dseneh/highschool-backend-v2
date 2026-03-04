"""Staff Adapters - Database Operations"""

from .staff_adapter import (
    django_staff_to_data,
    create_staff_in_db,
    update_staff_in_db,
    delete_staff_from_db,
    check_staff_exists_by_id,
    check_staff_exists_by_email,
    check_staff_exists_by_name_dob,
    staff_has_user_account,
    staff_has_teaching_sections,
    get_staff_by_id_or_id_number,
)

from .position_adapter import (
    django_position_to_data,
    create_position_in_db,
    update_position_in_db,
    delete_position_from_db,
    position_has_staff,
)

from .department_adapter import (
    django_department_to_data,
    create_department_in_db,
    update_department_in_db,
    delete_department_from_db,
    department_has_staff,
    department_has_positions,
)

__all__ = [
    # Staff
    'django_staff_to_data',
    'create_staff_in_db',
    'update_staff_in_db',
    'delete_staff_from_db',
    'check_staff_exists_by_id',
    'check_staff_exists_by_email',
    'check_staff_exists_by_name_dob',
    'staff_has_user_account',
    'staff_has_teaching_sections',
    'get_staff_by_id_or_id_number',
    # Position
    'django_position_to_data',
    'create_position_in_db',
    'update_position_in_db',
    'delete_position_from_db',
    'position_has_staff',
    # Department
    'django_department_to_data',
    'create_department_in_db',
    'update_department_in_db',
    'delete_department_from_db',
    'department_has_staff',
    'department_has_positions',
]
