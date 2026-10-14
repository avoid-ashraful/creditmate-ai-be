from rest_framework.routers import DefaultRouter

from django.urls import include, path

from credit_cards.api.advanced_views import AdvancedSearchViewSet
from credit_cards.api.views import CreditCardViewSet

router = DefaultRouter()
router.register(r"credit-cards", CreditCardViewSet)

# Advanced search endpoints
advanced_search = AdvancedSearchViewSet.as_view(
    {
        "get": "list",
    }
)

# These must come BEFORE the router.urls to avoid being captured by the
# router's detail route (credit-cards/(?P<pk>[^/.]+)/$)
urlpatterns = [
    path(
        "credit-cards/advanced-search/",
        advanced_search,
        name="creditcard-advanced-search",
    ),
    path(
        "credit-cards/advanced-search/sort-options/",
        AdvancedSearchViewSet.as_view({"get": "sort_options"}),
        name="creditcard-sort-options",
    ),
    path(
        "credit-cards/advanced-search/categories/",
        AdvancedSearchViewSet.as_view({"get": "categories"}),
        name="creditcard-categories",
    ),
    path(
        "credit-cards/advanced-search/normalize/",
        AdvancedSearchViewSet.as_view({"get": "normalize"}),
        name="creditcard-normalize-query",
    ),
    path("", include(router.urls)),
]
