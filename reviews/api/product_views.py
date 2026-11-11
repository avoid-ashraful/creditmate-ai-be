"""Generic review endpoints for deposits, loans and bank accounts.

Phase 3B generalises the card review system: these views mirror the
card views' behaviour exactly (approved-only public reads, pending on
create, edit returns to pending, email-verified authors, one review per
user+product, idempotent helpful votes, staff-only moderation) driven
by the :mod:`reviews.api.product_types` registry. Comments span all
four review types, cards included, and follow the same moderation
posture as reviews: pending until a moderator approves them.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, F
from django.shortcuts import get_object_or_404

from reviews.cache import review_summary_key
from reviews.models import (
    COMMUNITY_REVIEWED_THRESHOLD,
    ProductReviewVote,
    ReviewComment,
)

from .product_types import ALL_REVIEW_TYPES, PRODUCT_REVIEW_TYPES, review_content_type
from .serializers import (
    OwnReviewCommentSerializer,
    OwnReviewCommentTreeSerializer,
    ReviewCommentSerializer,
    ReviewCommentTreeSerializer,
    product_review_serializer_class,
)
from .throttles import ReviewUserThrottle, ReviewWriteThrottleMixin

SUMMARY_CACHE_TTL = 300


def require_verified_email(request):
    """Reviews and comments require a verified email, as card reviews do."""
    profile = getattr(request.user, "profile", None)
    if not (profile and profile.email_verified):
        raise PermissionDenied(
            {
                "detail": "Verify your email address before posting a review.",
                "code": "email_not_verified",
            }
        )


def _parse_product_param(request, name="product"):
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: ["A valid integer is required."]}) from None


def build_review_summary(review_model, product_type, product_id, product_field="product"):
    approved = review_model.objects.filter(
        status=review_model.Status.APPROVED, **{f"{product_field}_id": product_id}
    )
    grouped = {
        row["rating"]: row["count"]
        for row in approved.values("rating").annotate(count=Count("id"))
    }
    count = sum(grouped.values())
    return {
        "product_type": product_type,
        "product": product_id,
        "average_rating": approved.aggregate(value=Avg("rating"))["value"],
        "review_count": count,
        "approved_count": count,
        "distribution": {str(rating): grouped.get(rating, 0) for rating in range(1, 6)},
        "community_reviewed": count >= COMMUNITY_REVIEWED_THRESHOLD,
    }


class ProductReviewListCreateView(ReviewWriteThrottleMixin, generics.ListCreateAPIView):
    product_type = None
    throttle_classes = [ReviewUserThrottle]

    @property
    def config(self):
        return PRODUCT_REVIEW_TYPES[self.product_type]

    def get_serializer_class(self):
        return product_review_serializer_class(self.product_type)

    def get_queryset(self):
        model = self.config["review_model"]
        qs = model.objects.filter(status=model.Status.APPROVED).select_related(
            "user", "product"
        )
        product_id = _parse_product_param(self.request)
        if product_id is None:
            return qs
        return qs.filter(product_id=product_id)

    def get_permissions(self):
        return (
            [permissions.IsAuthenticated()]
            if self.request.method == "POST"
            else [permissions.AllowAny()]
        )

    def perform_create(self, serializer):
        require_verified_email(self.request)
        serializer.save(
            user=self.request.user,
            status=self.config["review_model"].Status.PENDING,
        )


class ProductOwnReviewListView(generics.ListAPIView):
    """The signed-in user's own reviews for one product type, any status."""

    product_type = None
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return product_review_serializer_class(self.product_type, own=True)

    def get_queryset(self):
        model = PRODUCT_REVIEW_TYPES[self.product_type]["review_model"]
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return model.objects.none()
        qs = model.objects.filter(user=self.request.user).select_related("product")
        product_id = _parse_product_param(self.request)
        if product_id is not None:
            qs = qs.filter(product_id=product_id)
        return qs


