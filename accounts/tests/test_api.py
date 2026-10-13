"""Tests for accounts API views."""

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.signing import TimestampSigner
from rest_framework import status
from rest_framework.test import APIClient


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

    def test_register_duplicate_email(self, api_client, user):
        """Test registration with duplicate email."""
        data = {
            "email": "test@example.com",
            "password": "securepass123",
            "password_confirm": "securepass123",
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

    def test_password_reset_confirm_success(self, api_client, user):
        """Test successful password reset confirmation."""
        signer = TimestampSigner()
        uid = signer.sign(user.email)

        data = {
            "uid": uid,
            "token": "dummy",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = api_client.post("/api/v1/auth/password-reset/confirm/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data

        # Verify password was changed
        user.refresh_from_db()
        assert user.check_password("newsecurepass123")

    def test_password_reset_confirm_mismatch(self, api_client, user):
        """Test password reset with mismatched passwords."""
        signer = TimestampSigner()
        uid = signer.sign(user.email)

        data = {
            "uid": uid,
            "token": "dummy",
            "new_password": "newsecurepass123",
            "new_password_confirm": "differentpass123",
        }

        response = api_client.post("/api/v1/auth/password-reset/confirm/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password_confirm" in response.data

    def test_password_reset_confirm_invalid_uid(self, api_client):
        """Test password reset with invalid UID."""
        data = {
            "uid": "invalid.uid.here",
            "token": "dummy",
            "new_password": "newsecurepass123",
            "new_password_confirm": "newsecurepass123",
        }

        response = api_client.post("/api/v1/auth/password-reset/confirm/", data, format="json")

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
