from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_centralauthsession_oauthclient_authorizationrequest_and_more"),
    ]

    operations = [
        migrations.DeleteModel(name="RoleDefaultPrivilege"),
        migrations.DeleteModel(name="SpecialPrivilege"),
    ]
