from rest_framework.routers import SimpleRouter

from django.urls import include, path

from saved.views import (
    CollectionViewSet,
    SavedComparisonViewSet,
    SavedScenarioViewSet,
    SavedSearchViewSet,
    SharedCollectionView,
    SharedComparisonView,
    ShortlistImportView,
    ShortlistItemView,
    ShortlistView,
)

router = SimpleRouter()
router.register("comparisons", SavedComparisonViewSet, basename="saved-comparison")
router.register("collections", CollectionViewSet, basename="saved-collection")
router.register("searches", SavedSearchViewSet, basename="saved-search")
router.register("scenarios", SavedScenarioViewSet, basename="saved-scenario")

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
    path("shortlist/", ShortlistView.as_view(), name="saved-shortlist"),
    path(
        "shortlist/import/",
        ShortlistImportView.as_view(),
        name="saved-shortlist-import",
    ),
    path(
        "shortlist/<str:vertical>/<str:key>/",
        ShortlistItemView.as_view(),
        name="saved-shortlist-item",
    ),
    path("", include(router.urls)),
]
