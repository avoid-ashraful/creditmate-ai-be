from django.apps import AppConfig
class StreamingConfig(AppConfig):
    default_auto_field="django.db.models.BigAutoField"
    name="streaming"; verbose_name="Event streaming"
    def ready(self):
        from django.conf import settings
        if getattr(settings,"EVENT_STREAMING_ENABLED",False):
            from streaming import signals  # noqa: F401
