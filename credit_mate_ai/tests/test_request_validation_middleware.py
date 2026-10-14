import json

from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from credit_mate_ai.middleware import RequestValidationMiddleware


def always_ok(request):
    return request


def test_api_request_without_body_is_allowed():
    request = RequestFactory().get(reverse("bank-list"))
    request.META["CONTENT_LENGTH"] = "0"
    request.META["CONTENT_TYPE"] = ""
    middleware = RequestValidationMiddleware(always_ok)
    assert middleware(request) is request


def test_api_delete_with_empty_body_is_allowed():
    request = RequestFactory().delete(reverse("bank-list"))
    request.META["CONTENT_LENGTH"] = "0"
    middleware = RequestValidationMiddleware(always_ok)
    assert middleware(request) is request


def test_non_api_path_is_not_validated():
    request = RequestFactory().post("/admin/", data={}, content_type="application/xml")
    middleware = RequestValidationMiddleware(always_ok)
    assert middleware(request) is request


@override_settings(MAX_JSON_REQUEST_BYTES=1024, MAX_UPLOAD_REQUEST_BYTES=2048)
def test_json_payload_over_limit_returns_413():
    request = RequestFactory().post(
        reverse("bank-list"), data="x" * 1025, content_type="application/json"
    )
    response = RequestValidationMiddleware(always_ok)(request)
    assert response.status_code == 413
    assert json.loads(response.content) == {
        "detail": "Request body exceeds the configured size limit."
    }


@override_settings(MAX_JSON_REQUEST_BYTES=1024, MAX_UPLOAD_REQUEST_BYTES=2048)
def test_json_payload_at_limit_is_allowed():
    request = RequestFactory().post(
        reverse("bank-list"), data="x" * 1024, content_type="application/json"
    )
    assert RequestValidationMiddleware(always_ok)(request) is request


@override_settings(MAX_JSON_REQUEST_BYTES=1024, MAX_UPLOAD_REQUEST_BYTES=2048)
def test_multipart_payload_uses_upload_limit():
    request = RequestFactory().post(
        reverse("bank-list"),
        data="x" * 2048,
        content_type="multipart/form-data; boundary=boundary",
    )
    assert RequestValidationMiddleware(always_ok)(request) is request


def test_unsupported_content_type_returns_415():
    request = RequestFactory().post(
        reverse("bank-list"), data="<root/>", content_type="application/xml"
    )
    response = RequestValidationMiddleware(always_ok)(request)
    assert response.status_code == 415
    assert json.loads(response.content) == {"detail": "Unsupported Content-Type header."}


def test_unsupported_content_type_with_body_is_rejected():
    request = RequestFactory().post(
        reverse("bank-list"), data="x" * 10, content_type="text/plain"
    )
    response = RequestValidationMiddleware(always_ok)(request)
    assert response.status_code == 415


def test_absent_content_type_with_body_is_rejected():
    request = RequestFactory().post(
        reverse("bank-list"), data="x" * 10, content_type="application/json"
    )
    del request.META["CONTENT_TYPE"]
    response = RequestValidationMiddleware(always_ok)(request)
    assert response.status_code == 400
    assert json.loads(response.content) == {"detail": "Content-Type header is required."}


def test_invalid_content_length_returns_400():
    request = RequestFactory().post(
        reverse("bank-list"), data="x", content_type="application/json"
    )
    request.META["CONTENT_LENGTH"] = "invalid"
    response = RequestValidationMiddleware(always_ok)(request)
    assert response.status_code == 400
    assert json.loads(response.content) == {"detail": "Invalid Content-Length header."}


def test_chunked_api_body_returns_400():
    request = RequestFactory().post(
        reverse("bank-list"), data="x", content_type="application/json"
    )
    request.META["TRANSFER_ENCODING"] = "chunked"
    response = RequestValidationMiddleware(always_ok)(request)
    assert response.status_code == 400
    assert json.loads(response.content) == {
        "detail": "Chunked request bodies are not supported."
    }


def test_client_reaches_middleware_errors_without_view_exception():
    client = Client()
    response = client.post(reverse("bank-list"), data="x", content_type="application/xml")
    assert response.status_code == 415
