"""Advisor tool layer — framework-free, typed, read-only (plan §7.1).

These are plain Python functions with Pydantic v2 input/output models.
LangGraph (``advisor.graph``) and the MCP server (``advisor.mcp_server``)
are both thin adapters over this module; neither contains business logic.

Rules enforced here, in code rather than in a prompt:

- **Read-only only.** Every registered tool carries the ``read-only``
  scope tag. There is deliberately no write or external-action tool; the
  one state change a user can make (save to shortlist) happens through
  the existing saved API on an explicit UI click, never via a tool.
- **Published figures only.** Outputs are built from the public
  querysets (``.public()`` = active + verified), so the model can only
  quote figures that are already public on the site.
- **Eligibility inputs are never persisted.** ``check_eligibility``
  delegates to :mod:`credit_cards.eligibility` in memory and stores
  nothing (the caller in ``graph.py`` hashes args for the trace and
  discards the values).
- **Loans are bands.** ``search_products`` returns ``rate_min`` /
  ``rate_max`` for loans and deposits — never a single invented point.
- **Islamic terminology.** Islamic products expose their cost under a
  profit label (``rate_kind="expected_profit"``), never as interest.
"""

import hashlib
import json
import time
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# Shared output shapes
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """A pointer from an answer back to a live product page."""

    product_type: str  # cards | deposits | loans | accounts
    product_id: int | None = None
    slug: str | None = None
    label: str
    url_path: str
    field: str | None = None


class CardSummary(BaseModel):
    id: int
    name: str
    bank_name: str
    annual_fee_bdt: str | None = None
    # None when the card publishes no APR (e.g. Islamic cards) — callers
    # must say "not published / not applicable", never 0%.
    apr_percent: str | None = None
    is_islamic: bool = False
    lounge_summary: str = ""
    min_monthly_income_bdt: str | None = None
    creditmate_score: float | None = None


class SuggestedAction(BaseModel):
    """A proposed — never executed — action for the user to confirm."""

    kind: str  # save_to_shortlist | open_compare | open_eligibility
    label: str
    product_type: str | None = None
    product_id: int | None = None
    slug: str | None = None


class AdvisorAnswer(BaseModel):
    """The validated structured output of one advisor run (plan §7.1)."""

    answer_markdown: str
    cited_product_ids: list[int] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    is_fallback: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _money(value):
    return None if value is None else str(value)


def _card_path(card):
    from django.utils.text import slugify

    return f"/card/{slugify(card.bank.name)}/{slugify(card.name)}"


def card_summary(card):
    try:
        from credit_cards.scoring import evaluate_score

        score = evaluate_score(card)["score"]
    except Exception:
        score = None
    return CardSummary(
        id=card.id,
        name=card.name,
        bank_name=card.bank.name,
        annual_fee_bdt=_money(card.annual_fee),
        apr_percent=_money(card.interest_rate_apr),
        is_islamic=card.is_islamic,
        lounge_summary=card.lounge_access_summary,
        min_monthly_income_bdt=_money(card.min_monthly_income),
        creditmate_score=float(score) if score is not None else None,
    )


