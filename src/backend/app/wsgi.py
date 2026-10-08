"""WSGI entry point for the independently served trading application."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.trading.config.settings")
application = get_wsgi_application()
