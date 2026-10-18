"""Serializers for the accounts application."""

from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenRefreshSerializer as SimpleJWTTokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import UserProfile

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for the UserProfile model."""

    class Meta:
        model = UserProfile
        fields = [
            "email_verified",
            "email_opt_in",
            "marketing_opt_in",
            "terms_accepted_at",
            "terms_version",
            "preferences",
        ]
        read_only_fields = ["email_verified", "terms_accepted_at", "terms_version"]


class UserSerializer(serializers.ModelSerializer):
    """Serializer for the User model with profile data."""

    profile = UserProfileSerializer(required=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "profile"]
        read_only_fields = ["id", "username", "email"]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)
        if profile_data:
            profile_serializer = UserProfileSerializer(
                instance.profile, data=profile_data, partial=True
            )
            profile_serializer.is_valid(raise_exception=True)
            profile_serializer.save()
        return super().update(instance, validated_data)


class RegisterSerializer(serializers.Serializer):
    """Serializer for user registration."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True, min_length=8, validators=[validate_password]
    )
    password_confirm = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email_opt_in = serializers.BooleanField(default=False, required=False)
    accept_terms = serializers.BooleanField(required=True)
    marketing_opt_in = serializers.BooleanField(default=False, required=False)

    def validate_accept_terms(self, value):
        """Require explicit acceptance of the terms and privacy notice."""
        if value is not True:
            raise serializers.ValidationError(
                _("You must accept the terms and privacy notice to register.")
            )
        return value

    def validate_email(self, value):
        """Normalize email to lowercase and check uniqueness."""
        normalized = value.lower().strip()
        if User.objects.filter(username__iexact=normalized).exists():
            raise serializers.ValidationError(_("A user with this email already exists."))
        return normalized

    def validate(self, attrs):
        """Check that passwords match."""
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": _("Passwords do not match.")}
            )
        return attrs

    def create(self, validated_data):
        """Create user with email as username."""
        email = validated_data.pop("email")
        password = validated_data.pop("password")
        validated_data.pop("password_confirm")
        email_opt_in = validated_data.pop("email_opt_in", False)
        validated_data.pop("accept_terms")
        marketing_opt_in = validated_data.pop("marketing_opt_in", False)

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
        )
        profile = user.profile
        profile.email_opt_in = email_opt_in
        profile.marketing_opt_in = marketing_opt_in
        profile.terms_accepted_at = timezone.now()
        profile.terms_version = settings.TERMS_VERSION
        profile.save()

        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """Authenticate user and return tokens."""
        from django.contrib.auth import authenticate

        email = attrs["email"].lower().strip()
        password = attrs["password"]

        user = authenticate(username=email, password=password)
        if not user:
            raise serializers.ValidationError(_("Invalid email or password."))

        if not user.is_active:
            raise serializers.ValidationError(_("This account is inactive."))

        refresh = RefreshToken.for_user(user)
        attrs["user"] = user
        attrs["access"] = str(refresh.access_token)
        attrs["refresh"] = str(refresh)
        return attrs


class LogoutSerializer(serializers.Serializer):
    """Serializer for user logout (blacklist refresh token)."""

    refresh = serializers.CharField()

    def validate_refresh(self, value):
        """Validate the refresh token can be blacklisted."""
        try:
            token = RefreshToken(value)
            token.blacklist()
        except Exception:
            raise serializers.ValidationError(_("Invalid refresh token."))
        return value


class TokenRefreshSerializer(SimpleJWTTokenRefreshSerializer):
    """Serializer for refreshing access token with rotation and reuse detection."""

    def validate(self, attrs):
        """Validate refresh token and return new access (and optionally refresh) token."""
        try:
            return super().validate(attrs)
        except TokenError as e:
            raise serializers.ValidationError({"refresh": str(e)})


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for requesting a password reset."""

    email = serializers.EmailField()

    def validate_email(self, value):
        """Check if user exists (but don't leak existence)."""
        # We intentionally don't raise an error if user doesn't exist
        # to prevent user enumeration
        return value.lower().strip()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for confirming password reset with token."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True, min_length=8, validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """Validate the reset token and passwords match."""
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": _("Passwords do not match.")}
            )

        # Use Django's default_token_generator for proper single-use tokens
        # uid is base64-encoded user pk, token is from default_token_generator
        try:
            from django.utils.http import urlsafe_base64_decode

            user_pk = urlsafe_base64_decode(attrs["uid"]).decode()
            user = User.objects.get(pk=user_pk)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError(_("Invalid password reset link."))

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                _("Invalid or expired password reset link.")
            )

        attrs["user"] = user
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    """Serializer for email verification."""

    token = serializers.CharField()

    def validate_token(self, value):
        """Validate the verification token."""
        signer = TimestampSigner()
        try:
            email = signer.unsign(value, max_age=86400)  # 24 hour expiry
        except SignatureExpired:
            raise serializers.ValidationError(_("Verification link has expired."))
        except BadSignature:
            raise serializers.ValidationError(_("Invalid verification link."))

        user = User.objects.filter(username__iexact=email).first()
        if not user:
            raise serializers.ValidationError(_("Invalid verification link."))

        if user.profile.email_verified:
            raise serializers.ValidationError(_("Email is already verified."))

        self.context["user"] = user
        return value


class ResendVerificationSerializer(serializers.Serializer):
    """Serializer for requesting a new verification email."""

    email = serializers.EmailField()

    def validate_email(self, value):
        """Normalize only; never reveal whether the account exists."""
        return value.lower().strip()


class DeleteAccountSerializer(serializers.Serializer):
    """Serializer confirming account deletion with the current password."""

    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        """Require the current password."""
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError(_("Current password is incorrect."))
        return value


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password."""

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True, min_length=8, validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """Validate old password and confirm new passwords match."""
        user = self.context["request"].user
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError(
                {"old_password": _("Current password is incorrect.")}
            )

        if attrs["new_password"] == attrs["old_password"]:
            raise serializers.ValidationError(
                {
                    "new_password": _(
                        "New password must be different from current password."
                    )
                }
            )

        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": _("Passwords do not match.")}
            )

        return attrs

    def save(self):
        """Change the user's password."""
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user