def card_citation(card, field=None):
    return Citation(
        product_type="cards",
        product_id=card.id,
        label=f"{card.bank.name} {card.name}",
        url_path=_card_path(card),
        field=field,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SearchCardsInput(BaseModel):
    query: str = ""
    bank_name: str | None = None
    islamic_only: bool = False
    conventional_only: bool = False
    max_annual_fee_bdt: Decimal | None = None
    lounge_required: bool = False
    limit: int = Field(default=5, ge=1, le=10)


class SearchCardsOutput(BaseModel):
    cards: list[CardSummary] = Field(default_factory=list)
    total_matching: int = 0


def search_cards(inp: SearchCardsInput) -> SearchCardsOutput:
    """Search the public card catalogue with simple structured filters."""
    from django.db.models import Q

    from credit_cards.models import CreditCard

    qs = CreditCard.objects.public().select_related("bank").order_by("bank__name", "name")
    if inp.query:
        # Callers (the advisor, the fallback) pass natural-language text,
        # so match on any significant token rather than the whole string
        # as one substring — a full sentence would match nothing.
        stopwords = {
            "the",
            "a",
            "an",
            "for",
            "me",
            "show",
            "best",
            "card",
            "cards",
            "please",
            "want",
            "need",
            "with",
            "and",
            "or",
            "of",
            "to",
            "i",
        }
        tokens = [
            t.strip(".,!?")
            for t in inp.query.lower().split()
            if len(t.strip(".,!?")) > 2 and t.strip(".,!?") not in stopwords
        ] or [inp.query]
        token_q = Q()
        for token in tokens:
            token_q |= (
                Q(name__icontains=token)
                | Q(bank__name__icontains=token)
                | Q(reward_program_name__icontains=token)
            )
        qs = qs.filter(token_q)
    if inp.bank_name:
        qs = qs.filter(bank__name__icontains=inp.bank_name)
    if inp.islamic_only:
        qs = qs.filter(is_islamic=True)
    if inp.conventional_only:
        qs = qs.filter(is_islamic=False)
    if inp.max_annual_fee_bdt is not None:
        qs = qs.filter(annual_fee__lte=inp.max_annual_fee_bdt)
    total = qs.count()
    cards = list(qs[: inp.limit * 3])
    if inp.lounge_required:
        cards = [c for c in cards if c.has_lounge_access]
    return SearchCardsOutput(
        cards=[card_summary(c) for c in cards[: inp.limit]],
        total_matching=total,
    )


class CardDetailInput(BaseModel):
    card_id: int


class CardDetailOutput(BaseModel):
    card: CardSummary
    cash_advance_fee: str = ""
    late_payment_fee: str = ""
    supplementary_card_fee: str = ""
    foreign_transaction_fee: str = ""
    reward_program_name: str = ""
    source_url: str = ""


def get_card_detail(inp: CardDetailInput) -> CardDetailOutput:
    from credit_cards.models import CreditCard

    card = CreditCard.objects.public().select_related("bank").get(pk=inp.card_id)
    return CardDetailOutput(
        card=card_summary(card),
        cash_advance_fee=card.cash_advance_fee or "",
        late_payment_fee=card.late_payment_fee or "",
        supplementary_card_fee=card.supplementary_card_fee or "",
        foreign_transaction_fee=card.foreign_transaction_fee or "",
        reward_program_name=card.reward_program_name or "",
        source_url=card.source_url or "",
    )


class CompareCardsInput(BaseModel):
    card_ids: list[int] = Field(min_length=2, max_length=4)


class CompareCardsOutput(BaseModel):
    cards: list[CardSummary] = Field(default_factory=list)
    differing_fields: list[str] = Field(default_factory=list)


_COMPARE_FIELDS = (
    "annual_fee_bdt",
    "apr_percent",
    "is_islamic",
    "lounge_summary",
    "min_monthly_income_bdt",
)


def compare_cards(inp: CompareCardsInput) -> CompareCardsOutput:
    """Compare 2–4 public cards; report which published fields differ."""
    from credit_cards.models import CreditCard

    by_id = {
        c.id: c
        for c in CreditCard.objects.public()
        .select_related("bank")
        .filter(pk__in=inp.card_ids)
    }
    summaries = [card_summary(by_id[i]) for i in inp.card_ids if i in by_id]
    differing = []
    for field_name in _COMPARE_FIELDS:
        values = {getattr(s, field_name) for s in summaries}
        if len(values) > 1:
            differing.append(field_name)
    return CompareCardsOutput(cards=summaries, differing_fields=differing)


class EligibilityInput(BaseModel):
    monthly_income_bdt: Decimal = Field(ge=0)
    employment_type: str = "salaried"  # salaried | self_employed | other
    has_tin: bool | None = None
    cib_status: str = "unknown"  # clean | has_issues | unknown
    islamic_only: bool = False
    limit: int = Field(default=10, ge=1, le=25)


class EligibilityResultItem(BaseModel):
    card: CardSummary
    # Exactly the engine's vocabulary: eligible | likely | unknown | not_yet.
    verdict: str
    reasons: list[str] = Field(default_factory=list)


class EligibilityOutput(BaseModel):
    results: list[EligibilityResultItem] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    disclaimer: str = ""


def check_eligibility(inp: EligibilityInput) -> EligibilityOutput:
    """Per-card eligibility estimates. INPUTS ARE NEVER PERSISTED."""
    from credit_cards.eligibility import (
        DISCLAIMER,
        VERDICT_ORDER,
        evaluate_card,
        profile_notes,
    )
    from credit_cards.models import CreditCard

    cards = CreditCard.objects.public().select_related("bank")
    if inp.islamic_only:
        cards = cards.filter(is_islamic=True)
    evaluated = []
    counts: dict[str, int] = {}
    for card in cards:
        verdict, reasons = evaluate_card(
            card.min_monthly_income, inp.monthly_income_bdt, inp.cib_status
        )
        counts[verdict] = counts.get(verdict, 0) + 1
        evaluated.append((VERDICT_ORDER[verdict], card, verdict, reasons))
    evaluated.sort(key=lambda item: (item[0], item[1].bank.name, item[1].name))
    return EligibilityOutput(
        results=[
            EligibilityResultItem(
                card=card_summary(card), verdict=verdict, reasons=reasons
            )
            for _, card, verdict, reasons in evaluated[: inp.limit]
        ],
        counts=counts,
        notes=profile_notes(inp.employment_type, None, inp.has_tin),
        disclaimer=DISCLAIMER,
    )


class CalculatorInput(BaseModel):
    mode: str  # emi | payoff
    principal_bdt: Decimal = Field(gt=0)
    # Required for payoff, and for EMI when the card publishes no APR.
    annual_rate_percent: Decimal | None = None
    card_id: int | None = None
    months: int | None = Field(default=None, gt=0, le=360)  # EMI tenure
    monthly_payment_bdt: Decimal | None = Field(default=None, gt=0)  # payoff


class CalculatorOutput(BaseModel):
    mode: str
    rate_percent_used: str | None = None
    monthly_emi_bdt: str | None = None
    months_to_clear: int | None = None
    total_interest_bdt: str | None = None
    total_payable_bdt: str | None = None
    warning: str | None = None


def _payoff(balance: Decimal, apr_percent: Decimal, payment: Decimal):
    """Months to clear ``balance`` paying ``payment``/month (FE-mirrored)."""
    from loans.costs import money

    monthly_rate = apr_percent / Decimal("100") / Decimal("12")
    first_interest = money(balance * monthly_rate)
    if payment <= first_interest:
        return (
            None,
            None,
            (
                "The monthly payment does not cover the first month's "
                f"interest of BDT {first_interest}; the balance would not "
                "come down. Increase the monthly payment."
            ),
        )
    months = 0
    total_interest = Decimal("0")
    remaining = balance
    while remaining > 0 and months < 1200:
        interest = money(remaining * monthly_rate)
        total_interest += interest
        due = remaining + interest
        actual = min(payment, due)
        remaining = money(due - actual)
        months += 1
    return months, money(total_interest), None


def calculate_emi_or_payoff(inp: CalculatorInput) -> CalculatorOutput:
    """EMI via ``loans.costs``; payoff via month-by-month simulation.

    Rate rule (existing product behaviour): a card's published APR is
    used when ``card_id`` is given; cards that publish no APR (including
    Islamic cards) NEVER fall back to 0% — a custom rate is required.
    """
    from loans.costs import amortisation_totals

    rate = inp.annual_rate_percent
    if inp.card_id is not None:
        from credit_cards.models import CreditCard

        card = CreditCard.objects.public().get(pk=inp.card_id)
        if card.interest_rate_apr is not None:
            rate = card.interest_rate_apr
    if rate is None:
        raise ValueError(
            "No published APR for this card and no custom rate given — "
            "a custom annual rate is required; a missing APR is never "
            "treated as 0%."
        )
    if inp.mode == "emi":
        if not inp.months:
            raise ValueError("months (tenure) is required for an EMI calculation")
        emi, total_interest, total = amortisation_totals(
            inp.principal_bdt, rate, inp.months
        )
        return CalculatorOutput(
            mode="emi",
            rate_percent_used=str(rate),
            monthly_emi_bdt=str(emi),
            total_interest_bdt=str(total_interest),
            total_payable_bdt=str(total),
        )
    if inp.mode == "payoff":
        if not inp.monthly_payment_bdt:
            raise ValueError("monthly_payment_bdt is required for a payoff calculation")
        months, total_interest, warning = _payoff(
            inp.principal_bdt, rate, inp.monthly_payment_bdt
        )
        return CalculatorOutput(
            mode="payoff",
            rate_percent_used=str(rate),
            months_to_clear=months,
            total_interest_bdt=(
                str(total_interest) if total_interest is not None else None
            ),
            warning=warning,
        )
    raise ValueError("mode must be 'emi' or 'payoff'")


class SearchProductsInput(BaseModel):
    product_type: str  # deposits | loans | accounts
    query: str = ""
    islamic_only: bool = False
    limit: int = Field(default=5, ge=1, le=10)


class ProductSummary(BaseModel):
    id: int
    product_type: str
    name: str
    institution_name: str = ""
    is_islamic: bool = False
    # Bands, never a point. rate_kind says whether the band is interest
    # or expected profit (Islamic products).
    rate_min_percent: str | None = None
    rate_max_percent: str | None = None
    rate_kind: str | None = None
    slug: str | None = None


class SearchProductsOutput(BaseModel):
    products: list[ProductSummary] = Field(default_factory=list)


def _band(product, rate_rows):
    """(min, max, kind) from published rate rows, or (None, None, None)."""
    if not rate_rows:
        return None, None, None
    low = min(r.rate_min for r in rate_rows)
    high = max(r.rate_max for r in rate_rows)
    kind = getattr(product, "rate_type", None) or "interest"
    if getattr(product, "is_islamic", False):
        kind = "expected_profit"
    return str(low), str(high), kind


def search_products(inp: SearchProductsInput) -> SearchProductsOutput:
    """Search deposits / loans / accounts public listings (bands only)."""
    from django.db.models import Q

    products: list[ProductSummary] = []
    if inp.product_type == "deposits":
        from deposits.models import DepositProduct

        qs = DepositProduct.objects.public().prefetch_related("rates")
        if inp.query:
            qs = qs.filter(Q(name__icontains=inp.query))
        if inp.islamic_only:
            qs = qs.filter(is_islamic=True)
        for p in qs[: inp.limit]:
            low, high, kind = _band(p, list(p.rates.all()))
            products.append(
                ProductSummary(
                    id=p.id,
                    product_type="deposits",
                    name=p.name,
                    institution_name=p.institution_name
                    or (p.bank.name if p.bank else ""),
                    is_islamic=p.is_islamic,
                    rate_min_percent=low,
                    rate_max_percent=high,
                    rate_kind=kind,
                    slug=p.slug or None,
                )
            )
    elif inp.product_type == "loans":
        from loans.models import LoanProduct

        qs = LoanProduct.objects.public()
        if inp.query:
            qs = qs.filter(Q(name__icontains=inp.query))
        if inp.islamic_only:
            qs = qs.filter(is_islamic=True)
        for p in qs[: inp.limit]:
            # The band lives on the product itself (rate_min/rate_max);
            # it is returned as a band, never collapsed to a point.
            products.append(
                ProductSummary(
                    id=p.id,
                    product_type="loans",
                    name=p.name,
                    institution_name=p.lender_display_name,
                    is_islamic=p.is_islamic,
                    rate_min_percent=_money(p.rate_min),
                    rate_max_percent=_money(p.rate_max),
                    rate_kind=p.rate_label,
                    slug=p.slug or None,
                )
            )
    elif inp.product_type == "accounts":
        from bank_accounts.models import AccountProduct

        qs = AccountProduct.objects.public().select_related("bank")
        if inp.query:
            qs = qs.filter(Q(name__icontains=inp.query))
        if inp.islamic_only:
            qs = qs.filter(is_islamic=True)
        for p in qs[: inp.limit]:
            products.append(
                ProductSummary(
                    id=p.id,
                    product_type="accounts",
                    name=p.name,
                    institution_name=p.bank.name if p.bank else "",
                    is_islamic=p.is_islamic,
                    slug=p.slug or None,
                )
            )
    else:
        raise ValueError("product_type must be deposits, loans or accounts")
    return SearchProductsOutput(products=products)


class RetrieveGroundingInput(BaseModel):
    query: str
    product_type: str | None = None
    limit: int = Field(default=5, ge=1, le=10)


class GroundingChunk(BaseModel):
    text: str
    citation: Citation | None = None
    score: float | None = None


class RetrieveGroundingOutput(BaseModel):
    chunks: list[GroundingChunk] = Field(default_factory=list)
    available: bool = False


def retrieve_grounding(inp: RetrieveGroundingInput) -> RetrieveGroundingOutput:
    """Semantic grounding from the `retrieval` app, when it exists.

    The retrieval app lands in a parallel branch (Stream C). Until it is
    merged this tool returns ``available=False`` with no chunks — the
    advisor then answers from the structured catalogue tools only, which
    is the designed degradation, not an error.
    """
    try:
        from retrieval.services import search as retrieval_search
    except Exception:
        return RetrieveGroundingOutput(chunks=[], available=False)
    try:
        results = retrieval_search(
            inp.query, product_type=inp.product_type, limit=inp.limit
        )
    except Exception:
        return RetrieveGroundingOutput(chunks=[], available=False)
    chunks = []
    for item in results or []:
        citation = None
        raw_citation = getattr(item, "citation", None) or (
            item.get("citation") if isinstance(item, dict) else None
        )
        if raw_citation:
            try:
                citation = Citation.model_validate(raw_citation)
            except ValidationError:
                citation = None
        text = getattr(item, "text", None) or (
            item.get("text", "") if isinstance(item, dict) else ""
        )
        score = getattr(item, "score", None) or (
            item.get("score") if isinstance(item, dict) else None
        )
        chunks.append(
            GroundingChunk(
                text=str(text),
                citation=citation,
                score=float(score) if score is not None else None,
            )
        )
    return RetrieveGroundingOutput(chunks=chunks, available=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

READ_ONLY = "read-only"


class ToolSpec(BaseModel):
    name: str
    description: str
    scope: str = READ_ONLY
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    class Config:
        arbitrary_types_allowed = True


TOOL_FUNCTIONS = {
    "search_cards": search_cards,
    "get_card_detail": get_card_detail,
    "compare_cards": compare_cards,
    "check_eligibility": check_eligibility,
    "calculate_emi_or_payoff": calculate_emi_or_payoff,
    "search_products": search_products,
    "retrieve_grounding": retrieve_grounding,
}

TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_cards": ToolSpec(
        name="search_cards",
        description="Search public credit cards by text/bank/fee/Islamic/lounge filters.",
        input_model=SearchCardsInput,
        output_model=SearchCardsOutput,
    ),
    "get_card_detail": ToolSpec(
        name="get_card_detail",
        description="Published fee/APR detail for one public card by id.",
        input_model=CardDetailInput,
        output_model=CardDetailOutput,
    ),
    "compare_cards": ToolSpec(
        name="compare_cards",
        description="Compare 2-4 public cards and list which published fields differ.",
        input_model=CompareCardsInput,
        output_model=CompareCardsOutput,
    ),
    "check_eligibility": ToolSpec(
        name="check_eligibility",
        description=(
            "Estimate per-card eligibility from income + CIB self-declaration "
            "using only published minimum incomes. Inputs are never stored."
        ),
        input_model=EligibilityInput,
        output_model=EligibilityOutput,
    ),
    "calculate_emi_or_payoff": ToolSpec(
        name="calculate_emi_or_payoff",
        description="EMI or balance-payoff maths at a published or custom rate.",
        input_model=CalculatorInput,
        output_model=CalculatorOutput,
    ),
    "search_products": ToolSpec(
        name="search_products",
        description="Search public deposits/loans/accounts; rates are bands.",
        input_model=SearchProductsInput,
        output_model=SearchProductsOutput,
    ),
    "retrieve_grounding": ToolSpec(
        name="retrieve_grounding",
        description="Semantic grounding chunks with citations, when retrieval is enabled.",
        input_model=RetrieveGroundingInput,
        output_model=RetrieveGroundingOutput,
    ),
}


