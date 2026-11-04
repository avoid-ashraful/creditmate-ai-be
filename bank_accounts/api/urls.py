from rest_framework.routers import DefaultRouter

from django.urls import include, path

from bank_accounts.api.views import AccountProductViewSet

router = DefaultRouter()
router.register(r"account-products", AccountProductViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
