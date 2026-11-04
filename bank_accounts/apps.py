from django.apps import AppConfig


class BankAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bank_accounts"
    verbose_name = "Bank accounts"

    def ready(self):
        import bank_accounts.signals  # noqa: F401
