from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0011_parentinvitation_parentprofile_parentstudentlink")]
    operations = [migrations.AddField(
        model_name="user", name="date_of_birth",
        field=models.DateField(blank=True, null=True),
    )]
