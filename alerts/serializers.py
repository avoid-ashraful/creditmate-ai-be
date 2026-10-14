from rest_framework import serializers

from .models import AlertSubscription, NotificationPreference


class AlertSubscriptionSerializer(serializers.ModelSerializer):
    card_name = serializers.CharField(source="card.name", read_only=True, default=None)
    bank_name = serializers.CharField(
        source="card.bank.name", read_only=True, default=None
    )

    class Meta:
        model = AlertSubscription
        fields = ("id", "card", "card_name", "bank_name", "kind", "is_active", "created")
        read_only_fields = ("id", "card_name", "bank_name", "created")


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("frequency",)
