"""NLP-side publisher for the trading service's TCP event contract."""

import json
import logging
import os
import socket
import time

logger = logging.getLogger(__name__)


def publish_score_update(event_id: str, ticker_ids: list[str]) -> bool:
    host = os.getenv("NLP_TRADING_SOCKET_HOST", "localhost")
    port = int(os.getenv("NLP_TRADING_SOCKET_PORT", "8765"))
    message = json.dumps({"type": "news_scores_updated", "event_id": event_id, "ticker_ids": ticker_ids})
    for attempt in range(3):
        try:
            with socket.create_connection((host, port), timeout=3.0) as connection:
                connection.settimeout(3.0)
                connection.sendall(message.encode("utf-8") + b"\n")
                acknowledgement = connection.makefile("rb").readline()
            accepted = json.loads(acknowledgement).get("status") == "accepted"
            if not accepted:
                logger.warning("Trading service did not accept news event %s.", event_id)
            return accepted
        except (OSError, ValueError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
    logger.warning("Could not notify the trading service about news event %s after retries.", event_id)
    return False
