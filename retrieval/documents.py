"""Document builders: verified catalogue rows -> canonical text sections.

Each builder returns a plain dict::

    {
        "product_type": ..., "product_id": ..., "title": ...,
        "bank_id": ..., "bank_name": ..., "is_islamic": ...,
        "url_path": ..., "sections": [(field, text), ...],
    }

Sections keep field provenance so chunks (and therefore citations) know
which published field a passage came from. Honesty rules are inherited
from the data itself and from the labels chosen here: Islamic products
are described with expected-profit terminology, loan rates are rendered
as the published band (min-max), never as a single point rate, and
unpublished values are simply omitted — never guessed.
"""

from django.utils.text import slugify


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(
                    "; ".join(f"{k}: {v}" for k, v in item.items() if v not in ("", None))
                )
            elif item not in ("", None):
                parts.append(str(item))
        return "; ".join(p for p in parts if p)
    return str(value).strip()


def _section(field, label, value):
    text = _clean(value)
    if not text:
        return None
    return (field, f"{label}: {text}.")


def _collect(*candidates):
    return [c for c in candidates if c]


def build_credit_card_document(card):
    bank_name = card.bank.name if card.bank_id else ""
    rate_label = "Expected profit rate" if card.is_islamic else "Interest rate (APR)"
    rate_value = (
        None
        if card.is_islamic
        else (
            f"{card.interest_rate_apr}%" if card.interest_rate_apr is not None else None
        )
    )
    sections = _collect(
        _section(
            "overview",
            "Product",
            f"{card.name} credit card issued by {bank_name}"
            + (" (Islamic / Shariah-compliant)" if card.is_islamic else "")
            + (f". Card network: {card.card_network}" if card.card_network else ""),
        ),
        _section("fees", "Annual fee (BDT)", card.annual_fee),
        _section("fees", "Annual fee waiver policy", card.annual_fee_waiver_policy),
        _section("fees", "Cash advance fee", card.cash_advance_fee),
        _section("fees", "Late payment fee", card.late_payment_fee),
        _section("fees", "Supplementary card fee", card.supplementary_card_fee),
        _section("fees", "Foreign transaction fee", card.foreign_transaction_fee),
        _section("interest", rate_label, rate_value),
        _section("rewards", "Reward programme", card.reward_program_name),
        _section("rewards", "Reward points policy", card.reward_points_policy),
        _section("rewards", "Reward earn rules", card.reward_earn_rules),
        _section("rewards", "Cashback rules", card.cashback_rules),
        _section(
            "lounge",
            "Lounge access",
            "; ".join(
                p
                for p in [
                    card.lounge_access_summary or "",
                    card.lounge_access_condition or "",
                ]
                if p
            ),
        ),
        _section(
            "eligibility",
            "Minimum monthly income (BDT)",
            card.min_monthly_income,
        ),
        _section("features", "Additional features", card.additional_features),
        _section("source", "Published source", card.source_url),
    )
    url_path = (
        f"/card/{slugify(bank_name)}/{slugify(card.name)}" if bank_name else "/cards"
    )
    return {
        "product_type": "credit_card",
        "product_id": card.pk,
        "title": f"{bank_name} {card.name}".strip(),
        "bank_id": card.bank_id,
        "bank_name": bank_name,
        "is_islamic": bool(card.is_islamic),
        "url_path": url_path,
        "sections": sections,
    }


def build_deposit_document(product):
    bank_name = product.bank.name if product.bank_id else (product.institution_name or "")
    rate_word = "expected profit" if product.is_islamic else "interest"
    rate_lines = []
    rates = list(product.rates.all()[:50]) if product.pk else []
    for rate in rates:
        tenure = f"{rate.tenure_months_min} months"
        if rate.tenure_max:
            tenure += f" to {rate.tenure_max} months"
        rate_lines.append(
            f"Tenure {tenure}: {rate_word} rate {rate.rate_min}%"
            + (f" to {rate.rate_max}%" if rate.rate_max != rate.rate_min else "")
            + (" (derived from published maturity table)" if rate.is_derived else "")
        )
    sections = _collect(
        _section(
            "overview",
            "Product",
            f"{product.name} deposit ({product.kind}) from {bank_name}"
            + (" (Islamic / Shariah-compliant)" if product.is_islamic else "")
            + (
                " — government benchmark (Sanchayapatra), not a bank product"
                if getattr(product, "is_benchmark", False)
                else ""
            ),
        ),
        _section("rates", f"Published {rate_word} rates", "; ".join(rate_lines)),
        _section("amounts", "Minimum amount (BDT)", product.min_amount),
        _section("amounts", "Maximum amount (BDT)", product.max_amount),
        _section("amounts", "Minimum instalment (BDT)", product.min_instalment),
        _section("source", "Published source", getattr(product, "source_url", "")),
    )
    return {
        "product_type": "deposit",
        "product_id": product.pk,
        "title": f"{bank_name} {product.name}".strip(),
        "bank_id": product.bank_id,
        "bank_name": bank_name,
        "is_islamic": bool(product.is_islamic),
        "url_path": f"/deposits/{product.slug}" if product.slug else "/deposits",
        "sections": sections,
    }


