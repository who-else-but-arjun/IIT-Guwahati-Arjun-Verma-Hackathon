"""Clean stored news headline/body/summary strings without changing other fields."""

from __future__ import annotations

import argparse
import os
from collections import Counter

from pymongo import MongoClient

from utils.text_utils import clean_news_text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report affected documents without writing changes.")
    args = parser.parse_args()

    client = MongoClient(
        os.getenv("MONGO_URI", "mongodb://mongo:27017"),
        serverSelectionTimeoutMS=10_000,
    )
    collection = client[os.getenv("MONGO_DATABASE", "financial_nlp")]["news_events"]
    totals: Counter[str] = Counter()
    modified = 0

    projection = {"headline": 1, "text": 1, "metadata.summary": 1, "metadata.provider": 1}
    for document in collection.find({}, projection).batch_size(500):
        provider = str(document.get("metadata", {}).get("provider") or "unknown")
        updates: dict[str, str] = {}
        for field in ("headline", "text"):
            value = document.get(field)
            cleaned = clean_news_text(value)
            if isinstance(value, str) and cleaned != value:
                updates[field] = cleaned
                totals[f"{provider}.{field}"] += 1

        metadata = document.get("metadata") or {}
        summary = metadata.get("summary")
        cleaned_summary = clean_news_text(summary)
        if isinstance(summary, str) and cleaned_summary != summary:
            updates["metadata.summary"] = cleaned_summary
            totals[f"{provider}.summary"] += 1

        if updates:
            modified += 1
            if not args.dry_run:
                collection.update_one({"_id": document["_id"]}, {"$set": updates})

    action = "would update" if args.dry_run else "updated"
    print(f"News text cleanup {action} {modified} documents.")
    for field, count in sorted(totals.items()):
        print(f"  {field}: {count}")
    client.close()


if __name__ == "__main__":
    main()
