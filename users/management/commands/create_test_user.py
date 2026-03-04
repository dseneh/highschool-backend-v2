"""Create test user for API authentication."""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import random

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a test superuser for API testing'

    def handle(self, *args, **options):
        email = "testadmin@test.com"
        password = "testpass123"
        
        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f'User {email} already exists'))
            user = User.objects.get(email=email)
        else:
            # Generate unique ID number
            id_number = f"{random.randint(100000, 999999)}"
            
            user = User.objects.create_superuser(
                email=email,
                username=email,
                password=password,
                first_name="Test",
                last_name="Admin",
                id_number=id_number
            )
            self.stdout.write(self.style.SUCCESS(f'✓ Created superuser: {email}'))
        
        self.stdout.write(f'\nCredentials:')
        self.stdout.write(f'  Email: {email}')
        self.stdout.write(f'  Password: {password}')
        self.stdout.write(f'\nTest token endpoint:')
        self.stdout.write(f'  curl -X POST http://localhost:8000/api/v1/auth/token/ \\')
        self.stdout.write(f'    -H "Content-Type: application/json" \\')
        self.stdout.write(f'    -H "X-Tenant: test" \\')
        self.stdout.write(f'    -d \'{{"username":"{email}","password":"{password}"}}\'')
        self.stdout.write('')
