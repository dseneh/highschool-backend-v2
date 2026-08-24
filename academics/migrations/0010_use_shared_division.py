import django.db.models.deletion
from django.db import migrations, models
from django_tenants.utils import get_public_schema_name


def remap_grade_level_divisions(apps, schema_editor):
    LocalDivision = apps.get_model("academics", "Division")
    GradeLevel = apps.get_model("academics", "GradeLevel")
    SharedDivision = apps.get_model("core", "Division")
    connection = schema_editor.connection
    quote = connection.ops.quote_name

    with connection.cursor() as cursor:
        cursor.execute(
            """
                        SELECT tc.constraint_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                            ON tc.constraint_schema = kcu.constraint_schema
                         AND tc.constraint_name = kcu.constraint_name
                        WHERE tc.table_schema = current_schema()
                            AND tc.table_name = 'grade_level'
                            AND tc.constraint_type = 'FOREIGN KEY'
                            AND kcu.column_name = 'division_id'
            """
        )
        for (constraint_name,) in cursor.fetchall():
            cursor.execute(
                f"ALTER TABLE {quote('grade_level')} DROP CONSTRAINT {quote(constraint_name)}"
            )

    for local in LocalDivision.objects.all().iterator():
        shared = SharedDivision.objects.filter(name__iexact=local.name).first()
        if shared is None:
            shared = SharedDivision.objects.create(
                id=local.id,
                name=local.name,
                description=local.description,
                active=local.active,
            )
        GradeLevel.objects.filter(division_id=local.id).update(division_id=shared.id)

    public_schema = get_public_schema_name()
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {quote('grade_level')} "
            f"ADD CONSTRAINT {quote('grade_level_division_shared_fk')} "
            f"FOREIGN KEY ({quote('division_id')}) "
            f"REFERENCES {quote(public_schema)}.{quote('school_division')} ({quote('id')}) "
            "DEFERRABLE INITIALLY DEFERRED"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0009_alter_academicyear_options_and_more"),
        ("core", "0021_shared_division_catalog"),
    ]

    operations = [
        migrations.RunPython(remap_grade_level_divisions, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="gradelevel",
                    name="division",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grade_levels",
                        to="core.division",
                    ),
                ),
            ],
        ),
        migrations.DeleteModel(name="Division"),
    ]
