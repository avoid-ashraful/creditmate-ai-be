#!/usr/bin/env python3
"""End-to-end smoke checks for the merged Credit Mate API."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import requests
except ImportError:  # pragma: no cover - exercised in minimal environments
    requests = None


BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
DELAY = float(os.environ.get("SMOKE_REQUEST_DELAY", "0.12"))
results = []
token = None
refresh = None
card_id = None
share_token = None
unsubscribe_token = None


def request(method, path, payload=None, auth=False):
    url = BASE + path
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if auth and token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload).encode() if payload is not None else None
    if requests:
        response = requests.request(method, url, data=body, headers=headers, timeout=15)
        status, raw = response.status_code, response.text
    else:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                status, raw = response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode()
    time.sleep(DELAY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = raw
    return status, data


def check(name, fn):
    try:
        fn()
    except Exception as exc:  # keep running so the report covers all surfaces
        results.append((name, False, str(exc)[:240]))
    else:
        results.append((name, True, ""))


def expect(method, path, codes=(200,), payload=None, auth=False):
    status, data = request(method, path, payload, auth)
    if status not in codes:
        raise AssertionError(f"{method} {path}: HTTP {status}, expected {codes}; {data!r}")
    return data


def card_suite():
    global card_id
    data = expect("GET", "/api/v1/credit-cards/")
    rows = data.get("results", data) if isinstance(data, dict) else data
    if not rows:
        raise AssertionError("card list is empty")
    card_id = rows[0]["id"]
    bank = rows[0].get("bank")
    bank_id = bank.get("id") if isinstance(bank, dict) else bank
    expect("GET", f"/api/v1/credit-cards/?bank={bank_id}")
    expect("GET", f"/api/v1/credit-cards/{card_id}/")
    ahead = expect("GET", "/api/v1/credit-cards/typeahead/?q=Smoke")
    if "suggestions" not in ahead:
        raise AssertionError("typeahead omitted suggestions")
    expect("GET", "/api/v1/credit-cards/search-suggestions/")
    expect("GET", "/api/v1/credit-cards/advanced-search/")
    expect("GET", "/api/v1/credit-cards/advanced-search/sort-options/")
    expect("GET", "/api/v1/credit-cards/advanced-search/categories/")
    expect("GET", "/api/v1/credit-cards/advanced-search/normalize/?q=smoke")


def auth_suite():
    global token, refresh
    email = "smoke-user@example.test"
    expect("POST", "/api/v1/auth/register/", (201,), {
        "email": email, "password": "Smoke-test-pass-482!",
        "password_confirm": "Smoke-test-pass-482!", "first_name": "Smoke",
        "last_name": "Runner",
    })
    data = expect("POST", "/api/v1/auth/login/", (200,), {
        "email": email, "password": "Smoke-test-pass-482!",
    })
    token, refresh = data.get("access"), data.get("refresh")
    if not token or not refresh:
        raise AssertionError("login omitted access/refresh tokens")
    expect("GET", "/api/v1/auth/me/", auth=True)
    data = expect("POST", "/api/v1/auth/token/refresh/", (200,), {"refresh": refresh})
    token = data.get("access", token)
    expect("POST", "/api/v1/auth/logout/", (200, 204), {"refresh": refresh}, auth=True)


def comparison_suite():
    global share_token
    data = expect("POST", "/api/v1/saved/comparisons/", (201,), {
        "name": "Smoke comparison", "card_ids": [card_id], "is_public": True,
    }, auth=True)
    expect("GET", "/api/v1/saved/comparisons/", auth=True)
    share_token = data.get("share_token")
    if not share_token:
        raise AssertionError("comparison omitted share_token")
    expect("GET", f"/api/v1/saved/shared/{share_token}/")


def review_suite():
    data = expect("POST", "/api/v1/reviews/", (201,), {
        "card": card_id, "rating": 4, "title": "Smoke review", "body": "Smoke run review content.",
    }, auth=True)
    expect("GET", f"/api/v1/reviews/?card={card_id}")
    expect("GET", f"/api/v1/reviews/cards/{card_id}/summary/")
    if not data:
        raise AssertionError("review creation response was empty")


def alert_suite():
    data = expect("POST", "/api/v1/alerts/subscriptions/", (201,), {
        "kind": "fee_change", "card": card_id,
    }, auth=True)
    expect("GET", "/api/v1/alerts/subscriptions/", auth=True)
    # Owner deletion is the supported authenticated unsubscribe path; the
    # public signed-token route is for links delivered in alert email.
    expect("DELETE", f"/api/v1/alerts/subscriptions/{data['id']}/", (204,), {}, auth=True)


def main():
    check("GET /health/", lambda: expect("GET", "/health/"))
    check("GET /api/healthz/", lambda: expect("GET", "/api/healthz/"))
    check("GET /api/readyz/", lambda: expect("GET", "/api/readyz/"))
    check("Cards: list, filter, detail, typeahead, suggestions, advanced search", card_suite)
    check("Auth: register → login → me → refresh → logout", auth_suite)
    check("Cards: field history (authenticated)", lambda: expect("GET", f"/api/v1/credit-cards/{card_id}/field-history/", auth=True))
    check("Saved comparisons: create, list, public share", comparison_suite)
    check("Reviews: create pending, public list and summary", review_suite)
    check("Alerts: subscribe, list, unsubscribe", alert_suite)
    check("GET /api/v1/schema/", lambda: expect("GET", "/api/v1/schema/"))
    check("GET /metrics denied without token", lambda: expect("GET", "/metrics", (401, 403)))
    width = max(len(name) for name, _, _ in results)
    print(f"{'CHECK':<{width}}  RESULT  DETAILS")
    print(f"{'-' * width}  ------  -------")
    for name, passed, detail in results:
        print(f"{name:<{width}}  {'PASS' if passed else 'FAIL':<6}  {detail}")
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
