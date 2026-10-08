# Financial NLP benchmark datasets

This document describes optional local benchmark datasets used by the training notebooks. The large CSV files under `data/benchmarks/` are intentionally excluded from the deployment repository; they are not required to run the website or restore its MongoDB seed. Obtain the datasets from their cited sources and check their reuse terms before downloading or redistributing them.

This folder contains four curated benchmark datasets in CSV format for financial sentiment classification, sentiment regression, and ticker/entity linking. The four datasets are:

1. Financial PhraseBank (`financial_phrasebank_dataset/`)
2. FiQA 2018 sentiment regression (`fiqa_2018_sentiment_regression.csv`)
3. Twitter Financial News Sentiment (`twitter_financial_news_sentiment.csv`)
4. Financial News ticker/entity linking (`financial_news_ticker_linking.csv`)

## Dataset overview

| Dataset | Files | Rows | Task | Labels/target |
|---|---|---:|---|---|
| Financial PhraseBank | Four agreement-subset CSVs in `financial_phrasebank_dataset/` | 4,846 / 4,217 / 3,453 / 2,264 | 3-class sentiment classification | negative, neutral, positive |
| FiQA 2018 | `fiqa_2018_sentiment_regression.csv` | 1,213 | Sentiment regression | `sentiment_score`, observed range −0.938 to +0.975 |
| Twitter Financial News Sentiment | `twitter_financial_news_sentiment.csv` | 11,931 | 3-class sentiment classification | bearish, bullish, neutral |
| Financial News ticker/entity linking | `financial_news_ticker_linking.csv` | 70,974 | Multi-label ticker/entity linking | One or more ticker symbols |

PhraseBank's four CSVs are nested, overlapping agreement subsets of one dataset. Select one agreement threshold for an evaluation; do not combine the files because that duplicates examples. PhraseBank has no official train/test split, so create and document a fixed split. The source card reports 4,840 sentences; the local 50%-agreement CSV contains 4,846 rows.

## Column definitions

### Financial PhraseBank

Each CSV in `financial_phrasebank_dataset/` uses the same columns:

| Header | Meaning |
|---|---|
| `text` | Financial news sentence to classify. |
| `label` | Human-annotated investor sentiment: `negative`, `neutral`, or `positive`. |
| `label_id` | Numeric class code: `0 = negative`, `1 = neutral`, `2 = positive`. |

### FiQA 2018 sentiment regression

| Header | Meaning |
|---|---|
| `split` | Source partition: `train`, `validation`, or `test`. |
| `sentence` | Financial post or headline being scored. |
| `snippets` | JSON array of annotated text snippets relevant to the target/aspect. |
| `target` | Entity or aspect judged by annotators, often a company name or ticker. |
| `sentiment_score` | Continuous regression target; observed values range from −0.938 to +0.975. |
| `aspects` | JSON array of financial aspect categories. |
| `format` | Source text type, such as `post` or `headline`. |

Use `sentiment_score` as the regression target. A derived class `label` from the source mirror is omitted from this export to keep the continuous target unambiguous. Split counts are 961 train, 102 validation, and 150 test.

### Twitter Financial News Sentiment

| Header | Meaning |
|---|---|
| `split` | Source partition: `train` or `validation`. |
| `text` | Finance-related tweet or post. |
| `label` | Sentiment class: `bearish`, `bullish`, or `neutral`. |
| `label_id` | Numeric code: `0 = bearish`, `1 = bullish`, `2 = neutral`. |

These labels represent market sentiment, not general emotional tone. This dataset is for classification, not regression.

### Financial News ticker/entity linking

| Header | Meaning |
|---|---|
| `text` | Full article body used as input; title and description provide fallback text when the body is missing. |
| `title` | Article headline. |
| `description` | Article summary or description. |
| `date_publish` | Publication timestamp supplied by the source. |
| `url` | Original article URL. |
| `mentioned_companies` | JSON array of ticker symbols associated with the article; this is the multi-label target. |
| `year` | Year of the source file. |

This snapshot covers 2017–2023 with 70,974 records and 49 distinct ticker labels. The ticker arrays match the source's normalized `named_entities` labels on all 70,974 rows. They are source annotations, not manually adjudicated gold labels. The upstream README reports 51,272 articles, while the local snapshot contains 70,974 unique URLs; treat this as a source-version/statistics discrepancy and report the local count. For evaluation, consider time-based splits and group duplicate URLs/headlines so duplicates do not cross splits. Report micro/macro precision, recall, F1, and exact-set accuracy.

## Quality review and exclusions

- The retained CSVs were checked with a strict CSV parser for consistent field counts and proper quoting. List-valued fields are stored as JSON arrays inside CSV cells.
- Massive Stock News was excluded after review because its `stock` field did not reliably match the companies named in headlines.
- Cheruvo Financial News Sentiment was excluded because it contains multiple languages and its scores are generated by `llm2`, rather than independent human gold labels.
- ModernFinBERT training data was removed from this benchmark set.
- The proposed `us_equities_news_dataset.csv` was not included because the Kaggle page was unavailable and its download endpoint returned HTTP 403; a public GitHub mirror only links back to Kaggle.

## Sources and reuse notes

- [Financial PhraseBank dataset card](https://huggingface.co/datasets/takala/financial_phrasebank) declares CC BY-NC-SA 3.0; commercial use requires permission from the dataset authors.
- [FiQA 2018 Task 1](https://huggingface.co/datasets/pauri32/fiqa-2018) provides the continuous sentiment scores. The repository card does not state a clear reuse license.
- [Twitter Financial News Sentiment](https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment) declares MIT.
- [Financial News Dataset by Felix Drinkall](https://github.com/FelixDrinkall/financial-news-dataset) provides the ticker-linked articles. Its repository does not declare a recognized SPDX license; verify reuse terms before redistribution.
