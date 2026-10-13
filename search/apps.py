from django.apps import AppConfig


class SearchConfig(AppConfig):
    """App configuration for the search index service."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "search"
    verbose_name = "Search index"
    label = "search"

    def ready(self):
        """Connect model signals when the app registry is ready.

        Returns
        -------
        None
        """
        from django.conf import settings

        sync_mode = getattr(settings, "SEARCH_SYNC_MODE", "queue")
        if sync_mode and sync_mode != "off":
            from search import signals  # noqa: F401
