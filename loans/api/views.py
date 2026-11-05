"""ViewSet for loan products: list/detail, field history, scenario costing.

The scenario endpoint is the heart of the vertical: given a loan type, an
amount and a tenure (plus optional monthly income), every public product
of that type is evaluated server-side with :mod:`loans.costs` at BOTH
ends of its effective rate band, and returned with eligibility flags.
Ineligible products are returned flagged — never silently dropped — so
the frontend can show them greyed with the reason.

Band resolution: a product's own published band wins (Annexure-A /
product page / SoC); otherwise the bank's Bangladesh Bank lending-chart
band for the mapped category is the provenance-labelled fallback.
Formula-priced products (spread over a deposit rate) have no band and
are returned with an explanatory note instead of an invented EMI.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from loans import costs
from loans.api.filters import LoanProductFilter
from loans.api.serializers import (
    LoanFieldHistorySerializer,
    LoanProductListSerializer,
    LoanProductSerializer,
    LoanScenarioInputSerializer,
    RegulatoryCapSerializer,
)
from loans.constants import CHART_CATEGORY_FOR_TYPE
from loans.models import LoanChartBand, LoanProduct, RegulatoryCap

SCENARIO_NOTES = [
    "EMI uses reducing-balance amortisation: monthly rate = annual rate / 12; "
    "totals come from a month-by-month schedule simulation (final month pays "
    "the remaining balance plus interest).",
    "Figures are shown at both ends of each product's published rate band — "
    "your actual rate is set by the lender within the band.",
    "Total cost = loan amount + total interest/profit + processing fee "
    "including 15% VAT on the fee. Where a bank publishes a processing-fee "
    "range, the highest published percentage is used.",
    "Supervision charges, where published, are shown separately and are NOT "
    "included in total cost.",
    "BHBFC products use simple interest (flagged per product), unlike the "
    "amortising convention used by banks.",
    "Eligibility flags are estimates from published criteria only — the "
    "lender makes the final decision after CIB checks and document "
    "verification.",
]


#: Sentinel distinguishing "resolve the unsecured ceiling from config"
#: from "the caller already resolved it (possibly to None)".
_UNSET = object()


def preload_chart_bands(products):
    """Load every BB chart band the products could fall back to, in ONE query.

    Returns ``(by_bank, by_institution)``: ``{(bank_id, category): band}``
    and ``{(institution_name, category): band}`` for bank-less rows. The
    chart band table has unique (bank, category) / (institution,
    category) constraints, so a dict lookup is exactly equivalent to the
    per-product filtered query in :func:`chart_band_for`.
    """
    categories = {CHART_CATEGORY_FOR_TYPE.get(p.loan_type) for p in products}
    categories.discard(None)
    by_bank, by_institution = {}, {}
    if categories:
        for band in LoanChartBand.objects.filter(category__in=categories):
            if band.bank_id is not None:
                by_bank[(band.bank_id, band.category)] = band
            elif band.institution_name:
                by_institution[(band.institution_name, band.category)] = band
    return by_bank, by_institution


def chart_band_for(product, chart_bands=None):
    """The BB lending-chart fallback band for a product, or None.

    ``chart_bands`` is the preloaded pair from :func:`preload_chart_bands`
    (the scenario path); without it the band is queried per product.
    """
    category = CHART_CATEGORY_FOR_TYPE.get(product.loan_type)
    if category is None:
        return None
    if chart_bands is not None:
        by_bank, by_institution = chart_bands
        if product.bank_id:
            return by_bank.get((product.bank_id, category))
        if product.institution_name:
            return by_institution.get((product.institution_name, category))
        return None
    qs = LoanChartBand.objects.filter(category=category)
    if product.bank_id:
        return qs.filter(bank_id=product.bank_id).first()
    if product.institution_name:
        return qs.filter(
            bank__isnull=True, institution_name=product.institution_name
        ).first()
    return None


def effective_band(product, chart_bands=None):
    """(min, max, source, category) for a product, or None if no band exists.

    ``category`` is the BB chart category a chart-sourced band came from
    — it matters because the chart has no car column: a car loan's
    fallback band is the bank's blended CONSUMER CREDIT band, and the
    payload must say so rather than present it as a car band. It is None
    for a product's own non-chart band.
    """
    if product.rate_min is not None and product.rate_max is not None:
        category = None
        if product.rate_source == "bb_chart":
            category = CHART_CATEGORY_FOR_TYPE.get(product.loan_type)
        return product.rate_min, product.rate_max, product.rate_source, category
    band = chart_band_for(product, chart_bands=chart_bands)
    if band is not None:
        return band.rate_min, band.rate_max, "bb_chart", band.category
    return None


def _income_check(product, monthly_income, segment=None):
    """Income check against published segment minima -> (flag, warning).

    With an explicit ``segment`` the check is against that segment's
    published minimum (no minimum published for the segment -> no
    finding). Without a segment: income below EVERY published minimum is
    a hard flag; income meeting some segments' minima but not others is
    a warning naming both sides — the scenario does not know the
    applicant's segment, so silently comparing against the lowest
    minimum alone would overstate eligibility. Reasons always quote the
    published figures — the check is an estimate from published
    criteria, nothing more.
    """
    minima = {
        seg: value
        for seg, value in (product.min_income_by_segment or {}).items()
        if isinstance(value, (int, float)) and value
    }
    if not minima:
        return None, None
    figures = ", ".join(
        f"{seg} Tk {value:,}/month" for seg, value in sorted(minima.items())
    )

    if segment:
        required = minima.get(segment)
        if required is None or monthly_income >= required:
            return None, None
        return {
            "code": "income_below_minimum",
            "message": (
                f"Your income (Tk {monthly_income:,}) is below this product's "
                f"published minimum for {segment} (Tk {required:,}). "
                f"Published minima: {figures} ({product.income_metric} income)."
            ),
        }, None

    met = sorted(seg for seg, value in minima.items() if monthly_income >= value)
    unmet = sorted(seg for seg, value in minima.items() if monthly_income < value)
    if not unmet:
        return None, None
    if not met:
        lowest_segment, lowest_value = min(minima.items(), key=lambda item: item[1])
        return {
            "code": "income_below_minimum",
            "message": (
                f"Your income (Tk {monthly_income:,}) is below this product's "
                f"lowest published minimum ({lowest_segment} Tk {lowest_value:,}). "
                f"Published minima: {figures} ({product.income_metric} income)."
            ),
        }, None
    met_text = ", ".join(f"{seg} (Tk {minima[seg]:,})" for seg in met)
    unmet_text = ", ".join(f"{seg} (Tk {minima[seg]:,})" for seg in unmet)
    return None, {
        "code": "income_segment_dependent",
        "message": (
            f"Meets the published minimum for {met_text}; below the "
            f"published minimum for {unmet_text} "
            f"({product.income_metric} income)."
        ),
    }


def _unsecured_warning(product, amount, unsecured_ceiling=_UNSET):
    """Warn when the scenario amount outruns unsecured lending limits.

    ``unsecured_ceiling`` is the dated BB cap on unsecured personal
    loans, resolved once per request by the scenario view; the sentinel
    default resolves it here for direct callers.
    """
    if product.loan_type != "personal":
        return None
    if product.unsecured_max_bdt and amount > product.unsecured_max_bdt:
        return {
            "code": "security_may_be_required",
            "message": (
                f"Above Tk {product.unsecured_max_bdt:,} this product requires "
                "security/collateral as published by the lender."
            ),
        }
    if unsecured_ceiling is _UNSET:
        rule = RegulatoryCap.latest("personal_loan_ceiling")
        unsecured_ceiling = (rule.params or {}).get("unsecured_max_bdt") if rule else None
    # Below this point the loan is unsecured at this amount: either it is
    # within the product's own published unsecured limit, or the product
    # publishes no limit and no security. The BB ceiling still applies —
    # even when the product publishes a HIGHER unsecured limit than the
    # regulator's cap (e.g. Pubali's Tk 20 lakh for its own salary-
    # account holders, against the Tk 10 lakh ceiling).
    if unsecured_ceiling and amount > unsecured_ceiling and not product.secured_by:
        return {
            "code": "security_may_be_required",
            "message": (
                f"Bangladesh Bank caps unsecured personal loans at Tk {unsecured_ceiling:,}; "
                "above that, lenders generally require security."
            ),
        }
    return None


def _eligibility_flags(product, amount, tenure_months):
    """Hard flags: published amount/tenure bounds (income is separate)."""
    flags = []
    # Messages are lambdas: the bounds they quote may be None when the
    # bound is not violated, and f-strings would format eagerly.
    bounds = [
        (
            product.amount_min_bdt is not None and amount < product.amount_min_bdt,
            "amount_below_min",
            lambda: f"Amount Tk {amount:,} is below this product's published "
            f"minimum of Tk {product.amount_min_bdt:,}.",
        ),
        (
            product.amount_max_bdt is not None and amount > product.amount_max_bdt,
            "amount_above_max",
            lambda: f"Amount Tk {amount:,} exceeds this product's published "
            f"maximum of Tk {product.amount_max_bdt:,}.",
        ),
        (
            product.tenure_min_months is not None
            and tenure_months < product.tenure_min_months,
            "tenure_below_min",
            lambda: f"Tenure {tenure_months} months is below this product's "
            f"published minimum of {product.tenure_min_months} months.",
        ),
        (
            product.tenure_max_months is not None
            and tenure_months > product.tenure_max_months,
            "tenure_above_max",
            lambda: f"Tenure {tenure_months} months exceeds this product's "
            f"published maximum of {product.tenure_max_months} months.",
        ),
    ]
    for violated, code, message in bounds:
        if violated:
            flags.append({"code": code, "message": message()})
    return flags


def evaluate_product(
    product,
    amount,
    tenure_months,
    monthly_income,
    segment=None,
    chart_bands=None,
    unsecured_ceiling=_UNSET,
):
    """Cost one product for the scenario at both band ends + flags.

    ``chart_bands`` / ``unsecured_ceiling`` are the request-level
    preloads from the scenario view (N+1 guards); direct callers may
    omit them and pay the per-product queries instead.
    """
    flags = _eligibility_flags(product, amount, tenure_months)
    warnings = []
    if monthly_income:
        income_flag, income_warning = _income_check(
            product, monthly_income, segment=segment
        )
        if income_flag:
            flags.append(income_flag)
        if income_warning:
            warnings.append(income_warning)
    warning = _unsecured_warning(product, amount, unsecured_ceiling=unsecured_ceiling)
    if warning:
        warnings.append(warning)

    band = effective_band(product, chart_bands=chart_bands)
    fee = costs.processing_fee(product, amount)
    fee_incl_vat = costs.fee_with_vat(fee)
    supervision = None
    if product.supervision_charge_percent is not None:
        from decimal import Decimal

        supervision = costs.money(
            Decimal(str(amount)) * product.supervision_charge_percent / Decimal("100")
        )

    result = {
        "product": None,  # filled by the caller (serializer needs context)
        "eligible": not flags,
        "flags": flags,
        "warnings": warnings,
        "band": None,
        "rate_label": product.rate_label,
        "uses_simple_interest": product.uses_simple_interest,
        "processing_fee": fee,
        "processing_fee_incl_vat": fee_incl_vat,
        "supervision_charge": supervision,
        "at_min_rate": None,
        "at_max_rate": None,
        "note": None,
    }
    if band is None:
        if product.spread_over_deposit_rate is not None:
            result["note"] = (
                "Priced by formula: deposit rate + "
                f"{product.spread_over_deposit_rate}% spread — no fixed band "
                "is published, so no EMI is shown."
            )
        else:
            result["note"] = (
                "This lender does not publish a usable rate band for this "
                "product, so no EMI is shown."
            )
        return result

    rate_min, rate_max, source, category = band
    result["band"] = {
        "min": rate_min,
        "max": rate_max,
        "source": source,
        "category": category,
    }
    for key, rate in (("at_min_rate", rate_min), ("at_max_rate", rate_max)):
        emi, total_interest, total_repayable = costs.amortisation_totals(
            amount, rate, tenure_months, simple_interest=product.uses_simple_interest
        )
        total_cost = total_repayable + (fee_incl_vat or 0)
        result[key] = {
            "rate": rate,
            "emi": emi,
            # Neutral key: for Islamic (HPSM/Bai-Muajjal) products this
            # figure is expected profit, never "interest".
            "total_interest_or_profit": total_interest,
            "total_cost": costs.money(total_cost),
        }
    return result


class LoanProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only API for loan products."""

    queryset = LoanProduct.objects.select_related("bank").public()
    serializer_class = LoanProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = LoanProductFilter
    search_fields = ["name", "bank__name", "institution_name"]
    ordering_fields = ["name", "created"]
    ordering = ["bank__name", "institution_name", "name"]

    def get_serializer_class(self):
        if self.action == "list":
            return LoanProductListSerializer
        return LoanProductSerializer

    @extend_schema(responses=LoanFieldHistorySerializer(many=True))
    @action(detail=True, methods=["get"], url_path="field-history")
    def field_history(self, request, *args, **kwargs):
        """Bounded, newest-first field history.

        Public (redesign decision D1), mirroring the credit-card endpoint.
        """
        product = self.get_object()
        history = product.field_history.all()[:100]
        return Response(LoanFieldHistorySerializer(history, many=True).data)

    @extend_schema(responses=RegulatoryCapSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="regulatory-caps")
    def regulatory_caps(self, request):
        """The latest dated regulatory ceiling per key (context for the FE)."""
        keys = (
            RegulatoryCap.objects.order_by("key", "-effective_from")
            .values_list("key", flat=True)
            .distinct()
        )
        latest = [RegulatoryCap.latest(key) for key in keys]
        return Response(RegulatoryCapSerializer([r for r in latest if r], many=True).data)

    @extend_schema(request=LoanScenarioInputSerializer)
    @action(detail=False, methods=["post"], url_path="scenario")
    def scenario(self, request):
        """Cost every public product of a type at both band ends."""
        serializer = LoanScenarioInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        products = self.get_queryset().filter(loan_type=data["loan_type"])
        if data.get("islamic_only"):
            products = products.filter(is_islamic=True)
        if data.get("bank"):
            products = products.filter(bank_id=data["bank"])
        products = list(products)

        # N+1 guards: preload every chart band these products could fall
        # back to in ONE query (shared with the product serializer via
        # the request), and resolve the personal-loan unsecured ceiling
        # once for the whole request instead of once per product.
        chart_bands = preload_chart_bands(products)
        request._loan_chart_bands_preload = chart_bands
        ceiling_rule = RegulatoryCap.latest("personal_loan_ceiling")
        unsecured_ceiling = (
            (ceiling_rule.params or {}).get("unsecured_max_bdt") if ceiling_rule else None
        )

        results = []
        for product in products:
            evaluated = evaluate_product(
                product,
                data["amount"],
                data["tenure_months"],
                data.get("monthly_income"),
                segment=data.get("segment"),
                chart_bands=chart_bands,
                unsecured_ceiling=unsecured_ceiling,
            )
            evaluated["product"] = LoanProductListSerializer(
                product, context={"request": request}
            ).data
            results.append(evaluated)

        def sort_key(item):
            if item["eligible"] and item["at_min_rate"]:
                return (0, item["at_min_rate"]["total_cost"])
            if item["eligible"]:
                return (1, 0)
            return (2, 0)

        results.sort(key=sort_key)
        return Response(
            {
                "loan_type": data["loan_type"],
                "amount": data["amount"],
                "tenure_months": data["tenure_months"],
                "monthly_income": data.get("monthly_income"),
                "segment": data.get("segment"),
                "results": results,
                "notes": SCENARIO_NOTES,
            }
        )
