"""Search query builders (pure functions, no engine access).

Keeping query construction free of Elasticsearch client access makes the
behaviour of filters, synonyms and facet aggregations unit testable.
"""

from django.conf import settings

from search.documents import (
    ANALYZER_BENGALI,
    ANALYZER_ENGLISH,
    ANALYZER_MULTILANG,
    CREDIT_CARD_INDEX_BODY,
)

#: Card fields used for full text matching (multi language + sub fields).
CARD_TEXT_FIELDS = [
    "name^3",
    "bank_name^2",
    "content",
    "reward_points_policy",
    "additional_features.text",
    "lounge_access_international",
    "lounge_access_domestic",
    "lounge_access_condition",
    "cash_advance_fee",
    "late_payment_fee",
]

#: Bank fields used for full text matching.
BANK_TEXT_FIELDS = ["name^3", "content"]

#: Card fields used for type ahead suggestions.
CARD_SUGGEST_FIELDS = [
    "name_suggest",
    "name_suggest._2gram",
    "name_suggest._3gram",
    "bank_name_suggest",
    "bank_name_suggest._2gram",
]

#: Bank fields used for type ahead suggestions.
BANK_SUGGEST_FIELDS = ["name_suggest", "name_suggest._2gram", "name_suggest._3gram"]

#: ``filters -> Elasticsearch clause`` map for credit cards.
#:
#: A ``("term", field)`` entry uses the request value; a ``("term", field,
#: constant)`` entry always emits ``field = constant`` when the key is present.
CARD_FILTERS = {
    "bank_id": ("term", "bank_id"),
    "is_active": ("term", "is_active"),
    "has_annual_fee": ("term", "has_annual_fee"),
    "has_lounge_access": ("term", "has_lounge_access"),
    "has_lounge_access_international": ("term", "has_international_lounge"),
    "has_lounge_access_domestic": ("term", "has_domestic_lounge"),
    "has_fee_waiver": ("exists", "annual_fee_waiver_policy"),
    # Exact zero fee: never matches a card whose fee was never published.
    "no_annual_fee": ("term", "annual_fee", 0),
    # Only cards whose fee is unknown (``annual_fee`` missing in the index).
    "annual_fee_unknown": ("term", "annual_fee_known", False),
    "annual_fee_min": ("range", "annual_fee", "gte"),
    "annual_fee_max": ("range", "annual_fee", "lte"),
    "annual_fee_exact": ("term", "annual_fee"),
    "interest_rate_min": ("range", "interest_rate_apr", "gte"),
    "interest_rate_max": ("range", "interest_rate_apr", "lte"),
    "min_lounge_visits_international": ("range", "lounge_visits_international", "gte"),
    "min_lounge_visits_domestic": ("range", "lounge_visits_domestic", "gte"),
    # Category filters map to multi-field queries (OR logic across fields).
    # These are handled specially in _build_category_filter.
    "category": ("category",),
}

#: ``filters -> Elasticsearch clause`` map for banks.
BANK_FILTERS = {
    "is_active": ("term", "is_active"),
    "min_credit_card_count": ("range", "credit_card_count", "gte"),
    "max_credit_card_count": ("range", "credit_card_count", "lte"),
}

#: Facet aggregations exposed for credit cards.
CARD_AGGREGATIONS = {
    "bank_name": {"terms": {"field": "bank_name.keyword", "size": 50}},
    "bank_ids": {"terms": {"field": "bank_id", "size": 50}},
    "is_active": {"terms": {"field": "is_active"}},
    "has_annual_fee": {"terms": {"field": "has_annual_fee"}},
    "annual_fee_known": {"terms": {"field": "annual_fee_known"}},
    "has_lounge_access": {"terms": {"field": "has_lounge_access"}},
    "additional_features": {"terms": {"field": "additional_features", "size": 30}},
    "annual_fee_ranges": {
        "range": {
            "field": "annual_fee",
            "ranges": [
                {"key": "free", "to": 0.01},
                {"key": "0-1000", "from": 0, "to": 1000},
                {"key": "1000-3000", "from": 1000, "to": 3000},
                {"key": "3000-5000", "from": 3000, "to": 5000},
                {"key": "5000+", "from": 5000},
            ],
        }
    },
    "interest_rate_apr_ranges": {
        "range": {
            "field": "interest_rate_apr",
            "ranges": [
                {"key": "under_20", "to": 20},
                {"key": "20-25", "from": 20, "to": 25},
                {"key": "25-30", "from": 25, "to": 30},
                {"key": "30_plus", "from": 30},
            ],
        }
    },
}

