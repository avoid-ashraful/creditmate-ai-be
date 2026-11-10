from django.urls import path

from retrieval.api.views import RetrievalSearchView

urlpatterns = [
    path("retrieval/search/", RetrievalSearchView.as_view(), name="retrieval-search"),
]
