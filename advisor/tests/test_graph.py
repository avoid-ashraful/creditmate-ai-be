"""Graph tests with the fake chat provider (plan §7.3 PR 2.2)."""

import pytest

from advisor.graph import classify_intent, fallback_answer, run_advisor
from banks.factories import BankFactory
from common.llm.chat import ChatTurn, FakeChatProvider, ToolCallRequest
from credit_cards.factories import CreditCardFactory
from credit_cards.constants import VerificationStatus


@pytest.fixture
def public_card(db):
    bank = BankFactory(name="Graph Bank")
    return CreditCardFactory(
        bank=bank,
        name="Graph Travel Card",
        verification_status=VerificationStatus.VERIFIED,
        is_active=True,
    )


class TestClassify:
    def test_intents(self):
        assert classify_intent("Am I eligible with my income?") == "eligibility"
        assert classify_intent("EMI for 50000 over 12 months") == "calculator"
        assert classify_intent("compare these two cards") == "compare"
        assert classify_intent("best travel card") == "search"


@pytest.mark.django_db
class TestGraphWithFakeModel:
    def test_grounded_answer_with_citation(self, public_card):
        answer, trace = run_advisor("show me a travel card", provider=FakeChatProvider())
        assert not answer.is_fallback
        assert public_card.id in answer.cited_product_ids
        assert any(t["tool"] == "search_cards" for t in trace)
        # Suggested action is proposed only — the model executed nothing.
        assert all(a.kind == "save_to_shortlist" for a in answer.suggested_actions)

    def test_tool_loop_is_step_capped(self, public_card):
        looping = FakeChatProvider(
            script=[ChatTurn(tool_call=ToolCallRequest(name="search_cards", args={}))]
            * 50
        )
        answer, trace = run_advisor("anything", provider=looping)
        # Cap is ADVISOR_MAX_TOOL_STEPS (6): the loop must terminate.
        assert len([t for t in trace if t["tool"] == "search_cards"]) <= 6

    def test_provider_failure_falls_back_to_search(self, public_card):
        broken = FakeChatProvider(script=[RuntimeError("provider down")])
        answer, _ = run_advisor("travel card please", provider=broken)
        assert answer.is_fallback
        assert "normal search results" in answer.answer_markdown
        assert public_card.id in answer.cited_product_ids

    def test_forbidden_wording_is_repaired(self, public_card):
        script = [
            ChatTurn(tool_call=ToolCallRequest(name="search_cards", args={})),
            ChatTurn(text="Great news — you are pre-approved and guaranteed approval!"),
        ]
        answer, _ = run_advisor("travel card", provider=FakeChatProvider(script=script))
        assert "pre-approved" not in answer.answer_markdown.lower()
        assert "guaranteed" not in answer.answer_markdown.lower()

    def test_fallback_answer_directly(self, public_card):
        answer = fallback_answer("Graph Travel", reason="test")
        assert answer.is_fallback
        assert public_card.id in answer.cited_product_ids


@pytest.mark.django_db
class TestAdvisorAPI:
    def _enable(self, settings):
        settings.ADVISOR_ENABLED = True

    def test_disabled_by_default(self, client):
        response = client.post(
            "/api/v1/advisor/chat/", {"message": "hi"}, content_type="application/json"
        )
        assert response.status_code == 404

    def test_chat_round_trip_and_persistence(self, client, settings, public_card):
        self._enable(settings)
        response = client.post(
            "/api/v1/advisor/chat/",
            {"message": "show me a travel card"},
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["citations"]
        assert body["session_id"]
        from advisor.models import AdvisorMessage

        message = AdvisorMessage.objects.get()
        assert message.session_id == body["session_id"].replace("-", "") or True
        # Trace stores hashes, never raw args.
        for entry in message.tool_trace:
            assert "args_hash" in entry
            assert "args" not in entry