#: Facet aggregations exposed for banks.
BANK_AGGREGATIONS = {
    "is_active": {"terms": {"field": "is_active"}},
    "credit_card_count_ranges": {
        "range": {
            "field": "credit_card_count",
            "ranges": [
                {"key": "none", "to": 1},
                {"key": "1-5", "from": 1, "to": 5},
                {"key": "5-10", "from": 5, "to": 10},
                {"key": "10_plus", "from": 10},
            ],
        }
    },
}

#: Allowed ordering fields for credit cards.
CARD_ORDERING_FIELDS = {
    "annual_fee",
    "interest_rate_apr",
    "name.keyword",
    "bank_name.keyword",
    "created",
    "modified",
    "has_lounge_access",
    "has_annual_fee",
}

#: Allowed ordering fields for banks.
BANK_ORDERING_FIELDS = {"name.keyword", "credit_card_count", "created", "modified"}


def index_name(kind):
    """Return the configured index name for a logical kind.

    Parameters
    ----------
    kind : str
        ``banks``, ``cards`` or ``credit_cards``.

    Returns
    -------
    str
        Index name.

    Raises
    ------
    ValueError
        If the logical kind is unknown.
    """
    if kind in ("banks",):
        return f"{getattr(settings, 'SEARCH_INDEX_PREFIX', '')}banks"
    if kind in ("cards", "credit_cards"):
        return f"{getattr(settings, 'SEARCH_INDEX_PREFIX', '')}credit_cards"
    raise ValueError(f"Unknown search index kind: {kind}")


def index_body(kind):
    """Return the index creation body for a logical kind.

    Parameters
    ----------
    kind : str
        ``banks``, ``cards`` or ``credit_cards``.

    Returns
    -------
    dict
        Settings and mappings payload.
    """
    from search.documents import BANK_INDEX_BODY

    if kind in ("banks",):
        return BANK_INDEX_BODY
    return CREDIT_CARD_INDEX_BODY


def mapping_of(kind):
    """Return the mapping of an index for filter introspection.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.

    Returns
    -------
    dict
        Mapping properties.
    """
    return index_body(kind)["mappings"]["properties"]


def filterable_fields(kind):
    """Return the declared list of filterable field names for an index.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.

    Returns
    -------
    list of str
        Filterable field names.
    """
    from search.documents import BANK_FILTERABLE_FIELDS, CREDIT_CARD_FILTERABLE_FIELDS

    if kind == "banks":
        return list(BANK_FILTERABLE_FIELDS)
    return list(CREDIT_CARD_FILTERABLE_FIELDS)


def mapped_filterable_fields(kind):
    """Return the filterable paths derived from the mapping itself.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.

    Returns
    -------
    list of str
        Sorted filterable paths computed from the mapping.
    """
    from search.documents import filterable_paths

    return filterable_paths(mapping_of(kind))


