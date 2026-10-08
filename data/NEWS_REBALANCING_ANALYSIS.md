# News Based Rebalancing: 30 Day Portfolio Comparison

## Executive summary

In the saved 30 day replay, the portfolio using **news signals alongside the normal strategy** finished with a higher value than the portfolio using normal rebalancing alone.

| Strategy | Value at shared checkpoint (Sep 4, 2026) | Value at final session (Oct 2, 2026) | 30 day P&L | Return over checkpoint |
|---|---:|---:|---:|---:|
| Normal rebalancing | $324,350.44 | $336,159.69 | $11,809.25 | 3.6409% |
| News + normal rebalancing | $324,350.44 | $338,408.51 | $14,058.07 | 4.3342% |
| **News-enabled advantage** | — | **+$2,248.82** | **+$2,248.82** | **+0.6933 percentage points** |

Both portfolios started this comparison at the same checkpoint value. The news-enabled portfolio therefore ended the replay approximately **0.69 percentage points ahead** over the measured period. Relative to the normal strategy's 30 day profit, the uplift was about **19.0%** ($2,248.82 / $11,809.25).

This is evidence that news based rebalancing added value in this replay. It is one historical comparison, not proof that news signals will outperform in every market regime. The result is sensitive to the chosen period, available news coverage, model scores, execution assumptions, and strategy settings.

## What was compared

- **Period:** common checkpoint at the Sep 4, 2026 New York session close through the final completed session on Oct 2, 2026. The replay covered 19 market sessions.
- **Starting state:** both strategies used the same portfolio state and $324,350.44 checkpoint value.
- **Normal strategy:** the S&P 100 residual-strength strategy with its ordinary static and volume-triggered rebalancing.
- **News strategy:** the same normal strategy, plus event-driven adjustments when analyzed news changed the scores of directly relevant stocks or graph-linked stocks enough to meet the news trigger.
- **News sample:** the historical replay selected at most 10 events per day, up to 300 total. 298 events had completed analyses; 2 were excluded because their analyses were incomplete.
- **Execution:** decisions generated from a news event are placed as pending orders and execute at the next eligible session's opening price. Transaction costs are applied by the simulator.
- **Reproducibility:** the staged comparison and promotion procedure is in `scripts/rebuild-comparison.ps1`, implemented by `src/backend/scripts/rebuild_monthly_comparison.py`.

The shared starting value matters: the comparison isolates the effect of enabling the news overlay during this one-month replay, rather than comparing two portfolios with different initial capital or historical starting dates.

## Observed news activity and outcome

The saved replay recorded **39 news-sentiment order rows** on **14 distinct execution dates**, associated with **29 distinct news event IDs**. This shows the news layer produced actions on a subset of the 19 market sessions rather than forcing a trade for every article or every day. Order rows are individual ticker-level actions; they are not equivalent to 39 independent market calls or 39 full portfolio resets.

That is about **2.8 ticker order rows per active execution date** and **1.34 order rows per event ID linked to an order**. Only 29 of the 298 analyzed events appeared in the saved order links, so the overlay did not turn every analyzed article into a trade. These counts are consistent with an event threshold and capped weight changes filtering the stream. The analysis completion rate was **99.3%** (298 of 300 selected events).

The replay's event cap is a historical workload limit used to make the one-month comparison tractable and consistent. It is not the intended live policy: while running, news events are processed as they arrive, without the historical 10-per-day cap. The normal strategy continues alongside the event-driven overlay.

### Why these results are consistent with a useful news overlay

1. **It can react between scheduled rebalances.** A static schedule can wait for its next review date. A sufficiently strong event signal can instead create a pending order for the next session.
2. **It targets the stocks implicated by the event.** The workflow combines article sentiment, estimated event impact, and per-stock relevance. Correlation graph propagation extends a smaller effect to related stocks.
3. **It scales the position change with signal strength.** The configured sizing rule uses sentiment magnitude, impact, and ticker relevance, and caps each adjustment. A high-impact, highly relevant event can justify a larger change than a weak or tangential mention.
4. **It does not replace the base strategy.** Static and volume-triggered rebalancing remain active. News provides another source of information that can alter holdings when the event score crosses the trigger.
5. **It produced a positive net difference after modeled costs in this replay.** The final value difference was $2,248.82 under the replay's execution and cost assumptions. That makes the observed advantage more informative than a gross, pre-cost signal comparison.

The replay establishes that the overlay generated identifiable event-linked orders and ended ahead for this sample. It does not by itself establish that any one event caused the full portfolio-level difference; both portfolios also experience market moves and normal strategy trades.

## How event signals affect portfolio weights

