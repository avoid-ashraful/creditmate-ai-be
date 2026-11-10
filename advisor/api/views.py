"""Advisor API (plan §7.2).

Both endpoints sit behind ``settings.ADVISOR_ENABLED`` (default False):
when disabled they answer 404, so the feature is merged but dark until
Ash enables it. POST runs one turn synchronously; the stream variant
emits the same payload as a small SSE sequence (meta → answer → done)
so the FE can render progressively — the graph itself is synchronous in
v1, so events are emitted as stages complete rather than per-token.

Sessions/messages persist ONLY the user text, the validated answer, its
citations and a hashed tool trace — never eligibility inputs (see
``advisor.models``).
"""

import json

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from django.conf import settings
from django.http import Http404, StreamingHttpResponse

from advisor.api.serializers import (
    AdvisorChatRequestSerializer,
    AdvisorChatResponseSerializer,
)
from advisor.graph import run_advisor
from advisor.models import AdvisorMessage, AdvisorSession


def _require_enabled():
    if not getattr(settings, "ADVISOR_ENABLED", False):
        raise Http404("advisor is not enabled")


def _get_or_create_session(request, data):
    session_id = data.get("session_id")
    if session_id:
        session = AdvisorSession.objects.filter(pk=session_id).first()
        if session is not None:
            return session
    return AdvisorSession.objects.create(
        user=request.user if request.user.is_authenticated else None,
        anon_id=data.get("anon_id") or "",
    )


def _run_and_persist(request, data):
    session = _get_or_create_session(request, data)
    answer, trace = run_advisor(data["message"])
    AdvisorMessage.objects.create(
        session=session,
        user_text=data["message"],
        answer_markdown=answer.answer_markdown,
        citations=[c.model_dump(mode="json") for c in answer.citations],
        tool_trace=trace,
        is_fallback=answer.is_fallback,
    )
    payload = {
        "session_id": session.id,
        **answer.model_dump(mode="json"),
        "tool_trace": trace,
    }
    return AdvisorChatResponseSerializer(payload).data


class AdvisorChatView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "advisor"

    @extend_schema(
        request=AdvisorChatRequestSerializer,
        responses=AdvisorChatResponseSerializer,
    )
    def post(self, request):
        _require_enabled()
        serializer = AdvisorChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_run_and_persist(request, serializer.validated_data))


class AdvisorChatStreamView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "advisor"

    @extend_schema(
        request=AdvisorChatRequestSerializer,
        responses=AdvisorChatResponseSerializer,
        description="Server-sent events stream; the answer event carries the "
        "AdvisorChatResponse payload.",
    )
    def post(self, request):
        _require_enabled()
        serializer = AdvisorChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def events():
            yield 'event: meta\ndata: {"status": "working"}\n\n'
            try:
                payload = _run_and_persist(request, data)
                yield f"event: answer\ndata: {json.dumps(payload, default=str)}\n\n"
            except Exception:  # last-resort guard: SSE must not die mid-stream
                from advisor.graph import fallback_answer

                fallback = fallback_answer(data["message"], reason="stream_error")
                yield (
                    "event: answer\ndata: "
                    f"{json.dumps(fallback.model_dump(mode='json'), default=str)}\n\n"
                )
            yield "event: done\ndata: {}\n\n"

        response = StreamingHttpResponse(events(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
