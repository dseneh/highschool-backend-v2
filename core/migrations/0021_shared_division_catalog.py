import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


DEFAULT_DIVISIONS = (
    ("Preschool", "Early childhood education for children aged 3-5."),
    ("Elementary", "Primary education for children aged 6-11."),
    ("Junior High School", "Intermediate education for students aged 12-14."),
    ("Senior High School", "Secondary education for students aged 15-18."),
)


def catalog_id(name):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"ezyschool:division:{name.lower()}")


def seed_and_remap_schools(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    Tenant = apps.get_model("core", "Tenant")
    connection = schema_editor.connection
    quote = connection.ops.quote_name

    for name, description in DEFAULT_DIVISIONS:
        Division.objects.get_or_create(
            id=catalog_id(name),
            defaults={"name": name, "description": description, "active": True},
        )

    for tenant in Tenant.objects.exclude(school_division_id__isnull=True).iterator():
        selected_id = tenant.school_division_id
        if Division.objects.filter(pk=selected_id).exists():
            continue

        division_name = None
        division_description = ""
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT name, COALESCE(description, '') FROM {quote(tenant.schema_name)}.{quote('division')} WHERE id = %s",
                    [selected_id],
                )
                row = cursor.fetchone()
                if row:
                    division_name, division_description = row
        except Exception:
            division_name = None

        if not division_name:
            tenant.school_division_id = None
            tenant.save(update_fields=["school_division_id"])
            continue

        shared = Division.objects.filter(name__iexact=division_name).first()
        if shared is None:
            shared = Division.objects.create(
                id=selected_id,
                name=division_name,
                description=division_description,
                active=True,
            )
        tenant.school_division_id = shared.id
        tenant.save(update_fields=["school_division_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_replace_school_type_with_school_division"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Division",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True, default=None, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_%(class)s_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_%(class)s_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Division",
                "verbose_name_plural": "Divisions",
                "db_table": "school_division",
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(seed_and_remap_schools, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="tenant",
            old_name="school_division_id",
            new_name="school_division",
        ),
        migrations.AlterField(
            model_name="tenant",
            name="school_division",
            field=models.ForeignKey(
                blank=True,
                help_text="Platform division that defines the school's highest grade-level range.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="schools",
                to="core.division",
            ),
        ),
    ]