def _coerce_bool(value):
    """Parse a boolean query parameter.

    Parameters
    ----------
    value : object
        Raw value from the request.

    Returns
    -------
    bool | None
        Parsed value or ``None`` when it cannot be parsed.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return None


def _coerce_float(value):
    """Parse a numeric query parameter.

    Parameters
    ----------
    value : object
        Raw value from the request.

    Returns
    -------
    float | None
        Parsed value or ``None`` when it cannot be parsed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_str_list(value):
    """Normalize a list/single value into a list of strings.

    Parameters
    ----------
    value : object
        Raw value from the request.

    Returns
    -------
    list of str
        Normalized list (empty when nothing usable was provided).
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _term_clause(field, value):
    """Build a term/terms clause for ``field``.

    Parameters
    ----------
    field : str
        Target field.
    value : object
        Raw filter value.

    Returns
    -------
    dict | None
        Clause or ``None`` when the value is unusable.
    """
    if isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value if str(item).strip()]
        return {"terms": {field: values}} if values else None
    return {"term": {field: value}}


def _build_defined_filter(definition, value):
    """Build one clause for a declared scalar or presence filter."""
    filter_kind = definition[0]

    # Special handling for category filter - it's multi-value and handled in _build_multi_value_filters
    if filter_kind == "category":
        return None  # Handled in _build_multi_value_filters

    field = definition[1]
    if filter_kind == "term":
        if len(definition) == 3:
            # Fixed-value clause: the key toggles it on/off by itself.
            return (
                {"term": {field: definition[2]}} if _coerce_bool(value) is True else None
            )

        numeric = _coerce_float(value)
        if field in (
            "is_active",
            "has_annual_fee",
            "has_lounge_access",
            "has_international_lounge",
            "has_domestic_lounge",
        ):
            boolean = _coerce_bool(value)
            return _term_clause(field, boolean) if boolean is not None else None
        if numeric is not None and field not in ("name", "bank_name"):
            numeric = int(numeric) if numeric.is_integer() else numeric
            return {"term": {field: numeric}}
        return _term_clause(field, value)

    if filter_kind == "range":
        numeric = _coerce_float(value)
        return (
            {"range": {field: {definition[2]: numeric}}} if numeric is not None else None
        )
    if filter_kind == "exists":
        return {"exists": {"field": field}}
    if filter_kind == "not_empty":
        # Text fields must exist and differ from the empty string so cards
        # without lounge access never match.
        return {
            "bool": {
                "filter": [{"exists": {"field": field}}],
                "must_not": [{"term": {field: ""}}],
            }
        }
    return None


def _build_category_filter(value):
    """Build ES query for a category slug.

    Mirrors the DB fallback logic in CreditCardAdvancedFilter.filter_categories.
    Each category maps to a boolean OR query across specific fields.

    Parameters
    ----------
    value : str
        Category slug (e.g., "travel", "cashback", "premium", etc.)

    Returns
    -------
    dict | None
        Elasticsearch query clause or None if slug is unknown.
    """
    if not value:
        return None

    # Map category slugs to ES field queries matching DB logic
    category_queries = {
        "travel": {
            "bool": {
                "should": [
                    {"match": {"reward_points_policy": {"query": "travel"}}},
                    {"match": {"additional_features.text": {"query": "travel"}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "cashback": {
            "bool": {
                "should": [
                    {"match": {"reward_points_policy": {"query": "cashback"}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "premium": {
            "bool": {
                "should": [
                    {"range": {"annual_fee": {"gte": 2000}}},
                    {"term": {"has_international_lounge": True}},
                ],
                "minimum_should_match": 1,
            }
        },
        "student": {
            "bool": {
                "should": [
                    {"match": {"reward_points_policy": {"query": "student"}}},
                    {"match": {"additional_features.text": {"query": "student"}}},
                    {"range": {"annual_fee": {"lte": 500}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "business": {
            "bool": {
                "should": [
                    {"match": {"reward_points_policy": {"query": "business"}}},
                    {"match": {"additional_features.text": {"query": "business"}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "no-annual-fee": {
            "bool": {
                "should": [
                    {"term": {"annual_fee": 0}},
                ],
                "minimum_should_match": 1,
            }
        },
    }

    if value not in category_queries:
        return None

    return category_queries[value]


def _build_multi_value_filters(filters):
    """Build clauses for the supported multi-value and text filters."""
    clauses = []
    bank_ids = _coerce_str_list(filters.get("bank_ids"))
    if bank_ids:
        ids = [int(item) for item in bank_ids if item.isdigit()]
        if ids:
            clauses.append({"terms": {"bank_id": ids}})
    features = _coerce_str_list(filters.get("features"))
    if features:
        clauses.append({"terms": {"additional_features": features}})
    feature_search = filters.get("feature_search")
    if feature_search:
        clauses.append(
            {"match": {"additional_features.text": {"query": str(feature_search)}}}
        )
    # Handle category filter (multi-value, OR logic)
    categories = _coerce_str_list(filters.get("category"))
    for cat in categories:
        clause = _build_category_filter(cat)
        if clause:
            clauses.append(clause)
    return clauses


def build_filters(kind, filters):
    """Convert validated request filters into an Elasticsearch filter list.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.
    filters : dict
        Raw filter values keyed by filter name.

    Returns
    -------
    list of dict
        Elasticsearch filter clauses (may be empty).
    """
    spec = BANK_FILTERS if kind == "banks" else CARD_FILTERS
    clauses = []
    for name, definition in spec.items():
        value = filters.get(name)
        if name not in filters or value is None or value == "" or value == []:
            continue
        clause = _build_defined_filter(definition, value)
        if clause:
            clauses.append(clause)
    return clauses + _build_multi_value_filters(filters)


def build_match_query(query, fields):
    """Build a full text query with fuzziness and synonym aware analyzers.

    Parameters
    ----------
    query : str | None
        Raw user query.
    fields : list of str
        Fields to search (boosts supported via ``field^3``).

    Returns
    -------
    dict | None
        Query clause, or ``None`` for an empty query.
    """
    text = (query or "").strip()
    if not text:
        return None
    return {
        "multi_match": {
            "query": text,
            "fields": fields,
            "type": "best_fields",
            "operator": "and",
            "fuzziness": "AUTO",
            "prefix_length": 2,
        }
    }


def build_bengali_query(query, kind):
    """Build a Bengali specific query against the dedicated sub fields.

    Parameters
    ----------
    query : str | None
        Raw user query.
    kind : str
        ``banks`` or ``cards``.

    Returns
    -------
    dict | None
        Query clause, or ``None`` when the query has no Bengali characters.
    """
    text = (query or "").strip()
    if not text or not _has_bengali(text):
        return None
    if kind == "banks":
        fields = ["name.bengali^3", "name.english", "content.bengali"]
    else:
        fields = [
            "name.bengali^3",
            "bank_name.bengali^2",
            "content.bengali",
            "reward_points_policy.bengali",
            "lounge_access_condition.bengali",
        ]
    return {
        "multi_match": {
            "query": text,
            "fields": fields,
            "type": "best_fields",
            "operator": "and",
        }
    }


def build_english_query(query, kind):
    """Build an English specific query against the dedicated sub fields.

    Parameters
    ----------
    query : str | None
        Raw user query.
    kind : str
        ``banks`` or ``cards``.

    Returns
    -------
    dict | None
        Query clause, or ``None`` for an empty query.
    """
    text = (query or "").strip()
    if not text:
        return None
    if kind == "banks":
        fields = ["name.english^3", "content.english"]
    else:
        fields = [
            "name.english^3",
            "bank_name.english^2",
            "content.english",
            "reward_points_policy.english",
        ]
    return {
        "multi_match": {
            "query": text,
            "fields": fields,
            "type": "best_fields",
            "operator": "and",
            "fuzziness": "AUTO",
            "prefix_length": 2,
        }
    }


def build_query(kind, query=None, filters=None, bengali=True):
    """Build the ``query`` section of a search request.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.
    query : str | None
        Full text query.
    filters : dict | None
        Validated filters.
    bengali : bool
        Include the Bengali specific clause when the query is Bengali.

    Returns
    -------
    dict
        Elasticsearch ``query`` payload with ``bool.should`` clauses.
    """
    filters = filters or {}
    text_fields = BANK_TEXT_FIELDS if kind == "banks" else CARD_TEXT_FIELDS
    should = []
    base = build_match_query(query, text_fields)
    if base:
        should.append(base)
    if bengali:
        bengali_clause = build_bengali_query(query, kind)
        if bengali_clause:
            should.append(bengali_clause)
    english_clause = build_english_query(query, kind)
    if english_clause:
        should.append(english_clause)

    must = list(build_filters(kind, filters))
    body = {"bool": {}}
    if must:
        body["bool"]["filter"] = must
    if should:
        # ``minimum_should_match`` of 1 with the default analyzer clause first
        # keeps relevance ranking while the language clauses add recall.
        body["bool"]["should"] = should
        body["bool"]["minimum_should_match"] = 1
    if not body["bool"]:
        return {"match_all": {}}
    return body


def build_ordering(kind, ordering=None):
    """Return the Elasticsearch sort payload.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.
    ordering : str | None
        Django style ordering value (``-`` prefix means descending).

    Returns
    -------
    list
        Sort payload; empty list keeps relevance ordering.
    """
    if not ordering:
        return []
    field = ordering.lstrip("+-")
    descending = ordering.startswith("-")
    allowed = BANK_ORDERING_FIELDS if kind == "banks" else CARD_ORDERING_FIELDS
    if field not in allowed:
        return []
    return [{field: {"order": "desc" if descending else "asc"}}]


def build_body(kind, query=None, filters=None, page=1, page_size=20, ordering=None):
    """Build a complete search request body.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.
    query : str | None
        Full text query.
    filters : dict | None
        Validated filters.
    page : int
        1 based page number.
    page_size : int
        Page size (capped at 100).
    ordering : str | None
        Django style ordering value.

    Returns
    -------
    dict
        Search body with query, aggregations and pagination.
    """
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    aggregations = BANK_AGGREGATIONS if kind == "banks" else CARD_AGGREGATIONS
    body = {
        "query": build_query(kind, query, filters),
        "track_total_hits": True,
        "from": (page - 1) * page_size,
        "size": page_size,
    }
    sort = build_ordering(kind, ordering)
    if sort:
        body["sort"] = sort
    if aggregations:
        body["aggs"] = aggregations
    return body


def build_suggest_body(kind, query, size=8):
    """Build a type ahead request body.

    Parameters
    ----------
    kind : str
        ``banks`` or ``cards``.
    query : str
        Partial user input.
    size : int
        Maximum number of suggestions.

    Returns
    -------
    dict | None
        Search body, or ``None`` when the query is empty.
    """
    text = (query or "").strip()
    if not text:
        return None
    fields = BANK_SUGGEST_FIELDS if kind == "banks" else CARD_SUGGEST_FIELDS
    return {
        "query": {
            "multi_match": {
                "query": text,
                "type": "bool_prefix",
                "fields": fields,
            }
        },
        "_source": ["id", "name", "bank_name", "bank_id"],
        "size": min(max(int(size or 8), 1), 20),
    }


def explain_analysis():
    """Return the analysis configuration for documentation/tests.

    Returns
    -------
    dict
        Settings section of the index body including analyzers/synonyms.
    """
    return {
        "analyzer": index_body("cards")["settings"]["analysis"]["analyzer"],
        "filter": index_body("cards")["settings"]["analysis"]["filter"],
        "normalizer": index_body("cards")["settings"]["analysis"]["normalizer"],
    }


def analyzer_reference():
    """Return the analyzer names used by the service.

    Returns
    -------
    dict
        Mapping of purpose to analyzer name.
    """
    return {
        "multilang": ANALYZER_MULTILANG,
        "bengali": ANALYZER_BENGALI,
        "english": ANALYZER_ENGLISH,
    }


def _has_bengali(text):
    """Return True when the text contains Bengali characters.

    Parameters
    ----------
    text : str
        Text to inspect.

    Returns
    -------
    bool
        True if at least one Bengali Unicode character is present.
    """
    return any("\u0980" <= char <= "\u09ff" for char in text)
