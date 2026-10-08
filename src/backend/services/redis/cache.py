"""Small fail-open read-through cache built on Django's configured cache."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from functools import wraps
from typing import Callable, TypeVar

# Standalone connector workers use the shared default cache configuration but
# do not start through Django's WSGI entry point.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.core.cache import cache

logger = logging.getLogger(__name__)
T = TypeVar("T")


def make_cache_key(namespace: str, *parts: object) -> str:
    """Create a stable, bounded key from arbitrary request parameters."""
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"crisil:{namespace}:{digest}"


def remember(key: str, loader: Callable[[], T], timeout: int) -> T:
    """Return a shared cached value, loading it when absent or Redis is down."""
    try:
        value = cache.get(key)
        if value is not None:
            return value
    except Exception:
        logger.warning("Redis cache read failed; loading live data", exc_info=True)

    value = loader()
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("Redis cache write failed; returning live data", exc_info=True)
    return value


def remember_with_stale(key: str, loader: Callable[[], T], timeout: int, stale_timeout: int) -> T:
    """Serve the last good market-data response if the upstream is failing."""
    stale_key = f"{key}:stale"
    try:
        value = cache.get(key)
        if value is not None:
            return value
    except Exception:
        logger.warning("Redis cache read failed; loading live data", exc_info=True)

    try:
        value = loader()
    except Exception:
        try:
            stale = cache.get(stale_key)
        except Exception:
            stale = None
        if stale is not None:
            logger.warning("Market-data source failed; returning last good cached data", exc_info=True)
            return stale
        raise

    try:
        cache.set(key, value, timeout=timeout)
        cache.set(stale_key, value, timeout=stale_timeout)
    except Exception:
        logger.warning("Redis cache write failed; returning live data", exc_info=True)
    return value


def invalidate_read_cache(*tags: str) -> None:
    """Invalidate only the data domain changed by a successful write."""
    for tag in tags or ("news", "ticker", "trading"):
        generation_key = f"crisil:read-cache-generation:{tag}"
        try:
            # Bulk news ingestion may commit thousands of individual rows. One
            # generation bump per short window keeps shared reads warm while
            # still making fresh stories visible promptly.
            if not cache.add(f"{generation_key}:lock", 1, timeout=2):
                continue
            if cache.add(generation_key, 1, timeout=30 * 24 * 60 * 60):
                continue
            cache.incr(generation_key)
        except Exception:
            # A failed invalidation is bounded by each entry's TTL.
            logger.warning("Redis cache invalidation failed for %s", tag, exc_info=True)


def cached_read(namespace: str, timeout: int, key_args: Callable[..., object] | None = None):
    """Cache a read method by its arguments; methods must not mutate results."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            parts = key_args(*args, **kwargs) if key_args else (args[1:], kwargs)
            tag = ("trading" if namespace.startswith("trading-") else
                   "news" if namespace in {"mongo-ticker-events"} else
                   "ticker" if "ticker" in namespace else "news")
            try:
                generation = cache.get(f"crisil:read-cache-generation:{tag}", 0)
            except Exception:
                generation = 0
            key = make_cache_key(namespace, generation, parts)
            return remember(key, lambda: function(*args, **kwargs), timeout)
        return wrapped
    return decorate


def invalidates_read_cache(*tags: str):
    """Invalidate cached database reads after a successful mutation."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            result = function(*args, **kwargs)
            invalidate_read_cache(*tags)
            return result
        return wrapped
    return decorate
