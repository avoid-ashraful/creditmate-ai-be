"""Advanced filter classes for credit card search.

This module provides filter classes and utilities for advanced search features
including multi-category OR logic, facet aggregations, and relevance tuning.
"""

import django_filters
from django.db import models

from credit_cards.lounge import (
    card_lounge_access_q,
    filter_lounge_count_min,
    lounge_access_q,
)
from credit_cards.models import CreditCard


# Canonical category taxonomy matching the frontend
CANONICAL_CATEGORIES = [
    {"slug": "travel", "name": "Travel"},
    {"slug": "cashback", "name": "Cashback"},
    {"slug": "premium", "name": "Premium"},
    {"slug": "student", "name": "Student"},
    {"slug": "business", "name": "Business"},
    {"slug": "no-annual-fee", "name": "No Annual Fee"},
]

CATEGORY_SLUGS = [cat["slug"] for cat in CANONICAL_CATEGORIES]


#: Lounge access text fields that the boolean facets classify per direction.
LOUNGE_DIRECTION_FIELDS = ("lounge_access_international", "lounge_access_domestic")


class CreditCardAdvancedFilter(django_filters.FilterSet):
    """Advanced filter set for credit cards with multi-category OR logic and faceted search."""

    # Basic filters
    name = django_filters.CharFilter(lookup_expr="icontains")
    bank_name = django_filters.CharFilter(
        field_name="bank__name", lookup_expr="icontains"
    )

    # Multi-category filter with OR logic (categories=travel,cashback)
    categories = django_filters.CharFilter(method="filter_categories")

    # Price range filters
    annual_fee_min = django_filters.NumberFilter(
        field_name="annual_fee", lookup_expr="gte"
    )
    annual_fee_max = django_filters.NumberFilter(
        field_name="annual_fee", lookup_expr="lte"
    )
    annual_fee_range = django_filters.RangeFilter(field_name="annual_fee")

    # Interest rate filters
    interest_rate_min = django_filters.NumberFilter(
        field_name="interest_rate_apr", lookup_expr="gte"
    )
    interest_rate_max = django_filters.NumberFilter(
        field_name="interest_rate_apr", lookup_expr="lte"
    )
    interest_rate_range = django_filters.RangeFilter(field_name="interest_rate_apr")

    # Lounge access filters
    has_lounge_access = django_filters.BooleanFilter(method="filter_has_lounge_access")
    has_international_lounge = django_filters.BooleanFilter(
        method="filter_has_international_lounge"
    )
    has_domestic_lounge = django_filters.BooleanFilter(
        method="filter_has_domestic_lounge"
    )
    min_international_lounge = django_filters.NumberFilter(
        method="filter_min_international_lounge"
    )
    min_domestic_lounge = django_filters.NumberFilter(
        method="filter_min_domestic_lounge"
    )

    # Fee filters
    has_annual_fee = django_filters.BooleanFilter(method="filter_has_annual_fee")
    no_annual_fee = django_filters.BooleanFilter(method="filter_no_annual_fee")

    # Feature filters
    has_additional_features = django_filters.BooleanFilter(
        method="filter_has_additional_features"
    )
    feature_search = django_filters.CharFilter(method="filter_feature_search")

    # Waiver policy filters
    has_fee_waiver = django_filters.BooleanFilter(method="filter_has_fee_waiver")

    # IDs filter for filtering multiple credit cards
    ids = django_filters.BaseInFilter(field_name="id", lookup_expr="in")

    # Bank IDs filter for filtering by multiple banks
    bank_ids = django_filters.BaseInFilter(field_name="bank", lookup_expr="in")

    # Search query parameter for full-text search
    search = django_filters.CharFilter(method="filter_search")

    # Ordering is handled by DRF OrderingFilter, but we declare allowed fields here for documentation
    # ordering = django_filters.OrderingFilter(
    #     fields=(
    #         ("name", "name"),
    #         ("annual_fee", "annual_fee"),
    #         ("interest_rate_apr", "interest_rate_apr"),
    #         ("lounge_access_international", "lounge_access_international"),
    #         ("lounge_access_domestic", "lounge_access_domestic"),
    #         ("created", "created"),
    #         ("modified", "modified"),
    #         ("_score", "relevance"),  # For ES-backed search
    #     )
    # )

    class Meta:
        model = CreditCard
        fields = {
            "bank": ["exact"],
            "is_active": ["exact"],
            "created": ["gte", "lte"],
            "modified": ["gte", "lte"],
        }

    def filter_categories(self, queryset, name, value):  # noqa: C901
        """Filter by multiple categories with OR logic.

        Parameters
        ----------
        queryset : QuerySet
            Base queryset to filter.
        name : str
            Filter parameter name (unused).
        value : str
            Comma-separated category slugs (e.g., "travel,cashback").

        Returns
        -------
        QuerySet
            Filtered queryset matching any of the specified categories.
        """
        if not value:
            return queryset

        category_slugs = [slug.strip().lower() for slug in value.split(",") if slug.strip()]
        if not category_slugs:
            return queryset

        # Validate category slugs
        valid_slugs = [slug for slug in category_slugs if slug in CATEGORY_SLUGS]
        if not valid_slugs:
            return queryset.none()

        # Build OR query across category definitions
        # Each category maps to specific field conditions
        category_conditions = models.Q()

        for slug in valid_slugs:
            if slug == "travel":
                category_conditions |= models.Q(
                    models.Q(reward_points_policy__icontains="travel")
                    | models.Q(additional_features__icontains="travel")
                )
            elif slug == "cashback":
                category_conditions |= models.Q(
                    reward_points_policy__icontains="cashback"
                )
            elif slug == "premium":
                category_conditions |= models.Q(
                    models.Q(annual_fee__gte=2000)
                    | lounge_access_q("lounge_access_international", True)
                )
            elif slug == "student":
                category_conditions |= models.Q(
                    models.Q(reward_points_policy__icontains="student")
                    | models.Q(additional_features__icontains="student")
                    | models.Q(annual_fee__lte=500)
                )
            elif slug == "business":
                category_conditions |= models.Q(
                    models.Q(reward_points_policy__icontains="business")
                    | models.Q(additional_features__icontains="business")
                )
            elif slug == "no-annual-fee":
                category_conditions |= models.Q(annual_fee=0)

        return queryset.filter(category_conditions)

    def filter_search(self, queryset, name, value):
        """Full-text search across multiple fields.

        Parameters
        ----------
        queryset : QuerySet
            Base queryset to filter.
        name : str
            Filter parameter name (unused).
        value : str
            Search query string.

        Returns
        -------
        QuerySet
            Filtered queryset matching the search query.
        """
        if not value:
            return queryset

        query = value.strip()
        if not query:
            return queryset

        return queryset.filter(
            models.Q(name__icontains=query)
            | models.Q(bank__name__icontains=query)
            | models.Q(reward_points_policy__icontains=query)
            | models.Q(additional_features__icontains=query)
            | models.Q(cash_advance_fee__icontains=query)
            | models.Q(late_payment_fee__icontains=query)
        )

    def filter_has_lounge_access(self, queryset, name, value):
        """Filter by card-level lounge access (True: any access, False: known none)."""
        return queryset.filter(card_lounge_access_q(value))

    def filter_has_international_lounge(self, queryset, name, value):
        """Filter by international lounge access (True: access, False: known none)."""
        return queryset.filter(lounge_access_q("lounge_access_international", value))

    def filter_has_domestic_lounge(self, queryset, name, value):
        """Filter by domestic lounge access (True: access, False: known none)."""
        return queryset.filter(lounge_access_q("lounge_access_domestic", value))

    def filter_min_international_lounge(self, queryset, name, value):
        """Filter cards whose stated international visit count is at least value."""
        return filter_lounge_count_min(queryset, "lounge_access_international", value)

    def filter_min_domestic_lounge(self, queryset, name, value):
        """Filter cards whose stated domestic visit count is at least value."""
        return filter_lounge_count_min(queryset, "lounge_access_domestic", value)

    def filter_has_annual_fee(self, queryset, name, value):
        """Filter cards that have annual fee."""
        if value:
            return queryset.filter(annual_fee__gt=0)
        return queryset.filter(annual_fee=0)

    def filter_no_annual_fee(self, queryset, name, value):
        """Filter cards that have no annual fee."""
        if value:
            return queryset.filter(annual_fee=0)
        return queryset.filter(annual_fee__gt=0)

    def filter_has_additional_features(self, queryset, name, value):
        """Filter cards that have additional features."""
        if value:
            return queryset.exclude(additional_features=[])
        return queryset.filter(additional_features=[])

    def filter_feature_search(self, queryset, name, value):
        """Search in additional features."""
        if value:
            return queryset.filter(additional_features__icontains=value)
        return queryset

    def filter_has_fee_waiver(self, queryset, name, value):
        """Filter cards that have fee waiver policy."""
        if value:
            return queryset.filter(annual_fee_waiver_policy__isnull=False)
        return queryset.filter(annual_fee_waiver_policy__isnull=True)


