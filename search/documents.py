"""Elasticsearch index definitions for the CreditMate search service.

This module is the single source of truth for:

* index level settings (single node local defaults, refresh interval),
* the analysis chain: a Bengali aware multi language analyzer, the built in
  Bengali language analyzer, an English analyzer and a case insensitive
  keyword normalizer,
* the synonym sets (including the mandated ``visa`` = ``credit card`` and
  ``apr`` = ``interest rate`` equivalents),
* the field mappings for both indexes including every filterable field,
* document serialization from Django models to index documents.

Nothing in here talks to Elasticsearch; it only declares the JSON payloads so
they can be created by :mod:`search.service` and asserted by unit tests.
"""

from credit_cards.lounge import direction_has_access, lounge_access_count

# ---------------------------------------------------------------------------
# Analyzer / filter / normalizer names
# ---------------------------------------------------------------------------

ANALYZER_MULTILANG = "creditmate_multilang"
ANALYZER_BENGALI = "creditmate_bengali"
ANALYZER_ENGLISH = "creditmate_english"
# Analyzer for ``search_as_you_type`` prefix fields.  It intentionally omits
# the synonym filter: Elasticsearch 8.19 rejects documents when a multi word
# synonym source ("credit card", "interest rate") is analysed into a
# ``search_as_you_type`` sub field
# (``first position increment must be > 0 (got 0) for field 'name._3gram'``).
# Prefix completion does not need synonyms anyway.
ANALYZER_SUGGEST = "creditmate_suggest"
FILTER_SYNONYMS = "creditmate_synonyms"
FILTER_ENGLISH_STEMMER = "creditmate_english_stemmer"
FILTER_BENGALI_STEMMER = "creditmate_bengali_stemmer"
NORMALIZER_KEYWORD = "creditmate_keyword"

# ---------------------------------------------------------------------------
# Synonyms
# ---------------------------------------------------------------------------

#: Explicit synonym groups.  Each entry is a comma separated group where every
#: term is treated as equivalent of the others (``expand: true`` semantics).
#: The two groups required by the acceptance criteria come first.
SYNONYMS = [
    # Required: "visa" = "credit card"
    "visa, credit card",
    # Required: "apr" = "interest rate"
    "apr, interest rate, annual percentage rate",
    # Bengali equivalents of the required groups (local language search).
    "কার্ড, ক্রেডিট কার্ড",
    "সুদের হার, এপিআর, সুদ",
    # Domain vocabulary used on Bangladeshi banking sites.
    "cashback, cash back",
    "lounge access, lounge",
    "annual fee, membership fee",
    "reward points, points",
    "islami, islamic, shariah",
]

#: Human readable description of the mandated synonym pairs, used in docs and
#: tests so the requirement stays traceable.
REQUIRED_SYNONYM_GROUPS = [
    ("visa", "credit card"),
    ("apr", "interest rate"),
]

# ---------------------------------------------------------------------------
# Index level settings
# ---------------------------------------------------------------------------

