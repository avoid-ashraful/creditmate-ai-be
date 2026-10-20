from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, F
from django.shortcuts import get_object_or_404

from credit_cards.models import CreditCard
from reviews.models import CardReview, ReviewVote

from .serializers import CardReviewSerializer, ReviewVoteSerializer
from .throttles import ReviewUserThrottle, ReviewWriteThrottleMixin


class PublicReviewListCreateView(ReviewWriteThrottleMixin, generics.ListCreateAPIView):
    serializer_class = CardReviewSerializer
    # Use default throttles for reads; ReviewWriteThrottleMixin applies
    # ReviewUserThrottle only to write requests (POST).
    throttle_classes = []

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_list",
        responses={200: CardReviewSerializer(many=True)},
        parameters=[OpenApiParameter("card", int, OpenApiParameter.QUERY)],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_create",
        request=CardReviewSerializer,
        responses={201: CardReviewSerializer},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        qs = CardReview.objects.filter(status=CardReview.Status.APPROVED).select_related(
            "user", "card"
        )
        card_id = self.request.query_params.get("card")
        if not card_id:
            return qs
        try:
            card_id = int(card_id)
        except (TypeError, ValueError):
            raise ValidationError({"card": ["A valid integer is required."]}) from None
        return qs.filter(card_id=card_id)

    def get_permissions(self):
        return (
            [permissions.IsAuthenticated()]
            if self.request.method == "POST"
            else [permissions.AllowAny()]
        )

    def perform_create(self, serializer):
        profile = getattr(self.request.user, "profile", None)
        if not (profile and profile.email_verified):
            raise PermissionDenied(
                {
                    "detail": "Verify your email address before posting a review.",
                    "code": "email_not_verified",
                }
            )
        serializer.save(user=self.request.user, status=CardReview.Status.PENDING)


class OwnReviewDetailView(
    ReviewWriteThrottleMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = CardReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_mine_retrieve",
        responses={200: CardReviewSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_mine_update",
        request=CardReviewSerializer,
        responses={200: CardReviewSerializer},
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_mine_partial_update",
        request=CardReviewSerializer,
        responses={200: CardReviewSerializer},
    )
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(
        tags=["reviews"], operation_id="reviews_mine_delete", responses={204: None}
    )
    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)

    def get_queryset(self):
        return CardReview.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        # Editing any review returns it to moderation, preventing edited approved content
        # from appearing publicly before a moderator checks it.
        serializer.save(status=CardReview.Status.PENDING)


class CardReviewSummaryView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = CardReviewSerializer

    @extend_schema(
        parameters=[OpenApiParameter("card_id", int, OpenApiParameter.PATH)],
        responses={200: OpenApiTypes.OBJECT},
        tags=["reviews"],
        operation_id="reviews_card_summary",
    )
    def get(self, request, card_id):
        get_object_or_404(CreditCard, pk=card_id)
        key = f"reviews:summary:card:{card_id}"
        summary = cache.get(key)
        if summary is None:
            approved = CardReview.objects.filter(
                card_id=card_id, status=CardReview.Status.APPROVED
            )
            grouped = {
                row["rating"]: row["count"]
                for row in approved.values("rating").annotate(count=Count("id"))
            }
            summary = {
                "card": card_id,
                "average_rating": approved.aggregate(value=Avg("rating"))["value"],
                "review_count": sum(grouped.values()),
                "distribution": {
                    str(rating): grouped.get(rating, 0) for rating in range(1, 6)
                },
            }
            cache.set(key, summary, 300)
        return Response(summary)


class HelpfulVoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]
    serializer_class = ReviewVoteSerializer

    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT},
        parameters=[OpenApiParameter("review_id", int, OpenApiParameter.PATH)],
        tags=["reviews"],
        operation_id="reviews_helpful_vote",
    )
    def post(self, request, review_id):
        review = get_object_or_404(
            CardReview, pk=review_id, status=CardReview.Status.APPROVED
        )
        if review.user_id == request.user.id:
            raise PermissionDenied("You cannot vote on your own review.")
        with transaction.atomic():
            vote, created = ReviewVote.objects.get_or_create(
                review=review, user=request.user
            )
            if created:
                CardReview.objects.filter(pk=review.pk).update(
                    helpful_count=F("helpful_count") + 1
                )
        review.refresh_from_db(fields=["helpful_count"])
        return Response(
            {"helpful_count": review.helpful_count},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class StaffModerationView(generics.ListAPIView):
    serializer_class = CardReviewSerializer
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_moderation_list",
        responses={200: CardReviewSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = CardReview.objects.filter(status=CardReview.Status.PENDING).select_related(
            "user", "card"
        )
        return qs.order_by("created")


class StaffModerationActionView(StaffModerationView):
    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_moderation_detail",
        responses={200: CardReviewSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["reviews"],
        operation_id="reviews_moderation_update",
        request=OpenApiTypes.OBJECT,
        responses={200: CardReviewSerializer, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request, pk):
        review = get_object_or_404(CardReview, pk=pk)
        new_status = request.data.get("status")
        if new_status not in (CardReview.Status.APPROVED, CardReview.Status.REJECTED):
            return Response(
                {"status": "Choose approved or rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        review.status = new_status
        review.save(update_fields=["status", "modified"])
        return Response(CardReviewSerializer(review).data)
