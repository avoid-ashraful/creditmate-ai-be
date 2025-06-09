from django.db import models


class Audit(models.Model):
    """Abstract base model for audit trails with timestamp tracking."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
