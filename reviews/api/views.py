from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, F
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from credit_cards.models import CreditCard
from reviews.models import CardReview, ReviewVote
from .serializers import CardReviewSerializer
from .throttles import ReviewUserThrottle


class PublicReviewListCreateView(generics.ListCreateAPIView):
    serializer_class = CardReviewSerializer
    throttle_classes = [ReviewUserThrottle]
    throttle_scope = "review_write"

    def get_queryset(self):
        qs = CardReview.objects.filter(status=CardReview.Status.APPROVED).select_related("user", "card")
        card_id = self.request.query_params.get("card")
        return qs.filter(card_id=card_id) if card_id else qs

    def get_permissions(self):
        return [permissions.IsAuthenticated()] if self.request.method == "POST" else [permissions.AllowAny()]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, status=CardReview.Status.PENDING)


class OwnReviewDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CardReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]

    def get_queryset(self):
        return CardReview.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        # Editing any review returns it to moderation, preventing edited approved content
        # from appearing publicly before a moderator checks it.
        serializer.save(status=CardReview.Status.PENDING)


class CardReviewSummaryView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("card_id", int, OpenApiParameter.PATH)])
    def get(self, request, card_id):
        get_object_or_404(CreditCard, pk=card_id)
        key = f"reviews:summary:card:{card_id}"
        summary = cache.get(key)
        if summary is None:
            approved = CardReview.objects.filter(card_id=card_id, status=CardReview.Status.APPROVED)
            grouped = {row["rating"]: row["count"] for row in approved.values("rating").annotate(count=Count("id"))}
            summary = {
                "card": card_id,
                "average_rating": approved.aggregate(value=Avg("rating"))["value"],
                "review_count": sum(grouped.values()),
                "distribution": {str(rating): grouped.get(rating, 0) for rating in range(1, 6)},
            }
            cache.set(key, summary, 300)
        return Response(summary)


class HelpfulVoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]

    def post(self, request, review_id):
        review = get_object_or_404(CardReview, pk=review_id, status=CardReview.Status.APPROVED)
        if review.user_id == request.user.id:
            raise PermissionDenied("You cannot vote on your own review.")
        with transaction.atomic():
            vote, created = ReviewVote.objects.get_or_create(review=review, user=request.user)
            if created:
                CardReview.objects.filter(pk=review.pk).update(helpful_count=F("helpful_count") + 1)
        review.refresh_from_db(fields=["helpful_count"])
        return Response({"helpful_count": review.helpful_count}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class StaffModerationView(generics.ListAPIView):
    serializer_class = CardReviewSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        qs = CardReview.objects.filter(status=CardReview.Status.PENDING).select_related("user", "card")
        return qs.order_by("created")

    def post(self, request, pk):
        review = get_object_or_404(CardReview, pk=pk)
        new_status = request.data.get("status")
        if new_status not in (CardReview.Status.APPROVED, CardReview.Status.REJECTED):
            return Response({"status": "Choose approved or rejected."}, status=status.HTTP_400_BAD_REQUEST)
        review.status = new_status
        review.save(update_fields=["status", "modified"])
        return Response(CardReviewSerializer(review).data)
