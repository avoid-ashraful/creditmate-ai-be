"""Limits and tunables for saved comparisons and collections."""

MAX_CARDS_PER_COMPARISON = 4
MAX_COMPARISONS_PER_USER = 50
MAX_COLLECTIONS_PER_USER = 20
MAX_CARDS_PER_COLLECTION = 50
# Redesign Phase 3 (Section 4.7): the shortlist holds at most the compare
# cap per vertical — a fifth product of a vertical is refused, never
# silently swapped in.
MAX_SHORTLIST_PER_VERTICAL = 4
MAX_SAVED_SEARCHES_PER_USER = 50
MAX_SAVED_SCENARIOS_PER_USER = 50

SHARE_TOKEN_BYTES = 32
SLUG_BASE_MAX_LENGTH = 50
