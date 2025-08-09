from rest_framework.routers import DefaultRouter

from django.urls import include, path

from banks.api.views import BankViewSet

router = DefaultRouter()
router.register(r"banks", BankViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
