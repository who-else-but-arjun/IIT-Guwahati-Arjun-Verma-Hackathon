from django.urls import path

from app.trading import views

urlpatterns = [
    path("health/", views.trading_health, name="trading-health"),
    path("events/activity/", views.event_activity, name="event-activity"),
    path("portfolios/", views.portfolios, name="portfolio-list-create"),
    path("portfolios/<str:portfolio_id>/", views.portfolio_detail, name="portfolio-detail-update"),
    path("portfolios/<str:portfolio_id>/orders/", views.portfolio_orders, name="portfolio-orders"),
    path("portfolios/<str:portfolio_id>/orders/pending/", views.portfolio_pending_orders, name="portfolio-pending-orders"),
    path("portfolios/<str:portfolio_id>/rebalance/", views.portfolio_rebalance, name="portfolio-rebalance"),
]
