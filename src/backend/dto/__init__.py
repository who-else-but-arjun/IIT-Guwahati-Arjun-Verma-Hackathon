"""Typed data-transfer objects returned by external connectors."""

from .news import EffectiveNewsScoresDTO, NewsCategory, NewsEventDTO, RelevantTickerDTO, SentimentDTO, SentimentTag
from .stock import StockBarDTO, TickerDTO, TickerGraphDTO, TickerNameDTO, TickerScoreDTO

__all__ = [
    "EffectiveNewsScoresDTO", "NewsCategory", "NewsEventDTO", "RelevantTickerDTO", "SentimentDTO", "SentimentTag",
    "StockBarDTO", "TickerDTO", "TickerGraphDTO", "TickerNameDTO", "TickerScoreDTO",
]
