"""Shared contract and dispatch behavior for news source connectors."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Callable

from dto.news import NewsEventDTO
from constants import SP100_COMPANIES
from utils.stock_utils import filter_sp100


class NewsConnector(ABC):
    """Common normalization and delivery contract for news providers.

    Provider transport stays in each subclass. The event callback is injected,
    so connectors compose cleanly with persistence, queues, or other consumers.
    """

    provider: str

    def __init__(self, on_article: Callable[[NewsEventDTO], object] | None = None, *, symbols: Sequence[str] | None = None):
        self.on_article = on_article
        self.symbols = set(filter_sp100(symbols)) if symbols else set(SP100_COMPANIES)

    @abstractmethod
    def normalize(self, payload: Mapping[str, object], context: object | None = None) -> NewsEventDTO | None:
        """Convert provider data into the shared DTO, or return None to skip."""

    def ingest(self, payload: Mapping[str, object], context: object | None = None) -> NewsEventDTO | None:
        """Normalize, apply the configured ticker universe, then deliver."""
        article = self.normalize(payload, context)
        if article is None:
            return None
        return self.dispatch(article)

    def dispatch(self, article: NewsEventDTO) -> NewsEventDTO | None:
        """Apply the ticker filter and pass a normalized event to its consumer."""
        related = {ticker.ticker_id for ticker in article.relevant_tickers}
        if not related.intersection(self.symbols):
            return None
        if self.on_article is not None:
            self.on_article(article)
        return article
