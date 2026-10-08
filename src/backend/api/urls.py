from django.urls import path

from api.views import get_event, get_events, get_ticker, get_ticker_events, get_tickers, get_ticker_quotes, get_ticker_universe, health

urlpatterns = [
    path("health/", health, name="health"),
    path("events/", get_events, name="events-list"),
    path("events/<str:event_id>/", get_event, name="event-detail"),
    path("tickers/", get_tickers, name="ticker-list"),
    path("tickers/universe/", get_ticker_universe, name="ticker-universe"),
    path("tickers/quotes/", get_ticker_quotes, name="ticker-quotes"),
    path("tickers/<str:ticker_name>/", get_ticker, name="ticker-detail"),
    path("tickers/<str:ticker_name>/events/", get_ticker_events, name="ticker-events"),
]