def args_hash(args: dict) -> str:
    """SHA-256 of tool args for the trace — values are never stored."""
    return hashlib.sha256(
        json.dumps(args, sort_keys=True, default=str).encode()
    ).hexdigest()


def run_tool(name: str, args: dict):
    """Validate args, run one registered read-only tool, return (output, latency_ms).

    Raises KeyError for unknown tools, pydantic ValidationError for bad
    args, and whatever the backing service raises — callers (graph) turn
    those into fallbacks, never into user-facing 500s.
    """
    spec = TOOL_REGISTRY[name]
    if spec.scope != READ_ONLY:  # defence in depth: no non-read-only tool may run
        raise PermissionError(f"tool {name} is not read-only")
    validated = spec.input_model.model_validate(args or {})
    started = time.perf_counter()
    output = TOOL_FUNCTIONS[name](validated)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return output, latency_ms


def citations_from_output(output) -> list[Citation]:
    """Best-effort citation extraction from any tool output."""
    citations: list[Citation] = []
    if isinstance(output, (SearchCardsOutput, CompareCardsOutput)):
        for summary in output.cards:
            from credit_cards.models import CreditCard

            card = CreditCard.objects.filter(pk=summary.id).select_related("bank").first()
            if card is not None:
                citations.append(card_citation(card))
    elif isinstance(output, EligibilityOutput):
        for item in output.results:
            from credit_cards.models import CreditCard

            card = (
                CreditCard.objects.filter(pk=item.card.id).select_related("bank").first()
            )
            if card is not None:
                citations.append(card_citation(card, field="min_monthly_income"))
    elif isinstance(output, SearchProductsOutput):
        paths = {
            "deposits": "/deposits/",
            "loans": "/loans/",
            "accounts": "/accounts/",
        }
        for p in output.products:
            if p.slug:
                citations.append(
                    Citation(
                        product_type=p.product_type,
                        product_id=p.id,
                        slug=p.slug,
                        label=f"{p.institution_name} {p.name}".strip(),
                        url_path=f"{paths[p.product_type]}{p.slug}",
                    )
                )
    elif isinstance(output, RetrieveGroundingOutput):
        citations.extend(c.citation for c in output.chunks if c.citation)
    return citations


FORBIDDEN_PHRASES = (
    "pre-approved",
    "pre approved",
    "guaranteed approval",
    "guaranteed to",
)


def contains_forbidden_phrase(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in FORBIDDEN_PHRASES)
