"""OpenCode Zen Jev inference adapter for news classification and impact."""

from __future__ import annotations

import os
import time
from typing import Mapping

import requests

from constants import NewsCategory, JEV_BASE_URL, JEV_MODEL, JEV_MAX_RETRIES, JEV_TIMEOUT_SECONDS


class JevClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 timeout: float = JEV_TIMEOUT_SECONDS) -> None:
        self.api_key = api_key or os.getenv("OPENCODE_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout
        self._rate_limited_until = 0.0

    def classify_category_and_impact(self, article_text: str) -> tuple[NewsCategory, float]:
        if time.monotonic() < self._rate_limited_until:
            raise RuntimeError("Jev rate-limit cooldown is active.")
        if not self.api_key:
            raise RuntimeError("OPENCODE_API_KEY is not configured; Jev news analysis is unavailable.")
        categories = {
            NewsCategory.EARNINGS.value: "Earnings, financial results, guidance, or company outlook.",
            NewsCategory.MERGERS_ACQUISITIONS.value: "Mergers, acquisitions, divestitures, or major investments.",
            NewsCategory.PRODUCT_INNOVATION.value: "Product launches, research, technology, or innovation.",
            NewsCategory.REGULATION_LEGAL.value: "Regulation, litigation, investigations, or legal decisions.",
            NewsCategory.MACROECONOMIC.value: "Interest rates, inflation, employment, or broad economic policy.",
            NewsCategory.ANALYST_RATINGS.value: "Analyst opinions, price targets, or rating changes.",
            NewsCategory.CORPORATE_ACTIONS.value: "Buybacks, dividends, splits, leadership, or other corporate actions.",
            NewsCategory.OPERATIONS_SUPPLY_CHAIN.value: "Production, operations, labor, logistics, or supply-chain news.",
            NewsCategory.MARKET_TRADING.value: "Market activity, trading, securities flows, or price moves.",
            NewsCategory.GEOPOLITICAL_EVENT.value: "Wars, armed conflicts, sanctions, elections, diplomatic crises, or geopolitical developments that may affect companies or markets.",
        }
        impact_criteria = [
            f"Impact level {level}/9: {'no material financial impact' if level == 0 else 'very high potential to move affected securities' if level == 9 else 'increasingly material potential financial or market impact'}."
            for level in range(10)
        ]
        response = self._ask(
            {"article": article_text[:12000]},
            {
                "category": {
                    "type": "choice",
                    "instructions": "Choose the single best primary financial-news category. Use market_trading if no more specific category applies.",
                    "criteria": categories,
                },
                "impact": {
                    "type": "score",
                    "instructions": "Estimate the magnitude of potential financial impact of this news, independent of sentiment. Use 0 for negligible and 9 for exceptionally high impact.",
                    "criteria": impact_criteria,
                },
            },
        )
        answers = response.get("answers", {})
        category_value = str(answers.get("category", {}).get("choice") or "").strip().lower()
        try:
            category = NewsCategory(category_value)
        except ValueError as exc:
            raise ValueError(f"Jev returned an unknown news category: {category_value!r}") from exc
        impact = max(0.0, min(1.0, float(answers.get("impact", {})["score"]) / 9.0))
        return category, impact

    def _ask(self, state: Mapping[str, str], questions: Mapping[str, object]) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {"model": JEV_MODEL, "state": dict(state), "questions": dict(questions)}
        for attempt in range(JEV_MAX_RETRIES):
            try:
                response = self.session.post(
                    f"{JEV_BASE_URL}/systemone", json=body, headers=headers, timeout=self.timeout
                )
            except requests.RequestException:
                if attempt + 1 == JEV_MAX_RETRIES:
                    raise
                time.sleep(min(2 ** attempt, 30))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        cooldown = max(600.0, min(3600.0, float(retry_after))) if retry_after else 600.0
                    except ValueError:
                        cooldown = 600.0
                    self._rate_limited_until = time.monotonic() + cooldown
                    response.raise_for_status()
                if attempt + 1 < JEV_MAX_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(max(float(retry_after), 1.0), 120.0) if retry_after else min(2 ** attempt, 30)
                    except ValueError:
                        delay = min(2 ** attempt, 30)
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Jev returned a non-object response.")
            return payload
        raise RuntimeError("Jev request failed after retries.")
