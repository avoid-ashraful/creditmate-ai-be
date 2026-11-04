from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from loans.caps import product_cap_flags
from loans.constants import CHART_CATEGORY_FOR_TYPE, LoanType
from loans.models import LoanFieldHistory, LoanProduct, RegulatoryCap


class EffectiveRateBandSerializer(serializers.Serializer):
    """Schema shape of the effective_rate object (see EffectiveBandMixin)."""

    min = serializers.DecimalField(max_digits=6, decimal_places=2)
    max = serializers.DecimalField(max_digits=6, decimal_places=2)
    source = serializers.CharField()
    label = serializers.CharField()
    # The BB chart category a chart-sourced band came from (the chart
    # has no car column, so a car band is really "consumer_credit");
    # None for a product's own non-chart band.
    category = serializers.CharField(allow_null=True)


class EffectiveBandMixin:
    """Adds the effective rate band: the product's own published band wins;
    otherwise the bank's BB lending-chart band for the mapped category is
    the provenance-labelled fallback; formula-priced products stay
    band-less (their price is a spread over a deposit rate)."""

    def _band(self, obj):
        request = self.context.get("request")
        # The scenario view preloads all chart bands in one query and
        # shares them via the request — reuse them instead of querying.
        preloaded = (
            getattr(request, "_loan_chart_bands_preload", None)
            if request is not None
            else None
        )
        if preloaded is not None:
            from loans.api.views import chart_band_for

            return chart_band_for(obj, chart_bands=preloaded)
        cache = getattr(request, "_loan_chart_band_cache", None)
        if cache is None:
            cache = {}
            if request is not None:
                request._loan_chart_band_cache = cache
        key = (obj.bank_id, obj.institution_name, obj.loan_type)
        if key not in cache:
            from loans.api.views import chart_band_for

            cache[key] = chart_band_for(obj)
        return cache[key]

    @extend_schema_field(EffectiveRateBandSerializer(allow_null=True))
    def get_effective_rate(self, obj):
        if obj.rate_min is not None and obj.rate_max is not None:
            category = None
            if obj.rate_source == "bb_chart":
                category = CHART_CATEGORY_FOR_TYPE.get(obj.loan_type)
            return {
                "min": obj.rate_min,
                "max": obj.rate_max,
                "source": obj.rate_source,
                "label": obj.rate_label,
                "category": category,
            }
        band = self._band(obj)
        if band is not None:
            return {
                "min": band.rate_min,
                "max": band.rate_max,
                "source": "bb_chart",
                "label": obj.rate_label,
                "category": band.category,
            }
        return None


class LoanProductListSerializer(EffectiveBandMixin, serializers.ModelSerializer):
    bank_name = serializers.SerializerMethodField()
    lender_name = serializers.SerializerMethodField()
    rate_label = serializers.SerializerMethodField()
    effective_rate = serializers.SerializerMethodField()

    class Meta:
        model = LoanProduct
        fields = [
            "id",
            "slug",
            "name",
            "bank",
            "bank_name",
            "institution_name",
            "lender_name",
            "lender_type",
            "loan_type",
            "segment_tags",
            "purpose_tags",
            "is_islamic",
            "shariah_mode",
            "rate_label",
            "rate_min",
            "rate_max",
            "rate_type",
            "rate_source",
            "spread_over_deposit_rate",
            "uses_simple_interest",
            "effective_rate",
            "amount_min_bdt",
            "amount_max_bdt",
            "tenure_min_months",
            "tenure_max_months",
            "ltv_percent",
            "processing_fee_percent",
            "processing_fee_percent_max",
            "processing_fee_cap_bdt",
            "min_income_by_segment",
            "income_metric",
            "source_url",
            "verified_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_bank_name(self, obj):
        return obj.bank.name if obj.bank_id else None

    @extend_schema_field(serializers.CharField())
    def get_lender_name(self, obj):
        return obj.lender_display_name

    @extend_schema_field(serializers.CharField())
    def get_rate_label(self, obj):
        return obj.rate_label


class LoanProductSerializer(EffectiveBandMixin, serializers.ModelSerializer):
    bank_name = serializers.SerializerMethodField()
    lender_name = serializers.SerializerMethodField()
    rate_label = serializers.SerializerMethodField()
    effective_rate = serializers.SerializerMethodField()
    regulatory_cap_flags = serializers.SerializerMethodField()

    class Meta:
        model = LoanProduct
        exclude = ["created", "modified"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_bank_name(self, obj):
        return obj.bank.name if obj.bank_id else None

    @extend_schema_field(serializers.CharField())
    def get_lender_name(self, obj):
        return obj.lender_display_name

    @extend_schema_field(serializers.CharField())
    def get_rate_label(self, obj):
        return obj.rate_label

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_regulatory_cap_flags(self, obj):
        stored = list(obj.regulatory_flags or [])
        computed = product_cap_flags(obj)
        return stored + [f for f in computed if f not in stored]


class LoanFieldHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanFieldHistory
        fields = ["id", "field_name", "old_value", "new_value", "source", "created"]


class RegulatoryCapSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryCap
        fields = ["key", "effective_from", "params", "description", "source_note"]


class LoanScenarioInputSerializer(serializers.Serializer):
    # Reuse the model's canonical choices (not a literal copy) so
    # drf-spectacular dedupes this enum with LoanProduct.loan_type
    # instead of warning about a naming collision.
    loan_type = serializers.ChoiceField(choices=LoanType.choices)
    amount = serializers.IntegerField(min_value=1)
    tenure_months = serializers.IntegerField(min_value=1, max_value=600)
    monthly_income = serializers.IntegerField(
        min_value=0, required=False, allow_null=True
    )
    # Optional borrower segment (e.g. "salaried", "business"): when
    # given, the income check uses that segment's published minimum;
    # when omitted, an income between segment minima yields a warning.
    segment = serializers.CharField(
        max_length=100, required=False, allow_blank=True, allow_null=True
    )
    islamic_only = serializers.BooleanField(required=False, default=False)
    bank = serializers.IntegerField(required=False, allow_null=True)
