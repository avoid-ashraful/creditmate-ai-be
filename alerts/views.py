from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from django.core import signing
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import AlertSubscription, NotificationPreference
from .serializers import AlertSubscriptionSerializer, NotificationPreferenceSerializer


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
