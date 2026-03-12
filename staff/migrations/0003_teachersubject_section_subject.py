from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0002_initial"),
        ("staff", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="teachersubject",
            name="section_subject",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="staff_teachers",
                to="academics.sectionsubject",
            ),
        ),
    ]
