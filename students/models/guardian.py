"""
Student guardian model for storing parent/guardian information
"""
from django.core.validators import RegexValidator

from common.utils import ID_ENTITY_PARENT, generate_entity_id_number

from .base import BaseModel, models


class StudentGuardian(BaseModel):
    """A parent or legal guardian associated with a student"""

    RELATIONSHIP_CHOICES = [
        ("father", "Father"),
        ("mother", "Mother"),
        ("stepfather", "Stepfather"),
        ("stepmother", "Stepmother"),
        ("grandfather", "Grandfather"),
        ("grandmother", "Grandmother"),
        ("uncle", "Uncle"),
        ("aunt", "Aunt"),
        ("legal_guardian", "Legal Guardian"),
        ("foster_parent", "Foster Parent"),
        ("other", "Other"),
    ]

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="guardians",
    )
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, default="")
    last_name = models.CharField(max_length=100)
    relationship = models.CharField(
        max_length=20,
        choices=RELATIONSHIP_CHOICES,
        default="other",
    )
    phone_number = models.CharField(max_length=20, blank=True, null=True, default=None)
    email = models.EmailField(blank=True, null=True, default=None)
    address = models.TextField(blank=True, null=True, default=None)
    occupation = models.CharField(max_length=100, blank=True, null=True, default=None)
    workplace = models.CharField(max_length=200, blank=True, null=True, default=None)
    is_primary = models.BooleanField(default=False)
    id_number = models.CharField(
        max_length=20,
        validators=[RegexValidator(r"^\d+$")],
        db_index=True,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    photo = models.URLField(blank=True, null=True, default=None)
    notes = models.TextField(blank=True, null=True, default=None)
    user_account_id_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text="Reference to User.id_number in public schema (avoid cross-schema FK)"
    )

    # UUID reference avoids a cross-schema FK. Legacy rows remain unverified.
    give_access = models.BooleanField(default=False)
    gender = models.CharField(max_length=10, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    parent_profile_id = models.UUIDField(null=True, blank=True, db_index=True)
    portal_state = models.CharField(max_length=16, default="unverified", choices=[
        ("unverified", "Unverified"), ("invited", "Invited"), ("active", "Active"),
        ("suspended", "Suspended"), ("disconnected", "Disconnected"),
    ])
    portal_approved_at = models.DateTimeField(null=True, blank=True)
    portal_approved_by = models.UUIDField(null=True, blank=True)
    portal_verified_at = models.DateTimeField(null=True, blank=True)
    portal_ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "student_guardian"
        verbose_name = "Student Guardian"
        verbose_name_plural = "Student Guardians"
        ordering = ["-is_primary", "last_name", "first_name"]
        indexes = [
            models.Index(fields=["student", "is_primary"]),
            models.Index(fields=["student", "relationship"]),
        ]

    def save(self, *args, **kwargs):
        if not self.id_number:
            self.id_number = generate_entity_id_number(
                self.__class__, ID_ENTITY_PARENT
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.relationship})"

    @property
    def full_name(self):
        return " ".join(part for part in [self.first_name, self.middle_name, self.last_name] if part)

    @property
    def default_photo(self):
        """Return a default photo URL based on relationship (mapped to gender)."""
        FEMALE_RELATIONSHIPS = {"mother", "stepmother", "grandmother", "aunt"}
        MALE_RELATIONSHIPS = {"father", "stepfather", "grandfather", "uncle"}
        rel = (self.relationship or "").lower()
        if rel in FEMALE_RELATIONSHIPS:
            return "images/default_female.jpg"
        elif rel in MALE_RELATIONSHIPS:
            return "images/default_male.jpg"
        return "images/default.jpg"
