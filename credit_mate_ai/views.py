"""
Health check views for deployment monitoring.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def health_check(request):
    """Simple health check endpoint for deployment monitoring.

    Returns
    -------
    JsonResponse
        JSON response with status and timestamp
    """
    return JsonResponse(
        {"status": "healthy", "message": "Credit Mate AI Backend is running"}
    )
