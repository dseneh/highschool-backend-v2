# High School SaaS Multi-Tenant API

This repository contains the backend API for a multi-tenant SaaS platform designed for high schools. The API provides features for managing students, teachers, classes, and other school-related operations.

## Features

- Multi-tenant architecture to support multiple schools.
- Role-based access control (Admin, Teacher, Student).
- CRUD operations for students, teachers, and classes.
- Authentication and authorization using JWT.
- RESTful API design for easy integration.

## Tech Stack

- **Language**: Python
- **Framework**: Django / Django REST Framework
- **Database**: PostgreSQL
- **Authentication**: JSON Web Tokens (JWT)
- **Deployment**: Railway

## Installation

1. Clone the repository:
    ```bash
    git clone <repository-url>
    cd highschool-saas-api
    ```

2. Create and activate a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4. Set up the database:
    ```bash
    python manage.py migrate
    ```

5. Run the development server:
    ```bash
    python manage.py runserver
    ```

## API Endpoints

| Method | Endpoint               | Description                  |
|--------|------------------------|------------------------------|
| GET    | `/api/students/`       | List all students            |
| POST   | `/api/students/`       | Create a new student         |
| GET    | `/api/teachers/`       | List all teachers            |
| POST   | `/api/teachers/`       | Create a new teacher         |
| GET    | `/api/classes/`        | List all classes             |
| POST   | `/api/classes/`        | Create a new class           |

## Deployment

This application is configured for deployment on Railway. See `RAILWAY_CI_CD_GUIDE.md` for detailed deployment instructions.

### Quick Start
1. Fork/clone this repository
2. Set up a Railway account
3. Create a Railway project
4. Connect your repository to Railway
5. Configure environment variables (see `.env.railway.template` template)
6. Deploy!

### Local Development
1. Copy `.env.example` to `.env`
2. Install dependencies: `pip install -r requirements.txt`
3. Run migrations: `python manage.py migrate`
4. Start server: `python manage.py runserver`

## Internal Use Only

This project is proprietary and intended for internal use by the development team. Please ensure that access to this repository is restricted to authorized personnel only.

## Contact

For questions or support, please contact the project administrator.


# API Process

## Auto generate tables process:
- School
    - Subjects
    - AcademyYear (Ask user for current year input for the next or current Academic year)
    - Semesters for Academic Year (user should provide input for the number of semester)
    - GradeLevel (user should provide the format as input)
    - MarkingPeriod (user should specified how many marking periods)

- Student Enrollment
    - GradeBook
    - Billing

# change admin password
.venv/bin/python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); u = User.objects.get(username='admin'); u.set_password('YOUR_NEW_PASSWORD'); u.save(); print('Password updated successfully')"