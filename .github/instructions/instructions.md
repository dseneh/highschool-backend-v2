# Project Instructions

## Django API Development Guidelines

## Models
- Always inherite from BaseModel (imported from the commom app)

### Views
- Use Django REST Framework's `APIView` class for all custom API endpoints
- Implement custom methods directly in the view classes
- Handle HTTP methods (GET, POST, PUT, DELETE) within the view methods
- Keep business logic in views, not in serializers
- Ensure the relevant permissions and authentication are applied to each view

### Serializers
- Use serializers ONLY for data validation and serialization/deserialization
- Do NOT add custom API actions or business logic in serializers
- Keep serializers focused on field definitions and validation rules
- Avoid adding custom methods that handle API responses or database operations

### Code Organization
- Each API endpoint should have its own view class inheriting from `APIView`
- Use meaningful class and method names
- Implement proper error handling in views
- Return appropriate HTTP status codes

### Documentation
- Document each API endpoint with clear descriptions of its purpose, parameters, and responses but shouldn't be too in detail, just highlevel unless necessary. An ordinary or common logic shouldn't have too long docstrings
- Maintain separate documentation files for different aspects of the API (e.g., settings, grading, reports)
- Update documentation whenever changes are made to the API
- Documentations should be created in a docs/ directory within the relevant app
- Update README files to reflect new commands or features
- Reference documentation files in the main README for easy access and with links and instructions
- Ensure unnecessary multiple docs files are not created, if the document is necessary to have, update where it is necessary. 
- If multiple files are created in the docs dir, ensure there is a main README.md that will be the main readme that links all the others in the docs dir.

### Example Structure