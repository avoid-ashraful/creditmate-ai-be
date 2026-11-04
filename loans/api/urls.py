from rest_framework.routers import DefaultRouter

from django.urls import include, path

from loans.api.views import LoanProductViewSet

router = DefaultRouter()
router.register(r"loan-products", LoanProductViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
