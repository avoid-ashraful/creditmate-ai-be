"""Views for the accounts application."""

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _

from accounts.serializers import (
    ChangePasswordSerializer,
    DeleteAccountSerializer,
    EmailVerificationSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    TokenRefreshSerializer,
    UserSerializer,
)
from accounts.throttling import AuthAnonThrottle, AuthBurstThrottle, AuthUserThrottle
from reviews.models import CardReview, ReviewVote

User = get_user_model()
logger = logging.getLogger(__name__)


def _send_account_email(user, subject, message):
    """Send a transactional account email without ever failing the request.

    Delivery errors are logged (user id only) so the API response cannot be used
    to tell whether an address exists or whether SMTP is healthy.

    Parameters
    ----------
    user : User
        Recipient
    subject : str
        Email subject
    message : str
        Plain-text body

    Returns
    -------
    bool
        True if the email was handed to the backend, False if sending failed
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send account email (user_id=%s)", user.pk)
        return False
    return True


def _send_verification_email(user):
    """Send the email verification link to a user."""
    token = TimestampSigner().sign(user.email)
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    return _send_account_email(
        user,
        _("Verify your email address"),
        _(f"Please click the following link to verify your email: {verification_url}"),
    )


class _AuthBurstThrottleMixin:
    throttle_classes = [AuthBurstThrottle]


class _AuthAnonThrottleMixin:
    throttle_classes = [AuthAnonThrottle]


class _AuthUserThrottleMixin:
    throttle_classes = [AuthUserThrottle]


class RegisterView(_AuthBurstThrottleMixin, APIView):
    """Register a new user."""

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=RegisterSerializer,
        responses={201: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_register",
        examples=[
            OpenApiExample(
                "Registration",
                value={
                    "email": "sam@example.com",
                    "password": "StrongPassword123!",
                    "password_confirm": "StrongPassword123!",
                    "first_name": "Sam",
                    "last_name": "User",
                    "email_opt_in": False,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Send verification email
        _send_verification_email(user)

        return Response(
            {
                "detail": _(
                    "Registration successful. Please check your email to verify your account."
                )
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(_AuthBurstThrottleMixin, APIView):
    """Login user and return JWT tokens."""

    permission_classes = [AllowAny]
    serializer_class = LoginSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=LoginSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_login",
        examples=[
            OpenApiExample(
                "Login",
                value={"email": "sam@example.com", "password": "StrongPassword123!"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        access = serializer.validated_data["access"]
        refresh = serializer.validated_data["refresh"]

        return Response(
            {
                "access": access,
                "refresh": refresh,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(_AuthUserThrottleMixin, APIView):
    """Logout user by blacklisting the refresh token."""

    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer
    throttle_scope = "user"

    @extend_schema(
        request=LogoutSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_logout",
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            {"detail": _("Successfully logged out.")},
            status=status.HTTP_200_OK,
        )


class TokenRefreshView(_AuthBurstThrottleMixin, APIView):
    """Refresh access token using refresh token."""

    permission_classes = [AllowAny]
    serializer_class = TokenRefreshSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=TokenRefreshSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_token_refresh",
    )
    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # ROTATE_REFRESH_TOKENS blacklists the submitted refresh token, so the
        # rotated one must be returned or the client's next refresh is rejected.
        data = {"access": serializer.validated_data["access"]}
        if "refresh" in serializer.validated_data:
            data["refresh"] = serializer.validated_data["refresh"]
        return Response(data, status=status.HTTP_200_OK)


class PasswordResetRequestView(_AuthBurstThrottleMixin, APIView):
    """Request a password reset email."""

    permission_classes = [AllowAny]
    serializer_class = PasswordResetRequestSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=PasswordResetRequestSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_password_reset_request",
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        # Always return success to prevent user enumeration
        # Only send email if user exists
        user = User.objects.filter(username__iexact=email).first()
        if user:
            self._send_reset_email(user)

        return Response(
            {"detail": _("If an account exists, a password reset email has been sent.")},
            status=status.HTTP_200_OK,
        )

    def _send_reset_email(self, user):
        """Send password reset email using Django's default_token_generator."""
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

        _send_account_email(
            user,
            _("Reset your password"),
            _(f"Please click the following link to reset your password: {reset_url}"),
        )


