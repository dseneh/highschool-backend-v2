from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0013_email_mfa_recovery"),
        ("users", "0018_unique_normalized_user_email"),
    ]

    operations = []
