"""Serializers for the deposits API."""

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


class DepositProductListSerializer(serializers.ModelSerializer):
    bank = BankSerializer(read_only=True)
    institution_display_name = serializers.CharField(read_only=True)
    rate_range = serializers.SerializerMethodField()

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
