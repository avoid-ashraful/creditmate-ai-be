"""Serializers for the deposits API."""

from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from banks.api.serializers import BankSerializer
from deposits.models import DepositFieldHistory, DepositProduct, DepositRate


class DepositRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepositRate
        fields = [
            "id",
            "tenure_months_min",
            "tenure_months_max",
            "amount_min",
            "amount_max",
            "rate_min",
            "rate_max",
            "is_derived",
            "note",
        ]


def _headline_rate_cell(rates):
    """The rate cell a product's history sparkline follows.

    The most specific cell covering a 12-month horizon when one exists
    (the horizon households actually compare); otherwise the cell with
    the highest published top rate. Deterministic for a given rate set.
    """
    if not rates:
        return None
    covering = [
        r
        for r in rates
        if r.tenure_months_min <= 12
        and (r.tenure_months_max is None or r.tenure_months_max >= 12)
    ]
    if covering:
        return min(covering, key=lambda r: (r.tenure_span, r.amount_span))
    return max(rates, key=lambda r: (r.rate_max, -r.tenure_span))


def _normalise_rate(value):
    """Canonical string form of a rate value ("9.750" -> "9.75").

    History payloads store rates as written by their source while the
    live rate is a 3dp Decimal; normalising through Decimal keeps the
    series' equality checks and the client's parsing honest.
    """
    if value is None:
        return None
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except InvalidOperation:
        return None


def _rate_cell_value(payload):
    """The plottable value of a stored rate-cell payload: its top rate."""
    if not isinstance(payload, dict):
        return None
    return _normalise_rate(payload.get("rate_max"))


class DepositProductListSerializer(serializers.ModelSerializer):
    bank = BankSerializer(read_only=True)
    institution_display_name = serializers.CharField(read_only=True)
    rate_range = serializers.SerializerMethodField()
    rate_history = serializers.SerializerMethodField()

    class Meta:
        model = DepositProduct
        fields = [
            "id",
            "slug",
            "name",
            "kind",
            "bank",
            "institution_name",
            "institution_display_name",
            "institution_type",
            "rate_type",
            "is_islamic",
            "is_generic",
            "is_benchmark",
            "payout_style",
            "segment",
            "min_amount",
            "max_amount",
            "min_instalment",
            "max_instalment",
            "instalment_step",
            "tenures_months",
            "compounding",
            "rate_range",
            "rate_history",
            "source_url",
            "source_kind",
            "rate_effective_date",
            "verified_at",
        ]

    def get_rate_range(self, obj) -> dict | None:
        rates = list(obj.rates.all())
        if not rates:
            return None
        return {
            "min": str(min(r.rate_min for r in rates)),
            "max": str(max(r.rate_max for r in rates)),
        }

    def get_rate_history(self, obj) -> dict | None:
        """Compact published-rate history for the headline cell (Phase 4).

        Points are reconstructed from the product's real field-history
        rows for that cell — one point per recorded change (the value
        the cell stepped *to*, top of the published band), preceded by
        the value it stepped *from* when the oldest row records one, and
        closed with the cell's current value when history and the live
        rate disagree (e.g. a rate corrected without a history row).
        Nothing is interpolated and no point is invented: a product
        with no recorded changes gets just its current value, and the
        client renders a trend only from 3+ real points.

        Returns at most the last 6 points, oldest first.
        """
        cell = _headline_rate_cell(list(obj.rates.all()))
        if cell is None:
            return None
        field_name = f"rate_{cell.tenure_months_min}_{cell.tenure_months_max or 'open'}"
        rows = [
            row
            for row in obj.field_history.all()
            if row.field_name == field_name
        ]
        # field_history is ordered newest-first; walk oldest -> newest.
        points = []
        for row in reversed(rows):
            new_value = _rate_cell_value(row.new_value)
            if new_value is not None:
                points.append({"at": row.created, "value": new_value})
        if rows:
            first_value = _rate_cell_value(rows[-1].old_value)
            if first_value is not None and (not points or points[0]["value"] != first_value):
                points.insert(0, {"at": rows[-1].created, "value": first_value})
        current = _normalise_rate(cell.rate_max)
        if not points or points[-1]["value"] != current:
            points.append(
                {
                    "at": obj.rate_effective_date or obj.modified,
                    "value": current,
                }
            )
        return {
            "tenure_months_min": cell.tenure_months_min,
            "tenure_months_max": cell.tenure_months_max,
            "points": points[-6:],
        }


class DepositProductSerializer(DepositProductListSerializer):
    rates = DepositRateSerializer(many=True, read_only=True)

    class Meta(DepositProductListSerializer.Meta):
        fields = DepositProductListSerializer.Meta.fields + [
            "rates",
            "premature_encashment_terms",
            "premature_encashment_rules",
            "loan_against_percent",
            "loan_spread_pp",
            "instalment_failure_penalty",
            "insurance_bundled",
            "insurance_note",
            "eligibility_notes",
            "investment_cap",
            "joint_cap",
            "verification_status",
        ]


class DepositFieldHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DepositFieldHistory
        fields = ["id", "field_name", "old_value", "new_value", "created"]


class DepositScenarioInputSerializer(serializers.Serializer):
    """Scenario ranking input: what-if money + horizon across all products."""

    kind = serializers.ChoiceField(choices=["fdr", "dps"])
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=1
    )
    monthly_instalment = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=1
    )
    months = serializers.IntegerField(min_value=1, max_value=600)
    has_tin = serializers.BooleanField(required=False, default=True)
    islamic_only = serializers.BooleanField(required=False, default=False)
    bank = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if attrs["kind"] == "dps" and not attrs.get("monthly_instalment"):
            raise serializers.ValidationError(
                {"monthly_instalment": "Required for a DPS scenario."}
            )
        if attrs["kind"] == "fdr" and not attrs.get("amount"):
            raise serializers.ValidationError({"amount": "Required for an FDR scenario."})
        return attrs
