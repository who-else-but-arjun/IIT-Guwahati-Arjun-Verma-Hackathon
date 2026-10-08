import os
import threading
import time
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from constants import SP100_COMPANIES
from repository.mongo_repository import MongoRepository
from utils.datetime_utils import parse_optional_float, parse_optional_time


_quote_cache_lock = threading.Lock()
_quote_cache: dict[tuple[str, ...], tuple[float, dict[str, object]]] = {}
_quote_request_locks: dict[tuple[str, ...], threading.Lock] = {}
_QUOTE_CACHE_TTL_SECONDS = 180


def health(request):
    """Return service status and whether MongoDB can be reached."""
    response = {"status": "ok", "service": "financial-nlp-api"}
    client = MongoClient(
        os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=3000,
        socketTimeoutMS=5000,
    )
    try:
        client.admin.command("ping")
        response["mongodb"] = "connected"
    except Exception as exc:
        response["status"] = "degraded"
        response["mongodb"] = "unavailable"
        response["mongodb_error"] = str(exc)
    finally:
        client.close()
    return JsonResponse(response)


@require_GET
def get_event(request: HttpRequest, event_id: str) -> JsonResponse:
    """Return a single news event DTO by Mongo ObjectId."""
    repository: MongoRepository | None = None
    try:
        repository = MongoRepository()
        event = repository.get_event(event_id)
        if event is None:
            return JsonResponse({"detail": "Event not found."}, status=404)
        return JsonResponse(event.model_dump(mode="json"))
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        if repository is not None:
            repository.close()