def build_loan_document(product):
    bank_name = product.bank.name if product.bank_id else (product.institution_name or "")
    rate_word = "expected profit" if product.is_islamic else "interest"
    band = None
    if product.rate_min is not None or product.rate_max is not None:
        band = f"{product.rate_min}% to {product.rate_max}% (published rate band)"
    sections = _collect(
        _section(
            "overview",
            "Product",
            f"{product.name} loan ({product.loan_type}) from {bank_name}"
            + (" (Islamic / Shariah-compliant)" if product.is_islamic else ""),
        ),
        _section("rates", f"Published {rate_word} rate band", band),
        _section("rates", "How the rate is set", product.rate_basis_text),
        _section("amounts", "Minimum amount (BDT)", product.amount_min_bdt),
        _section("amounts", "Maximum amount (BDT)", product.amount_max_bdt),
        _section(
            "tenure",
            "Tenure (months)",
            (
                f"{product.tenure_min_months} to {product.tenure_max_months}"
                if product.tenure_min_months or product.tenure_max_months
                else None
            ),
        ),
        _section("fees", "Processing fee (%)", product.processing_fee_percent),
        _section("fees", "Processing fee notes", product.processing_fee_notes),
        _section("source", "Published source", getattr(product, "source_url", "")),
    )
    return {
        "product_type": "loan",
        "product_id": product.pk,
        "title": f"{bank_name} {product.name}".strip(),
        "bank_id": product.bank_id,
        "bank_name": bank_name,
        "is_islamic": bool(product.is_islamic),
        "url_path": f"/loans/{product.slug}" if product.slug else "/loans",
        "sections": sections,
    }


def build_account_document(product):
    bank_name = product.bank.name if product.bank_id else ""
    rate_word = "expected profit" if product.is_islamic else "interest"
    sections = _collect(
        _section(
            "overview",
            "Product",
            f"{product.name} account ({product.account_type}) from {bank_name}"
            + (" (Islamic / Shariah-compliant)" if product.is_islamic else ""),
        ),
        _section("rates", f"Published {rate_word} rate slabs", product.rate_slabs),
        _section("rates", "Rate conditions", product.rate_conditions_text),
        _section("amounts", "Minimum balance to earn (BDT)", product.min_balance_to_earn),
        _section("source", "Published source", getattr(product, "source_url", "")),
    )
    return {
        "product_type": "account",
        "product_id": product.pk,
        "title": f"{bank_name} {product.name}".strip(),
        "bank_id": product.bank_id,
        "bank_name": bank_name,
        "is_islamic": bool(product.is_islamic),
        "url_path": f"/accounts/{product.slug}" if product.slug else "/accounts",
        "sections": sections,
    }


BUILDERS = {
    "credit_card": ("credit_cards", "CreditCard", build_credit_card_document),
    "deposit": ("deposits", "DepositProduct", build_deposit_document),
    "loan": ("loans", "LoanProduct", build_loan_document),
    "account": ("bank_accounts", "AccountProduct", build_account_document),
}


def build_document_for(product_type, product_id):
    """Load one public product and render its document dict (or None)."""
    from django.apps import apps

    spec = BUILDERS.get(product_type)
    if spec is None:
        return None
    app_label, model_name, builder = spec
    model = apps.get_model(app_label, model_name)
    queryset = (
        model.objects.public()
        if hasattr(model.objects, "public")
        else model.objects.all()
    )
    obj = queryset.filter(pk=product_id).first()
    if obj is None:
        return None
    return builder(obj)


def iter_public_documents(product_type=None, limit=None):
    """Yield document dicts for every public product of the given type(s)."""
    from django.apps import apps

    types = [product_type] if product_type else list(BUILDERS)
    for ptype in types:
        app_label, model_name, builder = BUILDERS[ptype]
        model = apps.get_model(app_label, model_name)
        queryset = (
            model.objects.public()
            if hasattr(model.objects, "public")
            else model.objects.all()
        )
        if ptype == "credit_card":
            queryset = queryset.select_related("bank")
        if limit:
            queryset = queryset[:limit]
        for obj in queryset:
            yield builder(obj)


def canonical_text(sections):
    """Flatten sections to the canonical document text (hash input)."""
    return "\n\n".join(f"## {field}\n{text}" for field, text in sections)
