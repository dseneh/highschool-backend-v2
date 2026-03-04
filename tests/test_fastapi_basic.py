import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add the fastapi_app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../fastapi_app'))

from main import app

client = TestClient(app)


def test_health_check():
    """Test the health check endpoint"""
    response = client.get("/")
    assert response.status_code in [200, 503]  # 503 if no database
    data = response.json()
    assert "status" in data
    assert "message" in data


def test_health_check_explicit():
    """Test the explicit health check endpoint"""
    response = client.get("/health")
    assert response.status_code in [200, 503]  # 503 if no database
    data = response.json()
    assert "status" in data
    assert "message" in data


def test_docs_accessible():
    """Test that API docs are accessible"""
    response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_schema():
    """Test that OpenAPI schema is available"""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data