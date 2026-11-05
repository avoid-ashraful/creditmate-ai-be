from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.html import strip_tags

from credit_cards.models import CreditCard
from reviews.models import CardReview, ReviewComment, ReviewVote
from reviews.validators import clean_review_text


class CardReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()
    card = serializers.PrimaryKeyRelatedField(
        queryset=CreditCard.objects.public(),
        help_text="Published card the review is about.",
    )

    class Meta:
        model = CardReview
        fields = (
            "id",
            "card",
            "rating",
            "title",
            "body",
            "pros",
            "cons",
            "reviewer_name",
            "helpful_count",
            "created",
            "modified",
        )
        read_only_fields = ("id", "reviewer_name", "helpful_count", "created", "modified")

    @extend_schema_field(serializers.CharField())
    def get_reviewer_name(self, obj):
        name = (
            getattr(obj.user, "get_full_name", lambda: "")()
            or getattr(obj.user, "username", "")
        ).strip()
        if not name or "@" in name:
            return "Community member"
        return name

    def validate(self, attrs):
        for field in ("title", "body", "pros", "cons"):
            if field in attrs:
                attrs[field] = strip_tags(attrs[field] or "").strip()
                if not attrs[field]:
                    raise serializers.ValidationError(
                        {field: "This field may not be empty after removing HTML."}
                    )
                try:
                    attrs[field] = clean_review_text(attrs[field])
                except DjangoValidationError as exc:
                    raise serializers.ValidationError({field: exc.messages}) from exc
        request = self.context.get("request")
        card = attrs.get("card", getattr(self.instance, "card", None))
        if request and request.user.is_authenticated and card:
            existing = CardReview.objects.filter(user=request.user, card=card)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"card": "You have already reviewed this card."}
                )
        return attrs


class ReviewVoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewVote
        fields = ("helpful",)


def reviewer_display_name(user):
    """Public display name for a review/comment author (never an email)."""
    name = (
        getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "")
    ).strip()
    if not name or "@" in name:
        return "Community member"
    return name


def clean_text_fields(attrs, fields):
    """Strip markup and apply the shared abuse heuristics, as card reviews do."""
    for field in fields:
        if field in attrs:
            attrs[field] = strip_tags(attrs[field] or "").strip()
            if not attrs[field]:
                raise serializers.ValidationError(
                    {field: "This field may not be empty after removing HTML."}
                )
            try:
                attrs[field] = clean_review_text(attrs[field])
            except DjangoValidationError as exc:
                raise serializers.ValidationError({field: exc.messages}) from exc
    return attrs


class OwnCardReviewSerializer(CardReviewSerializer):
    """Card review as its author (or a moderator) sees it: with status.

    ``status`` is read-only — authors can never set their own status;
    moderation actions go through the staff endpoints.
    """

    class Meta(CardReviewSerializer.Meta):
        fields = CardReviewSerializer.Meta.fields + ("status",)
        read_only_fields = CardReviewSerializer.Meta.read_only_fields + ("status",)


_product_serializer_cache = {}


