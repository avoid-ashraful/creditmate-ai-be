"""Views for the accounts application."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.utils.translation import gettext_lazy as _

from accounts.serializers import (
    ChangePasswordSerializer,
    EmailVerificationSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    TokenRefreshSerializer,
    UserSerializer,
)

User = get_user_model()


class RegisterView(APIView):
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
        self._send_verification_email(user)

        return Response(
            {
                "detail": _(
                    "Registration successful. Please check your email to verify your account."
                )
            },
            status=status.HTTP_201_CREATED,
        )

    def _send_verification_email(self, user):
        """Send email verification link."""
        signer = TimestampSigner()
        token = signer.sign(user.email)

        verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

        send_mail(
            subject=_("Verify your email address"),
            message=_(
                f"Please click the following link to verify your email: {verification_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )


class LoginView(APIView):
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


class LogoutView(APIView):
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


class TokenRefreshView(APIView):
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
        return Response(
            {"access": serializer.validated_data["access"]},
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(APIView):
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
        """Send password reset email."""
        signer = TimestampSigner()
        uid = signer.sign(user.email)

        reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}"

        send_mail(
            subject=_("Reset your password"),
            message=_(
                f"Please click the following link to reset your password: {reset_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )


class PasswordResetConfirmView(APIView):
    """Confirm password reset with token."""

    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    throttle_scope = "burst"

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["auth"],
        operation_id="auth_password_reset_confirm",
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        return Response(
            {"detail": _("Password has been reset successfully.")},
            status=status.HTTP_200_OK,
        )


class EmailVerificationView(APIView):
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


class MeView(APIView):
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


class ChangePasswordView(APIView):
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
        return Response(
            {"detail": _("Password changed successfully.")},
            status=status.HTTP_200_OK,
        )
