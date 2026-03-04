"""Staff validation logic"""

from rest_framework.exceptions import ValidationError
from staff.models import Staff, Position


class StaffValidator:
    """Validates staff data and business rules"""

    @staticmethod
    def validate_create(data):
        """
        Validate staff creation data

        Args:
            data: Request data dictionary

        Raises:
            ValidationError: If validation fails
        """
        errors = {}

        # Required fields
        first_name = data.get("first_name").strip()
        last_name = data.get("last_name").strip()
        hire_date = data.get("hire_date")
        gender = data.get("gender")
        email = data.get("email")
        phone_number = data.get("phone_number")
        date_of_birth = data.get("date_of_birth")

        if not first_name:
            errors["first_name"] = "First name is required"
        if not last_name:
            errors["last_name"] = "Last name is required"
        if not hire_date:
            errors["hire_date"] = "Date hired is required"
        if not gender:
            errors["gender"] = "Gender is required"
        if not email:
            errors["email"] = "Email is required"
        if not phone_number:
            errors["phone_number"] = "Phone number is required"
        if not date_of_birth:
            errors["date_of_birth"] = "Date of birth is required"

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def check_duplicates(data):
        """
        Check for duplicate staff

        Args:
            data: Request data dictionary

        Raises:
            ValidationError: If duplicate found
        """
        id_number = data.get("id_number") or None
        email = data.get("email").strip() or None
        first_name = data.get("first_name").strip()
        last_name = data.get("last_name").strip()
        date_of_birth = data.get("date_of_birth")
        gender = data.get("gender")

        # Check ID number uniqueness
        if id_number and Staff.objects.filter(id_number=id_number).exists():
            raise ValidationError(
                {"detail": "Staff with this ID number already exists"}
            )

        if email and Staff.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                {"detail": "Staff with this email already exists"}
            )

        # Check name + DOB + gender combination
        if date_of_birth and first_name and last_name and gender:
            if Staff.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name,
                date_of_birth=date_of_birth,
                gender=gender,
            ).exists():
                raise ValidationError(
                    {
                        "detail": "A staff with the same name and date of birth already exists"
                    }
                )

    @staticmethod
    def validate_position(position_id):
        """
        Validate and get position if provided

        Args:
            position_id: Position ID

        Returns:
            Position instance or None

        Raises:
            ValidationError: If position doesn't exist
        """
        if not position_id:
            return None

        position = Position.objects.filter(id=position_id).first()
        if not position:
            raise ValidationError({"detail": "Position does not exist"})

        return position

    @staticmethod
    def validate_update(data, staff):
        """
        Validate staff update data

        Args:
            data: Request data dictionary
            staff: Staff instance being updated

        Raises:
            ValidationError: If validation fails
        """
        # Check ID number uniqueness if being updated
        id_number = data.get("id_number")
        if id_number and id_number != staff.id_number:
            if Staff.objects.filter(id_number=id_number).exists():
                raise ValidationError(
                    {"detail": "Staff with this ID number already exists"}
                )

        # Validate position if being updated
        position_id = data.get("position")
        if position_id:
            position = Position.objects.filter(
                id=position_id
            ).first()
            if not position:
                raise ValidationError({"detail": "Position does not exist"})

        return True

