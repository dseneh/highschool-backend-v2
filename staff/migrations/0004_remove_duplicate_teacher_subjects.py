"""Remove duplicate TeacherSubject rows before adding unique constraint."""
from django.db import migrations


def remove_duplicates(apps, schema_editor):
    TeacherSubject = apps.get_model("staff", "TeacherSubject")
    seen = set()
    to_delete = []

    for ts in TeacherSubject.objects.order_by("created_at"):
        key = (str(ts.teacher_id), str(ts.section_subject_id))
        if key in seen:
            to_delete.append(ts.id)
        else:
            seen.add(key)

    if to_delete:
        TeacherSubject.objects.filter(id__in=to_delete).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("staff", "0003_teachersubject_section_subject"),
    ]

    operations = [
        migrations.RunPython(remove_duplicates, migrations.RunPython.noop),
    ]
