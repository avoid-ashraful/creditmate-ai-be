"""Middleware for common application concerns."""
import logging

from django.http import JsonResponse

logger = logging.getLogger(__name__)


class RequestSizeValidationMiddleware:
    """Middleware to validate and limit the size of incoming requests.

    Prevents denial of service attacks and abuse by limiting maximum
    request body size. Configurable via settings.

    Parameters
    ----------
    get_response : callable
        Django middleware get_response callable

    Attributes
    ----------
    MAX_UPLOAD_SIZE : int
        Maximum allowed request body size in bytes (default: 10MB)
    """

    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB in bytes

    def __init__(self, get_response):
        """Initialize middleware.

        Parameters
        ----------
        get_response : callable
            Django middleware get_response callable
        """
        self.get_response = get_response

    def __call__(self, request):
        """Process request and validate size.

        Parameters
        ----------
        request : HttpRequest
            Django HTTP request object

        Returns
        -------
        HttpResponse
            Response object, either error response for oversized requests
            or normal response from view
        """
        # Get content length from headers
        content_length = request.META.get("CONTENT_LENGTH")

        if content_length is not None:
            try:
                content_length = int(content_length)

                # Check if request exceeds maximum allowed size
                if content_length > self.MAX_UPLOAD_SIZE:
                    logger.warning(
                        f"Request rejected: Size {content_length} bytes exceeds "
                        f"maximum {self.MAX_UPLOAD_SIZE} bytes from IP {self.get_client_ip(request)}"
                    )

                    return JsonResponse(
                        {
                            "error": "Request too large",
                            "detail": f"Request body size exceeds maximum allowed size of "
                            f"{self.MAX_UPLOAD_SIZE / (1024 * 1024):.1f}MB",
                            "max_size_mb": self.MAX_UPLOAD_SIZE / (1024 * 1024),
                        },
                        status=413,  # 413 Payload Too Large
                    )

            except ValueError:
                # Invalid content-length header, let Django handle it
                logger.warning(f"Invalid CONTENT_LENGTH header: {content_length}")

        # Continue processing request
        response = self.get_response(request)
        return response

    def get_client_ip(self, request):
        """Get client IP address from request.

        Parameters
        ----------
        request : HttpRequest
            Django HTTP request object

        Returns
        -------
        str
            Client IP address
        """
        # Check for forwarded IP (when behind proxy/load balancer)
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "unknown")
        return ip
