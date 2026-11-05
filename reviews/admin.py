from django.contrib import admin
from django.utils import timezone

from .cache import invalidate_card_summary, invalidate_review_summary
from .models import (
    AccountReview,
    CardReview,
    DepositReview,
    LoanReview,
    ProductReviewVote,
    ReviewComment,
    ReviewVote,
)


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


def _make_product_review_actions(product_type):
    def approve(modeladmin, request, queryset):
        product_ids = set(queryset.values_list("product_id", flat=True))
        queryset.update(status="approved", modified=timezone.now())
        for product_id in product_ids:
            invalidate_review_summary(product_type, product_id)

    def reject(modeladmin, request, queryset):
        product_ids = set(queryset.values_list("product_id", flat=True))
        queryset.update(status="rejected", modified=timezone.now())
        for product_id in product_ids:
            invalidate_review_summary(product_type, product_id)

    approve.short_description = "Approve selected reviews"
    reject.short_description = "Reject selected reviews"
    return approve, reject


class ProductReviewAdmin(admin.ModelAdmin):
    product_type = None
    list_display = ("id", "product", "user", "rating", "status", "created")
    list_filter = ("status", "rating", "created")
    search_fields = ("title", "body", "product__name", "user__username")
    readonly_fields = ("helpful_count", "created", "modified")

    def get_actions(self, request):
        actions = super().get_actions(request)
        approve, reject = _make_product_review_actions(self.product_type)
        actions["approve_reviews"] = (approve, "approve_reviews", approve.short_description)
        actions["reject_reviews"] = (reject, "reject_reviews", reject.short_description)
        return actions


@admin.register(DepositReview)
class DepositReviewAdmin(ProductReviewAdmin):
    product_type = "deposit"


@admin.register(LoanReview)
class LoanReviewAdmin(ProductReviewAdmin):
    product_type = "loan"


@admin.register(AccountReview)
class AccountReviewAdmin(ProductReviewAdmin):
    product_type = "account"


@admin.register(ProductReviewVote)
class ProductReviewVoteAdmin(admin.ModelAdmin):
    list_display = ("content_type", "object_id", "user", "helpful", "created")
    list_filter = ("helpful", "content_type")


@admin.action(description="Approve selected comments")
def approve_comments(modeladmin, request, queryset):
    queryset.update(status=ReviewComment.Status.APPROVED, modified=timezone.now())


@admin.action(description="Reject selected comments")
def reject_comments(modeladmin, request, queryset):
    queryset.update(status=ReviewComment.Status.REJECTED, modified=timezone.now())


@admin.register(ReviewComment)
class ReviewCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "author", "status", "created")
    list_filter = ("status", "content_type", "created")
    search_fields = ("body", "author__username")
    readonly_fields = ("created", "modified")
    actions = (approve_comments, reject_comments)
