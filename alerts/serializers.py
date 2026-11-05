from rest_framework import serializers

from banks.models import Bank
from credit_cards.models import CreditCard

from .models import AlertSubscription, BankFollow, NotificationPreference


class AlertSubscriptionSerializer(serializers.ModelSerializer):
    card_name = serializers.CharField(source="card.name", read_only=True, default=None)
    bank_name = serializers.CharField(
        source="card.bank.name", read_only=True, default=None
    )
    card = serializers.PrimaryKeyRelatedField(
        queryset=CreditCard.objects.public(),
        required=False,
        allow_null=True,
        help_text="Published card to watch, or null for a general alert.",
    )

    class Meta:
        model = AlertSubscription
        fields = ("id", "card", "card_name", "bank_name", "kind", "is_active", "created")
        read_only_fields = ("id", "card_name", "bank_name", "created")


class BankFollowSerializer(serializers.ModelSerializer):
    bank = serializers.PrimaryKeyRelatedField(
        queryset=Bank.objects.filter(is_active=True),
        help_text="Bank to follow.",
    )
    bank_name = serializers.CharField(source="bank.name", read_only=True)

    class Meta:
        model = BankFollow
        fields = ("id", "bank", "bank_name", "created")
        read_only_fields = ("id", "bank_name", "created")


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("frequency",)


class BankFollowFeedEntrySerializer(serializers.Serializer):
    """One field-change event in the bank-follow feed (alerts/feed.py)."""

    id = serializers.CharField()
    vertical = serializers.CharField()
    product_name = serializers.CharField()
    product_key = serializers.CharField()
    bank_id = serializers.IntegerField(allow_null=True)
    bank_name = serializers.CharField()
    field_name = serializers.CharField()
    old_value = serializers.JSONField(allow_null=True)
    new_value = serializers.JSONField(allow_null=True)
    source = serializers.CharField(allow_null=True)
    changed_at = serializers.DateTimeField()
    # Phase 4 (D4): true when this change is newer than the requesting
    # user's seen watermark. Computed by the view; defaults to False so
    # entries built outside the feed view never claim to be new.
    is_new = serializers.BooleanField(default=False)


class FeedMarkSeenInputSerializer(serializers.Serializer):
    """Input for the mark-seen call: the newest change the user was shown.

    Optional — omitting ``through`` marks everything up to now as seen.
    """

    through = serializers.DateTimeField(required=False, allow_null=True)
