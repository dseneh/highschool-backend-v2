"""
WSGI config for api project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import json

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")

# Get Django WSGI application
django_app = get_wsgi_application()


def health_check_middleware(environ, start_response):
    """
    WSGI middleware that intercepts health check requests BEFORE they hit Django.
    This ensures health checks are fast and don't depend on any Django middleware,
    database connections, or tenant resolution.
    """
    path = environ.get('PATH_INFO', '')
    
    # Handle health check requests at WSGI level
    if path in ('/', '/health', '/health/'):
        status = '200 OK'
        headers = [
            ('Content-Type', 'application/json'),
            ('Content-Length', '37'),
        ]
        start_response(status, headers)
        return [b'{"status":"ok","service":"backend"}']
    
    # All other requests go to Django
    return django_app(environ, start_response)


# Export the wrapped application
application = health_check_middleware
