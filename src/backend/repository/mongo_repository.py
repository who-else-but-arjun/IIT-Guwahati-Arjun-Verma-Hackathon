"""MongoDB persistence for connector DTOs and typed documents."""

from __future__ import annotations

import os
from threading import Lock
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

from dto.news import NewsEventDTO
from dto.stock import TickerNameDTO
from models.documents import NewsEvent
from repository.ticker_repository import TickerRepositoryMixin
from utils.datetime_utils import utc_date_boundary
from constants import NewsAnalysisStatus
from constants import MAX_NEWS_EVENT_DOCUMENTS
from services.redis.cache import cached_read, invalidates_read_cache

_retention_checked = False
_repository_setup_lock = Lock()
_repository_setup_complete = False


class MongoRepository(TickerRepositoryMixin):
    """Persist news and prices and maintain the reciprocal event/ticker links."""

    def __init__(self, uri: str | None = None, database_name: str | None = None,
                 client: MongoClient | None = None):
        self.client = client or MongoClient(uri or os.getenv("MONGO_URI", "mongodb://mongo:27017"))
        self.database: Database = self.client[database_name or os.getenv("MONGO_DATABASE", "stock_news")]
        self.news_events: Collection = self.database["news_events"]
        self.tickers: Collection = self.database["tickers"]
        self._retention_insert_count = 0
        # API views create repositories per request. Schema migrations, index
        # checks and retention scans are startup work; repeating them for every
        # GET starves the request pool while the news stream is ingesting.
        global _retention_checked, _repository_setup_complete
        if not _repository_setup_complete:
            with _repository_setup_lock:
                if not _repository_setup_complete:
                    self.migrate_analysis_metadata()
                    self.ensure_indexes()
                    if not _retention_checked:
                        self.prune_oldest_news_events()
                        _retention_checked = True
                    _repository_setup_complete = True

    def migrate_analysis_metadata(self) -> None:
        """Keep workflow status in metadata and discard obsolete error details."""
        workflow_fields = ("analysis_status", "analysis_updated_at")
        self.news_events.update_many(
            {"$or": [
                {name: {"$exists": True}} for name in (*workflow_fields, "analysis_started_at", "analysis_error")
            ] + [
                {"metadata.analysis_error": {"$exists": True}}
            ]},
            [
                {"$set": {
                    "metadata.analysis_status": {"$ifNull": ["$metadata.analysis_status", "$analysis_status"]},
                    "metadata.analysis_updated_at": {
                        "$convert": {
                            "input": {"$ifNull": ["$metadata.analysis_updated_at", "$analysis_updated_at"]},
                            "to": "string", "onError": None, "onNull": None,
                        }
                    },
                }},
                {"$unset": ["analysis_status", "analysis_updated_at", "analysis_started_at", "analysis_error", "metadata.analysis_error"]},
            ],
        )
        # Records written by older versions used this status enum value. Fold
        # those documents into the remaining retryable status before Pydantic
        # validates them against the current enum.
        self.news_events.update_many(
            {"metadata.analysis_status": "awaiting_opencode_key"},
            {"$set": {"metadata.analysis_status": NewsAnalysisStatus.PENDING_ANALYSIS.value}},
        )
        # Older imports may have persisted model output before introducing the
        # workflow status field. Mark only records with all core analysis fields.
        self.news_events.update_many(
            {"metadata.analysis_status": {"$exists": False}, "category": {"$type": "string"},
             "sentiment.score": {"$type": "number"}, "sentiment.impact_score": {"$type": "number"}},
            {"$set": {"metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value}},
        )

    def ensure_indexes(self) -> None:
        self.news_events.create_index([("event_timestamp", DESCENDING)], name="news_datetime")
        self.news_events.create_index(
            [("metadata.analysis_status", ASCENDING),
             ("metadata.analysis_updated_at", DESCENDING),
             ("event_timestamp", DESCENDING)],
            name="news_latest_analyzed",
        )
        expected_pending_key = {"metadata.analysis_status": ASCENDING, "event_timestamp": ASCENDING}
        for existing in self.news_events.list_indexes():
            if existing.get("name") == "news_pending_analysis" and dict(existing["key"]) != expected_pending_key:
                self.news_events.drop_index("news_pending_analysis")
                break
        self.news_events.create_index(
            list(expected_pending_key.items()),
            name="news_pending_analysis",
        )
        self.news_events.create_index([("relevant_tickers.ticker_id", ASCENDING)], name="news_by_ticker")
        self.news_events.create_index(
            [("metadata.provider", ASCENDING), ("metadata.provider_article_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"metadata.provider_article_id": {"$type": "string"}},
            name="news_provider_article_unique",
        )
        self.news_events.create_index([("url", ASCENDING)], sparse=True, name="news_url")
        self.tickers.create_index([("ticker_name.ticker_id", ASCENDING)], unique=True, name="ticker_symbol_unique")
        self.tickers.create_index([("relevant_events.event_id", ASCENDING)], name="ticker_by_event")

    @invalidates_read_cache("news")
    def save_news(self, event: NewsEventDTO) -> str:
        document = NewsEvent.from_dto(event)
        update_fields: dict[str, object] = {
            "headline": document.headline,
            "text": document.text,
            "date": document.date.isoformat(),
            "time": document.time.isoformat(),
            "event_timestamp": event.event_datetime,
            "url": document.url,
        }
        # Workflow status is maintained in metadata by the processing pipeline.
        internal_fields = {"analysis_status", "analysis_updated_at", "analysis_started_at", "analysis_error"}
        update_fields.update({f"metadata.{key}": value for key, value in document.metadata.items()
                              if key not in internal_fields})
        if document.category is not None:
            update_fields["category"] = document.category.value
        if document.sentiment is not None:
            sentiment = document.sentiment.model_dump(mode="python")
            sentiment["tag"] = document.sentiment.tag.value
            update_fields["sentiment"] = sentiment
        provider_id = event.metadata.get("provider_article_id")
        already_processed = False
        if isinstance(provider_id, str) and provider_id:
            query = {"metadata.provider": event.metadata.get("provider"),
                     "metadata.provider_article_id": provider_id}
            existing = self.news_events.find_one(query, {"metadata.analysis_status": 1, "sentiment": 1})
            already_processed = bool(existing and (
                existing.get("metadata", {}).get("analysis_status") in {NewsAnalysisStatus.COMPLETE.value, NewsAnalysisStatus.APPLYING_SCORES.value}
                or existing.get("sentiment") is not None
            ))
            if event.relevant_tickers and not already_processed:
                update_fields["relevant_tickers"] = [x.model_dump(mode="python") for x in event.relevant_tickers]
            self.news_events.update_one(query, {"$set": update_fields, "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "metadata.analysis_status": NewsAnalysisStatus.QUEUED.value,
            }}, upsert=True)
            record = self.news_events.find_one(query, {"_id": 1})
            event_id = record["_id"]
        else:
            key = event.url or f"{event.date.isoformat()}T{event.time.isoformat()}:{event.headline}"
            query = {"url": key}
            existing = self.news_events.find_one(query, {"metadata.analysis_status": 1, "sentiment": 1})
            already_processed = bool(existing and (
                existing.get("metadata", {}).get("analysis_status") in {NewsAnalysisStatus.COMPLETE.value, NewsAnalysisStatus.APPLYING_SCORES.value}
                or existing.get("sentiment") is not None
            ))
            if event.relevant_tickers and not already_processed:
                update_fields["relevant_tickers"] = [x.model_dump(mode="python") for x in event.relevant_tickers]
            self.news_events.update_one({"url": key}, {"$set": update_fields, "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "metadata.analysis_status": NewsAnalysisStatus.QUEUED.value,
            }}, upsert=True)
            record = self.news_events.find_one({"url": key}, {"_id": 1})
            event_id = record["_id"]
        event_id_text = str(event_id)
        event_timestamp = event.event_datetime
        for related in (event.relevant_tickers if not already_processed else []):
            symbol = related.ticker_id
            ticker_query = {"ticker_name.ticker_id": symbol}
            self.tickers.update_one(
                ticker_query,
                {"$setOnInsert": {
                    "ticker_name": {"ticker_id": symbol, "company_name": ""},
                    "ticker_score": {"sentiment": {"score": 0.0, "tag": "neutral", "impact_score": 0.0}, "delta_score": 0.0},
                    "ticker_graph": None, "relevant_events": [],
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            event_link = {
                "event_id": event_id_text,
                "relevance_score": related.relevance_score,
                "scored_at": related.scored_at or event_timestamp,
            }
            self.tickers.update_one(
                ticker_query,
                [{"$set": {
                    "relevant_events": {"$let": {
                        "vars": {"events": {"$ifNull": ["$relevant_events", []]}},
                        "in": {"$cond": [
                            {"$in": [event_id_text, {"$map": {"input": "$$events", "as": "event", "in": "$$event.event_id"}}]},
                            {"$map": {
                                "input": "$$events", "as": "event",
                                "in": {"$cond": [
                                    {"$eq": ["$$event.event_id", event_id_text]},
                                    event_link,
                                    "$$event",
                                ]},
                            }},
                            {"$concatArrays": ["$$events", [event_link]]},
                        ]},
                    }},
                    "updated_at": datetime.now(timezone.utc),
                }}],
            )
        if existing is None:
            self._retention_insert_count += 1
            if self._retention_insert_count >= 100:
                self.prune_oldest_news_events()
                self._retention_insert_count = 0
        return event_id_text

    def prune_oldest_news_events(self, *, max_documents: int = MAX_NEWS_EVENT_DOCUMENTS) -> int:
        """Delete the oldest events if the collection exceeds its configured bound."""
        count = self.news_events.count_documents({})
        excess = count - max_documents
        if excess <= 0:
            return 0
        oldest_ids = [row["_id"] for row in self.news_events.find({}, {"_id": 1})
                      .sort([("event_timestamp", ASCENDING), ("_id", ASCENDING)]).limit(excess)]
        if not oldest_ids:
            return 0
        event_ids = [str(event_id) for event_id in oldest_ids]
        self.tickers.update_many(
            {"relevant_events.event_id": {"$in": event_ids}},
            {"$pull": {"relevant_events": {"event_id": {"$in": event_ids}}}},
        )
        return self.news_events.delete_many({"_id": {"$in": oldest_ids}}).deleted_count

    def save_news_analysis(self, event_id: str, event: NewsEventDTO) -> None:
        """Persist completed model outputs and synchronize reciprocal event links."""
        if not ObjectId.is_valid(event_id):
            raise ValueError("Invalid event ObjectId")
        existing = self.news_events.find_one({"_id": ObjectId(event_id)}, {"relevant_tickers.ticker_id": 1})
        if existing is None:
            raise LookupError(f"News event {event_id} does not exist")
        old_symbols = {x["ticker_id"] for x in existing.get("relevant_tickers", [])}
        new_symbols = {x.ticker_id for x in event.relevant_tickers}
        sentiment_payload = event.sentiment.model_dump(mode="python") if event.sentiment else None
        if sentiment_payload is not None:
            sentiment_payload["tag"] = event.sentiment.tag.value
        self.news_events.update_one(
            {"_id": ObjectId(event_id)},
            {"$set": {
                "category": event.category.value if event.category else None,
                "sentiment": sentiment_payload,
                "relevant_tickers": [x.model_dump(mode="python") for x in event.relevant_tickers],
                "metadata.analysis_status": NewsAnalysisStatus.APPLYING_SCORES.value,
                "metadata.analysis_models": event.metadata.get("analysis_models"),
            }},
        )
        for removed in old_symbols - new_symbols:
            self.tickers.update_one(
                {"ticker_name.ticker_id": removed},
                {"$pull": {"relevant_events": {"event_id": event_id}}},
            )
        for related in event.relevant_tickers:
            symbol = related.ticker_id
            self.ensure_ticker_identity(TickerNameDTO(ticker_id=symbol))
            link = {"event_id": event_id, "relevance_score": related.relevance_score,
                    "scored_at": related.scored_at or event.event_datetime}
            self.tickers.update_one(
                {"ticker_name.ticker_id": symbol},
                [{"$set": {
                    "relevant_events": {"$let": {
                        "vars": {"events": {"$ifNull": ["$relevant_events", []]}},
                        "in": {"$cond": [
                            {"$in": [event_id, {"$map": {"input": "$$events", "as": "event", "in": "$$event.event_id"}}]},
                            {"$map": {"input": "$$events", "as": "event", "in": {"$cond": [
                                {"$eq": ["$$event.event_id", event_id]}, link, "$$event"
                            ]}}},
                            {"$concatArrays": ["$$events", [link]]},
                        ]},
                    }},
                    "updated_at": datetime.now(timezone.utc),
                }}],
            )

    @invalidates_read_cache("news")
    def mark_news_processing_status(self, event_id: str, status: str) -> None:
        if not ObjectId.is_valid(event_id):
            return
        fields: dict[str, object] = {
            "metadata.analysis_status": NewsAnalysisStatus(status).value,
            "metadata.analysis_updated_at": datetime.now(timezone.utc).isoformat(),
        }
        update: dict[str, object] = {"$set": fields}
        if NewsAnalysisStatus(status) == NewsAnalysisStatus.COMPLETE:
            update["$unset"] = {"metadata.analysis_retry_at": "", "metadata.analysis_retry_count": "",
                                 "metadata.analysis_claim_until": ""}
        self.news_events.update_one({"_id": ObjectId(event_id)}, update)

    @invalidates_read_cache("news")
    def defer_news_analysis(self, event_id: str, error: Exception) -> None:
        """Back off retryable model/provider failures without retrying the same row continuously."""
        if not ObjectId.is_valid(event_id):
            return
        record = self.news_events.find_one(
            {"_id": ObjectId(event_id)}, {"metadata.analysis_retry_count": 1}
        ) or {}
        metadata = record.get("metadata", {})
        attempts = int(metadata.get("analysis_retry_count", 0)) + 1
        retry_seconds = min(3600, 120 * (2 ** min(attempts - 1, 5)))
        response = getattr(error, "response", None)
        if getattr(response, "status_code", None) == 429:
            retry_after = getattr(response, "headers", {}).get("Retry-After")
            try:
                retry_seconds = max(retry_seconds, min(3600, int(retry_after)))
            except (TypeError, ValueError):
                retry_seconds = max(retry_seconds, 600)
        now = datetime.now(timezone.utc)
        self.news_events.update_one(
            {"_id": ObjectId(event_id)},
            {"$set": {
                "metadata.analysis_status": NewsAnalysisStatus.PENDING_ANALYSIS.value,
                "metadata.analysis_updated_at": now.isoformat(),
                "metadata.analysis_retry_at": (now + timedelta(seconds=retry_seconds)).isoformat(),
                "metadata.analysis_retry_count": attempts,
            }, "$unset": {"metadata.analysis_claim_until": ""}},
        )

    def is_event_processed(self, event_id: str) -> bool:
        if not ObjectId.is_valid(event_id):
            return False
        return self.news_events.find_one(
            {"_id": ObjectId(event_id), "metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value}, {"_id": 1}
        ) is not None

    def is_news_analysis_due(self, event_id: str) -> bool:
        if not ObjectId.is_valid(event_id):
            return False
        now = datetime.now(timezone.utc).isoformat()
        return self.news_events.find_one({
            "_id": ObjectId(event_id),
            "metadata.analysis_status": {"$ne": NewsAnalysisStatus.COMPLETE.value},
            "$or": [
                {"metadata.analysis_retry_at": {"$exists": False}},
                {"metadata.analysis_retry_at": {"$lte": now}},
            ],
        }, {"_id": 1}) is not None

    def get_pending_news(self, limit: int = 50) -> list[tuple[str, NewsEventDTO]]:
        now_text = datetime.now(timezone.utc).isoformat()
        rows = self.news_events.find({
            "metadata.analysis_status": {"$in": [status.value for status in (
                NewsAnalysisStatus.QUEUED, NewsAnalysisStatus.PENDING_ANALYSIS,
                NewsAnalysisStatus.APPLYING_SCORES,
            )]},
            "$or": [
                {"metadata.analysis_retry_at": {"$exists": False}},
                {"metadata.analysis_retry_at": {"$lte": now_text}},
            ],
        }).sort([("event_timestamp", ASCENDING), ("_id", ASCENDING)]).limit(limit)
        return [(str(row["_id"]), NewsEvent.model_validate(row).to_dto()) for row in rows]

    def claim_pending_news(self, *, lease_seconds: int = 600) -> tuple[str, NewsEventDTO] | None:
        """Claim the oldest due story atomically so workers cannot process it twice."""
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        row = self.news_events.find_one_and_update(
            {
                "metadata.analysis_status": {"$in": [status.value for status in (
                    NewsAnalysisStatus.QUEUED, NewsAnalysisStatus.PENDING_ANALYSIS,
                    NewsAnalysisStatus.APPLYING_SCORES,
                )]},
                "$and": [
                    {"$or": [
                        {"metadata.analysis_retry_at": {"$exists": False}},
                        {"metadata.analysis_retry_at": {"$lte": now_text}},
                    ]},
                    {"$or": [
                        {"metadata.analysis_claim_until": {"$exists": False}},
                        {"metadata.analysis_claim_until": {"$lte": now_text}},
                    ]},
                ],
            },
            {"$set": {"metadata.analysis_claim_until": (now + timedelta(seconds=lease_seconds)).isoformat()}},
            sort=[("event_timestamp", ASCENDING), ("_id", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        if row is None:
            return None
        return str(row["_id"]), NewsEvent.model_validate(row).to_dto()



    def save_news_many(self, events: Iterable[NewsEventDTO]) -> list[str]:
        return [self.save_news(event) for event in events]




    @cached_read("mongo-event", 30)
    def get_event(self, event_id: str) -> NewsEventDTO | None:
        if not ObjectId.is_valid(event_id):
            return None
        record = self.news_events.find_one({
            "_id": ObjectId(event_id),
            "metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value,
            "category": {"$type": "string"},
            "sentiment.score": {"$type": "number"},
            "sentiment.impact_score": {"$type": "number"},
        })
        event = NewsEvent.model_validate(record).to_dto() if record else None
        return event.with_effective_scores() if event else None

    @cached_read("mongo-ticker-graph-list", 60)
    def list_ticker_graph(self, limit: int = 200) -> list[dict[str, object]]:
        """Return persisted ticker identities and correlation edges for the universe view."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        rows = self.tickers.find(
            {},
            {"_id": 0, "ticker_name": 1, "ticker_graph": 1, "ticker_score": 1, "updated_at": 1, "logo_url": 1},
        ).sort("ticker_name.ticker_id", ASCENDING).limit(limit)
        return list(rows)

    def get_news_event(self, event_id: str) -> NewsEventDTO | None:
        """Compatibility alias for get_event."""
        return self.get_event(event_id)

    def get_event_for_processing(self, event_id: str) -> NewsEventDTO | None:
        """Load a queued or partially analyzed event for an idempotent retry."""
        if not ObjectId.is_valid(event_id):
            return None
        record = self.news_events.find_one({"_id": ObjectId(event_id)})
        return NewsEvent.model_validate(record).to_dto() if record else None

    @cached_read("mongo-events", 20)
    def get_events(
        self,
        *,
        category: str | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        since: datetime | date | None = None,
        until: datetime | date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NewsEventDTO]:
        """Return newest-first stories whose analysis and trading handoff completed."""
        query: dict[str, object] = {
            "metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value,
            "category": {"$type": "string"},
            "sentiment.score": {"$type": "number"},
            "sentiment.impact_score": {"$type": "number"},
        }
        if category is not None:
            query["category"] = category
        return self._query_events(query, score_min=score_min, score_max=score_max,
                                  since=since, until=until, limit=limit, offset=offset)

    @cached_read("mongo-event-count", 20)
    def count_events(
        self,
        *,
        category: str | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        since: datetime | date | None = None,
        until: datetime | date | None = None,
    ) -> int:
        """Count stories whose analysis and trading handoff completed."""
        query: dict[str, object] = {
            "metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value,
            "category": {"$type": "string"},
            "sentiment.score": {"$type": "number"},
            "sentiment.impact_score": {"$type": "number"},
        }
        if category is not None:
            query["category"] = category
        if score_min is not None or score_max is not None:
            score_query: dict[str, float] = {}
            if score_min is not None:
                score_query["$gte"] = score_min
            if score_max is not None:
                score_query["$lte"] = score_max
            query["sentiment.score"] = score_query
        if since is not None or until is not None:
            time_query: dict[str, datetime] = {}
            if since is not None:
                time_query["$gte"] = utc_date_boundary(since, end_of_date=False)
            if until is not None:
                time_query["$lte"] = utc_date_boundary(until, end_of_date=True)
            query["event_timestamp"] = time_query
        return self.news_events.count_documents(query)

    @cached_read("mongo-ticker-events", 20)
    def get_ticker_events(
        self,
        ticker_name: str,
        *,
        category: str | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        since: datetime | date | None = None,
        until: datetime | date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NewsEventDTO]:
        """Return newest-first events associated with a ticker."""
        ticker = self.get_ticker(ticker_name)
        if ticker is None:
            return []
        query: dict[str, object] = {
            "relevant_tickers.ticker_id": ticker.ticker_name.ticker_id,
            "metadata.analysis_status": NewsAnalysisStatus.COMPLETE.value,
            "category": {"$type": "string"},
            "sentiment.score": {"$type": "number"},
            "sentiment.impact_score": {"$type": "number"},
        }
        if category is not None:
            query["category"] = category
        return self._query_events(query, score_min=score_min, score_max=score_max,
                                  since=since, until=until, limit=limit, offset=offset)

    def _query_events(
        self,
        query: dict[str, object],
        *,
        score_min: float | None,
        score_max: float | None,
        since: datetime | date | None,
        until: datetime | date | None,
        limit: int,
        offset: int,
    ) -> list[NewsEventDTO]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if not 0 <= offset <= 100_000:
            raise ValueError("offset must be between 0 and 100000")
        if score_min is not None and not -1.0 <= score_min <= 1.0:
            raise ValueError("score_min must be between -1 and 1")
        if score_max is not None and not -1.0 <= score_max <= 1.0:
            raise ValueError("score_max must be between -1 and 1")
        if score_min is not None and score_max is not None and score_min > score_max:
            raise ValueError("score_min cannot exceed score_max")

        if since is not None or until is not None:
            time_query: dict[str, datetime] = {}
            if since is not None:
                time_query["$gte"] = utc_date_boundary(since, end_of_date=False)
            if until is not None:
                time_query["$lte"] = utc_date_boundary(until, end_of_date=True)
            if since is not None and until is not None:
                if time_query["$gte"] > time_query["$lte"]:
                    raise ValueError("since must be earlier than or equal to until")
            query["event_timestamp"] = time_query

        cursor = self.news_events.find(query).sort([
            ("metadata.analysis_updated_at", DESCENDING),
            ("event_timestamp", DESCENDING),
        ])
        as_of = datetime.now(timezone.utc)
        matches: list[NewsEventDTO] = []
        skipped = 0
        for row in cursor:
            event = NewsEvent.model_validate(row).to_dto().with_effective_scores(as_of=as_of)
            score = event.sentiment.score if event.sentiment is not None else 0.0
            if score_min is not None and score < score_min:
                continue
            if score_max is not None and score > score_max:
                continue
            if skipped < offset:
                skipped += 1
                continue
            matches.append(event)
            if len(matches) >= limit:
                break
        return matches



    def close(self) -> None:
        self.client.close()