@require_GET
def get_events(request: HttpRequest) -> JsonResponse:
    """Return news events with optional category, score, and recency filters."""
    repository: MongoRepository | None = None
    try:
        score_min = parse_optional_float(request.GET.get("score_min"), "score_min")
        score_max = parse_optional_float(request.GET.get("score_max"), "score_max")
        since = parse_optional_time(request.GET.get("since"))
        until = parse_optional_time(request.GET.get("until"))
        limit = int(request.GET.get("limit", "100"))
        offset = int(request.GET.get("offset", "0"))
        repository = MongoRepository()
        events = repository.get_events(
            category=request.GET.get("category"),
            score_min=score_min,
            score_max=score_max,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        total_count = repository.count_events(
            category=request.GET.get("category"),
            score_min=score_min,
            score_max=score_max,
            since=since,
            until=until,
        )
        return JsonResponse({"count": len(events), "total_count": total_count,
                             "analysis_summary": repository.event_summary(),
                             "high_impact_events": [
                                 event.model_dump(mode="json")
                                 for event in repository.get_high_impact_events()
                             ],
                             "offset": offset, "limit": limit,
                             "has_more": offset + len(events) < total_count, "events": [
            event.model_dump(mode="json") for event in events
        ]})
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        if repository is not None:
            repository.close()


@require_GET
def get_tickers(_request: HttpRequest) -> JsonResponse:
    """List persisted ticker graph data without making market-price requests."""
    repository: MongoRepository | None = None
    try:
        repository = MongoRepository()
        tickers = repository.list_ticker_graph()
        return JsonResponse({"count": len(tickers), "tickers": tickers}, safe=True)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        if repository is not None:
            repository.close()


@require_GET
def get_ticker_universe(_request: HttpRequest) -> JsonResponse:
    """Return every stock in the tracked S&P 100 universe for market breadth."""
    return JsonResponse({"count": len(SP100_COMPANIES), "tickers": [
        {"ticker_id": symbol, "company_name": company}
        for symbol, company in SP100_COMPANIES.items()
    ]})


@require_GET
def get_ticker_quotes(request: HttpRequest) -> JsonResponse:
    """Return current quotes plus a compact three-month history for sparklines."""
    symbols = list(dict.fromkeys(
        value.strip().upper() for value in request.GET.get("symbols", "").split(",") if value.strip()
    ))
    if not symbols or len(symbols) > 60:
        return JsonResponse({"detail": "Provide between 1 and 60 ticker symbols."}, status=400)
    cache_key = tuple(symbols)
    with _quote_cache_lock:
        request_lock = _quote_request_locks.setdefault(cache_key, threading.Lock())
    request_lock.acquire()
    cached = _quote_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _QUOTE_CACHE_TTL_SECONDS:
        request_lock.release()
        return JsonResponse(cached[1])
    repository: MongoRepository | None = None
    try:
        repository = MongoRepository()
        known = {symbol: repository.get_ticker(symbol) for symbol in symbols}
        known = {symbol: ticker for symbol, ticker in known.items() if ticker is not None}
        supported = [symbol for symbol in symbols if symbol in SP100_COMPANIES]
        # Import pandas/yfinance only for quote requests. Keeping these heavy
        # market-data packages out of Django's URL import lets health and
        # database-backed endpoints come up immediately after a restart.
        if supported:
            from services.connectors.yfinance_stocks import YFinanceStocksConnector
            bars = YFinanceStocksConnector().get_history(supported, period="3mo", interval="1d")
        else:
            bars = []
        history: dict[str, list[dict]] = {symbol: [] for symbol in supported}
        for bar in bars:
            history.setdefault(bar.ticker_id, []).append(bar.model_dump(mode="json"))
        payload = {"quotes": [{
            "ticker": symbol,
            "company": (known[symbol].ticker_name.company_name if known.get(symbol) else None) or SP100_COMPANIES.get(symbol, symbol),
            "ticker_data": history.get(symbol, []),
        } for symbol in symbols if symbol in supported]}
        with _quote_cache_lock:
            _quote_cache[cache_key] = (time.monotonic(), payload)
        return JsonResponse(payload)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        if repository is not None:
            repository.close()
        request_lock.release()


@require_GET
def get_ticker_events(request: HttpRequest, ticker_name: str) -> JsonResponse:
    """Return ticker news DTOs, newest first, with optional filters."""
    repository: MongoRepository | None = None
    try:
        score_min = parse_optional_float(request.GET.get("score_min"), "score_min")
        score_max = parse_optional_float(request.GET.get("score_max"), "score_max")
        since = parse_optional_time(request.GET.get("since"))
        until = parse_optional_time(request.GET.get("until"))
        limit = int(request.GET.get("limit", "100"))
        offset = int(request.GET.get("offset", "0"))
        repository = MongoRepository()
        events = repository.get_ticker_events(
            ticker_name,
            category=request.GET.get("category"),
            score_min=score_min,
            score_max=score_max,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        total_count = repository.count_ticker_events(ticker_name)
        return JsonResponse({"ticker": ticker_name, "count": len(events), "total_count": total_count, "offset": offset,
                             "limit": limit, "has_more": offset + len(events) < total_count,
                             "events": [event.model_dump(mode="json") for event in events]})
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        if repository is not None:
            repository.close()


@require_GET
def get_ticker(request: HttpRequest, ticker_name: str) -> JsonResponse:
    """Return ticker metadata plus on-demand OHLCV data from yfinance."""
    repository: MongoRepository | None = None
    try:
        repository = MongoRepository()
        ticker = repository.get_ticker(ticker_name)
        if ticker is None:
            return JsonResponse({"detail": "Ticker not found."}, status=404)
        ticker_dto = ticker.to_dto()
        period = request.GET.get("period", "5d")
        interval = request.GET.get("interval", "1d")
        from services.connectors.yfinance_stocks import YFinanceStocksConnector
        live_bars = YFinanceStocksConnector().get_history(
            [ticker.ticker_name.ticker_id], period=period, interval=interval
        )
        ticker_dto = ticker_dto.model_copy(update={"ticker_data": live_bars})
        effective = ticker_dto.effective_scores()
        effective_relevance = {item.event_id: item.relevance_score for item in effective.relevant_events}
        ticker_response = ticker_dto.model_copy(update={
            "ticker_score": ticker_dto.ticker_score.model_copy(update={
                "sentiment": ticker_dto.ticker_score.sentiment.model_copy(update={
                    "score": effective.sentiment_score,
                    "impact_score": effective.impact_score,
                }),
            }),
            "relevant_events": [item.model_copy(update={
                "relevance_score": effective_relevance.get(item.event_id, item.relevance_score)
            }) for item in ticker_dto.relevant_events],
        })
        return JsonResponse(ticker_response.model_dump(mode="json"))
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        if repository is not None:
            repository.close()
