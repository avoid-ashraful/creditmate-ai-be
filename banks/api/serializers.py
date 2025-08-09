from rest_framework import serializers

from banks.models import Bank


class BankSerializer(serializers.ModelSerializer):
    """Serializer for Bank model."""

    credit_card_count = serializers.ReadOnlyField()

    class Meta:
        model = Bank
        fields = [
            "id",
            "name",
            "logo",
            "website",
            "is_active",
            "credit_card_count",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "created", "modified", "credit_card_count"]


class BankListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for Bank list views."""

    credit_card_count = serializers.ReadOnlyField()

    class Meta:
        model = Bank
        fields = ["id", "name", "logo", "credit_card_count", "is_active"]
