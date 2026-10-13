from rest_framework.routers import SimpleRouter

from django.urls import include, path

from saved.views import (
    CollectionViewSet,
    SavedComparisonViewSet,
    SharedCollectionView,
    SharedComparisonView,
)

router = SimpleRouter()
router.register("comparisons", SavedComparisonViewSet, basename="saved-comparison")
router.register("collections", CollectionViewSet, basename="saved-collection")

# Public share routes are listed before the router so that the shared/<token>/
# pattern never shadows the collection slug route.
urlpatterns = [
    path(
        "shared/collections/<slug:slug>/",
        SharedCollectionView.as_view(),
        name="saved-shared-collection",
    ),
    path(
        "shared/<str:token>/",
        SharedComparisonView.as_view(),
        name="saved-shared-comparison",
    ),
    path("", include(router.urls)),
]
