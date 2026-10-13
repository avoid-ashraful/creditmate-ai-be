"""Tests for lounge access classification and the filters built on it.

Covers the Python classifier, the model helpers, the SQL helpers that the
API filters and facets use, and parity between the two so that a value
classified one way in Python is never filtered another way in the database.
"""

import pytest

from credit_cards.api.advanced_filters import CreditCardAdvancedFilter, compute_facets
from credit_cards.api.filters import CreditCardFilter
from credit_cards.factories import CreditCardFactory
from credit_cards.lounge import (
    LIMITED,
    NONE,
    UNKNOWN,
    UNLIMITED,
    card_has_lounge_access,
    card_lounge_access_q,
    classify_lounge_access,
    direction_has_access,
    lounge_access_count,
    lounge_status_q,
)
from credit_cards.models import CreditCard

UNKNOWN_SAMPLES = [None, "", "   ", "-", "?", "Unknown", "Not specified", "not mentioned"]
NONE_SAMPLES = [
    "0",
    "0.0",
    "0 visits",
    "None",
    "none",
    "No",
    "N/A",
    "n/a.",
    "Not applicable",
    "Not available",
    "No lounge access",
    "Nil",
]
UNLIMITED_SAMPLES = ["Unlimited", "unlimited domestic visits", "No limit"]
LIMITED_SAMPLES = ["4 per year", "5 visits", "2 visits per quarter", "Priority Pass"]
ALL_SAMPLES = UNKNOWN_SAMPLES + NONE_SAMPLES + UNLIMITED_SAMPLES + LIMITED_SAMPLES


class TestClassifyLoungeAccess:
    """Classification of one free-text value into a status."""

    @pytest.mark.parametrize("value", UNKNOWN_SAMPLES)
    def test_unknown_values(self, value):
        """Empty and placeholder values are unknown, not none."""
        assert classify_lounge_access(value) == UNKNOWN

    @pytest.mark.parametrize("value", NONE_SAMPLES)
    def test_none_values(self, value):
        """Zero and not-applicable phrasing is an explicit none."""
        assert classify_lounge_access(value) == NONE

    @pytest.mark.parametrize("value", UNLIMITED_SAMPLES)
    def test_unlimited_values(self, value):
        """Unlimited phrasing is its own status, never a number and never none."""
        assert classify_lounge_access(value) == UNLIMITED

    @pytest.mark.parametrize("value", LIMITED_SAMPLES)
    def test_limited_values(self, value):
        """Any other value that grants access is limited."""
        assert classify_lounge_access(value) == LIMITED


class TestLoungeAccessCount:
    """Finite visit counts derived from the classified status."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("5 visits per year", 5),
            ("2 visits per quarter", 2),
            ("0", 0),
            ("N/A", 0),
            ("Priority Pass", None),
            ("Unlimited", None),
            ("", None),
            (None, None),
        ],
    )
    def test_count_by_status(self, value, expected):
        """Known none is 0; unknown and unlimited have no finite count."""
        assert lounge_access_count(value) == expected


class TestDirectionAndCardAccess:
    """Access flags for one direction and for the card as a whole."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("5 visits", True),
            ("Unlimited", True),
            ("0", False),
            ("N/A", False),
            ("", None),
        ],
    )
    def test_direction_flag(self, value, expected):
        """Limited and unlimited grant access; none denies; unknown is None."""
        assert direction_has_access(value) is expected

    @pytest.mark.parametrize(
        ("international", "domestic", "expected"),
        [
            ("5 visits", "", True),
            ("Unlimited", "0", True),
            ("0", "None", False),
            ("N/A", "0 visits", False),
            ("N/A", "", None),
            ("0", "unknown", None),
            ("", "", None),
        ],
    )
    def test_card_flag(self, international, domestic, expected):
        """Any access wins; both none is False; anything unstated is None."""
        assert card_has_lounge_access(international, domestic) is expected


class TestModelLoungeHelpers:
    """The CreditCard properties use the same classification."""

    @pytest.mark.parametrize(
        ("international", "domestic", "expected"),
        [("0", "N/A", False), ("", "", None), ("2 visits", "", True)],
    )
    def test_has_lounge_access(self, international, domestic, expected):
        """Model property reports True, False or None (unknown)."""
        card = CreditCard(
            name="Card",
            lounge_access_international=international,
            lounge_access_domestic=domestic,
        )
        assert card.has_lounge_access is expected

    def test_summary_lists_only_directions_with_access(self):
        """Summary omits none and unknown directions."""
        card = CreditCard(
            name="Card",
            lounge_access_international="N/A",
            lounge_access_domestic="2 visits",
        )
        assert card.lounge_access_summary == "Domestic: 2 visits"

    def test_summary_none_and_unknown_wording(self):
        """Known none and unknown produce different summaries."""
        none_card = CreditCard(
            name="None", lounge_access_international="0", lounge_access_domestic="N/A"
        )
        unknown_card = CreditCard(
            name="Unknown", lounge_access_international="", lounge_access_domestic=""
        )
        assert none_card.lounge_access_summary == "No lounge access"
        assert unknown_card.lounge_access_summary == "Lounge access not specified"


