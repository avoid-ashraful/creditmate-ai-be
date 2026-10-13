from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.html import strip_tags
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from django.core.exceptions import ValidationError as DjangoValidationError

from reviews.models import CardReview, ReviewVote
from reviews.validators import clean_review_text


class CardReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()

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
                    raise serializers.ValidationError({field: "This field may not be empty after removing HTML."})
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
