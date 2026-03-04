"""
Student guardian model for storing parent/guardian information
"""
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
    photo = models.URLField(blank=True, null=True, default=None)
    notes = models.TextField(blank=True, null=True, default=None)
    user_account_id_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text="Reference to User.id_number in public schema (avoid cross-schema FK)"
    )

    class Meta:
        db_table = "student_guardian"
        verbose_name = "Student Guardian"
        verbose_name_plural = "Student Guardians"
        ordering = ["-is_primary", "last_name", "first_name"]
        indexes = [
            models.Index(fields=["student", "is_primary"]),
            models.Index(fields=["student", "relationship"]),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.relationship})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

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
