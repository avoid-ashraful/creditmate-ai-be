"""Admin-facing views for the banks app.

Only the data-quality dashboard is currently exposed here; it is served under
``/admin/data-quality/`` (see ``credit_mate_ai.urls``) and restricted to
logged-in staff via Django's ``staff_member_required`` decorator, i.e. the
same login + is-staff gate used by the Django admin itself.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from banks.services.quality_dashboard import build_dashboard


@staff_member_required
@require_GET
def data_quality_dashboard(request):
    """Serve the data-quality snapshot as JSON for operations staff.

    Uses Django's ``staff_member_required`` decorator: anonymous users and
    authenticated non-staff users are redirected to the admin login (302),
    and staff members receive the JSON snapshot.

    Parameters
    ----------
    request : HttpRequest
        The GET request.

    Returns
    -------
    JsonResponse
        Snapshot produced by :func:`build_dashboard`.
    """
    return JsonResponse(build_dashboard())
