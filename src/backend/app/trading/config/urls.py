from django.urls import include, path

urlpatterns = [path("api/trading/", include("app.trading.urls"))]
