"""Read-time score decay helpers; raw persisted scores are never rewritten."""

from datetime import datetime, timezone
import math

from constants import SENTIMENT_HALF_LIFE_HOURS


def decay_factor(observed_at: datetime | None, *, as_of: datetime | None = None,
                 half_life_hours: float = SENTIMENT_HALF_LIFE_HOURS) -> float:
    """Return exponential half-life factor in [0, 1], clamping future ages to zero."""
    if half_life_hours <= 0:
        raise ValueError("half_life_hours must be positive")
    if observed_at is None:
        return 1.0
    current = as_of or datetime.now(timezone.utc)
    observed = observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (current - observed).total_seconds() / 3600.0)
    return math.exp2(-age_hours / half_life_hours)
