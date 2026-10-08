"""HTTP API for portfolio creation, updates, orders, and rebalancing."""

import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.trading.dto import (
    CreatePortfolioDTO,
    OrderRequestDTO,
    PendingRebalanceDTO,
    PortfolioDTO,
    PortfolioPatchDTO,
    TradeOrderDTO,
)
from app.trading.repository import TradingRepository
from app.trading.services.portfolio_service import PortfolioService


def _payload(request: HttpRequest) -> dict[str, object]:
    return json.loads(request.body or b"{}")


@require_http_methods(["GET", "POST"])
def portfolios(request: HttpRequest) -> JsonResponse:
    repository = TradingRepository()
    try:
        if request.method == "GET":
            rows = repository.list_portfolios()
            return JsonResponse({"count": len(rows), "portfolios": [
                PortfolioDTO.from_model(row).model_dump(mode="json") for row in rows
            ]})
        body = CreatePortfolioDTO.model_validate(_payload(request))
        portfolio = repository.create_portfolio(
            name=body.name,
            initial_capital=body.initial_capital,
            news_enabled=body.news_enabled,
            config=body.config.to_model(),
        )
        return JsonResponse(PortfolioDTO.from_model(portfolio).model_dump(mode="json"), status=201)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        repository.close()


@require_http_methods(["GET", "PATCH"])
def portfolio_detail(request: HttpRequest, portfolio_id: str) -> JsonResponse:
    service = PortfolioService()
    try:
        if request.method == "PATCH":
            patch = PortfolioPatchDTO.model_validate(_payload(request))
            portfolio = service.patch_portfolio(portfolio_id, patch)
            if portfolio is None:
                return JsonResponse({"detail": "Portfolio not found."}, status=404)
            return JsonResponse(PortfolioDTO.from_model(portfolio).model_dump(mode="json"))
        portfolio, orders = service.get_details(portfolio_id)
        if portfolio is None:
            return JsonResponse({"detail": "Portfolio not found."}, status=404)
        return JsonResponse({
            **PortfolioDTO.from_model(portfolio).model_dump(mode="json"),
            "recent_orders": [TradeOrderDTO.from_model(order).model_dump(mode="json") for order in orders],
        })
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        service.repository.close()


@require_http_methods(["GET", "POST"])
def portfolio_orders(request: HttpRequest, portfolio_id: str) -> JsonResponse:
    service = PortfolioService()
    try:
        portfolio = service.repository.get_portfolio(portfolio_id)
        if portfolio is None:
            return JsonResponse({"detail": "Portfolio not found."}, status=404)
        if request.method == "GET":
            limit = int(request.GET.get("limit", "100"))
            offset = int(request.GET.get("offset", "0"))
            if not 1 <= limit <= 500 or not 0 <= offset <= 1_000_000:
                return JsonResponse({"detail": "limit must be between 1 and 500 and offset between 0 and 1000000."}, status=400)
            ticker_id = request.GET.get("ticker_id", "").strip().upper() or None
            orders = service.repository.list_orders(portfolio_id, limit=limit, offset=offset, ticker_id=ticker_id)
            total_count = service.repository.count_orders(portfolio_id, ticker_id=ticker_id)
            return JsonResponse({"count": len(orders), "total_count": total_count,
                                 "offset": offset, "limit": limit,
                                 "has_more": offset + len(orders) < total_count, "orders": [
                TradeOrderDTO.from_model(order).model_dump(mode="json") for order in orders
            ]})
        order_request = OrderRequestDTO.model_validate(_payload(request))
        updated, order = service.place_order(portfolio_id, order_request)
        return JsonResponse({
            "portfolio": PortfolioDTO.from_model(updated).model_dump(mode="json"),
            "order": TradeOrderDTO.from_model(order).model_dump(mode="json"),
        }, status=201)
    except LookupError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        service.repository.close()


@require_GET
def portfolio_pending_orders(_request: HttpRequest, portfolio_id: str) -> JsonResponse:
    repository = TradingRepository()
    try:
        if repository.get_portfolio(portfolio_id) is None:
            return JsonResponse({"detail": "Portfolio not found."}, status=404)
        service = PortfolioService(repository)
        service.reconcile_pending_news_rebalances(portfolio_id=portfolio_id)
        rows = repository.get_pending_rebalances(portfolio_id=portfolio_id)
        history = repository.get_rebalance_history(portfolio_id, limit=5000)
        return JsonResponse({"count": len(rows), "pending_rebalances": [
            PendingRebalanceDTO.from_model(row).model_dump(mode="json") for row in rows
        ], "rebalance_history": [
            PendingRebalanceDTO.from_model(row).model_dump(mode="json") for row in history
        ]})
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        repository.close()


@require_GET
def event_activity(request: HttpRequest) -> JsonResponse:
    """Return the complete order/rebalance trail for the visible news events."""
    event_ids = [item.strip() for item in request.GET.getlist("event_id") if item.strip()]
    if not event_ids:
        return JsonResponse({"orders": [], "rebalances": []})
    if len(event_ids) > 100:
        return JsonResponse({"detail": "At most 100 event IDs may be requested."}, status=400)
    repository = TradingRepository()
    try:
        orders, plans = repository.list_event_activity(event_ids)
        return JsonResponse({
            "orders": [TradeOrderDTO.from_model(order).model_dump(mode="json") for order in orders],
            "rebalances": [PendingRebalanceDTO.from_model(plan).model_dump(mode="json") for plan in plans],
        })
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        repository.close()


@require_http_methods(["POST"])
def portfolio_rebalance(request: HttpRequest, portfolio_id: str) -> JsonResponse:
    service = PortfolioService()
    try:
        body = _payload(request)
        force = bool(body.get("force", True))
        portfolio, trigger = service.rebalance(portfolio_id, force=force)
        return JsonResponse({
            "trigger": trigger,
            "rebalanced": trigger is not None,
            "portfolio": PortfolioDTO.from_model(portfolio).model_dump(mode="json"),
        })
    except LookupError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except PyMongoError:
        return JsonResponse({"detail": "MongoDB is unavailable."}, status=503)
    finally:
        service.repository.close()


@require_GET
def trading_health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "paper-trading"})