# Facet computation utilities

FACET_DEFINITIONS = {
    "bank": {
        "label": "Bank",
        "type": "terms",
        "field": "bank__name",
        "size": 20,
    },
    "category": {
        "label": "Category",
        "type": "category",
        "size": len(CANONICAL_CATEGORIES),
    },
    "annual_fee_range": {
        "label": "Annual Fee Range",
        "type": "range",
        "field": "annual_fee",
        "ranges": [
            {"key": "free", "label": "Free", "to": 0.01},
            {"key": "low", "label": "1 - 1,000", "from": 0, "to": 1000},
            {"key": "medium", "label": "1,001 - 3,000", "from": 1000, "to": 3000},
            {"key": "high", "label": "3,001 - 5,000", "from": 3000, "to": 5000},
            {"key": "premium", "label": "5,000+", "from": 5000},
        ],
    },
    "interest_rate_range": {
        "label": "APR Range",
        "type": "range",
        "field": "interest_rate_apr",
        "ranges": [
            {"key": "low", "label": "Under 20%", "to": 20},
            {"key": "medium", "label": "20% - 25%", "from": 20, "to": 25},
            {"key": "high", "label": "25% - 30%", "from": 25, "to": 30},
            {"key": "very_high", "label": "30%+", "from": 30},
        ],
    },
    "lounge_access": {
        "label": "Lounge Access",
        "type": "boolean",
        "options": [
            {"key": "international", "label": "International", "field": "lounge_access_international"},
            {"key": "domestic", "label": "Domestic", "field": "lounge_access_domestic"},
            {"key": "any", "label": "Any", "field": "has_lounge_access", "is_property": True},
        ],
    },
    "fee_waiver": {
        "label": "Fee Waiver",
        "type": "boolean",
        "field": "annual_fee_waiver_policy",
    },
    "has_annual_fee": {
        "label": "Has Annual Fee",
        "type": "boolean",
        "field": "has_annual_fee",
        "is_property": True,
    },
}


