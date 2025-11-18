from rest_framework.routers import DefaultRouter

from django.urls import include, path

from credit_cards.api.views import (
    BenefitCategoryViewSet,
    CreditCardRatingViewSet,
    CreditCardReviewViewSet,
    CreditCardViewSet,
)

router = DefaultRouter(trailing_slash=False)
router.register(r"credit-cards", CreditCardViewSet, basename="creditcard")
router.register(r"benefit-categories", BenefitCategoryViewSet, basename="benefitcategory")
router.register(r"ratings", CreditCardRatingViewSet, basename="rating")
router.register(r"reviews", CreditCardReviewViewSet, basename="review")

urlpatterns = [
    path("", include(router.urls)),
]
