from rest_framework import serializers

from banks.api.serializers import BankListSerializer
from credit_cards.models import CreditCard, CreditCardFieldHistory


class CreditCardSerializer(serializers.ModelSerializer):
    """Serializer for CreditCard model."""

    bank = BankListSerializer(read_only=True)
    bank_id = serializers.IntegerField(write_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    total_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()

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
            "cash_advance_fee",
            "late_payment_fee",
            "annual_fee_waiver_policy",
            "reward_points_policy",
            "additional_features",
            "is_active",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
            "created",
            "modified",
        ]


class CreditCardFieldHistorySerializer(serializers.ModelSerializer):
    """Serializer for CreditCard field history entries."""

    class Meta:
        model = CreditCardFieldHistory
        fields = [
            "id",
            "card_id",
            "field_name",
            "old_value",
            "new_value",
            "created",
        ]
        read_only_fields = [
            "id",
            "created",
        ]


class CreditCardListSerializer(serializers.ModelSerializer):
    """Serializer for CreditCard list views.

    Includes the bank identity and the detail fields the frontend transforms
    and renders (reward policy, additional features, waiver policy and fee
    strings), while preserving the existing bank_name field.
    """

    bank = BankListSerializer(read_only=True)
    bank_id = serializers.IntegerField(source="bank.id", read_only=True)
    bank_name = serializers.CharField(source="bank.name", read_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()

    class Meta:
        model = CreditCard
        fields = [
            "id",
            "bank",
            "bank_id",
            "bank_name",
            "name",
            "annual_fee",
            "interest_rate_apr",
            "lounge_access_international",
            "lounge_access_domestic",
            "cash_advance_fee",
            "late_payment_fee",
            "annual_fee_waiver_policy",
            "reward_points_policy",
            "additional_features",
            "has_lounge_access",
            "has_annual_fee",
            "is_active",
            "created",
            "modified",
        ]


class CreditCardComparisonSerializer(serializers.ModelSerializer):
    """Serializer for credit card comparison views."""

    bank_name = serializers.CharField(source="bank.name", read_only=True)
    bank_logo = serializers.URLField(source="bank.logo", read_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    total_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()

    class Meta:
        model = CreditCard
        fields = [
            "id",
            "bank_name",
            "bank_logo",
            "name",
            "annual_fee",
            "interest_rate_apr",
            "lounge_access_international",
            "lounge_access_domestic",
            "cash_advance_fee",
            "late_payment_fee",
            "annual_fee_waiver_policy",
            "reward_points_policy",
            "additional_features",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
        ]
