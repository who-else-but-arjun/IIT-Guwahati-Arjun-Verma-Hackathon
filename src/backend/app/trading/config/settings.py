"""Django settings for the separate trading API process."""

import os
from pathlib import Path


def _csv_setting(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]

BASE_DIR = Path(__file__).resolve().parents[3]
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-paper-trading-key")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = _csv_setting(
    "DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "trading", "0.0.0.0"]
)
INSTALLED_APPS = ["django.contrib.contenttypes", "corsheaders", "app.trading.apps.TradingConfig"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "corsheaders.middleware.CorsMiddleware", "django.middleware.common.CommonMiddleware"]
CORS_ALLOWED_ORIGINS = _csv_setting(
    "CORS_ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"]
)
CSRF_TRUSTED_ORIGINS = _csv_setting("CSRF_TRUSTED_ORIGINS", CORS_ALLOWED_ORIGINS)
ROOT_URLCONF = "app.trading.config.urls"
TEMPLATES = []
WSGI_APPLICATION = "app.trading.config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "trading.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 300,
        "KEY_PREFIX": "crisil",
    }
}