def compute_facets(queryset, facet_names=None):  # noqa: C901
    """Compute facet counts for the given queryset.

    Parameters
    ----------
    queryset : QuerySet
        Filtered queryset to compute facets on.
    facet_names : list of str, optional
        Specific facet names to compute. If None, computes all facets.

    Returns
    -------
    dict
        Dictionary of facet data keyed by facet name.
    """
    from django.db.models import Count, Q

    if facet_names is None:
        facet_names = list(FACET_DEFINITIONS.keys())

    facets = {}

    for facet_name in facet_names:
        definition = FACET_DEFINITIONS.get(facet_name)
        if not definition:
            continue

        if definition["type"] == "terms":
            field = definition["field"]
            size = definition.get("size", 20)
            facet_data = (
                queryset.values(field)
                .annotate(count=Count("id"))
                .order_by("-count")[:size]
            )
            facets[facet_name] = {
                "label": definition["label"],
                "type": "terms",
                "buckets": [
                    {"key": item[field] or "Unknown", "count": item["count"]}
                    for item in facet_data
                ],
            }

        elif definition["type"] == "range":
            field = definition["field"]
            ranges = definition["ranges"]
            buckets = []

            for range_def in ranges:
                filter_kwargs = {}
                if "from" in range_def:
                    filter_kwargs[f"{field}__gte"] = range_def["from"]
                if "to" in range_def:
                    filter_kwargs[f"{field}__lt"] = range_def["to"]

                count = queryset.filter(**filter_kwargs).count()
                buckets.append(
                    {
                        "key": range_def["key"],
                        "label": range_def["label"],
                        "from": range_def.get("from"),
                        "to": range_def.get("to"),
                        "count": count,
                    }
                )

            facets[facet_name] = {
                "label": definition["label"],
                "type": "range",
                "buckets": buckets,
            }

        elif definition["type"] == "boolean":
            field = definition.get("field")
            options = definition.get("options", [])

            if options:
                # Multiple boolean options
                buckets = []
                for option in options:
                    opt_field = option["field"]
                    is_property = option.get("is_property", False)

                    if opt_field == "has_lounge_access":
                        true_count = queryset.filter(card_lounge_access_q(True)).count()
                        false_count = queryset.filter(card_lounge_access_q(False)).count()
                    elif opt_field in LOUNGE_DIRECTION_FIELDS:
                        true_count = queryset.filter(lounge_access_q(opt_field, True)).count()
                        false_count = queryset.filter(lounge_access_q(opt_field, False)).count()
                    elif opt_field == "has_annual_fee" or is_property:
                        true_count = queryset.filter(annual_fee__gt=0).count()
                        false_count = queryset.filter(annual_fee=0).count()
                    else:
                        true_count = queryset.exclude(**{f"{opt_field}__exact": ""}).count()
                        false_count = queryset.filter(**{f"{opt_field}__exact": ""}).count()

                    buckets.append(
                        {
                            "key": option["key"],
                            "label": option["label"],
                            "true_count": true_count,
                            "false_count": false_count,
                        }
                    )
                facets[facet_name] = {
                    "label": definition["label"],
                    "type": "boolean",
                    "buckets": buckets,
                }
            else:
                # Single boolean field
                is_property = definition.get("is_property", False)
                if is_property:
                    if field == "has_annual_fee":
                        true_count = queryset.filter(annual_fee__gt=0).count()
                        false_count = queryset.filter(annual_fee=0).count()
                    elif field == "has_lounge_access":
                        true_count = queryset.filter(card_lounge_access_q(True)).count()
                        false_count = queryset.filter(card_lounge_access_q(False)).count()
                    else:
                        true_count = queryset.exclude(**{f"{field}__exact": ""}).count()
                        false_count = queryset.filter(**{f"{field}__exact": ""}).count()
                else:
                    true_count = queryset.filter(**{f"{field}__exact": True}).count()
                    false_count = queryset.filter(**{f"{field}__exact": False}).count()

                facets[facet_name] = {
                    "label": definition["label"],
                    "type": "boolean",
                    "buckets": [
                        {"key": "true", "label": "Yes", "count": true_count},
                        {"key": "false", "label": "No", "count": false_count},
                    ],
                }

        elif definition["type"] == "category":
            # Canonical categories with counts
            buckets = []
            for cat in CANONICAL_CATEGORIES:
                slug = cat["slug"]
                if slug == "travel":
                    count = queryset.filter(
                        Q(reward_points_policy__icontains="travel")
                        | Q(additional_features__icontains="travel")
                    ).count()
                elif slug == "cashback":
                    count = queryset.filter(
                        reward_points_policy__icontains="cashback"
                    ).count()
                elif slug == "premium":
                    count = queryset.filter(
                        Q(annual_fee__gte=2000)
                        | lounge_access_q("lounge_access_international", True)
                    ).count()
                elif slug == "student":
                    count = queryset.filter(
                        Q(reward_points_policy__icontains="student")
                        | Q(additional_features__icontains="student")
                        | Q(annual_fee__lte=500)
                    ).count()
                elif slug == "business":
                    count = queryset.filter(
                        Q(reward_points_policy__icontains="business")
                        | Q(additional_features__icontains="business")
                    ).count()
                elif slug == "no-annual-fee":
                    count = queryset.filter(annual_fee=0).count()
                else:
                    count = 0

                if count > 0:
                    buckets.append(
                        {
                            "key": slug,
                            "label": cat["name"],
                            "count": count,
                            "filter": f"categories={slug}",
                        }
                    )

            facets[facet_name] = {
                "label": definition["label"],
                "type": "category",
                "buckets": buckets,
            }

    return facets


