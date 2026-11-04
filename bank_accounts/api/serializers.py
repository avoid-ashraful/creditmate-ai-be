"""Serializers for the bank-accounts API."""

from rest_framework import serializers

from bank_accounts.models import AccountFieldHistory, AccountProduct
from banks.api.serializers import BankSerializer


class AccountProductListSerializer(serializers.ModelSerializer):
    bank = BankSerializer(read_only=True)
    variant_of = serializers.SerializerMethodField()
    variants_count = serializers.SerializerMethodField()

    class Meta:
        model = AccountProduct
        fields = [
            "id",
            "slug",
            "name",
            "account_type",
            "bank",
            "variant_of",
            "variants_count",
            "segment",
            "is_islamic",
            "contract_type",
            "rate_type",
            "rate_slabs",
            "interest_basis",
            "interest_payout_frequency",
            "min_balance_to_earn",
            "maintenance_fee_slabs",
            "debit_card_fee_annual",
            "debit_card_waiver_text",
            "debit_card_waiver_min_balance",
            "sms_fee_annual",
            "online_banking_fee_annual",
            "cheque_per_leaf",
            "cheque_first_book_free",
            "closure_fee",
            "fee_data_complete",
            "fees_include_vat",
            "source_soc_url",
            "source_rate_url",
            "soc_effective_date",
            "rate_effective_date",
            "verified_at",
        ]

    def get_variant_of(self, obj) -> dict | None:
        if obj.variant_of_id is None:
            return None
        return {"slug": obj.variant_of.slug, "name": obj.variant_of.name}

    def get_variants_count(self, obj) -> int:
        variants = getattr(obj, "_prefetched_variants", None)
        if variants is not None:
            return len(variants)
        return obj.variants.public().count()


class AccountProductSerializer(AccountProductListSerializer):
    variants = serializers.SerializerMethodField()

    class Meta(AccountProductListSerializer.Meta):
        fields = AccountProductListSerializer.Meta.fields + [
            "variants",
            "rate_conditions_text",
            "withdrawal_limit_for_interest",
            "maintenance_waiver_text",
            "debit_card_first_year_fee",
            "debit_card_replacement_fee",
            "statement_duplicate_fee",
            "balance_confirmation_extra_fee",
            "min_balance_required",
            "opening_deposit",
            "cheque_book_available",
            "debit_card_included",
            "dormancy_terms",
            "eligibility_notes",
            "source_kind",
            "last_verified_at",
            "verification_status",
        ]

    def get_variants(self, obj) -> list:
        variants = getattr(obj, "_prefetched_variants", None)
        if variants is None:
            variants = list(obj.variants.public())
        return [{"slug": v.slug, "name": v.name, "segment": v.segment} for v in variants]


class AccountFieldHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountFieldHistory
        fields = ["id", "field_name", "old_value", "new_value", "created"]


class AccountScenarioInputSerializer(serializers.Serializer):
    """Scenario input: an average balance, ranked by net annual value."""

    average_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0
    )
    account_type = serializers.ChoiceField(
        choices=["savings", "current", "snd"], required=False, default="savings"
    )
    segments = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
                "general",
                "women",
                "student",
                "senior",
                "salary",
                "nrb",
                "digital",
                "minor",
                "inclusion",
                "premium",
            ]
        ),
        required=False,
    )
    bank = serializers.IntegerField(required=False)
    islamic_only = serializers.BooleanField(required=False, default=False)
    include_variants = serializers.BooleanField(required=False, default=True)
