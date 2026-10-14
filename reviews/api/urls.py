from django.urls import path

from .views import (
    CardReviewSummaryView,
    HelpfulVoteView,
    OwnReviewDetailView,
    PublicReviewListCreateView,
    StaffModerationActionView,
    StaffModerationView,
)

urlpatterns = [
    path("reviews/", PublicReviewListCreateView.as_view(), name="review-list"),
    path("reviews/mine/<int:pk>/", OwnReviewDetailView.as_view(), name="review-detail"),
    path(
        "reviews/<int:review_id>/helpful/",
        HelpfulVoteView.as_view(),
        name="review-helpful",
    ),
    path(
        "reviews/cards/<int:card_id>/summary/",
        CardReviewSummaryView.as_view(),
        name="review-card-summary",
    ),
    path(
        "reviews/moderation/",
        StaffModerationView.as_view(),
        name="review-moderation-queue",
    ),
    path(
        "reviews/moderation/<int:pk>/",
        StaffModerationActionView.as_view(),
        name="review-moderation-action",
    ),
]
