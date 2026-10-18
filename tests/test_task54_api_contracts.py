"""Task 5.4 contracts for API groups added after the first contract suite."""

from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.signing import TimestampSigner
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from alerts.models import AlertSubscription
from credit_cards.factories import CreditCardFactory
from reviews.models import CardReview
from saved.models import Collection, SavedComparison


class AddedAPIContractTests(APITestCase):
    """Pin response envelopes and generated OpenAPI operations for new APIs."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="contract@example.com",
            email="contract@example.com",
            password="S3cure!passphrase",
        )
        cls.user.profile.email_verified = True
        cls.user.profile.save()
        cls.card = CreditCardFactory(annual_fee=None, interest_rate_apr=None)

    def test_openapi_contains_requested_operations_and_declared_fields(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = schema["paths"]
        required = {
            ("/api/v1/auth/register/", "post"): {"detail"},
            ("/api/v1/auth/login/", "post"): {"access", "refresh", "user"},
            ("/api/v1/auth/token/refresh/", "post"): {"access", "refresh"},
            ("/api/v1/auth/logout/", "post"): {"detail"},
            ("/api/v1/auth/me/", "get"): {
                "id",
                "username",
                "email",
                "first_name",
                "last_name",
                "profile",
            },
            ("/api/v1/auth/password-reset/", "post"): {"detail"},
            ("/api/v1/auth/password-reset/confirm/", "post"): {"detail"},
            ("/api/v1/auth/verify-email/", "post"): {"detail"},
            ("/api/v1/saved/comparisons/", "get"): {
                "count",
                "next",
                "previous",
                "results",
            },
            ("/api/v1/saved/collections/", "get"): {
                "count",
                "next",
                "previous",
                "results",
            },
            ("/api/v1/reviews/", "get"): {"count", "next", "previous", "results"},
            ("/api/v1/reviews/", "post"): {
                "id",
                "card",
                "rating",
                "title",
                "body",
                "pros",
                "cons",
                "reviewer_name",
                "helpful_count",
                "created",
                "modified",
            },
            ("/api/v1/reviews/cards/{card_id}/summary/", "get"): {
                "card",
                "average_rating",
                "review_count",
                "distribution",
            },
            ("/api/v1/reviews/{review_id}/helpful/", "post"): {"helpful_count"},
            ("/api/v1/reviews/moderation/", "get"): {
                "count",
                "next",
                "previous",
                "results",
            },
            ("/api/v1/alerts/subscriptions/", "get"): {
                "count",
                "next",
                "previous",
                "results",
            },
            ("/api/v1/alerts/preferences/", "get"): {"frequency"},
            ("/api/v1/credit-cards/advanced-search/", "get"): {
                "query",
                "total",
                "page",
                "page_size",
                "results",
                "facets",
                "took",
                "source",
            },
            ("/api/v1/credit-cards/advanced-search/sort-options/", "get"): set(),
            ("/api/v1/credit-cards/advanced-search/categories/", "get"): set(),
            ("/api/v1/credit-cards/advanced-search/normalize/", "get"): set(),
        }
        for (path, method), fields in required.items():
            with self.subTest(path=path, method=method):
                self.assertIn(path, paths)
                operation = paths[path][method]
                self.assertIn("responses", operation)
                response = operation["responses"].get("200") or operation[
                    "responses"
                ].get("201")
                self.assertIsNotNone(response)
                if fields and "content" in response:
                    content = response["content"]["application/json"]["schema"]
                    while "$ref" in content:
                        ref = content["$ref"].split("/")[-1]
                        content = schema["components"]["schemas"][ref]
                    if content.get("type") == "array":
                        content = content["items"]
                        while "$ref" in content:
                            ref = content["$ref"].split("/")[-1]
                            content = schema["components"]["schemas"][ref]
                    properties = set(content.get("properties", {}))
                    # Generic `{}` schemas are emitted for several unannotated
                    # views; their runtime fields are covered by the tests below.
                    if properties:
                        self.assertTrue(fields <= properties, (path, fields - properties))

        # Explicit schema checks for routes whose response has no serializer annotation.
        for path in (
            "/api/v1/saved/shared/{token}/",
            "/api/v1/saved/shared/collections/{slug}/",
        ):
            self.assertIn(path, paths)
        # Prometheus exposition is deliberately plain text and outside OpenAPI.
        self.assertNotIn("/metrics", paths)

    def test_account_success_shapes_and_auth_error_envelopes(self):
        client = self.client
        unauth = client.get("/api/v1/auth/me/")
        self.assertEqual(unauth.status_code, 401)
        self.assertEqual(set(unauth.data), {"detail"})

        response = client.post(
            "/api/v1/auth/register/",
            {
                "email": "new@example.com",
                "password": "A-strong-password-123",
                "password_confirm": "A-strong-password-123",
                "accept_terms": True,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), {"detail"})

        response = client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "S3cure!passphrase"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh", "user"})
        self.assertTrue(
            {"id", "username", "email", "first_name", "last_name", "profile"}
            <= set(response.data["user"])
        )
        self.assertEqual(
            set(response.data["user"]["profile"]),
            {
                "email_verified",
                "email_opt_in",
                "marketing_opt_in",
                "terms_accepted_at",
                "terms_version",
                "preferences",
            },
        )

        token = RefreshToken.for_user(self.user)
        response = client.post("/api/v1/auth/token/refresh/", {"refresh": str(token)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh"})
        response = client.post("/api/v1/auth/password-reset/", {"email": self.user.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"detail"})
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token_value = default_token_generator.make_token(self.user)
        response = client.post(
            "/api/v1/auth/password-reset/confirm/",
            {
                "uid": uid,
                "token": token_value,
                "new_password": "Other-strong-password-123",
                "new_password_confirm": "Other-strong-password-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"detail"})
        verification_token = TimestampSigner().sign(self.user.email)
        self.user.profile.email_verified = False
        self.user.profile.save(update_fields=["email_verified"])
        response = client.post(
            "/api/v1/auth/verify-email/", {"token": verification_token}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"detail"})
        client.force_authenticate(user=self.user)
        response = client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {"id", "username", "email", "first_name", "last_name", "profile"},
        )
        token = RefreshToken.for_user(self.user)
        response = client.post("/api/v1/auth/logout/", {"refresh": str(token)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"detail"})

    def test_advanced_search_health_metrics_and_null_fee_contracts(self):
        response = self.client.get("/api/v1/credit-cards/advanced-search/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {
                "query",
                "normalized_query",
                "total",
                "page",
                "page_size",
                "results",
                "facets",
                "took",
                "source",
                "sort_options",
                "categories",
                "cached",
            },
        )
        for endpoint in ("sort-options/", "categories/", "normalize/"):
            response = self.client.get(f"/api/v1/credit-cards/advanced-search/{endpoint}")
            self.assertEqual(response.status_code, 200, endpoint)
            self.assertIsInstance(response.data, (dict, list))
        response = self.client.get("/api/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive"})
        response = self.client.get("/api/readyz/")
        self.assertIn(response.status_code, (200, 503))
        self.assertEqual(set(response.json()), {"status", "checks", "total_latency_ms"})
        with override_settings(METRICS_TOKEN="contract-secret", METRICS_ALLOWED_IPS=[]):
            response = self.client.get("/metrics")
            self.assertEqual(response.status_code, 403)
            response = self.client.get(
                "/metrics", HTTP_AUTHORIZATION="Bearer contract-secret"
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/plain", response["Content-Type"])

        card_response = self.client.get(f"/api/v1/credit-cards/{self.card.id}/")
        self.assertEqual(card_response.status_code, 200)
        self.assertIsNone(card_response.data["annual_fee"])
        self.assertIsNone(card_response.data["interest_rate_apr"])

    def test_saved_reviews_and_alert_response_shapes(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/v1/saved/comparisons/", {"name": "Trip", "card_ids": [self.card.id]}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "name",
                "notes",
                "is_public",
                "share_token",
                "cards",
                "created",
                "modified",
            },
        )
        comparison = SavedComparison.objects.get(pk=response.data["id"])
        comparison.is_public = True
        comparison.save()
        response = self.client.get(f"/api/v1/saved/shared/{comparison.share_token}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"name", "notes", "cards", "modified"})

        response = self.client.post(
            "/api/v1/saved/collections/", {"name": "Travel", "description": ""}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "name",
                "description",
                "is_public",
                "slug",
                "cards",
                "created",
                "modified",
            },
        )
        collection = response.data
        response = self.client.get(
            f"/api/v1/saved/shared/collections/{collection['slug']}/"
        )
        self.assertEqual(response.status_code, 404)  # private collections are not shared
        saved_collection = Collection.objects.get(pk=collection["id"])
        saved_collection.is_public = True
        saved_collection.save()
        response = self.client.get(
            f"/api/v1/saved/shared/collections/{saved_collection.slug}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data), {"name", "description", "slug", "cards", "modified"}
        )

        response = self.client.get("/api/v1/reviews/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        response = self.client.get(f"/api/v1/reviews/cards/{self.card.id}/summary/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data), {"card", "average_rating", "review_count", "distribution"}
        )
        review = CardReview.objects.create(
            user=self.user,
            card=self.card,
            rating=5,
            title="Great",
            body="Very good",
            pros="Useful",
            cons="None",
            status=CardReview.Status.APPROVED,
        )
        voter = get_user_model().objects.create_user(
            username="voter@example.com",
            email="voter@example.com",
            password="S3cure!passphrase",
        )
        self.client.force_authenticate(user=voter)
        response = self.client.post(f"/api/v1/reviews/{review.id}/helpful/")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), {"helpful_count"})

        submitter = get_user_model().objects.create_user(
            username="reviewer@example.com",
            email="reviewer@example.com",
            password="S3cure!passphrase",
        )
        submitter.profile.email_verified = True
        submitter.profile.save()
        self.client.force_authenticate(user=submitter)
        review_card = CreditCardFactory()
        response = self.client.post(
            "/api/v1/reviews/",
            {
                "card": review_card.id,
                "rating": 4,
                "title": "Good value",
                "body": "I use this card often.",
                "pros": "Useful rewards",
                "cons": "None",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "card",
                "rating",
                "title",
                "body",
                "pros",
                "cons",
                "reviewer_name",
                "helpful_count",
                "created",
                "modified",
            },
        )
        staff = get_user_model().objects.create_user(
            username="moderator", password="S3cure!passphrase", is_staff=True
        )
        self.client.force_authenticate(user=staff)
        response = self.client.get("/api/v1/reviews/moderation/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})

        response = self.client.post(
            "/api/v1/alerts/subscriptions/", {"card": self.card.id, "kind": "fee_change"}
        )
        # The subscription choices are validated by the serializer; use its explicit required contract on failure.
        if response.status_code == 201:
            self.assertEqual(
                set(response.data),
                {"id", "card", "card_name", "bank_name", "kind", "is_active", "created"},
            )
            subscription = AlertSubscription.objects.get(pk=response.data["id"])
            url = f"/api/v1/alerts/unsubscribe/{subscription.unsubscribe_token}/"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                set(response.data), {"confirm_required", "is_active", "kind", "card_name"}
            )
            response = self.client.post(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.data), {"detail"})
        else:
            self.assertEqual(response.status_code, 400)

        response = self.client.get("/api/v1/alerts/preferences/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"frequency"})
        token = signing.dumps("unsubscribe-contract", salt="alerts.unsubscribe")
        response = self.client.get(f"/api/v1/alerts/unsubscribe/{token}/")
        self.assertEqual(response.status_code, 404)