class ProductOwnReviewDetailView(
    ReviewWriteThrottleMixin, generics.RetrieveUpdateDestroyAPIView
):
    product_type = None
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]

    def get_serializer_class(self):
        return product_review_serializer_class(self.product_type, own=True)

    def get_queryset(self):
        model = PRODUCT_REVIEW_TYPES[self.product_type]["review_model"]
        return model.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        # Editing returns the review to moderation, as with card reviews.
        serializer.save(
            status=PRODUCT_REVIEW_TYPES[self.product_type]["review_model"].Status.PENDING
        )


class ProductReviewSummaryView(APIView):
    permission_classes = [permissions.AllowAny]
    product_type = None

    # No explicit operation_id: this view is bound once per product type,
    # so spectacular's path-derived auto id keeps the three operations
    # distinct (a shared static id collides).
    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        tags=["reviews"],
    )
    def get(self, request, product_id):
        config = PRODUCT_REVIEW_TYPES[self.product_type]
        get_object_or_404(config["product_model"], pk=product_id)
        key = review_summary_key(self.product_type, product_id)
        summary = cache.get(key)
        if summary is None:
            summary = build_review_summary(
                config["review_model"], self.product_type, product_id
            )
            cache.set(key, summary, SUMMARY_CACHE_TTL)
        return Response(summary)


class ProductHelpfulVoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]
    product_type = None

    # No explicit operation_id (see ProductReviewSummaryView above).
    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT},
        tags=["reviews"],
    )
    def post(self, request, review_id):
        model = PRODUCT_REVIEW_TYPES[self.product_type]["review_model"]
        review = get_object_or_404(model, pk=review_id, status=model.Status.APPROVED)
        if review.user_id == request.user.id:
            raise PermissionDenied("You cannot vote on your own review.")
        content_type = review_content_type(model)
        with transaction.atomic():
            vote, created = ProductReviewVote.objects.get_or_create(
                content_type=content_type, object_id=review.pk, user=request.user
            )
            if created:
                model.objects.filter(pk=review.pk).update(
                    helpful_count=F("helpful_count") + 1
                )
        review.refresh_from_db(fields=["helpful_count"])
        return Response(
            {"helpful_count": review.helpful_count},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ProductModerationListView(APIView):
    """Staff queue: pending deposit/loan/account reviews, oldest first."""

    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        tags=["reviews"],
        operation_id="reviews_product_moderation_list",
    )
    def get(self, request):
        items = []
        for product_type, config in PRODUCT_REVIEW_TYPES.items():
            model = config["review_model"]
            serializer_class = product_review_serializer_class(product_type, own=True)
            pending = model.objects.filter(status=model.Status.PENDING).select_related(
                "user", "product"
            )
            items.extend(serializer_class(pending, many=True).data)
        items.sort(key=lambda item: item["created"])
        return Response(items)


