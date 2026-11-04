from rest_framework.routers import DefaultRouter

from django.urls import include, path

from deposits.api.views import DepositProductViewSet

router = DefaultRouter()
router.register(r"deposit-products", DepositProductViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
