"""Views for the accounts application."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
    throttle_scope = "burst"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Send verification email
        self._send_verification_email(user)

        return Response(
            {"detail": _("Registration successful. Please check your email to verify your account.")},
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
    throttle_scope = "burst"

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
    throttle_scope = "user"

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
    throttle_scope = "burst"

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
    throttle_scope = "burst"

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
    throttle_scope = "burst"

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
    throttle_scope = "burst"

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
    throttle_scope = "user"

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):
    """Change user's password."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "user"

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": _("Password changed successfully.")},
            status=status.HTTP_200_OK,
        )
