"""URL configuration for the accounts application."""

from django.urls import path

from accounts.views import (
    ChangePasswordView,
    EmailVerificationView,
    LoginView,
    LogoutView,
    MeExportView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    ResendVerificationView,
    TokenRefreshView,
)

app_name = "accounts"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path(
        "password-reset/",
        PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("verify-email/", EmailVerificationView.as_view(), name="verify-email"),
    path(
        "resend-verification/",
        ResendVerificationView.as_view(),
        name="resend-verification",
    ),
    path("me/", MeView.as_view(), name="me"),
    path("me/export/", MeExportView.as_view(), name="me-export"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
]
