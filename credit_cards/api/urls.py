from rest_framework.routers import DefaultRouter

from django.urls import include, path

from credit_cards.api.views import CreditCardViewSet

router = DefaultRouter()
router.register(r"credit-cards", CreditCardViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
