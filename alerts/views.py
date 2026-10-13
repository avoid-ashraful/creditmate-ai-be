from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.core import signing
from django.shortcuts import get_object_or_404

from .models import AlertSubscription, NotificationPreference
from .serializers import AlertSubscriptionSerializer, NotificationPreferenceSerializer


class SubscriptionListCreateView(generics.ListCreateAPIView):
    serializer_class = AlertSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AlertSubscription.objects.none()
        return AlertSubscription.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SubscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AlertSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AlertSubscription.objects.none()
        return AlertSubscription.objects.filter(user=self.request.user)


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

    def unsubscribe(self, request, token):
        try:
            signing.loads(
                token, salt="alerts.unsubscribe", max_age=60 * 60 * 24 * 365 * 10
            )
        except signing.BadSignature:
            return Response(
                {"detail": "Invalid unsubscribe token."}, status=status.HTTP_404_NOT_FOUND
            )
        subscription = get_object_or_404(AlertSubscription, unsubscribe_token=token)
        subscription.is_active = False
        subscription.save(update_fields=["is_active", "modified"])
        return Response({"detail": "Subscription cancelled."}, status=status.HTTP_200_OK)

    def get(self, request, token):
        return self.unsubscribe(request, token)

    def post(self, request, token):
        return self.unsubscribe(request, token)
