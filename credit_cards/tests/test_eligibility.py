"""Tests for the stateless eligibility checker endpoint.

POST /api/v1/credit-cards/eligibility/

Verdict rules under test (see credit_cards/eligibility.py):
- eligible: income >= published minimum and CIB declared clean
- likely:   income >= minimum but CIB undeclared/unknown, or income within
            20% below the published minimum
- unknown:  card publishes no minimum income
- not_yet:  income below the likely band, or CIB declared with issues
"""

import json
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from credit_cards.constants import VerificationStatus
from credit_cards.eligibility import DISCLAIMER, evaluate_card, profile_notes
from credit_cards.factories import CreditCardFactory

URL = "/api/v1/credit-cards/eligibility/"


def make_card(name, min_income=None, **kwargs):
    return CreditCardFactory(
        name=name,
        min_monthly_income=Decimal(min_income) if min_income is not None else None,
        **kwargs,
    )


def check(client, **payload):
    payload.setdefault("monthly_income", "30000")
    payload.setdefault("employment_type", "salaried")
    return client.post(URL, payload, format="json")


def verdicts_by_name(response):
    return {item["card"]["name"]: item["verdict"] for item in response.data["results"]}


@pytest.mark.django_db
class TestEligibilityVerdicts:
    def test_eligible_when_income_meets_minimum_and_cib_clean(self, api_client):
        make_card("Meets Card", "30000")
        response = check(api_client, cib_status="clean")
        assert response.status_code == 200
        assert verdicts_by_name(response) == {"Meets Card": "eligible"}
        assert response.data["counts"]["eligible"] == 1
        reasons = response.data["results"][0]["reasons"]
        assert any("BDT 30,000" in reason for reason in reasons)

    def test_income_above_minimum_is_eligible(self, api_client):
        make_card("Low Bar Card", "20000")
        response = check(api_client, monthly_income="45000", cib_status="clean")
        assert verdicts_by_name(response) == {"Low Bar Card": "eligible"}

    def test_likely_when_income_within_twenty_percent_below_minimum(self, api_client):
        make_card("Close Card", "30000")
        response = check(api_client, monthly_income="25000", cib_status="clean")
        assert verdicts_by_name(response) == {"Close Card": "likely"}
        reasons = response.data["results"][0]["reasons"]
        assert any("within 20%" in reason for reason in reasons)

    def test_likely_band_lower_boundary_is_inclusive(self, api_client):
        make_card("Boundary Card", "30000")
        # 24,000 is exactly 80% of 30,000.
        response = check(api_client, monthly_income="24000", cib_status="clean")
        assert verdicts_by_name(response) == {"Boundary Card": "likely"}

    def test_not_yet_just_below_likely_band(self, api_client):
        make_card("Boundary Card", "30000")
        response = check(api_client, monthly_income="23999", cib_status="clean")
        assert verdicts_by_name(response) == {"Boundary Card": "not_yet"}

    def test_likely_when_cib_undeclared_even_if_income_meets_minimum(self, api_client):
        make_card("Meets Card", "30000")
        response = check(api_client)  # no cib_status sent
        assert verdicts_by_name(response) == {"Meets Card": "likely"}

    def test_likely_when_cib_explicitly_unknown(self, api_client):
        make_card("Meets Card", "30000")
        response = check(api_client, cib_status="unknown")
        assert verdicts_by_name(response) == {"Meets Card": "likely"}

    def test_not_yet_when_cib_has_issues_regardless_of_income(self, api_client):
        make_card("Easy Card", "20000")
        make_card("No Minimum Card", None)
        response = check(api_client, monthly_income="90000", cib_status="has_issues")
        assert verdicts_by_name(response) == {
            "Easy Card": "not_yet",
            "No Minimum Card": "not_yet",
        }
        reasons = response.data["results"][0]["reasons"]
        assert any("CIB" in reason for reason in reasons)

    def test_unknown_when_card_publishes_no_minimum_income(self, api_client):
        make_card("Silent Card", None)
        response = check(api_client, monthly_income="90000", cib_status="clean")
        assert verdicts_by_name(response) == {"Silent Card": "unknown"}
        reasons = response.data["results"][0]["reasons"]
        assert any("No published income requirement" in reason for reason in reasons)

    def test_results_ordered_eligible_first_not_yet_last(self, api_client):
        make_card("Z Not Yet", "70000")
        make_card("A Eligible", "20000")
        make_card("M Unknown", None)
        response = check(api_client, cib_status="clean")
        order = [item["verdict"] for item in response.data["results"]]
        assert order == ["eligible", "unknown", "not_yet"]

    def test_counts_and_total_cover_all_verdicts(self, api_client):
        make_card("Eligible Card", "20000")
        make_card("Likely Card", "34000")  # 30,000 is within 20% below 34,000
        make_card("Unknown Card", None)
        make_card("Not Yet Card", "70000")
        response = check(api_client, cib_status="clean")
        assert response.data["total_cards"] == 4
        assert response.data["counts"] == {
            "eligible": 1,
            "likely": 1,
            "unknown": 1,
            "not_yet": 1,
        }

    def test_draft_cards_are_not_considered(self, api_client):
        make_card("Public Card", "20000")
        CreditCardFactory(
            name="Draft Card",
            min_monthly_income=Decimal("20000"),
            verification_status=VerificationStatus.DRAFT,
        )
        response = check(api_client, cib_status="clean")
        assert verdicts_by_name(response) == {"Public Card": "eligible"}

    def test_islamic_only_filter(self, api_client):
        make_card("Islamic Card", "20000", is_islamic=True)
        make_card("Conventional Card", "20000", is_islamic=False)
        response = check(api_client, cib_status="clean", islamic_only=True)
        assert verdicts_by_name(response) == {"Islamic Card": "eligible"}
        assert response.data["total_cards"] == 1

    def test_response_contains_disclaimer_and_method(self, api_client):
        make_card("Any Card", "20000")
        response = check(api_client, cib_status="clean")
        assert response.data["disclaimer"] == DISCLAIMER
        assert "published minimum monthly income" in response.data["method"]

    def test_response_never_promises_approval(self, api_client):
        make_card("Any Card", "20000")
        make_card("Silent Card", None)
        response = check(
            api_client,
            cib_status="clean",
            has_tin=False,
            employment_type="self_employed",
            age=19,
        )
        blob = json.dumps(response.data).lower()
        assert "pre-approved" not in blob
        assert "pre approved" not in blob
        assert "guaranteed" not in blob

    def test_get_is_not_allowed(self, api_client):
        response = api_client.get(URL)
        assert response.status_code == 405


