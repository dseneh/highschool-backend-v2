import uuid

from django.db import models
from django_resized import ResizedImageField

from common.status import PersonStatus
from core.validators import ValidateImageFile


class BaseModel(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_%(class)s_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_%(class)s_set",
        to_field="id",
        blank=True,
        default=None,
    )
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls._meta.abstract or cls._meta.proxy:
            return

        default_table = f"{cls._meta.app_label}_{cls._meta.model_name}"
        if cls._meta.db_table == default_table:
            cls._meta.db_table = cls._meta.model_name

    @property
    def meta(self):
        r = {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": {
                "id": self.created_by.id,
                "username": self.created_by.username,
                "email": self.created_by.email,
            },
            "updated_by": {
                "id": self.updated_by.id or None,
                "username": self.updated_by.username or None,
                "email": self.updated_by.email or None,
            },
        }
        return r

    class Meta:
        abstract = True


class BasePersonModel(BaseModel):
    id_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        default=None,
        help_text=(
            "National / government-issued identification number. "
            "Per-tenant uniqueness is enforced by subclasses where required."
        ),
    )
    first_name = models.CharField(max_length=150)
    middle_name = models.CharField(max_length=150, blank=True, null=True, default=None)
    last_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(blank=True, null=True, default=None)
    gender = models.CharField(
        max_length=10,
        choices=[
            ("male", "Male"),
            ("female", "Female"),
        ],
        default="",
    )
    email = models.EmailField(blank=True, null=True, default=None)
    phone_number = models.CharField(max_length=15, blank=True, null=True, default=None)
    address = models.TextField(blank=True, null=True, default=None)
    city = models.CharField(max_length=100, blank=True, null=True, default=None)
    state = models.CharField(max_length=100, blank=True, null=True, default=None)
    postal_code = models.CharField(max_length=100, blank=True, null=True, default=None)
    country = models.CharField(max_length=100, blank=True, null=True, default=None)
    place_of_birth = models.CharField(
        max_length=250, blank=True, null=True, default=None
    )

    status = models.CharField(
        max_length=20, choices=PersonStatus.choices(), default=PersonStatus.ACTIVE
    )
    photo = ResizedImageField(
        size=[300, 300],
        crop=["middle", "center"],
        scale=1,
        quality=85,
        upload_to="photos",
        null=True,
        blank=True,
        validators=[ValidateImageFile],
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f"{self.first_name} {self.middle_name if self.middle_name else ''} {self.last_name}".replace(
            "  ", " "
        ).strip()