def normalize_query_params(query_params):  # noqa: C901
    """Normalize query parameters for saved searches.

    This function canonicalizes query parameters so that equivalent searches
    produce the same normalized representation, enabling reliable saved search
    matching and deduplication.

    Parameters
    ----------
    query_params : QueryDict or dict
        Raw query parameters from the request.

    Returns
    -------
    dict
        Normalized query parameters with sorted keys and consistent value formatting.
    """
    normalized = {}

    # Define parameter categories
    scalar_params = {
        "search",
        "name",
        "bank_name",
        "annual_fee_min",
        "annual_fee_max",
        "interest_rate_min",
        "interest_rate_max",
        "min_international_lounge",
        "min_domestic_lounge",
        "feature_search",
        "ordering",
        "page",
        "page_size",
        "facets",
    }

    boolean_params = {
        "has_lounge_access",
        "has_international_lounge",
        "has_domestic_lounge",
        "has_annual_fee",
        "no_annual_fee",
        "has_additional_features",
        "has_fee_waiver",
    }

    multi_value_params = {
        "categories",
        "ids",
        "bank_ids",
    }

    # Process scalar parameters
    for key in scalar_params:
        value = query_params.get(key)
        if value is not None and value != "":
            normalized[key] = str(value).strip()

    # Process boolean parameters - only include if explicitly true
    for key in boolean_params:
        value = query_params.get(key)
        if value is not None:
            if isinstance(value, str):
                normalized_value = value.lower().strip()
                if normalized_value in ("true", "1", "yes", "on"):
                    normalized[key] = "true"
            elif isinstance(value, bool) and value:
                normalized[key] = "true"

    # Process multi-value parameters - sort for consistency
    for key in multi_value_params:
        values = query_params.getlist(key) if hasattr(query_params, "getlist") else []
        # Flatten comma-separated values from getlist (e.g., ['a,b'] -> ['a', 'b'])
        flattened = []
        for v in values:
            if isinstance(v, str):
                flattened.extend([item.strip() for item in v.split(",") if item.strip()])
            else:
                s = str(v).strip()
                if s:
                    flattened.append(s)
        if flattened:
            normalized[key] = ",".join(sorted(set(flattened)))

    return normalized


