"""Request validation middleware for API traffic.

Payload limits use normal WSGI Content-Length framing. This does not claim
protection against protocol-level framing attacks handled by an upstream server.
"""

from django.http import JsonResponse

BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
JSON_MEDIA_TYPES = {"application/json"}
FORM_MEDIA_TYPES = {"application/x-www-form-urlencoded", "multipart/form-data"}
ALLOWED_MEDIA_TYPES = JSON_MEDIA_TYPES | FORM_MEDIA_TYPES


class SecurityHeadersMiddleware:
    """Apply defensive HTTP headers to every response.

    Adds Content-Security-Policy, X-Frame-Options, and Referrer-Policy.
    Values come from settings and are overridable via environment
    variables (CSP_HEADER, X_FRAME_OPTIONS, REFERRER_POLICY). HSTS and
    other TLS-related headers stay with Django's SecurityMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", settings.CSP_HEADER)
        response.headers["X-Frame-Options"] = settings.X_FRAME_OPTIONS
        response.headers["Referrer-Policy"] = settings.REFERRER_POLICY
        return response


class RequestValidationMiddleware:
    """Validate API body size/content type using normal WSGI framing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method in BODY_METHODS:
            response = self.validate_api_request(request)
            if response is not None:
                return response
        return self.get_response(request)

    def validate_api_request(self, request):
        from django.conf import settings

        media_type = (
            request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )

        try:
            content_length = int(request.headers.get("Content-Length", "0") or 0)
        except ValueError:
            return self.error_response(400, "Invalid Content-Length header.")

        if request.META.get("TRANSFER_ENCODING", "").lower() == "chunked":
            return self.error_response(400, "Chunked request bodies are not supported.")

        if media_type and media_type not in ALLOWED_MEDIA_TYPES:
            return self.error_response(415, "Unsupported Content-Type header.")

        if content_length < 0:
            return self.error_response(400, "Invalid Content-Length header.")

        if not media_type and content_length > 0:
            return self.error_response(400, "Content-Type header is required.")

        limit = (
            settings.MAX_JSON_REQUEST_BYTES
            if media_type in JSON_MEDIA_TYPES
            else settings.MAX_UPLOAD_REQUEST_BYTES
        )
        if content_length > limit:
            return self.error_response(
                413, "Request body exceeds the configured size limit."
            )

        return None

    @staticmethod
    def error_response(status_code, detail):
        return JsonResponse({"detail": detail}, status=status_code)
