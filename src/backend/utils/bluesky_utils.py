"""Company and ticker matching helpers for Bluesky social posts."""

import re

from constants import SP100_COMPANIES
from utils.stock_utils import filter_sp100

_TICKER_TAG = re.compile(r"(?<![A-Za-z0-9])(?:\$|#)([A-Za-z][A-Za-z0-9.-]{0,6})\b")
_COMPANY_SUFFIX = re.compile(r"\b(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc|group|holdings|holding)\b")
_FINANCIAL_CONTEXT = re.compile(
    r"\b(?:stock|stocks|share|shares|earnings|revenue|profit|guidance|quarter|quarterly|"
    r"investor|investors|analyst|market|ticker|ceo|cfo|dividend|buyback|sec|nasdaq|nyse|"
    r"acquisition|merger|acquire|acquires|acquired|reports|reported|announces|announced|"
    r"launches|launched|results|forecast|outlook|lawsuit|regulatory|trading|valuation|"
    r"cloud|antitrust|layoffs|restructuring)\b"
)


def _normalized_words(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _company_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    patterns = []
    for symbol, company_name in SP100_COMPANIES.items():
        normalized = re.sub(r"\bthe\b", " ", _normalized_words(company_name))
        alias = " ".join(_COMPANY_SUFFIX.sub(" ", normalized).split())
        if len(alias) >= 4:
            patterns.append((symbol, re.compile(rf"\b{re.escape(alias)}\b")))
    return tuple(patterns)


_COMPANY_PATTERNS = _company_patterns()


def extract_sp100_symbols(text: str) -> list[str]:
    """Return S&P 100 symbols tagged or named in a financially contextual post."""
    found = set()
    for match in _TICKER_TAG.finditer(text):
        tag, symbol = match.group(0), match.group(1).upper().replace("-", ".")
        # Short ambiguous symbols are accepted as cashtags only; e.g. #CAT
        # commonly means the animal, while $CAT is an explicit ticker.
        if tag.startswith("$") or len(symbol) >= 4:
            found.add(symbol)
    normalized_text = _normalized_words(text)
    if _FINANCIAL_CONTEXT.search(normalized_text):
        for symbol, pattern in _COMPANY_PATTERNS:
            if pattern.search(normalized_text):
                found.add(symbol)
    return filter_sp100(found)


def headline_from_post(post_text: str, *, limit: int = 180) -> str:
    """Create a concise display headline for a post without a title."""
    clean = re.sub(r"\s+", " ", post_text).strip()
    if len(clean) <= limit:
        return clean
    excerpt = clean[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{excerpt or clean[:limit - 1]}…"
