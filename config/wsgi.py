"""WSGI entry point: only for `manage.py runserver`; production runs ASGI (config.asgi)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
