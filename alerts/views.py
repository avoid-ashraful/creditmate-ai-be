from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from django.core import signing
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .feed import build_follow_feed
from .models import AlertSubscription, BankFollow, NotificationPreference
from .serializers import (
    AlertSubscriptionSerializer,
    BankFollowFeedEntrySerializer,
    BankFollowSerializer,
    NotificationPreferenceSerializer,
)


class SubscriptionListCreateView(generics.ListCreateAPIView):
    serializer_class = AlertSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AlertSubscription.objects.none()
        return AlertSubscription.objects.filter(user=self.request.user).select_related(
            "card__bank"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class BankFollowPagination(PageNumberPagination):
    """Follows are bounded by the bank catalogue (~61 banks), so one page
    must be able to hold all of them: the global page size (20) silently
    truncated follow state for users following many banks (Phase 2 review
    L4). Clients may still page explicitly via ?page_size=."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 200


@extend_schema_view(
    get=extend_schema(
        responses={200: BankFollowSerializer(many=True)},
        tags=["alerts"],
        operation_id="alerts_bank_follows_list",
        description="List the banks the current user follows.",
    ),
    post=extend_schema(
        request=BankFollowSerializer,
        responses={201: BankFollowSerializer, 200: BankFollowSerializer},
        tags=["alerts"],
        operation_id="alerts_bank_follows_follow",
        description=(
            "Follow a bank. Idempotent: following a bank you already "
            "follow returns the existing follow with 200, not an error."
        ),
    ),
)
class BankFollowListCreateView(generics.ListCreateAPIView):
    serializer_class = BankFollowSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = BankFollowPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BankFollow.objects.none()
        return BankFollow.objects.filter(user=self.request.user).select_related("bank")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = serializer.validated_data["bank"]
        try:
            follow, created = BankFollow.objects.get_or_create(
                user=request.user, bank=bank
            )
        except IntegrityError:
            # A concurrent first-follow for the same (user, bank) won the
            # race to the unique constraint; the follow exists, which is
            # exactly the idempotent outcome (Phase 2 review L3).
            follow = BankFollow.objects.get(user=request.user, bank=bank)
            created = False
        return Response(
            self.get_serializer(follow).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@extend_schema_view(
    delete=extend_schema(
        responses={204: None},
        tags=["alerts"],
        operation_id="alerts_bank_follows_unfollow",
        description=(
            "Unfollow a bank by bank id. Idempotent: unfollowing a bank "
            "you do not follow still returns 204."
        ),
    )
)
class BankFollowDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, bank_id: int):
        BankFollow.objects.filter(user=request.user, bank_id=bank_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        tags=["alerts"],
        operation_id="alerts_bank_follow_feed",
        description=(
            "Field-change events at the banks the current user follows, "
            "across all four verticals, newest first. Offset-paginated "
            "with an exact has_more flag (no invented total count)."
        ),
        parameters=[
            OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
    )
)
class BankFollowFeedView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BankFollowFeedEntrySerializer

    def get(self, request):
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            page_size = 20
        page_size = min(50, max(1, page_size))
        entries, has_more = build_follow_feed(request.user, page, page_size)
        return Response(
            {
                "results": BankFollowFeedEntrySerializer(entries, many=True).data,
                "page": page,
                "page_size": page_size,
                "has_more": has_more,
            }
        )


class SubscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AlertSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AlertSubscription.objects.none()
        return AlertSubscription.objects.filter(user=self.request.user).select_related(
            "card__bank"
        )


@extend_schema_view(
    get=extend_schema(
        responses={200: NotificationPreferenceSerializer},
        tags=["alerts"],
        operation_id="alerts_preferences_retrieve",
    ),
    put=extend_schema(
        request=NotificationPreferenceSerializer,
        responses={200: NotificationPreferenceSerializer},
        tags=["alerts"],
        operation_id="alerts_preferences_replace",
    ),
    patch=extend_schema(
        request=NotificationPreferenceSerializer,
        responses={200: NotificationPreferenceSerializer},
        tags=["alerts"],
        operation_id="alerts_preferences_update",
    ),
)
class PreferenceView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer

    def get_object(self):
        preference, _ = NotificationPreference.objects.get_or_create(
            user=self.request.user
        )
        return preference

    def get(self, request):
        return Response(NotificationPreferenceSerializer(self.get_object()).data)

    def put(self, request):
        serializer = NotificationPreferenceSerializer(
            self.get_object(), data=request.data
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def patch(self, request):
        serializer = NotificationPreferenceSerializer(
            self.get_object(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema_view(
    get=extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        parameters=[OpenApiParameter("token", OpenApiTypes.STR, OpenApiParameter.PATH)],
        tags=["alerts"],
        operation_id="alerts_unsubscribe_get",
        description="Read-only: returns the subscription; POST performs the unsubscribe.",
    ),
    post=extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        parameters=[OpenApiParameter("token", OpenApiTypes.STR, OpenApiParameter.PATH)],
        tags=["alerts"],
        operation_id="alerts_unsubscribe_post",
    ),
)
class PublicUnsubscribeView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = serializers.Serializer

    def get_subscription(self, token):
        """Return the subscription for a valid signed token, else 404."""
        try:
            signing.loads(
                token, salt="alerts.unsubscribe", max_age=60 * 60 * 24 * 365 * 10
            )
        except signing.BadSignature:
            raise NotFound("Invalid unsubscribe token.")
        return get_object_or_404(
            AlertSubscription.objects.select_related("card"), unsubscribe_token=token
        )

    def get(self, request, token):
        """Describe the subscription without changing it (safe for link scanners)."""
        subscription = self.get_subscription(token)
        return Response(
            {
                "confirm_required": True,
                "is_active": subscription.is_active,
                "kind": subscription.kind,
                "card_name": subscription.card.name if subscription.card else None,
            }
        )

    def post(self, request, token):
        """Cancel every active alert subscription of the token's owner.

        One alert email covers all of a user's subscriptions, so its single
        unsubscribe link must stop them all.
        """
        subscription = self.get_subscription(token)
        AlertSubscription.objects.filter(
            user_id=subscription.user_id, is_active=True
        ).update(is_active=False, modified=timezone.now())
        return Response({"detail": "Subscription cancelled."}, status=status.HTTP_200_OK)
