from rest_framework import serializers

from banks.api.serializers import BankListSerializer
from credit_cards.models import (
    BenefitCategory,
    CreditCard,
    CreditCardBenefit,
    CreditCardRating,
    CreditCardReview,
)


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
    average_rating = serializers.ReadOnlyField()
    total_ratings = serializers.ReadOnlyField()
    total_reviews = serializers.ReadOnlyField()
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
            "average_rating",
            "total_ratings",
            "total_reviews",
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
            "average_rating",
            "total_ratings",
            "total_reviews",
            "card_benefits",
        ]


class CreditCardListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for CreditCard list views."""

    bank_name = serializers.CharField(source="bank.name", read_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    has_annual_fee = serializers.ReadOnlyField()
    average_rating = serializers.ReadOnlyField()
    total_ratings = serializers.ReadOnlyField()
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
            "average_rating",
            "total_ratings",
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


class CreditCardRatingSerializer(serializers.ModelSerializer):
    """Serializer for CreditCardRating model."""

    class Meta:
        model = CreditCardRating
        fields = [
            "id",
            "credit_card",
            "user_name",
            "user_email",
            "rating",
            "is_verified_user",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "created", "modified", "is_verified_user"]


class CreditCardRatingCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a credit card rating."""

    class Meta:
        model = CreditCardRating
        fields = ["credit_card", "user_name", "user_email", "rating"]

    def validate(self, data):
        """Validate that user hasn't already rated this card."""
        credit_card = data.get("credit_card")
        user_email = data.get("user_email")

        if CreditCardRating.objects.filter(
            credit_card=credit_card, user_email=user_email
        ).exists():
            raise serializers.ValidationError(
                "You have already rated this credit card. Each user can only rate a card once."
            )

        return data


class CreditCardReviewSerializer(serializers.ModelSerializer):
    """Serializer for CreditCardReview model."""

    class Meta:
        model = CreditCardReview
        fields = [
            "id",
            "credit_card",
            "user_name",
            "user_email",
            "title",
            "review_text",
            "rating",
            "pros",
            "cons",
            "helpful_count",
            "usage_duration_months",
            "is_verified_user",
            "is_approved",
            "created",
            "modified",
        ]
        read_only_fields = [
            "id",
            "helpful_count",
            "is_verified_user",
            "is_approved",
            "created",
            "modified",
        ]


class CreditCardReviewCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a credit card review."""

    class Meta:
        model = CreditCardReview
        fields = [
            "credit_card",
            "user_name",
            "user_email",
            "title",
            "review_text",
            "rating",
            "pros",
            "cons",
            "usage_duration_months",
        ]


class CreditCardReviewListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for review list views (hides email)."""

    class Meta:
        model = CreditCardReview
        fields = [
            "id",
            "user_name",
            "title",
            "review_text",
            "rating",
            "pros",
            "cons",
            "helpful_count",
            "usage_duration_months",
            "is_verified_user",
            "created",
        ]
