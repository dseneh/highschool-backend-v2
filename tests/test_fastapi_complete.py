"""
Basic test to verify FastAPI endpoints are working
"""
import pytest
from fastapi.testclient import TestClient
from fastapi_app.main import app

client = TestClient(app)

def test_health_check():
    """Test health check endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_health_explicit():
    """Test explicit health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_docs_available():
    """Test that API docs are available"""
    response = client.get("/docs")
    assert response.status_code == 200

def test_redoc_available():
    """Test that ReDoc documentation is available"""
    response = client.get("/redoc")
    assert response.status_code == 200

def test_openapi_schema():
    """Test that OpenAPI schema is available"""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data
    assert data["info"]["title"] == "Highschool Backend API"

if __name__ == "__main__":
    print("Running basic FastAPI tests...")
    test_health_check()
    print("✓ Health check test passed")
    test_health_explicit()
    print("✓ Explicit health check test passed")
    test_docs_available()
    print("✓ Docs endpoint test passed")
    test_redoc_available()
    print("✓ ReDoc endpoint test passed")
    test_openapi_schema()
    print("✓ OpenAPI schema test passed")
    print("All basic tests passed!")