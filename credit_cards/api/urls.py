from rest_framework.routers import DefaultRouter

from django.urls import include, path

from credit_cards.api.views import BenefitCategoryViewSet, CreditCardViewSet

router = DefaultRouter()
router.register(r"credit-cards", CreditCardViewSet)
router.register(r"benefit-categories", BenefitCategoryViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
