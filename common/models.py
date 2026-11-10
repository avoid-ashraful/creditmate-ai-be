from django.db import models


class Audit(models.Model):
    """Abstract base model for audit trails with timestamp tracking."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class LLMPrice(Audit):
    """Dated per-model LLM pricing — data, not code (cf. DepositTaxRule).

    Prices change without a deploy; the cost engine reads the latest row
    effective on the usage date. Amounts are USD per 1,000 tokens.
    """

    provider = models.CharField(max_length=50, db_index=True)
    model = models.CharField(max_length=150, db_index=True)
    effective_from = models.DateField()
    input_per_1k = models.DecimalField(max_digits=12, decimal_places=6)
    output_per_1k = models.DecimalField(max_digits=12, decimal_places=6)
    source_note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["provider", "model", "-effective_from"]
        unique_together = ["provider", "model", "effective_from"]

    def __str__(self):
        return f"{self.provider}/{self.model} from {self.effective_from}"

    @classmethod
    def current_for(cls, provider, model, on_date=None):
        """Latest price effective on ``on_date`` (default today), or None."""
        from django.utils import timezone

        on_date = on_date or timezone.localdate()
        return (
            cls.objects.filter(
                provider=provider, model=model, effective_from__lte=on_date
            )
            .order_by("-effective_from")
            .first()
        )


class LLMUsage(Audit):
    """One row per LLM provider call (Stream F: cost & latency ledger).

    Token fields are nullable: when a provider does not return usage,
    tokens stay null and cost stays null — never estimated silently.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        ERROR = "error", "Error"

    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    provider = models.CharField(max_length=50, db_index=True)
    model = models.CharField(max_length=150, blank=True, default="")
    purpose = models.CharField(max_length=50, db_index=True, default="extraction")
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    cost_microusd = models.BigIntegerField(null=True, blank=True)
    run_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    routing_reason = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUCCESS
    )

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.provider}/{self.model} {self.purpose} {self.occurred_at:%Y-%m-%d %H:%M}"
