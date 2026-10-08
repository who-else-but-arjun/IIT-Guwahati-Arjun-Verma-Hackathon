# Final Model Evaluation and Decisions

This document summarizes the evaluated models in [`notebooks/final`](.) and records the selected direction for the CRISIL pipeline. Scores below are copied from the saved notebook outputs. Evaluation sizes and methods differ between notebooks; read each result in its own evaluation context rather than as a single controlled head-to-head benchmark.

## Decision summary

- **Sentiment classification:** use **FLANG-RoBERTa** (the RoBERTa FinBERT-family candidate) from the three encoder variants. It has the highest held-out macro-F1 on both classification datasets in the final sentiment-classification notebook.
- **Sentiment regression:** the three-model benchmark's strongest held-out result is **FLANG-RoBERTa**, but the selected model for the pipeline is **Jev** for sentiment regression, as agreed. Jev's saved zero-shot FiQA score is included below; it was measured on a separate, much smaller sample, so it is not directly comparable to the fine-tuned benchmark.
- **Ticker association:** do not make a single direct ticker-classification decision. The observed F1 scores are not strong enough for confident direct assignments. Instead, use a two-stage candidate-ranking approach: (1) identify a candidate ticker set with the FLANG/FinBERT-family stage, then (2) ask **Jev or Laya** to assess each candidate's relevance to the article and return a relevance score. Rank/filter candidates by score and calibrate thresholds on held-out data.

## Three encoder variants: sentiment classification

Held-out results from `sentiment-classification.ipynb`:

| Dataset | Model | Test rows | Accuracy | Macro-F1 | Weighted-F1 | Macro precision | Macro recall |
|---|---|---:|---:|---:|---:|---:|---:|
| Financial PhraseBank | FLANG-RoBERTa | 485 | **0.8515** | **0.8427** | **0.8519** | 0.8257 | 0.8645 |
| Financial PhraseBank | FinBERT | 485 | 0.8289 | 0.8076 | 0.8274 | 0.8065 | 0.8134 |
| Financial PhraseBank | FLANG-DistilBERT | 485 | 0.8247 | 0.8053 | 0.8243 | 0.8004 | 0.8120 |
| Twitter Financial News Sentiment | FLANG-RoBERTa | 2,388 | **0.8957** | **0.8675** | **0.8971** | 0.8523 | 0.8850 |
| Twitter Financial News Sentiment | FLANG-DistilBERT | 2,388 | 0.8786 | 0.8448 | 0.8791 | 0.8385 | 0.8521 |
| Twitter Financial News Sentiment | FinBERT | 2,388 | 0.8564 | 0.8142 | 0.8584 | 0.8003 | 0.8305 |

**Choice:** FLANG-RoBERTa ranks first on both datasets by macro-F1, the primary selection metric here. It leads the next-best variant by 0.0351 macro-F1 on PhraseBank and 0.0226 on Twitter Financial News.

## Three encoder variants: sentiment regression

Held-out FiQA regression results from `sentiment-regression.ipynb` (150 test rows):

| Model | MAE ↓ | RMSE ↓ | R² ↑ |
|---|---:|---:|---:|
| FLANG-RoBERTa | **0.1848** | **0.2628** | **0.4017** |
| FLANG-DistilBERT | 0.1984 | 0.2643 | 0.3948 |
| FinBERT | 0.2064 | 0.2828 | 0.3071 |

**Benchmark result:** FLANG-RoBERTa has the lowest MAE and RMSE and highest R². **Pipeline decision:** use Jev for sentiment regression, consistent with the project decision. In Jev's separate zero-shot run, FiQA (60 sampled rows) scored MAE 0.2244, RMSE 0.2634, and R² 0.4854. Because this used a different sample and evaluation approach, do not interpret it as a direct win over the fine-tuned models.

## Laya results

`laya-ai.ipynb` reports Laya base and fine-tuned performance. Classification uses 300 rows per dataset; ticker linking uses 100 rows; FiQA regression uses 150 rows.

| Task / dataset | Model | N | Accuracy | Macro-F1 | Weighted-F1 | MAE | RMSE | R² |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| PhraseBank sentiment | Laya base | 300 | 0.6900 | 0.6790 | 0.7147 | — | — | — |
| PhraseBank sentiment | Laya fine-tuned | 300 | **0.8700** | **0.8574** | **0.8685** | — | — | — |
| Twitter sentiment | Laya base | 300 | 0.5667 | 0.5766 | 0.5772 | — | — | — |
| Twitter sentiment | Laya fine-tuned | 300 | **0.8733** | **0.8396** | **0.8713** | — | — | — |
| FiQA regression | Laya base | 150 | — | — | — | 0.5043 | 0.5975 | -2.0921 |
| FiQA regression | Laya fine-tuned | 150 | — | — | — | **0.1985** | **0.2719** | **0.3596** |

