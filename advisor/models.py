"""Advisor session/message storage (plan §7.2).

PRIVACY INVARIANT — read before adding any field: eligibility inputs
(monthly income, employment type, TIN, CIB declaration) are NEVER stored.
They exist only in memory for the duration of one tool call, exactly as
in the stateless eligibility checker. ``AdvisorMessage.tool_trace``
stores tool *names* and a SHA-256 hash of the arguments — enough to audit
what ran, never enough to reconstruct a user's finances. A test pins the
model field list so a future field cannot quietly break this rule.
"""

import uuid

from django.conf import settings
from django.db import models

from common.models import Audit


class AdvisorSession(Audit):
    """One advisor conversation. Anonymous sessions are allowed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advisor_sessions",
    )
    # Cookie-scoped identifier for anonymous visitors (not a credential).
    anon_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    last_active = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_active"]
        db_table = "advisor_session"


class AdvisorMessage(Audit):
    """One exchange: the user's text and the advisor's validated answer."""

    session = models.ForeignKey(
        AdvisorSession, on_delete=models.CASCADE, related_name="messages"
    )
    user_text = models.TextField()
    answer_markdown = models.TextField(blank=True, default="")
    citations = models.JSONField(default=list, blank=True)
    # [{"tool": name, "args_hash": sha256hex, "latency_ms": int}] — names
    # and hashes only, by design (see module docstring).
    tool_trace = models.JSONField(default=list, blank=True)
    is_fallback = models.BooleanField(default=False)

    class Meta:
        ordering = ["created"]
        db_table = "advisor_message"
