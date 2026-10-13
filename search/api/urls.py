"""URL routes for the search API."""

from django.urls import path

from search.api.views import SearchStatusView, SearchView, SuggestView

urlpatterns = [
    path("", SearchView.as_view(), name="search"),
    path("suggest/", SuggestView.as_view(), name="search-suggest"),
    path("status/", SearchStatusView.as_view(), name="search-status"),
]