Fine-tuning substantially improves Laya over its base model on both classification datasets and on regression. For Laya's ticker linking, base macro-F1 is 0.0623 (micro-F1 0.0686); fine-tuned macro-F1 is 0.2001 (micro-F1 0.5581). The relatively low macro-F1 supports using ticker relevance ranking rather than treating direct ticker assignments as dependable.

## Jev results

`jev-ai.ipynb` evaluates Jev without task-specific fine-tuning on small sampled sets: 40 examples per classification dataset, 60 for regression, and 50 for ticker linking.

| Task / dataset | N | Accuracy | Macro-F1 | Weighted-F1 | MAE | RMSE | R² |
|---|---:|---:|---:|---:|---:|---:|---:|
| PhraseBank sentiment | 40 | 0.9250 | 0.9186 | 0.9266 | — | — | — |
| Twitter Financial News sentiment | 40 | 0.6250 | 0.6169 | 0.6299 | — | — | — |
| FiQA regression | 60 | — | — | — | 0.2244 | 0.2634 | 0.4854 |

The ticker-linking run reports 50 test articles, threshold 0.05, micro precision 0.3662, micro recall 0.8125, micro-F1 0.5049, macro precision 0.2184, macro recall 0.3255, macro-F1 0.2488, exact match 0.2400, hamming loss 0.0416, and macro average precision 0.6870. The notebook also prints a validation-selected macro-F1 of 0.1493; the test macro-F1 above is the test-set row. These small-sample results are directional and should not be taken as broad generalization estimates.

## Ticker model comparison

The saved ticker notebooks report different evaluation sizes and pipelines, so these are contextual results, not a matched comparison.

| Notebook / system | Test rows | Micro-F1 | Macro-F1 | Precision / recall detail |
|---|---:|---:|---:|---|
| Three-variant direct ticker model: FLANG-DistilBERT | 3,000 | **0.4932** | **0.5084** | Micro precision 0.6671, recall 0.3913 |
| Three-variant direct ticker model: FinBERT | 3,000 | 0.4867 | 0.4962 | Micro precision 0.6393, recall 0.3929 |
| Three-variant direct ticker model: FLANG-RoBERTa | 3,000 | 0.4598 | 0.4377 | Micro precision 0.6174, recall 0.3663 |
| Laya fine-tuned multilabel ticker model | 100 | 0.5581 | 0.2001 | Micro precision 0.5000, recall 0.6316 |
| Jev zero-shot ticker-linking model | 50 | 0.5049 | 0.2488 | Micro precision 0.3662, recall 0.8125 |
| Hybrid: FLANG-RoBERTa top-10 candidates + Jev relevance scoring | 50 | **0.5974** | **0.2576** | Micro precision 0.6216, recall 0.5750 |

While some micro-F1 scores are near 0.5, macro-F1 is lower for the small Laya/Jev evaluations and performance varies across tickers. The system should preserve uncertainty and return scored candidates, rather than presenting one ticker label as certain. The relevance score should be defined consistently (for example, a calibrated probability or normalized model score) and validated before production use.

## Why Laya and Jev

- **Laya over Jev for the fine-tuned sentiment classification path:** the final Laya evaluation has stronger fine-tuned Twitter sentiment performance than Jev's small zero-shot sample (macro-F1 0.8396 vs 0.6169). The runs use different sample sizes and methods, so this supports Laya as a useful task-adapted candidate, not a clean head-to-head claim. Laya also supports a directly fine-tuned model workflow.
- **Jev over Laya where flexible scoring is needed:** Jev's notebook demonstrates a single prompted interface across classification, numeric sentiment regression, and ticker relevance/linking. This is a practical fit for the proposed second-stage candidate relevance scoring, where each article–ticker pair needs contextual judgment and a score. Jev's regression result is also retained as the selected pipeline choice by project decision.
- **Use both where appropriate:** FLANG/FinBERT-family model proposes candidate tickers; Jev or Laya evaluates candidate relevance. Keep model scores and evidence so downstream users can inspect and rank the proposed associations.

## Evaluation notes

- Classification selection is based primarily on macro-F1 so each sentiment class contributes to the comparison; accuracy and weighted-F1 are also shown.
- Regression uses MAE/RMSE (lower is better) and R² (higher is better).
- Ticker linking is multilabel and long-tailed. Macro-F1, micro-F1, recall, exact match, and average precision capture different aspects; no single number should be read alone.
- The notebooks use different test-set sizes and, for Jev and Laya, different inference/fine-tuning methods. Treat comparisons across notebooks as directional. Re-evaluate candidate models on a shared held-out set before locking performance claims.

