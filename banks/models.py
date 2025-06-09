from django.core.validators import URLValidator
from django.db import models

from common.models import Audit


class Bank(Audit):
    """Model representing a bank that issues credit cards."""

    name = models.CharField(max_length=255, unique=True)
    logo = models.URLField(max_length=512, blank=True, validators=[URLValidator()])
    website = models.URLField(max_length=512, blank=True, validators=[URLValidator()])
    card_info_urls = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        db_table = "banks_bank"

    def __str__(self):
        return self.name

    @property
    def credit_card_count(self):
        """Return the number of active credit cards for this bank."""
        return self.credit_cards.filter(is_active=True).count()
