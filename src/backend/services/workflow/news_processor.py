"""Orchestrate news analysis and direct/correlation-based stock updates."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from dto.news import NewsEventDTO, RelevantTickerDTO, SentimentDTO
from repository.mongo_repository import MongoRepository
from services.models.inference import FinancialNewsModelSuite, MODEL_SUITE
from services.models.jev_client import JevClient
from constants import GRAPH_PROPAGATION_SCALE, SCORE_EPSILON, NewsAnalysisStatus
from services.workflow.trading_socket import publish_score_update

logger = logging.getLogger(__name__)


class NewsProcessingWorkflow:
    """Run model inference and persist derived event/ticker scores.

    Until model weights and the Jev key are available, events remain stored
    with a retryable analysis status instead of fabricated predictions.
    """

    def __init__(self, repository: MongoRepository, *, model_suite: FinancialNewsModelSuite | None = None,
                 jev_client: JevClient | None = None) -> None:
        self.repository = repository
        self.models = model_suite or MODEL_SUITE
        self.jev = jev_client or JevClient()

    def process(self, event: NewsEventDTO, event_id: str | None = None, *,
                score_time: datetime | None = None, notify_trading: bool = True) -> str:
        event_id = event_id or self.repository.save_news(event)
        if self.repository.is_event_processed(event_id):
            return event_id
        try:
            stored = self.repository.get_event_for_processing(event_id)
            enriched = stored or event
            already_analyzed = bool(
                enriched.category is not None
                and enriched.sentiment is not None
                and enriched.metadata.get("analysis_models")
            )
            if not already_analyzed:
                article_text = self.models.prepare_article_text(event.headline, event.text)
                # Jev has a tighter provider rate limit than local model inference.
                # Ask it first so a 429 does not also burn CPU on three local models.
                try:
                    category, impact_score = self.jev.classify_category_and_impact(article_text)
                except Exception as exc:
                    category, impact_score = self.models.classify_category_and_impact(article_text)
                    logger.warning("Jev unavailable for event %s (%s); category and impact came from FLANG-Laya.", event_id, type(exc).__name__)
                sentiment_tag, sentiment_score = self.models.analyze_sentiment(article_text)
                candidates = self.models.select_and_score_tickers(article_text)
                relevant_tickers = [
                    RelevantTickerDTO(
                        ticker_id=candidate.ticker_id,
                        relevance_score=candidate.relevance_score,
                        scored_at=event.event_datetime,
                    )
                    for candidate in candidates
                ]
                enriched = event.model_copy(update={
                    "category": category,
                    "sentiment": SentimentDTO(
                        score=sentiment_score,
                        tag=sentiment_tag,
                        impact_score=impact_score,
                        scored_at=event.event_datetime,
                    ),
                    "relevant_tickers": relevant_tickers,
                    "metadata": {
                        **event.metadata,
                        "analysis_models": "flang_roberta_classifier,flang_roberta_regressor,flang_roberta_stock_selector,flang_laya",
                    },
                })
                self.repository.save_news_analysis(event_id, enriched)
            # Score updates are idempotent, so retries can safely finish a
            # partially applied event without spending time on model inference.
            affected_symbols = self._apply_stock_updates(
                event_id, enriched, as_of=score_time or datetime.now(timezone.utc),
            )
            if affected_symbols and notify_trading:
                if not publish_score_update(event_id, affected_symbols):
                    raise RuntimeError("Trading service did not acknowledge the analyzed news decision.")
            # Feed queries only return COMPLETE events; this commit therefore
            # means model output, stock scores, and the trading decision exist.
            self.repository.mark_news_processing_status(event_id, "complete")
            return event_id
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"[:500]
            self.repository.defer_news_analysis(event_id, exc)
            logger.warning("News analysis pending for event %s: %s", event_id, reason)
            return event_id

    def retry_pending(self, limit: int = 50) -> int:
        processed = 0
        while processed < limit:
            claimed = self.repository.claim_pending_news()
            if claimed is None:
                break
            event_id, event = claimed
            logger.info("Analyzing queued story %s: %s", event_id, event.headline[:180])
            self.process(event, event_id)
            processed += 1
        return processed

    def _apply_stock_updates(self, event_id: str, event: NewsEventDTO, *, as_of: datetime) -> list[str]:
        if event.sentiment is None:
            return []
        direct_symbols = {ticker.ticker_id for ticker in event.relevant_tickers}
        affected_symbols: set[str] = set()
        effective_sentiment = event.sentiment.effective_score(
            as_of=as_of, fallback_time=event.event_datetime,
        )
        effective_impact = event.sentiment.impact_score

        for ticker in event.relevant_tickers:
            effective_relevance = ticker.relevance_score
            contribution = effective_sentiment * effective_impact * effective_relevance
            updated = self.repository.update_ticker_sentiment(
                ticker.ticker_id,
                event_id=event_id,
                contribution=contribution,
                impact=effective_impact * effective_relevance,
                observed_at=as_of,
            )
            if updated:
                affected_symbols.add(ticker.ticker_id)

        # Propagate one hop from direct stocks only. The signed correlation
        # keeps inverse relationships directional; 0.15 keeps propagated
        # influence below the direct event contribution.
        for ticker in event.relevant_tickers:
            graph = self.repository.get_ticker_graph(ticker.ticker_id)
            if graph is None:
                continue
            effective_relevance = ticker.relevance_score
            direct_contribution = effective_sentiment * effective_impact * effective_relevance
            for neighbor, correlation in graph.correlations.items():
                if neighbor in direct_symbols or neighbor == ticker.ticker_id:
                    continue
                propagated = direct_contribution * float(correlation) * GRAPH_PROPAGATION_SCALE
                if abs(propagated) <= SCORE_EPSILON:
                    continue
                updated = self.repository.update_ticker_sentiment(
                    neighbor,
                    event_id=event_id,
                    contribution=propagated,
                    impact=effective_impact * abs(float(correlation)) * GRAPH_PROPAGATION_SCALE,
                    observed_at=as_of,
                )
                if updated:
                    affected_symbols.add(neighbor)
        return sorted(affected_symbols)
