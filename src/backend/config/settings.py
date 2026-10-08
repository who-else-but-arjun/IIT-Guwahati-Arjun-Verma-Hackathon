import os
from pathlib import Path


def _csv_setting(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-key-do-not-use-in-production")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = _csv_setting(
    "DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "backend", "0.0.0.0"]
)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "corsheaders",
    "api",
    "services.apps.ServicesConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {
    # Django's built-in checks expect a default relational backend. MongoDB is
    # checked directly through PyMongo; no Django ORM data is used currently.
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "django.sqlite3"}
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django's Redis backend is shared by API workers and background services.
# The cache helper fails open when Redis is unavailable.
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 300,
        "KEY_PREFIX": "crisil",
    }
}
CORS_ALLOWED_ORIGINS = _csv_setting(
    "CORS_ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"]
)
CSRF_TRUSTED_ORIGINS = _csv_setting("CSRF_TRUSTED_ORIGINS", CORS_ALLOWED_ORIGINS)
