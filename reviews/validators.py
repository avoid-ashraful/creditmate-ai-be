import re

from django.core.exceptions import ValidationError
from django.utils.html import strip_tags

# A small abuse heuristic, deliberately conservative to avoid rejecting ordinary criticism.
_PROFANITY = re.compile(r"\b(?:fuck|shit|bitch|asshole)\b", re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def clean_review_text(value):
    text = strip_tags(value or "").strip()
    if _PROFANITY.search(text):
        raise ValidationError("Please remove abusive language from your review.")
    if len(_URL.findall(text)) > 1:
        raise ValidationError("Reviews may not contain multiple links.")
    return text
