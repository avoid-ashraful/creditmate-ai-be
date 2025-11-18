from rest_framework import serializers

from banks.api.serializers import BankListSerializer
from credit_cards.models import BenefitCategory, CreditCard, CreditCardBenefit


class BenefitCategorySerializer(serializers.ModelSerializer):
    """Serializer for BenefitCategory model."""

    class Meta:
        model = BenefitCategory
        fields = [
            "id",
            "name",
            "category_type",
            "description",
            "icon",
            "display_order",
        ]


class CreditCardBenefitSerializer(serializers.ModelSerializer):
    """Serializer for CreditCardBenefit model."""

    benefit_category = BenefitCategorySerializer(read_only=True)

    class Meta:
        model = CreditCardBenefit
        fields = [
            "id",
            "benefit_category",
            "reward_rate",
            "reward_description",
            "conditions",
            "is_primary",
            "confidence_score",
        ]


class CreditCardSerializer(serializers.ModelSerializer):
    """Serializer for CreditCard model."""

    bank = BankListSerializer(read_only=True)
    bank_id = serializers.IntegerField(write_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    total_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()
    card_benefits = CreditCardBenefitSerializer(many=True, read_only=True)

    class Meta:
        model = CreditCard
        fields = [
            "id",
            "bank",
            "bank_id",
            "name",
            "annual_fee",
            "interest_rate_apr",
            "lounge_access_international",
            "lounge_access_domestic",
            "lounge_access_condition",
            "cash_advance_fee",
            "late_payment_fee",
            "annual_fee_waiver_policy",
            "reward_points_policy",
            "additional_features",
            # Application and affiliate fields
            "apply_url",
            # New AI classification fields
            "annual_fee_waiver_difficulty",
            "spending_tier",
            "best_for_tags",
            "card_benefits",
            # Computed fields
            "is_active",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
            "created",
            "modified",
        ]
        read_only_fields = [
            "id",
            "created",
            "modified",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
            "card_benefits",
        ]


class CreditCardListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for CreditCard list views."""

    bank_name = serializers.CharField(source="bank.name", read_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()
    card_benefits = CreditCardBenefitSerializer(many=True, read_only=True)

    class Meta:
        model = CreditCard
        fields = [
            "id",
            "bank_name",
            "name",
            "annual_fee",
            "interest_rate_apr",
            "apply_url",
            "annual_fee_waiver_difficulty",
            "spending_tier",
            "best_for_tags",
            "lounge_access_international",
            "lounge_access_domestic",
            "has_lounge_access",
            "has_annual_fee",
            "card_benefits",
            "is_active",
        ]


class CreditCardComparisonSerializer(serializers.ModelSerializer):
    """Serializer for credit card comparison views."""

    bank_name = serializers.CharField(source="bank.name", read_only=True)
    bank_logo = serializers.URLField(source="bank.logo", read_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    total_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()
    card_benefits = CreditCardBenefitSerializer(many=True, read_only=True)

    class Meta:
        model = CreditCard
        fields = [
            "id",
            "bank_name",
            "bank_logo",
            "name",
            "annual_fee",
            "annual_fee_waiver_difficulty",
            "spending_tier",
            "best_for_tags",
            "interest_rate_apr",
            "apply_url",
            "lounge_access_international",
            "lounge_access_domestic",
            "lounge_access_condition",
            "cash_advance_fee",
            "late_payment_fee",
            "annual_fee_waiver_policy",
            "reward_points_policy",
            "additional_features",
            "card_benefits",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
        ]