class ProductModerationActionView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
        tags=["reviews"],
        operation_id="reviews_product_moderation_update",
    )
    def post(self, request, product_type, pk):
        config = PRODUCT_REVIEW_TYPES.get(product_type)
        if config is None:
            raise NotFound("Unknown product type.")
        model = config["review_model"]
        review = get_object_or_404(model, pk=pk)
        new_status = request.data.get("status")
        if new_status not in (model.Status.APPROVED, model.Status.REJECTED):
            return Response(
                {"status": "Choose approved or rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        review.status = new_status
        review.save(update_fields=["status", "modified"])
        serializer_class = product_review_serializer_class(product_type, own=True)
        return Response(serializer_class(review).data)


class ReviewCommentListCreateView(ReviewWriteThrottleMixin, APIView):
    """Public thread for one review (any product type) + comment creation.

    Reads show approved comments; an authenticated author also sees
    their own comments in any state (with ``status``), so a pending
    comment is visible to its author in place and never to anyone else.
    """

    throttle_classes = [ReviewUserThrottle]

    def get_permissions(self):
        return (
            [permissions.IsAuthenticated()]
            if self.request.method == "POST"
            else [permissions.AllowAny()]
        )

    def _resolve_review(self, review_type, review_id):
        config = ALL_REVIEW_TYPES.get(review_type)
        if config is None:
            raise NotFound("Unknown review type.")
        review = get_object_or_404(config["review_model"], pk=review_id)
        return config, review

    def _review_visible(self, request, review):
        model = type(review)
        if review.status == model.Status.APPROVED:
            return True
        if not request.user.is_authenticated:
            return False
        return request.user.is_staff or review.user_id == request.user.id

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        tags=["reviews"],
        operation_id="reviews_comment_list",
    )
    def get(self, request, review_type, review_id):
        config, review = self._resolve_review(review_type, review_id)
        if not self._review_visible(request, review):
            raise NotFound("Review not found.")
        content_type = review_content_type(config["review_model"])
        comments = list(
            ReviewComment.objects.filter(
                content_type=content_type, object_id=review.pk
            ).select_related("author", "parent")
        )
        user = request.user
        authed = user.is_authenticated

        def is_visible(comment):
            return comment.status == ReviewComment.Status.APPROVED or (
                authed and comment.author_id == user.id
            )

        visible = [comment for comment in comments if is_visible(comment)]
        replies_by_parent = {}
        top_level = []
        for comment in visible:
            if comment.parent_id is None:
                top_level.append(comment)
            else:
                replies_by_parent.setdefault(comment.parent_id, []).append(comment)
        results = []
        for comment in top_level:
            comment._visible_replies = replies_by_parent.get(comment.pk, [])
            serializer_class = (
                OwnReviewCommentTreeSerializer
                if authed and comment.author_id == user.id
                else ReviewCommentTreeSerializer
            )
            results.append(
                serializer_class(comment, context={"request": request}).data
            )
        return Response({"count": len(results), "results": results})

    @extend_schema(
        request=ReviewCommentSerializer,
        responses={201: OwnReviewCommentSerializer},
        tags=["reviews"],
        operation_id="reviews_comment_create",
    )
    def post(self, request, review_type, review_id):
        config, review = self._resolve_review(review_type, review_id)
        model = config["review_model"]
        if review.status != model.Status.APPROVED:
            # You cannot comment on a review the public cannot see.
            raise NotFound("Review not found.")
        require_verified_email(request)
        content_type = review_content_type(model)
        parent = None
        parent_id = request.data.get("parent")
        if parent_id is not None:
            parent = ReviewComment.objects.filter(
                pk=parent_id, content_type=content_type, object_id=review.pk
            ).first()
            if parent is None:
                raise ValidationError({"parent": "Comment not found on this review."})
            if parent.parent_id is not None:
                raise ValidationError(
                    {"parent": "Replies cannot be nested further."}
                )
            if parent.status != ReviewComment.Status.APPROVED and (
                parent.author_id != request.user.id
            ):
                raise ValidationError({"parent": "Comment not found on this review."})
        serializer = ReviewCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(
            author=request.user,
            content_type=content_type,
            object_id=review.pk,
            parent=parent,
            status=ReviewComment.Status.PENDING,
        )
        return Response(
            OwnReviewCommentSerializer(comment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class OwnReviewCommentDetailView(
    ReviewWriteThrottleMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = OwnReviewCommentSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ReviewUserThrottle]

    def get_queryset(self):
        return ReviewComment.objects.filter(author=self.request.user)

    def perform_update(self, serializer):
        # Editing a comment returns it to moderation, as with reviews.
        serializer.save(status=ReviewComment.Status.PENDING)


class CommentModerationListView(generics.ListAPIView):
    """Staff queue: pending comments across all review types."""

    serializer_class = OwnReviewCommentSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return (
            ReviewComment.objects.filter(status=ReviewComment.Status.PENDING)
            .select_related("author")
            .order_by("created")
        )


class CommentModerationActionView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OwnReviewCommentSerializer, 400: OpenApiTypes.OBJECT},
        tags=["reviews"],
        operation_id="reviews_comment_moderation_update",
    )
    def post(self, request, pk):
        comment = get_object_or_404(ReviewComment, pk=pk)
        new_status = request.data.get("status")
        if new_status not in (
            ReviewComment.Status.APPROVED,
            ReviewComment.Status.REJECTED,
        ):
            return Response(
                {"status": "Choose approved or rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        comment.status = new_status
        comment.save(update_fields=["status", "modified"])
        return Response(OwnReviewCommentSerializer(comment).data)