def product_review_serializer_class(product_type, *, own=False):
    """Build (and cache) the review serializer for a generalised type.

    The payload mirrors :class:`CardReviewSerializer`, with ``product``
    in place of ``card`` plus an explicit ``product_type`` so clients can
    use one grammar across verticals.
    """
    from .product_types import PRODUCT_REVIEW_TYPES

    key = (product_type, own)
    if key in _product_serializer_cache:
        return _product_serializer_cache[key]
    config = PRODUCT_REVIEW_TYPES[product_type]
    review_model = config["review_model"]
    product_model = config["product_model"]

    class ProductReviewSerializer(serializers.ModelSerializer):
        reviewer_name = serializers.SerializerMethodField()
        product = serializers.PrimaryKeyRelatedField(
            queryset=product_model.objects.public(),
            help_text="Published product the review is about.",
        )
        product_type = serializers.SerializerMethodField()

        class Meta:
            model = review_model
            fields = (
                "id",
                "product",
                "product_type",
                "rating",
                "title",
                "body",
                "pros",
                "cons",
                "reviewer_name",
                "helpful_count",
                "created",
                "modified",
            )
            read_only_fields = (
                "id",
                "product_type",
                "reviewer_name",
                "helpful_count",
                "created",
                "modified",
            )

        @extend_schema_field(serializers.CharField())
        def get_reviewer_name(self, obj):
            return reviewer_display_name(obj.user)

        @extend_schema_field(serializers.CharField())
        def get_product_type(self, obj):
            return product_type

        def validate(self, attrs):
            attrs = clean_text_fields(attrs, ("title", "body", "pros", "cons"))
            request = self.context.get("request")
            product = attrs.get("product", getattr(self.instance, "product", None))
            if request and request.user.is_authenticated and product:
                existing = review_model.objects.filter(
                    user=request.user, product=product
                )
                if self.instance:
                    existing = existing.exclude(pk=self.instance.pk)
                if existing.exists():
                    raise serializers.ValidationError(
                        {"product": "You have already reviewed this product."}
                    )
            return attrs

    ProductReviewSerializer.__name__ = (
        f"{product_type.capitalize()}ReviewSerializer{'Own' if own else ''}"
    )
    if own:

        class OwnProductReviewSerializer(ProductReviewSerializer):
            class Meta(ProductReviewSerializer.Meta):
                fields = ProductReviewSerializer.Meta.fields + ("status",)
                read_only_fields = ProductReviewSerializer.Meta.read_only_fields + (
                    "status",
                )

        OwnProductReviewSerializer.__name__ = ProductReviewSerializer.__name__
        _product_serializer_cache[key] = OwnProductReviewSerializer
        return OwnProductReviewSerializer
    _product_serializer_cache[key] = ProductReviewSerializer
    return ProductReviewSerializer


class ReviewCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    review = serializers.IntegerField(source="object_id", read_only=True)
    # Parent is resolved and validated by the create view (it must belong
    # to the same review and be top-level), never bound straight from input.
    parent = serializers.PrimaryKeyRelatedField(read_only=True)
    review_type = serializers.SerializerMethodField()

    class Meta:
        model = ReviewComment
        fields = (
            "id",
            "review",
            "review_type",
            "parent",
            "author_name",
            "body",
            "created",
            "modified",
        )
        read_only_fields = (
            "id",
            "review",
            "review_type",
            "parent",
            "author_name",
            "created",
            "modified",
        )

    @extend_schema_field(serializers.CharField())
    def get_author_name(self, obj):
        return reviewer_display_name(obj.author)

    @extend_schema_field(serializers.CharField())
    def get_review_type(self, obj):
        from .product_types import review_type_for_model

        return review_type_for_model(obj.content_type.model_class())

    def validate(self, attrs):
        return clean_text_fields(attrs, ("body",))


class OwnReviewCommentSerializer(ReviewCommentSerializer):
    """Comment as its author (or a moderator) sees it: with status."""

    class Meta(ReviewCommentSerializer.Meta):
        fields = ReviewCommentSerializer.Meta.fields + ("status",)
        read_only_fields = ReviewCommentSerializer.Meta.read_only_fields + ("status",)


class ReviewCommentTreeSerializer(ReviewCommentSerializer):
    """Top-level comment with its (one-level) replies nested."""

    replies = serializers.SerializerMethodField()

    class Meta(ReviewCommentSerializer.Meta):
        fields = ReviewCommentSerializer.Meta.fields + ("replies",)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, obj):
        request = self.context.get("request")
        visible = getattr(obj, "_visible_replies", None)
        if visible is None:
            visible = [
                reply
                for reply in obj.replies.all()
                if reply.status == ReviewComment.Status.APPROVED
            ]
        data = []
        for reply in visible:
            serializer_class = (
                OwnReviewCommentSerializer
                if request is not None
                and getattr(request, "user", None) is not None
                and request.user.is_authenticated
                and reply.author_id == request.user.id
                else ReviewCommentSerializer
            )
            data.append(serializer_class(reply, context=self.context).data)
        return data


class OwnReviewCommentTreeSerializer(ReviewCommentTreeSerializer):
    class Meta(ReviewCommentTreeSerializer.Meta):
        fields = ReviewCommentTreeSerializer.Meta.fields + ("status",)
        read_only_fields = ReviewCommentTreeSerializer.Meta.read_only_fields + (
            "status",
        )