class PasswordResetConfirmView(_AuthBurstThrottleMixin, APIView):
    """Confirm password reset with token."""

    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_password_reset_confirm",
        examples=[
            OpenApiExample(
                "Password Reset Confirm",
                value={
                    "uid": "MQ",
                    "token": "abc123-token",
                    "new_password": "NewStrongPassword123!",
                    "new_password_confirm": "NewStrongPassword123!",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        # Blacklist all outstanding refresh tokens for this user
        self._blacklist_user_refresh_tokens(user)

        return Response(
            {"detail": _("Password has been reset successfully.")},
            status=status.HTTP_200_OK,
        )

    def _blacklist_user_refresh_tokens(self, user):
        """Blacklist all outstanding refresh tokens for a user."""
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        # Get all outstanding tokens for this user and blacklist them
        outstanding_tokens = OutstandingToken.objects.filter(user_id=user.pk)
        for token in outstanding_tokens:
            BlacklistedToken.objects.get_or_create(token=token)


class EmailVerificationView(_AuthBurstThrottleMixin, APIView):
    """Verify user's email address."""

    permission_classes = [AllowAny]
    serializer_class = EmailVerificationSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=EmailVerificationSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_verify_email",
    )
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.context["user"]
        user.profile.email_verified = True
        user.profile.save()

        return Response(
            {"detail": _("Email verified successfully.")},
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(_AuthBurstThrottleMixin, APIView):
    """Resend the verification email to an unverified account."""

    permission_classes = [AllowAny]
    serializer_class = ResendVerificationSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=ResendVerificationSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_resend_verification",
    )
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(
            username__iexact=serializer.validated_data["email"]
        ).first()
        # Same response whether or not the account exists or is verified.
        if user and not user.profile.email_verified:
            _send_verification_email(user)

        return Response(
            {
                "detail": _(
                    "If an unverified account exists, a verification email has been sent."
                )
            },
            status=status.HTTP_200_OK,
        )


class MeView(_AuthUserThrottleMixin, APIView):
    """Get or update current user's profile."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer
    throttle_scope = "user"

    @extend_schema(
        responses={200: UserSerializer}, tags=["auth"], operation_id="auth_me_retrieve"
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=UserSerializer,
        responses={200: UserSerializer},
        tags=["auth"],
        operation_id="auth_me_update",
    )
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=DeleteAccountSerializer,
        responses={204: None},
        tags=["auth"],
        operation_id="auth_me_delete",
    )
    def delete(self, request):
        """Permanently delete the account and its personal data.

        Saved comparisons, collections, alert subscriptions, notification
        preferences and the profile are removed by cascade. Reviews are deleted
        too (not anonymised): review text can carry personal data, and deleting
        keeps public averages equal to the remaining visible reviews because the
        summary cache is invalidated per deleted review. Helpful votes the user
        cast on other reviews are removed and those counters decremented.
        """
        serializer = DeleteAccountSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            voted = ReviewVote.objects.filter(user=request.user).values_list(
                "review_id", flat=True
            )
            CardReview.objects.filter(pk__in=list(voted)).update(
                helpful_count=Greatest(F("helpful_count") - 1, Value(0))
            )
            request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeExportView(_AuthUserThrottleMixin, APIView):
    """Download all personal data held for the current user as JSON."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer
    throttle_scope = "user"

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT}, tags=["auth"], operation_id="auth_me_export"
    )
    def get(self, request):
        user = request.user
        comparisons = [
            {
                "name": c.name,
                "notes": c.notes,
                "is_public": c.is_public,
                "created": c.created,
                "cards": [item.card.name for item in c.items.all()],
            }
            for c in user.saved_comparisons.prefetch_related("items__card")
        ]
        collections = [
            {
                "name": c.name,
                "description": c.description,
                "is_public": c.is_public,
                "created": c.created,
                "items": [
                    {"card": item.card.name, "notes": item.notes}
                    for item in c.items.all()
                ],
            }
            for c in user.saved_collections.prefetch_related("items__card")
        ]
        subscriptions = [
            {
                "card": s.card.name if s.card else None,
                "kind": s.kind,
                "is_active": s.is_active,
                "created": s.created,
            }
            for s in user.alert_subscriptions.select_related("card")
        ]
        preference = getattr(user, "notification_preference", None)
        reviews = [
            {
                "card": r.card.name,
                "rating": r.rating,
                "title": r.title,
                "body": r.body,
                "pros": r.pros,
                "cons": r.cons,
                "status": r.status,
                "created": r.created,
            }
            for r in user.card_reviews.select_related("card")
        ]
        return Response(
            {
                "profile": UserSerializer(user).data,
                "saved_comparisons": comparisons,
                "collections": collections,
                "alert_subscriptions": subscriptions,
                "notification_preference": (
                    {"frequency": preference.frequency} if preference else None
                ),
                "reviews": reviews,
            },
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(_AuthUserThrottleMixin, APIView):
    """Change user's password."""

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer
    throttle_scope = "user"

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_change_password",
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Blacklist all outstanding refresh tokens for this user (password change invalidates tokens)
        self._blacklist_user_refresh_tokens(request.user)

        return Response(
            {"detail": _("Password changed successfully.")},
            status=status.HTTP_200_OK,
        )

    def _blacklist_user_refresh_tokens(self, user):
        """Blacklist all outstanding refresh tokens for a user."""
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        # Get all outstanding tokens for this user and blacklist them
        outstanding_tokens = OutstandingToken.objects.filter(user_id=user.pk)
        for token in outstanding_tokens:
            BlacklistedToken.objects.get_or_create(token=token)
