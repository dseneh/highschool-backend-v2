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

HEALTH_BODY = b'{"status":"ok","service":"backend"}'
HEALTH_PATHS = ('/', '/health', '/health/')


def _health_response_headers(environ):
    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(HEALTH_BODY))),
    ]
    origin = environ.get('HTTP_ORIGIN', '')
    if origin:
        headers.extend([
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Vary', 'Origin'),
        ])
    return headers


def health_check_middleware(environ, start_response):
    """
    WSGI middleware that intercepts health check requests BEFORE they hit Django.
    This ensures health checks are fast and don't depend on any Django middleware,
    database connections, or tenant resolution.
    """
    path = environ.get('PATH_INFO', '')

    if path in HEALTH_PATHS:
        method = environ.get('REQUEST_METHOD', 'GET')
        headers = _health_response_headers(environ)

        if method == 'OPTIONS':
            headers.extend([
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Accept, Content-Type'),
                ('Access-Control-Max-Age', '86400'),
            ])
            start_response('200 OK', headers)
            return [b'']

        start_response('200 OK', headers)
        return [HEALTH_BODY]

    # All other requests go to Django
    return django_app(environ, start_response)


# Export the wrapped application
application = health_check_middleware
