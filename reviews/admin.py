from django.contrib import admin
from django.utils import timezone

from .cache import invalidate_card_summary
from .models import CardReview, ReviewVote


@admin.action(description="Approve selected reviews")
def approve_reviews(modeladmin, request, queryset):
    card_ids = set(queryset.values_list("card_id", flat=True))
    queryset.update(status=CardReview.Status.APPROVED, modified=timezone.now())
    for card_id in card_ids:
        invalidate_card_summary(card_id)


@admin.action(description="Reject selected reviews")
def reject_reviews(modeladmin, request, queryset):
    card_ids = set(queryset.values_list("card_id", flat=True))
    queryset.update(status=CardReview.Status.REJECTED, modified=timezone.now())
    for card_id in card_ids:
        invalidate_card_summary(card_id)


@admin.register(CardReview)
class CardReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "card", "user", "rating", "status", "created")
    list_filter = ("status", "rating", "created")
    search_fields = ("title", "body", "card__name", "user__username")
    readonly_fields = ("helpful_count", "created", "modified")
    actions = (approve_reviews, reject_reviews)


@admin.register(ReviewVote)
class ReviewVoteAdmin(admin.ModelAdmin):
    list_display = ("review", "user", "helpful", "created")
    list_filter = ("helpful",)
