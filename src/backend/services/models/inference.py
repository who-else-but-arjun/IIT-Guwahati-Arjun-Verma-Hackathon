"""Task-specific inference adapters for the selected financial models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
import math
import re
from typing import Callable

from pydantic import BaseModel, Field

from dto.news import SentimentTag

from .model_io import infer_laya, infer_stock_candidates, infer_text, load_model
from constants import STOCK_SELECTOR_TOP_K, SP100_COMPANIES, NewsCategory

MIN_STOCK_RELEVANCE = 0.30


class ScoredTickerCandidate(BaseModel):
    ticker_id: str
    selector_score: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)


class FinancialNewsModelSuite:
    """Lazy, cached adapters for classifier, regressor, selector, and Laya."""

    def __init__(self, *, model_loader: Callable = load_model,
                 laya_infer: Callable = infer_laya) -> None:
        self.model_loader = model_loader
        self.laya_infer = laya_infer
        self._models: dict[str, object] = {}
        self._load_error: str | None = None
        self._retry_after: datetime | None = None

    @staticmethod
    def prepare_article_text(headline: str, text: str, max_chars: int = 12000) -> str:
        """Normalize provider HTML and form the model's headline/article input."""
        body = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", str(text or ""))
        body = unescape(re.sub(r"<[^>]+>", " ", body))
        body = re.sub(r"\s+", " ", body).strip()
        title = re.sub(r"\s+", " ", str(headline or "")).strip()
        return f"Headline: {title}\n\nArticle: {body}"[:max_chars]

    def ensure_loaded(self) -> None:
        if self._models:
            return
        now = datetime.now(timezone.utc)
        if self._retry_after and now < self._retry_after:
            raise RuntimeError(self._load_error or "Model loading is in retry backoff.")
        try:
            loaded = {
                "sentiment_classification": self.model_loader("sentiment_classification"),
                "sentiment_regression": self.model_loader("sentiment_scorer"),
                "stock_selector": self.model_loader("stock_selector"),
                "laya": self.model_loader("flang_laya"),
            }
        except Exception as exc:
            self._load_error = f"Required model weights could not be loaded: {type(exc).__name__}: {exc}"
            self._retry_after = now + timedelta(minutes=5)
            raise RuntimeError(self._load_error) from exc
        self._models = loaded
        self._load_error = None
        self._retry_after = None

    def analyze_sentiment(self, article_text: str) -> tuple[SentimentTag, float]:
        self.ensure_loaded()
        classification = infer_text(self._models["sentiment_classification"], article_text)
        tag = SentimentTag(str(classification["label"]).strip().lower())
        score = float(infer_text(self._models["sentiment_regression"], article_text))
        if not math.isfinite(score):
            raise ValueError("FLANG-RoBERTa sentiment regressor returned a non-finite score.")
        return tag, max(-1.0, min(1.0, score))

    def classify_category_and_impact(self, article_text: str) -> tuple[NewsCategory, float]:
        """Use FLANG-Laya typed decisions when the Jev category/impact API is down."""
        self.ensure_loaded()
        state = [{"article": article_text[:12000]}]
        category_descriptions = {
            NewsCategory.EARNINGS: "Earnings, financial results, guidance, or company outlook.",
            NewsCategory.MERGERS_ACQUISITIONS: "Mergers, acquisitions, divestitures, or major investments.",
            NewsCategory.PRODUCT_INNOVATION: "Product launches, research, technology, or innovation.",
            NewsCategory.REGULATION_LEGAL: "Regulation, litigation, investigations, or legal decisions.",
            NewsCategory.MACROECONOMIC: "Interest rates, inflation, employment, or broad economic policy.",
            NewsCategory.ANALYST_RATINGS: "Analyst opinions, price targets, or rating changes.",
            NewsCategory.CORPORATE_ACTIONS: "Buybacks, dividends, splits, leadership, or other corporate actions.",
            NewsCategory.OPERATIONS_SUPPLY_CHAIN: "Production, operations, labor, logistics, or supply-chain news.",
            NewsCategory.MARKET_TRADING: "Market activity, trading, securities flows, or price moves.",
            NewsCategory.GEOPOLITICAL_EVENT: "Wars, armed conflicts, sanctions, elections, or geopolitical developments.",
        }
        category_question = {
            "type": "choice",
            "instructions": "Choose the primary financial-news category described by the article.",
            "criteria": {category.value: description for category, description in category_descriptions.items()},
        }
        category_output = self.laya_infer(
            self._models["laya"], state, category_question, batch_size=1,
        )[0].get("answers", {}).get("sentiment", {}).get("choice")
        try:
            category = NewsCategory(str(category_output).strip().lower())
        except ValueError as exc:
            raise ValueError(f"FLANG-Laya returned an unknown news category: {category_output!r}") from exc

        impact_values = [round(index / 10, 1) for index in range(11)]
        impact_question = {
            "type": "score",
            "instructions": "Estimate potential financial impact independent of whether the news is positive or negative.",
            "criteria": [
                f"Impact {value:.1f}: {'negligible' if value == 0 else 'exceptionally high potential to move affected securities' if value == 1 else 'increasing material financial or market impact'}."
                for value in impact_values
            ],
        }
        impact_output = self.laya_infer(
            self._models["laya"], state, impact_question, batch_size=1,
        )[0].get("answers", {}).get("sentiment", {}).get("score")
        # Laya returns the expected rubric index (0..10), as used by its
        # financial regression adapter; convert that index to the UI's 0..1.
        impact = max(0.0, min(1.0, float(impact_output) / 10.0))
        return category, impact

    def is_financial_news(self, headline: str, text: str) -> bool:
        """Use FLANG-Laya to accept only substantive financial Bluesky posts."""
        self.ensure_loaded()
        article_text = self.prepare_article_text(headline, text)
        question = {
            "type": "choice",
            "instructions": (
                "Decide whether this social post contains substantive financial news "
                "about a company, security, market, or economy. Answer yes only for "
                "a factual or material financial update; answer no for casual ticker "
                "mentions, opinions without news, jokes, promotions, and product ads."
            ),
            "criteria": {
                "yes": "The post reports a concrete financial or market development, company event, earnings update, regulatory action, or material business news.",
                "no": "The post is not substantive financial news, or only mentions a ticker/company casually, promotionally, or without a concrete update.",
            },
        }
        outputs = self.laya_infer(
            self._models["laya"], [{"article": article_text}], question, batch_size=1,
        )
        if not outputs:
            raise ValueError("FLANG-Laya returned no finance relevance decision for Bluesky post.")
        choice = outputs[0].get("answers", {}).get("sentiment", {}).get("choice")
        normalized = str(choice or "").strip().lower()
        if normalized not in {"yes", "no"}:
            raise ValueError(f"FLANG-Laya returned an invalid Bluesky finance decision: {choice!r}.")
        return normalized == "yes"

    def select_and_score_tickers(self, article_text: str, *, headline: str | None = None,
                                 article_body: str | None = None) -> list[ScoredTickerCandidate]:
        self.ensure_loaded()
        selector = self._models["stock_selector"]
        shortlisted = infer_stock_candidates(
            selector, article_text,
            headline=headline,
            article_body=article_body,
            top_k=STOCK_SELECTOR_TOP_K,
        )
        if not shortlisted:
            return []
        question = {
            "type": "noul",
            "instructions": (
                "Does this article materially discuss the candidate stock or company? "
                "Answer yes only when it is relevant to the news, not for incidental mentions."
            ),
            "criteria": {
                "true": "The company or security is a material subject of this financial news.",
                "false": "The company is unrelated or mentioned only incidentally.",
            },
        }
        states = [
            {"article": article_text,
             "candidate_stock": f"{candidate['ticker']} — {SP100_COMPANIES.get(str(candidate['ticker']), '')}"}
            for candidate in shortlisted
        ]
        outputs = self.laya_infer(self._models["laya"], states, question, batch_size=8)
        if len(outputs) != len(shortlisted):
            raise ValueError("FLANG-Laya returned fewer scores than stock-selector candidates.")
        candidates: list[ScoredTickerCandidate] = []
        for candidate, output in zip(shortlisted, outputs):
            answers = output.get("answers", {})
            answer = answers.get("sentiment") or answers.get("relevance")
            if not isinstance(answer, dict) or "noul" not in answer:
                raise ValueError(f"FLANG-Laya response is missing relevance for {candidate['ticker']}.")
            relevance = max(0.0, min(1.0, float(answer["noul"])))
            if relevance < MIN_STOCK_RELEVANCE:
                continue
            candidates.append(ScoredTickerCandidate(
                ticker_id=str(candidate["ticker"]),
                selector_score=max(0.0, min(1.0, float(candidate["relevance_score"]))),
                relevance_score=relevance,
            ))
        return candidates


# Shared by Django startup and the news-processing workflow.
MODEL_SUITE = FinancialNewsModelSuite()
