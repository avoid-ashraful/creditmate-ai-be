from django.urls import path

from .views import (
    BankFollowDetailView,
    BankFollowFeedView,
    BankFollowListCreateView,
    PreferenceView,
    PublicUnsubscribeView,
    SubscriptionDetailView,
    SubscriptionListCreateView,
)

urlpatterns = [
    path(
        "subscriptions/", SubscriptionListCreateView.as_view(), name="alert-subscriptions"
    ),
    path("bank-follows/", BankFollowListCreateView.as_view(), name="alert-bank-follows"),
    path("feed/", BankFollowFeedView.as_view(), name="alert-bank-follow-feed"),
    path(
        "bank-follows/<int:bank_id>/",
        BankFollowDetailView.as_view(),
        name="alert-bank-follow-detail",
    ),
    path(
        "subscriptions/<int:pk>/",
        SubscriptionDetailView.as_view(),
        name="alert-subscription-detail",
    ),
    path("preferences/", PreferenceView.as_view(), name="alert-preferences"),
    path(
        "unsubscribe/<str:token>/",
        PublicUnsubscribeView.as_view(),
        name="alert-unsubscribe",
    ),
]