def get_sort_options():
    """Return available sort options for the API.

    Returns
    -------
    list of dict
        Sort options with key, label, and description.
    """
    return [
        {"key": "relevance", "label": "Relevance", "description": "Best match first (default with search query)"},
        {"key": "annual_fee", "label": "Annual Fee (Low to High)", "description": "Sort by annual fee ascending"},
        {"key": "-annual_fee", "label": "Annual Fee (High to Low)", "description": "Sort by annual fee descending"},
        {"key": "interest_rate_apr", "label": "APR (Low to High)", "description": "Sort by interest rate ascending"},
        {"key": "-interest_rate_apr", "label": "APR (High to Low)", "description": "Sort by interest rate descending"},
        {"key": "-lounge_access_international", "label": "Lounge Access (Most First)", "description": "Sort by international lounge access descending"},
        {"key": "-lounge_access_domestic", "label": "Domestic Lounge (Most First)", "description": "Sort by domestic lounge access descending"},
        {"key": "name", "label": "Name (A-Z)", "description": "Sort by card name ascending"},
        {"key": "-name", "label": "Name (Z-A)", "description": "Sort by card name descending"},
        {"key": "-created", "label": "Newest First", "description": "Sort by creation date descending"},
        {"key": "created", "label": "Oldest First", "description": "Sort by creation date ascending"},
    ]
