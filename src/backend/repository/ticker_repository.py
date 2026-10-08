"""Ticker persistence operations mixed into MongoRepository."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from dto.stock import EffectiveTickerScoresDTO, TickerDTO, TickerGraphDTO, TickerNameDTO
from models.documents import Ticker
from constants import SENTIMENT_HALF_LIFE_MS
from services.redis.cache import cached_read, invalidates_read_cache


class TickerRepositoryMixin:
    """Ticker-specific Mongo persistence and score queries."""

    @cached_read("mongo-ticker-graph", 10)
    def get_ticker_graph(self, ticker_id: str) -> TickerGraphDTO | None:
        row = self.tickers.find_one(
            {"ticker_name.ticker_id": ticker_id}, {"ticker_graph": 1, "_id": 0}
        )
        if not row or not row.get("ticker_graph"):
            return None
        return TickerGraphDTO.model_validate(row["ticker_graph"])

    @invalidates_read_cache("ticker", "news")
    def update_ticker_sentiment(self, ticker_id: str, *, event_id: str, contribution: float,
                                impact: float, observed_at: datetime | None = None) -> bool:
        """Apply a bounded, decayed sentiment update once per event/ticker pair."""
        observed_at = observed_at or datetime.now(timezone.utc)
        if not math.isfinite(float(contribution)) or not math.isfinite(float(impact)):
            raise ValueError("Ticker score updates must be finite numbers.")
        contribution = max(-1.0, min(1.0, float(contribution)))
        impact = max(0.0, min(1.0, float(impact)))
        self.ensure_ticker_identity(TickerNameDTO(ticker_id=ticker_id))
        symbol = TickerNameDTO(ticker_id=ticker_id).ticker_id
        age_ms = {"$max": [0, {"$subtract": [observed_at, "$$old_stamp"]}]}
        prior_expr = {
            "$multiply": ["$$old_score", {"$pow": [2, {"$divide": [
                {"$multiply": [age_ms, -1]}, SENTIMENT_HALF_LIFE_MS
            ]}]}]
        }
        score_expression = {
            "$let": {
                "vars": {
                    "old_score": {"$ifNull": ["$ticker_score.sentiment.score", 0.0]},
                    "old_stamp": {"$ifNull": ["$ticker_score.sentiment.scored_at", observed_at]},
                },
                "in": {
                    "$let": {
                        "vars": {"prior": prior_expr},
                        "in": {
                            "$let": {
                                "vars": {
                                    "score": {"$max": [-1.0, {"$min": [1.0, {"$add": ["$$prior", float(contribution)]}]}]},
                                    "impact": {"$max": [0.0, {"$min": [1.0, {"$add": [{"$ifNull": ["$ticker_score.sentiment.impact_score", 0.0]}, max(0.0, float(impact))]}]}]},
                                },
                                "in": {
                                    "sentiment": {
                                        "score": "$$score",
                                        "tag": {"$switch": {"branches": [
                                            {"case": {"$gt": ["$$score", 0]}, "then": "positive"},
                                            {"case": {"$lt": ["$$score", 0]}, "then": "negative"},
                                        ], "default": "neutral"}},
                                        "impact_score": "$$impact",
                                        "scored_at": observed_at,
                                    },
                                    "delta_score": {"$subtract": ["$$score", "$$prior"]},
                                },
                            }
                        },
                    }
                },
            }
        }
        self.tickers.update_one(
            {"ticker_name.ticker_id": symbol, "score_update_event_ids": {"$ne": event_id}},
            [{"$set": {
                "ticker_score": score_expression,
                "updated_at": observed_at,
                "score_update_event_ids": {"$slice": [
                    {"$concatArrays": [{"$ifNull": ["$score_update_event_ids", []]}, [event_id]]}, -512
                ]},
            }}],
        )
        return self.tickers.find_one(
            {"ticker_name.ticker_id": symbol, "score_update_event_ids": event_id}, {"_id": 1}
        ) is not None

    @invalidates_read_cache("ticker")
    def save_ticker(self, ticker: TickerDTO) -> str:
        document = Ticker.from_dto(ticker)
        payload = document.model_dump(mode="python", by_alias=True, exclude={"id", "score_update_event_ids"})
        query = {"ticker_name.ticker_id": ticker.ticker_name.ticker_id}
        self.tickers.update_one(query, {"$set": payload}, upsert=True)
        saved = self.tickers.find_one(query, {"_id": 1})
        return str(saved["_id"])

    @invalidates_read_cache("ticker")
    def ensure_ticker_identity(self, ticker_name: TickerNameDTO) -> None:
        """Ensure a ticker identity exists without overwriting scores or links."""
        self.tickers.update_one(
            {"ticker_name.ticker_id": ticker_name.ticker_id},
            {"$setOnInsert": {
                "ticker_name": ticker_name.model_dump(mode="python"),
                "ticker_score": {"sentiment": {"score": 0.0, "tag": "neutral", "impact_score": 0.0}, "delta_score": 0.0},
                "relevant_events": [],
                "ticker_graph": None,
                "score_update_event_ids": [],
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        if ticker_name.company_name:
            self.tickers.update_one(
                {"ticker_name.ticker_id": ticker_name.ticker_id},
                {"$set": {"ticker_name.company_name": ticker_name.company_name}},
            )

    @invalidates_read_cache("ticker")
    def save_correlation_graph(self, graph: dict[str, TickerGraphDTO]) -> int:
        updated = 0
        for symbol, ticker_graph in graph.items():
            result = self.tickers.update_one(
                {"ticker_name.ticker_id": symbol},
                {
                    "$set": {"ticker_graph": ticker_graph.model_dump(mode="python"),
                             "updated_at": datetime.now(timezone.utc)},
                    "$setOnInsert": {
                        "ticker_name": {"ticker_id": symbol, "company_name": ""},
                        "ticker_score": {"sentiment": {"score": 0.0, "tag": "neutral", "impact_score": 0.0}, "delta_score": 0.0},
                        "relevant_events": [],
                    },
                },
                upsert=True,
            )
            updated += int(result.modified_count > 0 or result.upserted_id is not None)
        return updated

    @cached_read("mongo-ticker", 10)
    def get_ticker(self, ticker_name_or_company: str) -> Ticker | None:
        """Find a ticker by symbol or case-insensitive company-name substring."""
        search = ticker_name_or_company.strip()
        if not search:
            return None
        symbol = search.upper().replace("$", "").replace("-", ".")
        record = self.tickers.find_one({"$or": [
            {"ticker_name.ticker_id": symbol},
            {"ticker_name.company_name": {"$regex": re.escape(search), "$options": "i"}},
        ]})
        return Ticker.model_validate(record) if record else None

    def get_effective_ticker_scores(self, ticker_id: str, *, as_of: datetime | None = None) -> EffectiveTickerScoresDTO | None:
        ticker = self.get_ticker(ticker_id)
        return ticker.to_dto().effective_scores(as_of=as_of) if ticker else None
