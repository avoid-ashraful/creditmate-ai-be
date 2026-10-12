from django.apps import AppConfig


class CreditCardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "credit_cards"

    def ready(self):
        """Connect cache invalidation signal handlers."""
        import credit_mate_ai.cache  # noqa: F401