@pytest.mark.django_db
class TestEligibilityNotes:
    def test_no_tin_produces_tin_note(self, api_client):
        make_card("Any Card", "20000")
        response = check(api_client, cib_status="clean", has_tin=False)
        assert any("e-TIN" in note for note in response.data["notes"])

    def test_tin_holder_gets_no_tin_note(self, api_client):
        make_card("Any Card", "20000")
        response = check(api_client, cib_status="clean", has_tin=True)
        assert not any("e-TIN" in note for note in response.data["notes"])

    def test_self_employed_produces_documents_note(self, api_client):
        make_card("Any Card", "20000")
        response = check(api_client, cib_status="clean", employment_type="self_employed")
        assert any("trade" in note.lower() for note in response.data["notes"])

    def test_notes_do_not_change_verdicts(self, api_client):
        make_card("Steady Card", "20000")
        plain = check(APIClient(), cib_status="clean")
        noted = check(
            APIClient(),
            cib_status="clean",
            has_tin=False,
            employment_type="self_employed",
            age=19,
        )
        assert (
            verdicts_by_name(plain)
            == verdicts_by_name(noted)
            == {"Steady Card": "eligible"}
        )
        assert len(noted.data["notes"]) >= 2


@pytest.mark.django_db
class TestEligibilityValidation:
    def test_missing_monthly_income_is_400(self, api_client):
        response = api_client.post(URL, {"employment_type": "salaried"}, format="json")
        assert response.status_code == 400
        assert "monthly_income" in response.data

    def test_negative_monthly_income_is_400(self, api_client):
        response = check(api_client, monthly_income="-1")
        assert response.status_code == 400

    def test_missing_employment_type_is_400(self, api_client):
        response = api_client.post(URL, {"monthly_income": "30000"}, format="json")
        assert response.status_code == 400
        assert "employment_type" in response.data

    def test_invalid_employment_type_is_400(self, api_client):
        response = check(api_client, employment_type="student")
        assert response.status_code == 400

    def test_invalid_cib_status_is_400(self, api_client):
        response = check(api_client, cib_status="spotless")
        assert response.status_code == 400

    def test_zero_income_is_valid(self, api_client):
        make_card("Any Card", "20000")
        response = check(api_client, monthly_income="0", cib_status="clean")
        assert response.status_code == 200
        assert verdicts_by_name(response) == {"Any Card": "not_yet"}


class TestEvaluateCardLogic:
    def test_format_of_reasons_references_actual_numbers(self):
        verdict, reasons = evaluate_card(Decimal("50000"), Decimal("30000"), "clean")
        assert verdict == "not_yet"
        assert "BDT 50,000" in reasons[0]
        assert "BDT 30,000" in reasons[0]

    def test_profile_notes_for_other_employment(self):
        notes = profile_notes("other", None, None)
        assert len(notes) == 1
        assert "proof of your income source" in notes[0]

    def test_profile_notes_empty_for_plain_salaried_profile(self):
        assert profile_notes("salaried", 35, True) == []
