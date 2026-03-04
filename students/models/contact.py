"""
Student contact model for storing emergency and other contacts
"""
from .base import BaseModel, models


class StudentContact(BaseModel):
    """A contact person associated with a student (teacher, family friend, etc.)"""

    RELATIONSHIP_CHOICES = [
        ("parent", "Parent"),
        ("guardian", "Guardian"),
        ("sibling", "Sibling"),
        ("relative", "Relative"),
        ("family_friend", "Family Friend"),
        ("neighbor", "Neighbor"),
        ("teacher", "Teacher"),
        ("counselor", "Counselor"),
        ("other", "Other"),
    ]

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="contacts",
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
    is_emergency = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    photo = models.URLField(blank=True, null=True, default=None)
    notes = models.TextField(blank=True, null=True, default=None)

    class Meta:
        db_table = "student_contact"
        verbose_name = "Student Contact"
        verbose_name_plural = "Student Contacts"
        ordering = ["-is_primary", "-is_emergency", "last_name", "first_name"]
        indexes = [
            models.Index(fields=["student", "is_emergency"]),
            models.Index(fields=["student", "is_primary"]),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.relationship})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def default_photo(self):
        """Return a default photo URL based on relationship (mapped to gender)."""
        FEMALE_RELATIONSHIPS = {"mother", "stepmother", "grandmother", "aunt", "sister"}
        MALE_RELATIONSHIPS = {"father", "stepfather", "grandfather", "uncle", "brother"}
        rel = (self.relationship or "").lower()
        if rel in FEMALE_RELATIONSHIPS:
            return "images/default_female.jpg"
        elif rel in MALE_RELATIONSHIPS:
            return "images/default_male.jpg"
        return "images/default.jpg"
