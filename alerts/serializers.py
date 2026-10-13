from rest_framework import serializers

from .models import AlertSubscription, NotificationPreference


class AlertSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertSubscription
        fields = ("id", "card", "kind", "is_active", "created")
        read_only_fields = ("id", "created")


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("frequency",)
