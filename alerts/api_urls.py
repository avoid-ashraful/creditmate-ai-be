from django.urls import path

from .views import (
    PreferenceView,
    PublicUnsubscribeView,
    SubscriptionDetailView,
    SubscriptionListCreateView,
)

urlpatterns = [
    path("subscriptions/", SubscriptionListCreateView.as_view(), name="alert-subscriptions"),
    path("subscriptions/<int:pk>/", SubscriptionDetailView.as_view(), name="alert-subscription-detail"),
    path("preferences/", PreferenceView.as_view(), name="alert-preferences"),
    path("unsubscribe/<str:token>/", PublicUnsubscribeView.as_view(), name="alert-unsubscribe"),
]
