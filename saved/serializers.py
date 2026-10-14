from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from credit_cards.api.serializers import CreditCardListSerializer
from credit_cards.models import CreditCard
from saved import services
from saved.constants import MAX_CARDS_PER_COMPARISON
from saved.models import Collection, CollectionItem, SavedComparison


def serialize_ordered_cards(items, context):
    """Serialize comparison items as CreditCardListSerializer rows in position order.

    Parameters
    ----------
    items : iterable of SavedComparisonItem
        Items with card and card.bank already loaded, sorted by position
    context : dict
        Serializer context forwarded to CreditCardListSerializer

    Returns
    -------
    list of dict
        Serialized card data, one entry per item
    """
    return CreditCardListSerializer(
        [item.card for item in items],
        many=True,
        context=context,
    ).data


class SavedComparisonSerializer(serializers.ModelSerializer):
    """Owner-facing representation and writes for a saved comparison.

    Writes take ``card_ids`` (ordered, 1 to MAX_CARDS_PER_COMPARISON unique
    existing cards). Reads return ``cards`` in the same order, plus the share
    token so the owner can build a public link.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    card_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=MAX_CARDS_PER_COMPARISON,
        write_only=True,
        required=False,
        help_text="Ordered card ids. Replaces the comparison's cards when sent.",
    )
    cards = serializers.SerializerMethodField()
    share_token = serializers.CharField(read_only=True)

    class Meta:
        model = SavedComparison
        fields = [
            "id",
            "name",
            "notes",
            "is_public",
            "share_token",
            "card_ids",
            "cards",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "created", "modified"]

    @extend_schema_field(CreditCardListSerializer(many=True))
    def get_cards(self, obj):
        """Return the comparison's cards in position order.

        Parameters
        ----------
        obj : SavedComparison
            The comparison being serialized

        Returns
        -------
        list of dict
            Serialized CreditCardListSerializer rows
        """
        return serialize_ordered_cards(obj.items.all(), self.context)

    def validate_card_ids(self, value):
        """Check that card ids are unique and refer to existing cards.

        Parameters
        ----------
        value : list of int
            Submitted card ids in the user's chosen order

        Returns
        -------
        list of int
            The same ids, unchanged

        Raises
        ------
        ValidationError
            On duplicate ids or ids that do not match any card
        """
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Each card can appear only once.")
        existing = set(
            CreditCard.objects.filter(pk__in=value).values_list("pk", flat=True)
        )
        missing = [card_id for card_id in value if card_id not in existing]
        if missing:
            raise serializers.ValidationError(f"Unknown card ids: {missing}")
        return value

    def validate(self, attrs):
        """Require card_ids when creating a comparison.

        Parameters
        ----------
        attrs : dict
            Validated field values

        Returns
        -------
        dict
            The validated attributes

        Raises
        ------
        ValidationError
            When creating without card_ids
        """
        if self.instance is None and "card_ids" not in attrs:
            raise serializers.ValidationError({"card_ids": ["This field is required."]})
        return attrs

    def create(self, validated_data):
        """Create the comparison through the service layer.

        Parameters
        ----------
        validated_data : dict
            Validated fields including card_ids

        Returns
        -------
        SavedComparison
            The created comparison
        """
        card_ids = validated_data.pop("card_ids")
        return services.create_comparison(
            self.context["request"].user,
            validated_data,
            card_ids,
        )

    def update(self, instance, validated_data):
        """Update the comparison through the service layer.

        Parameters
        ----------
        instance : SavedComparison
            The comparison being updated
        validated_data : dict
            Validated fields; card_ids replaces the cards when present

        Returns
        -------
        SavedComparison
            The updated comparison
        """
        card_ids = validated_data.pop("card_ids", None)
        return services.update_comparison(instance, validated_data, card_ids)


class PublicSavedComparisonSerializer(serializers.ModelSerializer):
    """Read-only public view of a shared comparison.

    Exposes only the comparison content. The owner, identifiers and token
    are deliberately absent.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    cards = serializers.SerializerMethodField()

    class Meta:
        model = SavedComparison
        fields = ["name", "notes", "cards", "modified"]

    @extend_schema_field(CreditCardListSerializer(many=True))
    def get_cards(self, obj):
        """Return the shared comparison's cards in position order.

        Parameters
        ----------
        obj : SavedComparison
            The shared comparison

        Returns
        -------
        list of dict
            Serialized CreditCardListSerializer rows
        """
        return serialize_ordered_cards(obj.items.all(), self.context)


class CollectionItemSerializer(serializers.ModelSerializer):
    """A card inside a collection with the owner's notes.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    card = CreditCardListSerializer(read_only=True)

    class Meta:
        model = CollectionItem
        fields = ["card", "notes", "created"]


class CollectionSerializer(serializers.ModelSerializer):
    """Owner-facing representation and writes for a collection.

    Cards are added and removed through the collection's ``cards`` actions,
    not through this serializer.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    cards = CollectionItemSerializer(source="items", many=True, read_only=True)

    class Meta:
        model = Collection
        fields = [
            "id",
            "name",
            "description",
            "is_public",
            "slug",
            "cards",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "slug", "created", "modified"]

    def create(self, validated_data):
        """Create the collection through the service layer.

        Parameters
        ----------
        validated_data : dict
            Validated collection fields

        Returns
        -------
        Collection
            The created collection
        """
        return services.create_collection(self.context["request"].user, validated_data)


class PublicCollectionSerializer(serializers.ModelSerializer):
    """Read-only public view of a public collection.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    cards = CollectionItemSerializer(source="items", many=True, read_only=True)

    class Meta:
        model = Collection
        fields = ["name", "description", "slug", "cards", "modified"]


class CollectionCardAddSerializer(serializers.Serializer):
    """Input for adding one card to a collection.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    card_id = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
    )

    def validate_card_id(self, value):
        """Check that the card exists.

        Parameters
        ----------
        value : int
            Submitted card primary key

        Returns
        -------
        int
            The same card id

        Raises
        ------
        ValidationError
            When no card has this id
        """
        if not CreditCard.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Unknown card id.")
        return value