The pipeline scores each incoming event and its candidate stocks. Event sentiment and each stock's sentiment are separate concepts. The stock-level change is shaped by the event's sentiment, impact, the stock's relevance, and the portfolio limits. The signed contribution is then applied directly to the linked stock; graph-linked stocks can receive a smaller correlation-weighted contribution.

The current configured values include a **0.10 sentiment-delta trigger**, a **0.025 maximum news weight step**, a **0.10 maximum position weight**, a **0.15 graph propagation scale**, and **0.268% transaction cost**. The event sizing term is bounded as:

```text
event_strength = abs(event_sentiment × impact_score × ticker_relevance)
weight_step    = min(news_weight_step, max_position_weight × event_strength)
```

The event's sentiment sign determines the direction. The adjustment is still subject to the trigger, target-weight constraints, available portfolio state, and normal execution rules. A news decision made after a session is queued for the next eligible open, rather than filled at the already-known event-time price.

### Illustrative sizing examples

These examples apply the configured sizing rule; they are not claims about a specific historical article or fill.

| Example signal | Calculation | Illustrative sizing implication |
|---|---|---|
| Strong, directly relevant positive news: sentiment `+0.70`, impact `0.80`, relevance `0.90` | Strength = `0.70 × 0.80 × 0.90 = 0.504`; step = `min(0.025, 0.10 × 0.504)` | A positive adjustment capped at **2.5 percentage points** before other portfolio constraints. |
| Weak or tangential positive mention: sentiment `+0.30`, impact `0.30`, relevance `0.40` | Strength = `0.036`; the `0.10` trigger is not reached | No event-driven rebalance from this signal alone. |
| Strong negative news with the same magnitudes as the first example | Strength = `0.504`, with negative sign | A negative adjustment, subject to holdings and portfolio constraints. |

### Example of how an event becomes a next-session portfolio action

Suppose a news item receives negative sentiment `-0.70` and impact `0.80`, and the FLANG-Laya relevance score for one named S&P 100 company is `0.90`. The direct contribution is `-0.504`, which clears the configured `0.10` trigger. With a `0.025` step cap, the system schedules a reduction of up to **2.5 percentage points** in that company's target weight for the next session open, limited by its current position and portfolio constraints. If a correlated neighbor has correlation `0.60`, graph propagation scales its contribution to `-0.04536` (`-0.504 × 0.60 × 0.15`), which is below the `0.10` threshold in this configuration, so this example would not produce a neighbor trade. This illustrates why direct event-linked changes can be stronger than correlation spillovers.

The stock selector ranks the S&P 100 universe from news and company/ticker representations. FLANG-Laya estimates stock relevance. The sentiment models estimate the event's direction and score; the Jev analysis supplies event category and impact. The correlation graph is deliberately a lower-weight secondary path so that directly relevant companies dominate spillover effects.

## Interpretation and limitations

- **A one-month result is encouraging but noisy.** Nineteen sessions are not enough to generalize performance across bull, bear, high-volatility, or event-sparse periods.
- **The difference is portfolio-level, not event-level attribution.** The comparison reports the result of the complete news overlay. It does not attribute each dollar of excess return to a particular event or model component.
- **News coverage is selective.** The capped historical sample contained 300 selected events, of which 298 completed analysis. Provider coverage, article summaries, duplicate stories, and analysis completion can all affect which information reaches the workflow.
- **Backtest execution is an approximation.** Orders use next-session opening prices and modeled transaction costs. Live fills can differ because of spreads, market impact, liquidity, market hours, and order handling.
- **Model signals can be wrong.** Relevance, sentiment, impact, and event category are estimates. A high-confidence-looking score does not guarantee the market will react in the predicted direction.
- **No statistical significance claim is made.** This replay does not include a multi-period walk-forward evaluation, confidence intervals, or a broad parameter-sensitivity study.
- **Historical cap differs from live operation.** The 10-news-events-per-day cap applies only to the historical one-month update/replay. Live event processing is uncapped, subject to system availability and event deduplication.

## Conclusion

For Sep 4 through Oct 2, 2026, **news + normal rebalancing outperformed normal rebalancing alone**: it produced $14,058.07 in replay P&L versus $11,809.25, finishing $2,248.82 higher from the same checkpoint. The replay also shows the overlay was selective, generating 39 ticker-level news order rows across 14 execution dates from 29 event IDs.

The practical conclusion is to keep news as a measured overlay to the base S&P 100 strategy: it added value in this sample, reacted to event-specific information, and retained the normal schedule and volume rules. Continue recording both portfolios and compare them over additional rolling periods before treating this result as a durable performance expectation.
