"""Staff service layer for business logic"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from common.utils import generate_unique_id_number, update_model_fields_core
from common.images import update_model_image
from staff.models import Staff
from staff.utils import filter_allowed_fields
from staff.validators.staff_validator import StaffValidator


class StaffService:
    """Service for staff business logic"""

    @staticmethod
    @transaction.atomic
    def create_staff(school, data, user):
        """
        Create a new staff with all business logic

        Args:
            school: School instance
            data: Request data dictionary
            user: User creating the staff

        Returns:
            Staff: Created staff instance

        Raises:
            ValidationError: If validation fails
        """
        # Define allowed fields for creation (security filtering)
        allowed_fields = [
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "email",
            "phone_number",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "place_of_birth",
            "status",
            "hire_date",
            "id_number",
            "position",
            "primary_department",
            "is_teacher",
            # "photo",
        ]
        
        # Filter data to only include allowed fields
        filtered_data = filter_allowed_fields(data, allowed_fields)
        
        # Normalize data
        normalized_data = StaffService._normalize_create_data(filtered_data)

        # Validate
        StaffValidator.validate_create(normalized_data, school)
        StaffValidator.check_duplicates(normalized_data, school)

        # Validate and get position
        position = StaffValidator.validate_position(
            normalized_data.get("position"), school
        )

        # Generate ID if not provided
        id_number = normalized_data.get("id_number")
        if not id_number:
            id_number = StaffService._generate_id_number(school)

        # Validate and get primary_department if provided
        primary_department = None
        if normalized_data.get("primary_department"):
            from staff.models import Department
            try:
                primary_department = Department.objects.get(
                    id=normalized_data.get("primary_department"),
                    school=school
                )
            except Department.DoesNotExist:
                raise ValidationError("Invalid primary_department")

        # Create staff
        staff = Staff.objects.create(
            school=school,
            id_number=id_number,
            first_name=normalized_data["first_name"],
            last_name=normalized_data["last_name"],
            middle_name=normalized_data.get("middle_name"),
            date_of_birth=normalized_data.get("date_of_birth"),
            gender=normalized_data["gender"],
            email=normalized_data.get("email"),
            phone_number=normalized_data.get("phone_number", ""),
            address=normalized_data.get("address"),
            city=normalized_data.get("city"),
            state=normalized_data.get("state"),
            postal_code=normalized_data.get("postal_code"),
            country=normalized_data.get("country"),
            place_of_birth=normalized_data.get("place_of_birth"),
            status=normalized_data.get("status", "active"),
            hire_date=normalized_data.get("hire_date"),
            position=position,
            primary_department=primary_department,
            is_teacher=normalized_data.get("is_teacher", False),
            created_by=user,
            updated_by=user,
        )

        # Handle photo upload if provided
        photo = normalized_data.get("photo")
        if photo:
            StaffService._upload_photo(
                staff, photo, normalized_data.get("gender")
            )

        # Create user account if requested
        # Handle both boolean and string values for initialize_user
        initialize_user = data.get("initialize_user", False)
        if isinstance(initialize_user, str):
            initialize_user = initialize_user.lower() in ("true", "1", "yes")
        if initialize_user:
            StaffService._create_user_account(staff, data, user)

        return staff

    @staticmethod
    @transaction.atomic
    def update_staff(staff, data, user):
        """
        Update an existing staff

        Args:
            staff: Staff instance to update
            data: Request data dictionary
            user: User updating the staff

        Returns:
            Staff: Updated staff instance

        Raises:
            ValidationError: If validation fails
        """
        # Define allowed fields for update (security filtering)
        allowed_fields = [
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "email",
            "phone_number",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "place_of_birth",
            "status",
            "hire_date",
            "primary_department",
            "id_number",
            "position",
            "photo",
            "is_teacher",
            "suspension_date",
            "suspension_reason",
            "termination_date",
            "termination_reason",
        ]
        
        # Filter data to only include allowed fields
        filtered_data = filter_allowed_fields(data, allowed_fields)
        
        # Normalize data
        normalized_data = StaffService._normalize_update_data(filtered_data)

        # Validate
        StaffValidator.validate_update(normalized_data, staff)

        # Validate position if being updated
        position_id = normalized_data.get("position")
        if position_id:
            position = StaffValidator.validate_position(position_id, staff.school)
            normalized_data["position"] = position

        # Update fields using core utility function (fields already filtered above)
        update_model_fields_core(staff, normalized_data, allowed_fields, user)

        # Handle photo update if provided
        photo = normalized_data.get("photo")
        if photo is not None:
            StaffService._upload_photo(staff, photo)

        return staff

    @staticmethod
    def _normalize_create_data(data):
        """Normalize and clean input data for creation"""
        return {
            "first_name": data.get("first_name", "").strip(),
            "middle_name": data.get("middle_name", "").strip() or None,
            "last_name": data.get("last_name", "").strip(),
            "hire_date": data.get("hire_date"),
            "id_number": data.get("id_number", "").strip() or None,
            "gender": data.get("gender"),
            "email": data.get("email", "").strip() or None,
            "date_of_birth": data.get("date_of_birth"),
            "phone_number": data.get("phone_number", "").strip(),
            "address": data.get("address"),
            "city": data.get("city"),
            "state": data.get("state"),
            "postal_code": data.get("postal_code"),
            "country": data.get("country"),
            "place_of_birth": data.get("place_of_birth"),
            "status": data.get("status", "active"),
            "position": data.get("position"),
            "photo": data.get("photo"),
        }

    @staticmethod
    def _normalize_update_data(data):
        """Normalize and clean input data for update"""
        normalized = {}
        for key, value in data.items():
            if isinstance(value, str):
                normalized[key] = value.strip() if value else None
            else:
                normalized[key] = value
        return normalized

    @staticmethod
    def _generate_id_number(school):
        """Generate unique staff ID number"""
        return generate_unique_id_number(Staff, school)

    @staticmethod
    def _upload_photo(staff, photo, gender=None):
        """Handle photo upload"""
        default_image_path = None
        if gender:
            default_image_path = f"/images/default_{gender}.jpg"
        else:
            default_image_path = "/images/default-user.png"

        update_model_image(
            staff,
            "photo",
            photo,
            default_image_path=default_image_path,
        )

    @staticmethod
    def _create_user_account(staff, data, user):
        """
        Create a user account for the staff member
        
        Args:
            staff: Staff instance
            data: Request data dictionary (may contain username and role)
            user: User creating the staff
        """
        from users.models import CustomUser
        from common.status import Roles, PersonStatus, UserAccountType
        
        # Use provided username or default to staff id_number
        username = data.get("username") or staff.id_number
        role = data.get("role", Roles.VIEWER)
        
        # Check if username already exists
        if CustomUser.objects.filter(username=username).exists():
            raise ValidationError(f"Username '{username}' already exists")
        
        # Check if id_number already exists as a user
        if CustomUser.objects.filter(id_number=staff.id_number).exists():
            raise ValidationError(f"User account with ID number '{staff.id_number}' already exists")
        
        # Create user account
        user_account = CustomUser.objects.create_user(
            id_number=staff.id_number,
            username=username,
            email=staff.email or f"{username}@example.com",  # Fallback email if not provided
            first_name=staff.first_name,
            last_name=staff.last_name,
            gender=staff.gender,
            role=role,
            school=staff.school,
            account_type=UserAccountType.STAFF,
            status=PersonStatus.CREATED,
            created_by=user,
            updated_by=user,
            is_active=True,
        )
        
        # Set default password to id_number
        user_account.set_password(staff.id_number)
        user_account.save()
        
        # Link user account to staff (loose coupling via id_number)
        staff.user_account_id_number = user_account.id_number
        staff.save(update_fields=["user_account_id_number"])

