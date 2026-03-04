import os
import shutil


def delete_database():
    if os.path.exists("db.sqlite3"):
        os.remove("db.sqlite3")
        print("Deleted the SQLite database file...")


def delete_media_folders():
    if os.path.exists("media/school"):
        shutil.rmtree("media/school")
        print("Deleted the media/school directory...")
    if os.path.exists("media/users"):
        shutil.rmtree("media/users")
        print("Deleted the media/users directory...")


def delete_migrations(app_name):
    migrations_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", app_name, "migrations"
    )
    for root, dirs, files in os.walk(migrations_dir):
        for file in files:
            if file != "__init__.py":
                os.remove(os.path.join(root, file))
    print(f"Deleted all migration files for {app_name}...")


def run_cleanup():
    print("Running cleanup...")
    delete_database()
    delete_media_folders()
    delete_migrations("users")
    delete_migrations("core")
    delete_migrations("students")
    delete_migrations("employees")
    delete_migrations("finance")
