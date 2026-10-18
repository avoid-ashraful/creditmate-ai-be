from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from banks.api.serializers import BankListSerializer
from credit_cards.constants import REPORTABLE_FIELDS
from credit_cards.models import CreditCard, CreditCardFieldHistory


class TypeaheadCardSuggestionSerializer(serializers.Serializer):
    """Card suggestion in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    type = serializers.CharField(default="card")
    id = serializers.IntegerField()
    label = serializers.CharField()
    detail = serializers.CharField()
    query = serializers.CharField()


class TypeaheadBankSuggestionSerializer(serializers.Serializer):
    """Bank suggestion in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    type = serializers.CharField(default="bank")
    id = serializers.IntegerField()
    label = serializers.CharField()
    detail = serializers.CharField()
    query = serializers.CharField()


class TypeaheadCategorySuggestionSerializer(serializers.Serializer):
    """Category suggestion in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    type = serializers.CharField(default="category")
    slug = serializers.CharField()
    label = serializers.CharField()


class TypeaheadMatchesSerializer(serializers.Serializer):
    """Grouped matches by type in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    card = serializers.ListField(child=serializers.CharField())
    bank = serializers.ListField(child=serializers.CharField())
    category = serializers.ListField(child=serializers.CharField())
    source = serializers.CharField(default="database")


class TypeaheadFacetSerializer(serializers.Serializer):
    """Individual facet count and filter in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    label = serializers.CharField()
    count = serializers.IntegerField()
    filter = serializers.CharField()


class TypeaheadHighlightSerializer(serializers.Serializer):
    """Highlight metadata for UI rendering in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    terms = serializers.ListField(child=serializers.CharField())
    scope = serializers.CharField(allow_null=True)
    strategy = serializers.CharField(allow_null=True)


class TypeaheadMatchPolicySerializer(serializers.Serializer):
    """Matching policy constraints in typeahead response.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    minimum_characters = serializers.IntegerField()
    result_limit = serializers.IntegerField()
    active = serializers.BooleanField()


@extend_schema_field(
    {
        "oneOf": [
            {
                "type": "object",
                "title": "TypeaheadCardSuggestion",
                "properties": {
                    "type": {"type": "string", "enum": ["card"]},
                    "id": {"type": "integer"},
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["type", "id", "label", "detail", "query"],
            },
            {
                "type": "object",
                "title": "TypeaheadBankSuggestion",
                "properties": {
                    "type": {"type": "string", "enum": ["bank"]},
                    "id": {"type": "integer"},
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["type", "id", "label", "detail", "query"],
            },
            {
                "type": "object",
                "title": "TypeaheadCategorySuggestion",
                "properties": {
                    "type": {"type": "string", "enum": ["category"]},
                    "slug": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["type", "slug", "label"],
            },
        ]
    }
)
class TypeaheadSuggestionField(serializers.Field):
    """Polymorphic suggestion field supporting card/bank/category types.

    Uses oneOf schema in OpenAPI to document all possible suggestion shapes.
    Runtime payloads contain type discrimination field to distinguish shapes.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        return data


class TypeaheadResponseSerializer(serializers.Serializer):
    """Complete typeahead response envelope.

    Contains mixed suggestion types (cards, banks, categories) and optional
    did-you-mean suggestions for typo correction.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    query = serializers.CharField()
    suggestions = serializers.ListField(
        child=TypeaheadSuggestionField(),
        help_text="Array of mixed suggestion objects with type discrimination",
    )
    matches = TypeaheadMatchesSerializer()
    facets = serializers.DictField(
        child=TypeaheadFacetSerializer(),
        help_text="Facet counts keyed by facet slug (no_fee, travel, cashback, lounge)",
    )
    did_you_mean = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Safe typo suggestion when no prefix/substring matches found",
    )
    highlight = TypeaheadHighlightSerializer()
    match_policy = TypeaheadMatchPolicySerializer()


class CreditCardSerializer(serializers.ModelSerializer):
    """Serializer for CreditCard model."""

    bank = BankListSerializer(read_only=True)
    bank_id = serializers.IntegerField(write_only=True)
    has_lounge_access = serializers.BooleanField(read_only=True, allow_null=True)
    total_lounge_access = serializers.IntegerField(read_only=True)
    has_annual_fee = serializers.BooleanField(read_only=True)

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
            "reward_program_name",
            "reward_earn_rules",
            "cashback_rules",
            "reward_point_value_bdt",
            "points_expiry_text",
            "reward_source_url",
            "additional_features",
            "is_active",
            "source_url",
            "apply_url",
            "verification_status",
            "verified_at",
            "card_network",
            "is_islamic",
            "is_dual_currency",
            "min_monthly_income",
            "supplementary_card_fee",
            "foreign_transaction_fee",
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
    has_lounge_access = serializers.BooleanField(read_only=True, allow_null=True)
    has_annual_fee = serializers.BooleanField(read_only=True)

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
            "reward_program_name",
            "reward_earn_rules",
            "cashback_rules",
            "reward_point_value_bdt",
            "points_expiry_text",
            "reward_source_url",
            "additional_features",
            "has_lounge_access",
            "has_annual_fee",
            "is_active",
            "source_url",
            "apply_url",
            "verification_status",
            "verified_at",
            "card_network",
            "is_islamic",
            "is_dual_currency",
            "min_monthly_income",
            "supplementary_card_fee",
            "foreign_transaction_fee",
            "created",
            "modified",
        ]


class CreditCardComparisonSerializer(serializers.ModelSerializer):
    """Serializer for credit card comparison views."""

    bank_name = serializers.CharField(source="bank.name", read_only=True)
    bank_logo = serializers.URLField(source="bank.logo", read_only=True)
    has_lounge_access = serializers.ReadOnlyField()
    total_lounge_access = serializers.IntegerField(read_only=True)
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
            "source_url",
            "apply_url",
            "verification_status",
            "verified_at",
            "card_network",
            "is_islamic",
            "is_dual_currency",
            "min_monthly_income",
            "supplementary_card_fee",
            "foreign_transaction_fee",
            "has_lounge_access",
            "total_lounge_access",
            "has_annual_fee",
        ]


class ReportIssueSerializer(serializers.Serializer):
    """Input for reporting incorrect data on a credit card."""

    field = serializers.ChoiceField(
        choices=REPORTABLE_FIELDS,
        required=False,
        allow_blank=True,
        help_text="Card field the report is about, when it concerns one field.",
    )
    message = serializers.CharField(max_length=1000)
    suggested_value = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    contact_email = serializers.EmailField(required=False, allow_blank=True)


class ReportIssueResponseSerializer(serializers.Serializer):
    """Acknowledgement returned after a report is queued."""

    id = serializers.IntegerField(help_text="Review queue item id")
    status = serializers.CharField()
