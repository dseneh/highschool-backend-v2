from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_centralauthsession_oauthclient_authorizationrequest_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'user'
                      AND column_name = 'role'
                ) THEN
                    ALTER TABLE "user"
                        ADD COLUMN "role" varchar(20) NOT NULL DEFAULT 'viewer';
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
