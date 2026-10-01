from django.db import migrations, models
from django.db.models.functions import Lower, Trim


def check_duplicate_emails(apps, schema_editor):
    User = apps.get_model("users", "User")
    duplicates = (
        User.objects.using(schema_editor.connection.alias)
        .annotate(normalized_email=Lower(Trim("email")))
        .values("normalized_email")
        .annotate(total=models.Count("pk"))
        .filter(total__gt=1)
    )
    if duplicates.exists():
        raise RuntimeError(
            "Cannot enforce unique account emails: existing accounts share an email "
            "after trimming whitespace and ignoring case. Resolve these identities "
            "before retrying migration 0018; no accounts were merged or deleted."
        )


class Migration(migrations.Migration):
    dependencies = [("users", "0017_schooluseraccess_instructions_failed_and_more")]
    operations = [
        migrations.RunPython(check_duplicate_emails, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower(Trim("email")), name="unique_normalized_user_email"
            ),
        ),
    ]