@pytest.mark.django_db
class TestLoungeSqlParity:
    """SQL helpers must agree with the Python classifier for every sample."""

    def test_status_q_matches_python_classifier(self):
        """Each status Q selects exactly the rows Python classifies that way."""
        for index, value in enumerate(ALL_SAMPLES):
            CreditCardFactory(
                name=f"Sample {index}",
                lounge_access_international="" if value is None else value,
                lounge_access_domestic="",
            )

        for status in (UNKNOWN, NONE, UNLIMITED, LIMITED):
            expected = {
                card.name
                for card in CreditCard.objects.all()
                if classify_lounge_access(card.lounge_access_international) == status
            }
            actual = set(
                CreditCard.objects.filter(
                    lounge_status_q("lounge_access_international", status)
                ).values_list("name", flat=True)
            )
            assert actual == expected, status

    def test_card_q_matches_model_property(self):
        """Card-level Q selects cards whose has_lounge_access is True or False."""
        pairs = [
            ("5 visits", ""),
            ("Unlimited", "0"),
            ("0", "None"),
            ("N/A", ""),
            ("", ""),
        ]
        for index, (international, domestic) in enumerate(pairs):
            CreditCardFactory(
                name=f"Pair {index}",
                lounge_access_international=international,
                lounge_access_domestic=domestic,
            )

        cards = list(CreditCard.objects.all())
        true_names = set(
            CreditCard.objects.filter(card_lounge_access_q(True)).values_list(
                "name", flat=True
            )
        )
        false_names = set(
            CreditCard.objects.filter(card_lounge_access_q(False)).values_list(
                "name", flat=True
            )
        )
        assert true_names == {
            card.name for card in cards if card.has_lounge_access is True
        }
        assert false_names == {
            card.name for card in cards if card.has_lounge_access is False
        }


@pytest.mark.django_db
class TestLoungeFilters:
    """API filters return cards by known access, known none and visit counts."""

    @pytest.fixture(autouse=True)
    def lounge_cards(self):
        """Create one card for each lounge situation the filters must separate."""
        rows = {
            "Limited Both": ("5 visits", "2 visits"),
            "Unlimited Intl": ("Unlimited", ""),
            "Explicit None": ("0", "N/A"),
            "Unknown": ("", ""),
            "NA Intl Limited Dom": ("N/A", "3 visits"),
            "Partial None": ("None", ""),
            "Ten Visits": ("10 visits", ""),
        }
        for name, (international, domestic) in rows.items():
            CreditCardFactory(
                name=name,
                lounge_access_international=international,
                lounge_access_domestic=domestic,
            )

    @staticmethod
    def _names(queryset):
        """Return the set of card names in a queryset."""
        return set(queryset.values_list("name", flat=True))

    def _filter(self, params):
        """Run the API filterset with the given query parameters."""
        return self._names(CreditCardFilter(params, queryset=CreditCard.objects.all()).qs)

    def test_has_lounge_access_true_excludes_unknown_and_none(self):
        """True matches any direction with access, never unknown cards."""
        assert self._filter({"has_lounge_access": "true"}) == {
            "Limited Both",
            "Unlimited Intl",
            "NA Intl Limited Dom",
            "Ten Visits",
        }

    def test_has_lounge_access_false_matches_only_known_none(self):
        """False matches only cards where every direction is a known none."""
        assert self._filter({"has_lounge_access": "false"}) == {"Explicit None"}

    def test_has_international_lounge_false_excludes_unknown(self):
        """'N/A' international is a known none; empty international is unknown."""
        assert self._filter({"has_international_lounge": "false"}) == {
            "Explicit None",
            "NA Intl Limited Dom",
            "Partial None",
        }

    def test_has_international_lounge_true(self):
        """International access is true only for LIMITED or UNLIMITED values."""
        assert self._filter({"has_international_lounge": "true"}) == {
            "Limited Both",
            "Unlimited Intl",
            "Ten Visits",
        }

    def test_has_domestic_lounge_true(self):
        """Domestic access uses the same classification."""
        assert self._filter({"has_domestic_lounge": "true"}) == {
            "Limited Both",
            "NA Intl Limited Dom",
        }

    def test_min_international_lounge_uses_numeric_count(self):
        """Minimum counts compare numbers, not text ('N/A' and '10' must not match '5')."""
        assert self._filter({"min_international_lounge": "5"}) == {
            "Limited Both",
            "Ten Visits",
        }

    def test_min_international_lounge_excludes_unlimited_and_none(self):
        """Unlimited has no finite count, so it never matches a minimum."""
        names = self._filter({"min_international_lounge": "1"})
        assert "Unlimited Intl" not in names
        assert "Explicit None" not in names

    def test_advanced_filter_has_lounge_access(self):
        """Advanced search uses the same card-level rule."""
        queryset = CreditCardAdvancedFilter(
            {"has_lounge_access": "false"}, queryset=CreditCard.objects.all()
        ).qs
        assert self._names(queryset) == {"Explicit None"}

    def test_lounge_facet_counts_by_direction(self):
        """Facet buckets separate known access, known none and unknown."""
        facets = compute_facets(CreditCard.objects.all(), facet_names=["lounge_access"])
        buckets = {bucket["key"]: bucket for bucket in facets["lounge_access"]["buckets"]}
        assert buckets["international"]["true_count"] == 3
        assert buckets["international"]["false_count"] == 3
        assert buckets["domestic"]["true_count"] == 2
        assert buckets["domestic"]["false_count"] == 1