INDEX_SETTINGS = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "refresh_interval": "1s",
    "analysis": {
        "filter": {
            FILTER_SYNONYMS: {
                "type": "synonym_graph",
                "expand": True,
                "lenient": False,
                "synonyms": SYNONYMS,
            },
            FILTER_ENGLISH_STEMMER: {"type": "stemmer", "language": "english"},
            FILTER_BENGALI_STEMMER: {"type": "stemmer", "language": "bengali"},
        },
        "analyzer": {
            # Default analyzer for Latin text with Bengali fallback support.
            ANALYZER_MULTILANG: {
                "type": "custom",
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    # Bengali normalisation folds Bengali spelling variants.
                    "bengali_normalization",
                    FILTER_BENGALI_STEMMER,
                    "asciifolding",
                    FILTER_ENGLISH_STEMMER,
                    FILTER_SYNONYMS,
                ],
            },
            # Built in Elasticsearch Bengali language analyzer, used for the
            # dedicated ``.bengali`` sub fields of local language search.
            ANALYZER_BENGALI: {"type": "bengali"},
            ANALYZER_ENGLISH: {
                "type": "custom",
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "asciifolding",
                    FILTER_ENGLISH_STEMMER,
                    FILTER_SYNONYMS,
                ],
            },
            # Synonym free chain used by the ``search_as_you_type`` fields.
            ANALYZER_SUGGEST: {
                "type": "custom",
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "bengali_normalization",
                    FILTER_BENGALI_STEMMER,
                    "asciifolding",
                    FILTER_ENGLISH_STEMMER,
                ],
            },
        },
        "normalizer": {
            # Case insensitive keyword normalizer so filters/aggregations on
            # names are stable regardless of source casing.
            NORMALIZER_KEYWORD: {
                "type": "custom",
                "filter": ["lowercase", "asciifolding"],
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Filterable fields
# ---------------------------------------------------------------------------

#: Fields of the banks index that support exact filtering/aggregation.
#: Paths are concrete Elasticsearch paths (``name.keyword`` for text fields).
BANK_FILTERABLE_FIELDS = [
    "id",
    "name.keyword",
    "logo",
    "website",
    "schedule_charge_url",
    "is_active",
    "credit_card_count",
    "created",
    "modified",
]

#: Fields of the credit_cards index that support exact filtering/aggregation.
#: Paths are concrete Elasticsearch paths (``name.keyword`` for text fields).
CREDIT_CARD_FILTERABLE_FIELDS = [
    "id",
    "bank_id",
    "bank_name.keyword",
    "name.keyword",
    "annual_fee",
    "annual_fee_known",
    "interest_rate_apr",
    "annual_fee_waiver_policy",
    "additional_features",
    "cash_advance_fee.keyword",
    "late_payment_fee.keyword",
    "lounge_access_international.keyword",
    "lounge_access_domestic.keyword",
    "lounge_access_condition.keyword",
    "reward_points_policy.keyword",
    "lounge_visits_international",
    "lounge_visits_domestic",
    "is_active",
    "has_annual_fee",
    "has_lounge_access",
    "has_international_lounge",
    "has_domestic_lounge",
    "created",
    "modified",
]

#: Elasticsearch types that can be filtered/aggregated on.
FILTERABLE_TYPES = {
    "keyword",
    "boolean",
    "long",
    "integer",
    "short",
    "byte",
    "double",
    "float",
    "half_float",
    "scaled_float",
    "date",
    "ip",
    "flattened",
}


def filterable_paths(properties, prefix=""):
    """Walk a mapping and return every concrete filterable path.

    Parameters
    ----------
    properties : dict
        Mapping ``properties`` section.
    prefix : str
        Parent path used while recursing into multi-fields.

    Returns
    -------
    list of str
        Sorted list of paths that can be used in filters/aggregations.
    """
    paths = []
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}{name}"
        if spec.get("type") in FILTERABLE_TYPES:
            paths.append(path)
        sub_fields = spec.get("fields")
        if sub_fields:
            paths.extend(filterable_paths(sub_fields, prefix=f"{path}."))
    return sorted(paths)


def _text_field():
    """Return the definition of a multilanguage text field.

    Returns
    -------
    dict
        Mapping for a ``text`` field with ``keyword``, ``bengali`` and
        ``english`` sub fields.
    """
    return {
        "type": "text",
        "analyzer": ANALYZER_MULTILANG,
        "fields": {
            # Plain keyword (source casing preserved) so facet buckets keep
            # the value the user will see in the UI.
            "keyword": {"type": "keyword", "ignore_above": 256},
            "bengali": {"type": "text", "analyzer": ANALYZER_BENGALI},
            "english": {"type": "text", "analyzer": ANALYZER_ENGLISH},
        },
    }


def _keyword_field():
    """Return the definition of a case insensitive keyword field.

    Returns
    -------
    dict
        Mapping for a normalized ``keyword`` field.
    """
    return {"type": "keyword", "normalizer": NORMALIZER_KEYWORD}


# ---------------------------------------------------------------------------
# Bank index mapping
# ---------------------------------------------------------------------------

BANK_MAPPING = {
    "properties": {
        "id": {"type": "long"},
        "name": _text_field(),
        "name_suggest": {
            "type": "search_as_you_type",
            "analyzer": ANALYZER_SUGGEST,
            "max_shingle_size": 3,
        },
        "logo": _keyword_field(),
        "website": _keyword_field(),
        "schedule_charge_url": _keyword_field(),
        "is_active": {"type": "boolean"},
        "credit_card_count": {"type": "integer"},
        "created": {"type": "date"},
        "modified": {"type": "date"},
        # Catch-all field used as the base of every search query.
        "content": {"type": "text", "analyzer": ANALYZER_MULTILANG},
    }
}

# ---------------------------------------------------------------------------
# Credit card index mapping
# ---------------------------------------------------------------------------

CREDIT_CARD_MAPPING = {
    "properties": {
        "id": {"type": "long"},
        "bank_id": {"type": "long"},
        "bank_name": _text_field(),
        "bank_name_suggest": {
            "type": "search_as_you_type",
            "analyzer": ANALYZER_SUGGEST,
            "max_shingle_size": 3,
        },
        "name": _text_field(),
        "name_suggest": {
            "type": "search_as_you_type",
            "analyzer": ANALYZER_SUGGEST,
            "max_shingle_size": 3,
        },
        "annual_fee": {"type": "float"},
        # ``annual_fee_known`` separates "no fee" from "fee not published":
        # ``has_annual_fee`` stays null when the fee is unknown so that
        # ``has_annual_fee:false`` never matches an unknown fee.
        "annual_fee_known": {"type": "boolean"},
        "annual_fee_waiver_policy": {"type": "flattened"},
        "interest_rate_apr": {"type": "float"},
        "lounge_access_international": _text_field(),
        "lounge_access_domestic": _text_field(),
        "lounge_visits_international": {"type": "float"},
        "lounge_visits_domestic": {"type": "float"},
        "lounge_access_condition": _text_field(),
        "cash_advance_fee": _text_field(),
        "late_payment_fee": _text_field(),
        "reward_points_policy": _text_field(),
        # Facets must keep the source casing, so this stays a plain keyword.
        "additional_features": {
            "type": "keyword",
            "ignore_above": 256,
            "fields": {"text": {"type": "text", "analyzer": ANALYZER_MULTILANG}},
        },
        "is_active": {"type": "boolean"},
        "has_annual_fee": {"type": "boolean"},
        "has_lounge_access": {"type": "boolean"},
        "has_international_lounge": {"type": "boolean"},
        "has_domestic_lounge": {"type": "boolean"},
        "created": {"type": "date"},
        "modified": {"type": "date"},
        # Catch-all field used as the base of every search query.
        "content": {"type": "text", "analyzer": ANALYZER_MULTILANG},
    }
}

#: Full index bodies (``{"settings": ..., "mappings": ...}``).
BANK_INDEX_BODY = {"settings": INDEX_SETTINGS, "mappings": BANK_MAPPING}
CREDIT_CARD_INDEX_BODY = {"settings": INDEX_SETTINGS, "mappings": CREDIT_CARD_MAPPING}

# ---------------------------------------------------------------------------
# Document serialization helpers
# ---------------------------------------------------------------------------


def _flatten_json(value):
    """Flatten nested JSON structures into ``key=value`` searchable text.

    Parameters
    ----------
    value : object
        JSON compatible structure coming from the model.

    Returns
    -------
    str
        Space separated ``key=value`` representation.
    """
    parts = []

    def _walk(node, prefix=""):
        if isinstance(node, dict):
            for key, item in node.items():
                _walk(item, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item, prefix)
        elif node is not None:
            parts.append(f"{prefix}={node}")

    _walk(value)
    return " ".join(parts)


def _to_float(value):
    """Convert a decimal/None value to a JSON friendly float.

    Parameters
    ----------
    value : Decimal | float | int | None
        Value to convert.

    Returns
    -------
    float | None
        Converted value or ``None``.
    """
    if value is None:
        return None
    return float(value)


def bank_to_document(bank):
    """Serialize a :class:`banks.models.Bank` instance into an index document.

    Parameters
    ----------
    bank : Bank
        Bank instance to serialize.

    Returns
    -------
    dict
        Document ready to be indexed with ``id`` mirroring the database pk.
    """
    name = bank.name or ""
    content_parts = [name]
    if bank.website:
        content_parts.append(bank.website)
    if bank.schedule_charge_url:
        content_parts.append(bank.schedule_charge_url)
    # ``active_credit_card_count`` is available when the bank comes from an
    # annotated queryset (bulk rebuild); otherwise fall back to the property.
    count = getattr(bank, "active_credit_card_count", None)
    if count is None:
        count = bank.credit_card_count
    return {
        "id": bank.pk,
        "name": name,
        "name_suggest": name,
        "logo": bank.logo or "",
        "website": bank.website or "",
        "schedule_charge_url": bank.schedule_charge_url or "",
        "is_active": bool(bank.is_active),
        "credit_card_count": int(count),
        "created": bank.created,
        "modified": bank.modified,
        "content": " ".join(content_parts),
    }


def credit_card_to_document(card):
    """Serialize a :class:`credit_cards.models.CreditCard` into a document.

    Parameters
    ----------
    card : CreditCard
        Card instance (``bank`` must be selected or it will be fetched).

    Returns
    -------
    dict
        Document ready to be indexed with ``id`` mirroring the database pk.
    """
    bank = getattr(card, "bank", None)
    bank_name = bank.name if bank is not None else ""
    features = list(card.additional_features or [])
    waiver = card.annual_fee_waiver_policy or {}
    reward_policy = card.reward_points_policy or ""
    content_parts = [
        bank_name,
        card.name or "",
        reward_policy,
        " ".join(str(feature) for feature in features),
        _flatten_json(waiver),
        card.lounge_access_international or "",
        card.lounge_access_domestic or "",
        card.lounge_access_condition or "",
        card.cash_advance_fee or "",
        card.late_payment_fee or "",
    ]
    international = card.lounge_access_international or ""
    domestic = card.lounge_access_domestic or ""
    # Unknown fee must stay distinguishable from a genuine zero fee:
    #   annual_fee is None -> has_annual_fee stays null (not indexed)
    #   annual_fee == 0    -> has_annual_fee false (a real no-fee card)
    #   annual_fee > 0     -> has_annual_fee true
    fee = _to_float(card.annual_fee)
    if fee is None:
        has_annual_fee = None
        annual_fee_known = False
    else:
        has_annual_fee = fee > 0
        annual_fee_known = True
    return {
        "id": card.pk,
        "bank_id": card.bank_id,
        "bank_name": bank_name,
        "bank_name_suggest": bank_name,
        "name": card.name or "",
        "name_suggest": card.name or "",
        "annual_fee": fee,
        "annual_fee_known": annual_fee_known,
        "annual_fee_waiver_policy": waiver,
        "interest_rate_apr": _to_float(card.interest_rate_apr),
        "lounge_access_international": international,
        "lounge_access_domestic": domestic,
        "lounge_visits_international": lounge_access_count(international),
        "lounge_visits_domestic": lounge_access_count(domestic),
        "lounge_access_condition": card.lounge_access_condition or "",
        "cash_advance_fee": card.cash_advance_fee or "",
        "late_payment_fee": card.late_payment_fee or "",
        "reward_points_policy": reward_policy,
        "additional_features": features,
        "is_active": bool(card.is_active),
        "source_url": card.source_url or "",
        "apply_url": card.apply_url or "",
        "card_network": card.card_network or "",
        "is_islamic": bool(card.is_islamic),
        "is_dual_currency": card.is_dual_currency,
        "min_monthly_income": _to_float(card.min_monthly_income),
        "supplementary_card_fee": card.supplementary_card_fee or "",
        "foreign_transaction_fee": card.foreign_transaction_fee or "",
        "has_annual_fee": has_annual_fee,
        "has_lounge_access": card.has_lounge_access,
        "has_international_lounge": direction_has_access(international),
        "has_domestic_lounge": direction_has_access(domestic),
        "created": card.created,
        "modified": card.modified,
        "content": " ".join(part for part in content_parts if part),
    }
