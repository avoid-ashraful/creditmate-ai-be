from django.urls import path

from advisor.api.views import AdvisorChatStreamView, AdvisorChatView

urlpatterns = [
    path("advisor/chat/", AdvisorChatView.as_view(), name="advisor-chat"),
    path(
        "advisor/chat/stream/",
        AdvisorChatStreamView.as_view(),
        name="advisor-chat-stream",
    ),
]
