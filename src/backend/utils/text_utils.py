"""Text normalization helpers for provider-supplied news content."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser


class _VisibleHTML(HTMLParser):
    """Extract readable text while dropping markup and non-visible elements."""

    _BLOCK_TAGS = {"article", "br", "div", "footer", "h1", "h2", "h3", "li", "p", "section", "td", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        elif not self._hidden_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif not self._hidden_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"), None)
_SPACE_RUN = re.compile(r"[\t\f\v\u00a0 ]+")
_TOO_MANY_NEWLINES = re.compile(r"\n{3,}")


def clean_news_text(value: object) -> str:
    """Decode HTML/entities, remove markup and invisible controls, and normalize spacing."""
    if not isinstance(value, str) or not value:
        return ""

    text = unicodedata.normalize("NFC", value).translate(_ZERO_WIDTH)
    # Provider payloads sometimes double-escape HTML entities. Decode a few
    # levels before parsing so encoded tags are removed as markup too.
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded

    parser = _VisibleHTML()
    try:
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        # Keep the original readable text if a malformed provider fragment
        # defeats HTMLParser; the remaining normalization is still useful.
        pass

    text = unicodedata.normalize("NFC", html.unescape(text)).translate(_ZERO_WIDTH)
    text = "".join(
        char for char in text
        if char in "\n\r\t" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    lines = [_SPACE_RUN.sub(" ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    cleaned = _TOO_MANY_NEWLINES.sub("\n\n", "\n".join(line for line in lines if line))
    return cleaned.strip()
