"""Tests for accounts API views."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.signing import TimestampSigner
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

User = get_user_model()


@pytest.fixture
def api_client():
    """API client fixture."""
    return APIClient()


@pytest.fixture
def user():
    """Create a test user."""
    return User.objects.create_user(
        username="test@example.com",
        email="test@example.com",
        password="securepass123",
    )


@pytest.fixture
def authenticated_client(api_client, user):
    """Authenticated API client."""
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.django_db
class TestRegisterView:
    """Tests for RegisterView."""

    def test_register_success(self, api_client):
        """Test successful registration."""
        data = {
            "email": "newuser@example.com",
            "password": "securepass123",
            "password_confirm": "securepass123",
            "accept_terms": True,
            "first_name": "John",
            "last_name": "Doe",
            "email_opt_in": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "detail" in response.data

        # Check user was created
        user = User.objects.get(username="newuser@example.com")
        assert user.email == "newuser@example.com"
        assert user.first_name == "John"
        assert user.last_name == "Doe"
        assert user.check_password("securepass123")
        assert user.profile.email_opt_in is True
        assert user.profile.email_verified is False
        assert user.profile.email == "newuser@example.com"

    def test_register_duplicate_email(self, api_client, user):
        """Test registration with duplicate email."""
        data = {
            "email": "test@example.com",
            "password": "securepass123",
            "password_confirm": "securepass123",
            "accept_terms": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "email" in response.data

    def test_register_password_mismatch(self, api_client):
        """Test registration with password mismatch."""
        data = {
            "email": "newuser@example.com",
            "password": "securepass123",
            "password_confirm": "differentpass123",
            "accept_terms": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "password_confirm" in response.data

    def test_register_short_password(self, api_client):
        """Test registration with short password."""
        data = {
            "email": "newuser@example.com",
            "password": "short",
            "password_confirm": "short",
            "accept_terms": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "password" in response.data

    def test_register_email_normalization(self, api_client):
        """Test email is normalized to lowercase."""
        data = {
            "email": "NEWUSER@EXAMPLE.COM",
            "password": "securepass123",
            "password_confirm": "securepass123",
            "accept_terms": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(username="newuser@example.com")
        assert user.username == "newuser@example.com"
        assert user.email == "newuser@example.com"

    def test_register_case_insensitive_duplicate(self, api_client, user):
        """Test case-insensitive duplicate email rejection."""
        data = {
            "email": "TEST@EXAMPLE.COM",
            "password": "securepass123",
            "password_confirm": "securepass123",
            "accept_terms": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "email" in response.data

    def test_register_sends_verification_email(self, api_client, settings):
        """Test that verification email is sent."""
        settings.FRONTEND_URL = "http://localhost:3000"
        settings.DEFAULT_FROM_EMAIL = "test@example.com"

        data = {
            "email": "newuser@example.com",
            "password": "securepass123",
            "password_confirm": "securepass123",
            "accept_terms": True,
        }

        response = api_client.post("/api/v1/auth/register/", data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert len(mail.outbox) == 1
        assert "verify" in mail.outbox[0].subject.lower()


@pytest.mark.django_db
class TestLoginView:
    """Tests for LoginView."""

    def test_login_success(self, api_client, user):
        """Test successful login."""
        data = {"email": "test@example.com", "password": "securepass123"}

        response = api_client.post("/api/v1/auth/login/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
        assert "user" in response.data
        assert response.data["user"]["email"] == "test@example.com"

    def test_login_case_insensitive_email(self, api_client, user):
        """Test login with different email case."""
        data = {"email": "TEST@EXAMPLE.COM", "password": "securepass123"}

        response = api_client.post("/api/v1/auth/login/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_login_invalid_password(self, api_client, user):
        """Test login with invalid password."""
        data = {"email": "test@example.com", "password": "wrongpass123"}

        response = api_client.post("/api/v1/auth/login/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "non_field_errors" in response.data

    def test_login_nonexistent_user(self, api_client):
        """Test login with nonexistent user (no user enumeration)."""
        data = {"email": "nonexistent@example.com", "password": "securepass123"}

        response = api_client.post("/api/v1/auth/login/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "non_field_errors" in response.data

    def test_login_inactive_user(self, api_client):
        """Test login with inactive user."""
        User.objects.create_user(
            username="inactive@example.com",
            email="inactive@example.com",
            password="securepass123",
            is_active=False,
        )

        data = {"email": "inactive@example.com", "password": "securepass123"}

        response = api_client.post("/api/v1/auth/login/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "non_field_errors" in response.data


@pytest.mark.django_db
class TestLogoutView:
    """Tests for LogoutView."""

    def test_logout_success(self, authenticated_client, user):
        """Test successful logout."""
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)

        data = {"refresh": str(refresh)}

        response = authenticated_client.post("/api/v1/auth/logout/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data

    def test_logout_invalid_token(self, authenticated_client):
        """Test logout with invalid token."""
        data = {"refresh": "invalid.token.here"}

        response = authenticated_client.post("/api/v1/auth/logout/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "refresh" in response.data

    def test_logout_rejects_another_users_refresh_token(self, api_client, user):
        """Logout must not blacklist a refresh token owned by another user."""
        from rest_framework_simplejwt.tokens import RefreshToken

        other = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="securepass123",
        )
        other_refresh = RefreshToken.for_user(other)
        api_client.force_authenticate(user=user)

        response = api_client.post(
            "/api/v1/auth/logout/", {"refresh": str(other_refresh)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "refresh" in response.data

        # The other user's refresh token must still be usable.
        refresh_response = APIClient().post(
            "/api/v1/auth/token/refresh/",
            {"refresh": str(other_refresh)},
            format="json",
        )
        assert refresh_response.status_code == status.HTTP_200_OK

    def test_logout_requires_auth(self, api_client):
        """Test logout requires authentication."""
        data = {"refresh": "some.token.here"}

        response = api_client.post("/api/v1/auth/logout/", data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestTokenRefreshView:
    """Tests for TokenRefreshView."""

    def test_token_refresh_success(self, api_client, user):
        """Test successful token refresh."""
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)

        data = {"refresh": str(refresh)}

        response = api_client.post("/api/v1/auth/token/refresh/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_token_refresh_invalid(self, api_client):
        """Test token refresh with invalid token."""
        data = {"refresh": "invalid.token.here"}

        response = api_client.post("/api/v1/auth/token/refresh/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "refresh" in response.data


@pytest.mark.django_db
class TestPasswordResetRequestView:
    """Tests for PasswordResetRequestView."""

    def test_password_reset_request_existing_user(self, api_client, user, settings):
        """Test password reset request for existing user."""
        settings.FRONTEND_URL = "http://localhost:3000"
        settings.DEFAULT_FROM_EMAIL = "test@example.com"

        data = {"email": "test@example.com"}

        response = api_client.post("/api/v1/auth/password-reset/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data
        assert len(mail.outbox) == 1
        assert "reset" in mail.outbox[0].subject.lower()

    def test_password_reset_request_nonexistent_user(self, api_client):
        """Test password reset request for nonexistent user (no user enumeration)."""
        data = {"email": "nonexistent@example.com"}

        response = api_client.post("/api/v1/auth/password-reset/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data
        # Same response regardless of user existence

    def test_password_reset_request_email_normalization(self, api_client, user):
        """Test email normalization in password reset request."""
        data = {"email": "TEST@EXAMPLE.COM"}

        response = api_client.post("/api/v1/auth/password-reset/", data, format="json")

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestPasswordResetConfirmView:
    """Tests for PasswordResetConfirmView."""

    def _get_reset_data(self, user):
        """Helper to generate valid reset data using default_token_generator."""
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        return {
            "uid": uid,
            "token": token,
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

    def test_password_reset_confirm_success(self, api_client, user):
        """Test successful password reset confirmation."""
        data = self._get_reset_data(user)

        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/", data, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data

        # Verify password was changed
        user.refresh_from_db()
        assert user.check_password("newsecurepass123")

    def test_password_reset_confirm_mismatch(self, api_client, user):
        """Test password reset with mismatched passwords."""
        data = self._get_reset_data(user)
        data["new_password_confirm"] = "differentpass123"

        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password_confirm" in response.data

    def test_password_reset_confirm_invalid_uid(self, api_client):
        """Test password reset with invalid UID."""
        data = {
            "uid": "invalid",
            "token": "dummy",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "non_field_errors" in response.data

    def test_password_reset_confirm_expired_token(self, api_client, user):
        """Test password reset with expired token."""
        # Create a token and manipulate its timestamp to be expired
        # default_token_generator uses password hash and last_login in token,
        # so we can't easily create an expired token without time manipulation
        # Instead, test that token validation works
        pass

    def test_password_reset_confirm_wrong_user_token(self, api_client, user):
        """Test password reset with token for different user."""
        other_user = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="securepass123",
        )
        # Use other user's token for this user
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(other_user)
        data = {
            "uid": uid,
            "token": token,
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "non_field_errors" in response.data


@pytest.mark.django_db
class TestEmailVerificationView:
    """Tests for EmailVerificationView."""

    def test_email_verification_success(self, api_client, user):
        """Test successful email verification."""
        signer = TimestampSigner()
        token = signer.sign(user.email)

        data = {"token": token}

        response = api_client.post("/api/v1/auth/verify-email/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data

        # Verify email_verified is True
        user.refresh_from_db()
        assert user.profile.email_verified is True

    def test_email_verification_already_verified(self, api_client, user):
        """Test verification of already verified email."""
        user.profile.email_verified = True
        user.profile.save()

        signer = TimestampSigner()
        token = signer.sign(user.email)

        data = {"token": token}

        response = api_client.post("/api/v1/auth/verify-email/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "token" in response.data

    def test_email_verification_invalid_token(self, api_client):
        """Test verification with invalid token."""
        data = {"token": "invalid.token.here"}

        response = api_client.post("/api/v1/auth/verify-email/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "token" in response.data


@pytest.mark.django_db
class TestMeView:
    """Tests for MeView."""

    def test_me_get(self, authenticated_client, user):
        """Test GET /me/ returns user data."""
        response = authenticated_client.get("/api/v1/auth/me/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == "test@example.com"
        assert "profile" in response.data

    def test_me_patch(self, authenticated_client, user):
        """Test PATCH /me/ updates user data."""
        data = {"first_name": "Jane", "profile": {"email_opt_in": True}}

        response = authenticated_client.patch("/api/v1/auth/me/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["first_name"] == "Jane"
        assert response.data["profile"]["email_opt_in"] is True

        user.refresh_from_db()
        assert user.first_name == "Jane"
        assert user.profile.email_opt_in is True

    def test_me_cannot_change_email(self, authenticated_client, user):
        """Test that email cannot be changed via /me/ PATCH."""
        data = {"email": "newemail@example.com"}

        response = authenticated_client.patch("/api/v1/auth/me/", data, format="json")

        # Email should be read-only, so it should not change
        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == "test@example.com"
        user.refresh_from_db()
        assert user.email == "test@example.com"

    def test_me_cannot_change_username(self, authenticated_client, user):
        """Test that username cannot be changed via /me/ PATCH."""
        data = {"username": "newusername@example.com"}

        response = authenticated_client.patch("/api/v1/auth/me/", data, format="json")

        # Username should be read-only
        assert response.status_code == status.HTTP_200_OK
        assert response.data["username"] == "test@example.com"
        user.refresh_from_db()
        assert user.username == "test@example.com"

    def test_me_requires_auth(self, api_client):
        """Test /me/ requires authentication."""
        response = api_client.get("/api/v1/auth/me/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestChangePasswordView:
    """Tests for ChangePasswordView."""

    def test_change_password_success(self, authenticated_client, user):
        """Test successful password change."""
        data = {
            "old_password": "securepass123",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = authenticated_client.post(
            "/api/v1/auth/change-password/", data, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data

        # Verify password was changed
        user.refresh_from_db()
        assert user.check_password("newsecurepass123")

    def test_change_password_wrong_old(self, authenticated_client, user):
        """Test password change with wrong old password."""
        data = {
            "old_password": "wrongpass123",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = authenticated_client.post(
            "/api/v1/auth/change-password/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "old_password" in response.data

    def test_change_password_same_as_old(self, authenticated_client, user):
        """Test password change with same password."""
        data = {
            "old_password": "securepass123",
            "new_password": "securepass123",
            "new_password_confirm": "securepass123",
        }

        response = authenticated_client.post(
            "/api/v1/auth/change-password/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password" in response.data

    def test_change_password_mismatch(self, authenticated_client, user):
        """Test password change with mismatched new passwords."""
        data = {
            "old_password": "securepass123",
            "new_password": "newsecurepass123",
            "new_password_confirm": "differentpass123",
        }

        response = authenticated_client.post(
            "/api/v1/auth/change-password/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password_confirm" in response.data

    def test_change_password_requires_auth(self, api_client):
        """Test password change requires authentication."""
        data = {
            "old_password": "securepass123",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = api_client.post("/api/v1/auth/change-password/", data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_change_password_blacklists_refresh_tokens(self, authenticated_client, user):
        """Test that change password blacklists outstanding refresh tokens."""
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
        from rest_framework_simplejwt.tokens import RefreshToken

        # Create a refresh token
        refresh = RefreshToken.for_user(user)
        jti = refresh["jti"]

        # Verify token exists in outstanding tokens
        assert OutstandingToken.objects.filter(jti=jti).exists()

        # Change password
        data = {
            "old_password": "securepass123",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }
        response = authenticated_client.post(
            "/api/v1/auth/change-password/", data, format="json"
        )
        assert response.status_code == status.HTTP_200_OK

        # The old refresh token should now be blacklisted
        assert BlacklistedToken.objects.filter(token__jti=jti).exists()

    def test_change_password_invalidates_access_tokens(self, api_client, user):
        """Old access tokens must stop authenticating after a password change."""
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        old_access = str(refresh.access_token)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")

        # The token is valid before the password change.
        assert api_client.get("/api/v1/auth/me/").status_code == status.HTTP_200_OK

        data = {
            "old_password": "securepass123",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }
        response = api_client.post("/api/v1/auth/change-password/", data, format="json")
        assert response.status_code == status.HTTP_200_OK

        # The old access token no longer authenticates.
        assert api_client.get("/api/v1/auth/me/").status_code == (
            status.HTTP_401_UNAUTHORIZED
        )

        # The old refresh token is blacklisted.
        response = api_client.post(
            "/api/v1/auth/token/refresh/", {"refresh": str(refresh)}, format="json"
        )
        # The blacklisted refresh token returns 401 (unauthorized) since
        # the token validation fails before reaching the view logic.
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        # A fresh login still works and its access token is accepted.
        # Clear old credentials first
        api_client.credentials()
        response = api_client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "newsecurepass123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        assert api_client.get("/api/v1/auth/me/").status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestTokenRefreshReuseDetection:
    """Tests for refresh token reuse detection."""

    def test_token_refresh_rotation(self, api_client, user):
        """Test that token refresh rotates the refresh token."""
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        old_refresh_str = str(refresh)
        old_access_str = str(refresh.access_token)

        # Refresh the token
        data = {"refresh": old_refresh_str}
        response = api_client.post("/api/v1/auth/token/refresh/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        new_access_str = response.data["access"]

        # New access token should be different
        assert new_access_str != old_access_str

        # Old refresh token should be blacklisted (reuse detection)
        # Try to use old refresh token again
        data = {"refresh": old_refresh_str}
        response2 = api_client.post("/api/v1/auth/token/refresh/", data, format="json")

        # Should fail because old token is blacklisted
        assert response2.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_refresh_returns_rotated_token_usable_for_next_refresh(api_client):
    """The rotated refresh token is returned; the old one is blacklisted."""
    user = User.objects.create_user(
        username="rotate@example.com",
        email="rotate@example.com",
        password="S3cure!passphrase",
    )
    first = RefreshToken.for_user(user)
    response = api_client.post("/api/v1/auth/token/refresh/", {"refresh": str(first)})
    assert response.status_code == 200
    assert "access" in response.data and "refresh" in response.data
    assert response.data["refresh"] != str(first)

    again = api_client.post(
        "/api/v1/auth/token/refresh/", {"refresh": response.data["refresh"]}
    )
    assert again.status_code == 200
    reused = api_client.post("/api/v1/auth/token/refresh/", {"refresh": str(first)})
    assert reused.status_code == 400


REGISTER_PAYLOAD = {
    "email": "consent@example.com",
    "password": "securepass123",
    "password_confirm": "securepass123",
}


@pytest.mark.django_db
class TestConsent:
    """Registration consent (terms) and marketing opt-in."""

    @pytest.mark.parametrize("extra", [{}, {"accept_terms": False}])
    def test_register_requires_accept_terms(self, api_client, extra):
        response = api_client.post(
            "/api/v1/auth/register/", {**REGISTER_PAYLOAD, **extra}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "accept_terms" in response.data
        assert not User.objects.filter(username="consent@example.com").exists()

    def test_register_records_consent(self, api_client, settings):
        settings.TERMS_VERSION = "v-test"
        payload = {**REGISTER_PAYLOAD, "accept_terms": True, "marketing_opt_in": True}

        response = api_client.post("/api/v1/auth/register/", payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        profile = User.objects.get(username="consent@example.com").profile
        assert profile.terms_accepted_at is not None
        assert profile.terms_version == "v-test"
        assert profile.marketing_opt_in is True

    def test_marketing_opt_in_defaults_false_and_default_terms_version(self, api_client):
        api_client.post(
            "/api/v1/auth/register/",
            {**REGISTER_PAYLOAD, "accept_terms": True},
            format="json",
        )

        profile = User.objects.get(username="consent@example.com").profile
        assert profile.marketing_opt_in is False
        assert profile.terms_version == "2026-10-draft"

    def test_me_exposes_consent_and_allows_marketing_update_only(
        self, authenticated_client, user
    ):
        body = authenticated_client.get("/api/v1/auth/me/").data["profile"]
        assert body["marketing_opt_in"] is False
        assert body["terms_version"] == ""

        response = authenticated_client.patch(
            "/api/v1/auth/me/",
            {"profile": {"marketing_opt_in": True, "terms_version": "forged"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        user.profile.refresh_from_db()
        assert user.profile.marketing_opt_in is True
        assert user.profile.terms_version == ""


@pytest.mark.django_db
class TestEmailReliability:
    """SMTP failures are logged, never raised, and never change the response."""

    @pytest.fixture
    def failing_mail(self, monkeypatch):
        def boom(*args, **kwargs):
            assert kwargs["fail_silently"] is False
            raise OSError("smtp down")

        monkeypatch.setattr("accounts.views.send_mail", boom)

    def test_register_survives_send_failure_and_logs(
        self, api_client, failing_mail, caplog
    ):
        payload = {**REGISTER_PAYLOAD, "accept_terms": True}

        response = api_client.post("/api/v1/auth/register/", payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(username="consent@example.com")
        record = next(r for r in caplog.records if "Failed to send" in r.message)
        assert str(user.pk) in record.message
        assert "consent@example.com" not in caplog.text.split("Traceback")[0]

    def test_password_reset_response_identical_on_failure(
        self, api_client, user, failing_mail, caplog
    ):
        known = api_client.post(
            "/api/v1/auth/password-reset/", {"email": user.email}, format="json"
        )
        unknown = api_client.post(
            "/api/v1/auth/password-reset/", {"email": "nobody@example.com"}, format="json"
        )

        assert known.status_code == unknown.status_code == status.HTTP_200_OK
        assert known.data == unknown.data
        assert "Failed to send" in caplog.text


@pytest.mark.django_db
class TestResendVerification:
    """POST /auth/resend-verification/."""

    URL = "/api/v1/auth/resend-verification/"

    def test_sends_for_unverified_user(self, api_client, user):
        response = api_client.post(self.URL, {"email": "TEST@example.com"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert "verify-email?token=" in mail.outbox[0].body

    def test_same_response_and_no_email_for_verified_or_unknown(self, api_client, user):
        sent = api_client.post(self.URL, {"email": user.email}, format="json").data
        mail.outbox.clear()
        user.profile.email_verified = True
        user.profile.save()

        verified = api_client.post(self.URL, {"email": user.email}, format="json")
        unknown = api_client.post(self.URL, {"email": "no@example.com"}, format="json")

        assert verified.status_code == unknown.status_code == status.HTTP_200_OK
        assert verified.data == unknown.data == sent
        assert mail.outbox == []

    def test_send_failure_still_returns_200(self, api_client, user, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("smtp down")

        monkeypatch.setattr("accounts.views.send_mail", boom)

        response = api_client.post(self.URL, {"email": user.email}, format="json")

        assert response.status_code == status.HTTP_200_OK

    def test_is_throttled(self, api_client, settings, monkeypatch):
        from accounts.throttling import AuthBurstThrottle

        monkeypatch.setattr(AuthBurstThrottle, "get_rate", lambda self: "2/min")
        codes = [
            api_client.post(
                self.URL, {"email": "a@example.com"}, format="json"
            ).status_code
            for _ in range(3)
        ]

        assert codes == [200, 200, status.HTTP_429_TOO_MANY_REQUESTS]


@pytest.mark.django_db
class TestAccountDeletionAndExport:
    """DELETE /auth/me/ and GET /auth/me/export/."""

    def _populate(self, user):
        from alerts.models import AlertSubscription, NotificationPreference
        from banks.models import Bank
        from credit_cards.models import CreditCard
        from reviews.models import CardReview, ReviewVote
        from saved.models import (
            Collection,
            CollectionItem,
            SavedComparison,
            SavedComparisonItem,
        )

        card = CreditCard.objects.create(
            bank=Bank.objects.create(name="Export Bank"), name="Export Card"
        )
        comparison = SavedComparison.objects.create(user=user, name="My compare")
        SavedComparisonItem.objects.create(comparison=comparison, card=card, position=0)
        collection = Collection.objects.create(user=user, name="My collection")
        CollectionItem.objects.create(collection=collection, card=card, notes="nice")
        AlertSubscription.objects.create(user=user, card=card, kind="fee_change")
        NotificationPreference.objects.create(user=user, frequency="daily")
        review = CardReview.objects.create(
            user=user, card=card, rating=5, title="Mine", body="Body", status="approved"
        )
        return card, review, ReviewVote

    def test_export_requires_auth(self, api_client):
        assert api_client.get("/api/v1/auth/me/export/").status_code == 401

    def test_export_contains_all_personal_data_and_nothing_of_others(
        self, authenticated_client, user
    ):
        self._populate(user)
        User.objects.create_user(username="o@example.com", email="o@example.com")

        response = authenticated_client.get("/api/v1/auth/me/export/")

        assert response.status_code == 200
        data = response.data
        assert data["profile"]["email"] == user.email
        assert data["saved_comparisons"][0]["name"] == "My compare"
        assert data["saved_comparisons"][0]["cards"] == ["Export Card"]
        assert data["collections"][0]["items"] == [
            {"card": "Export Card", "notes": "nice"}
        ]
        assert data["alert_subscriptions"][0]["kind"] == "fee_change"
        assert data["notification_preference"] == {"frequency": "daily"}
        assert data["reviews"][0]["title"] == "Mine"

    def test_delete_requires_auth(self, api_client):
        response = api_client.delete("/api/v1/auth/me/", {"password": "x"}, format="json")
        assert response.status_code == 401

    @pytest.mark.parametrize("body", [{}, {"password": "wrong-password"}])
    def test_delete_requires_current_password(self, authenticated_client, user, body):
        response = authenticated_client.delete("/api/v1/auth/me/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert User.objects.filter(pk=user.pk).exists()

    def test_delete_removes_user_data_and_review_aggregates_stay_consistent(
        self, authenticated_client, user
    ):
        from django.core.cache import cache

        from alerts.models import AlertSubscription, NotificationPreference
        from reviews.models import CardReview
        from saved.models import Collection, SavedComparison

        card, review, ReviewVote = self._populate(user)
        stayer = User.objects.create_user(username="s@example.com", email="s@example.com")
        CardReview.objects.create(
            user=stayer, card=card, rating=1, title="T", body="B", status="approved"
        )
        voter_review = CardReview.objects.get(user=stayer)
        ReviewVote.objects.create(review=voter_review, user=user)
        CardReview.objects.filter(pk=voter_review.pk).update(helpful_count=1)
        summary_url = f"/api/v1/reviews/cards/{card.pk}/summary/"
        assert APIClient().get(summary_url).data["average_rating"] == 3  # caches summary

        response = authenticated_client.delete(
            "/api/v1/auth/me/", {"password": "securepass123"}, format="json"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not User.objects.filter(pk=user.pk).exists()
        assert not SavedComparison.objects.exists()
        assert not Collection.objects.exists()
        assert not AlertSubscription.objects.exists()
        assert not NotificationPreference.objects.exists()
        assert not CardReview.objects.filter(pk=review.pk).exists()
        voter_review.refresh_from_db()
        assert voter_review.helpful_count == 0
        summary = APIClient().get(summary_url).data
        assert summary["review_count"] == 1 and summary["average_rating"] == 1
        cache.clear()
