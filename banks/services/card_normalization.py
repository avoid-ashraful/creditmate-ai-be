"""Preserve fee denomination before numeric normalization loses the wording."""

import re

from banks.validators.numeric_fields import (
    REASON_FOREIGN_CURRENCY,
    parse_numeric_value_detailed,
)


def preserve_annual_fee_details(card):
    """Copy foreign annual fee wording to features and leave the BDT fee unknown.

    Parameters
    ----------
    card : dict
        Raw extracted card, possibly including fee currency/details columns.

    Returns
    -------
    dict
        Copy with foreign fees preserved as text and annual_fee set to None.
    """
    result = dict(card)
    fee = card.get("annual_fee")
    currency = str(card.get("annual_fee_currency") or card.get("currency") or "")
    details = str(card.get("annual_fee_details") or card.get("annual_fee_text") or "")
    foreign = _has_foreign_currency(fee)
    foreign_currency = currency.strip().upper() not in {"", "BDT", "TK", "TAKA", "৳"}
    foreign_details = _has_foreign_currency(details)
    raw_features = card.get("additional_features")
    features = list(raw_features) if isinstance(raw_features, list) else []
    # Numeric output can still carry denomination in an explicit fee detail.
    feature_details = " ".join(
        str(value)
        for value in features
        if str(value).lower().startswith("annual fee details:")
    )
    foreign_features = _has_foreign_currency(feature_details)
    if foreign or foreign_currency or foreign_details or foreign_features:
        wording = details or (f"{currency} {fee}".strip() if fee is not None else "")
        if wording and not foreign_features:
            detail = f"Annual fee details: {wording}"
            if detail not in features:
                features.append(detail)
        result["additional_features"] = features
        result["annual_fee"] = None
    return result


def _has_foreign_currency(value):
    """Recognize foreign fee denominations before their wording is discarded.

    Parameters
    ----------
    value : object
        Raw fee text or preserved annual-fee detail.

    Returns
    -------
    bool
        Whether the text contains a foreign denomination.
    """
    reason = parse_numeric_value_detailed(value, "annual_fee")[2]
    return reason == REASON_FOREIGN_CURRENCY or bool(
        re.search(
            r"\b(?:USD|EUR|GBP|INR|AED|AUD|CAD|CHF|CNY|HKD|JPY|KRW|MYR|NPR|PKR|QAR|SAR|SGD|THB)(?=\b|\d)|[$€£₹¥₩₨]",
            str(value or ""),
            re.I,
        )
    )
