"""Django startup hooks for loading public Kaggle Models."""

import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ServicesConfig(AppConfig):
    name = "services"
    verbose_name = "Financial NLP services"

    def ready(self) -> None:
        # Keep API startup and health checks independent of model downloads.
        # FinancialNewsModelSuite.ensure_loaded() initializes the models lazily
        # on the first request that actually performs news analysis.
        logger.info("NLP models will load on the first analysis request.")
