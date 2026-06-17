from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0007_rename_calendar_ev_recurre_6a8b0d_idx_calendar_ev_recurre_a89d32_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="academicyear",
            name="year_type",
            field=models.CharField(
                choices=[("regular", "Regular"), ("historical", "Historical")],
                db_index=True,
                default="regular",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="academicyear",
            name="start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="academicyear",
            name="end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="academicyear",
            index=models.Index(
                fields=["year_type", "name"],
                name="academic_ye_year_ty_8a4b2c_idx",
            ),
        ),
    ]
