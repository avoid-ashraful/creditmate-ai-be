"""Bounded page-number pagination.

Supports the real frontend's `page_size` requests while protecting the API
from unbounded result sets: default page size 20, hard maximum 100.
"""

import os

from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination


class BoundedPageNumberPagination(PageNumberPagination):
    """PageNumberPagination honoring `page_size` with a hard upper bound."""

    page_size = int(os.getenv("PAGE_SIZE_DEFAULT", "20"))
    page_size_query_param = "page_size"
    max_page_size = int(os.getenv("PAGE_SIZE_MAX", "100"))

    def _invalid(self, param, message):
        raise ValidationError({param: [message]})

    def get_page_number(self, request, paginator):
        """Return a validated page number, rejecting non-integer input.

        Malformed values raise a DRF ``ValidationError`` (HTTP 400) instead of
        the default 404 so every numeric query parameter reports the same
        error envelope.
        """
        raw = request.query_params.get(self.page_query_param)
        if raw is None or raw == "":
            return 1
        if raw in self.last_page_strings:
            return paginator.num_pages
        try:
            number = int(raw)
        except (TypeError, ValueError):
            self._invalid(self.page_query_param, "A valid integer is required.")
        if number < 1:
            self._invalid(self.page_query_param, "A positive integer is required.")
        return number

    def get_page_size(self, request):
        """Return a validated page size bounded by ``max_page_size``.

        Non-integer values raise a DRF ``ValidationError`` (HTTP 400); values
        above the maximum are clamped as before.
        """
        raw = request.query_params.get(self.page_size_query_param)
        if raw is None or raw == "":
            return self.page_size
        try:
            size = int(raw)
        except (TypeError, ValueError):
            self._invalid(self.page_size_query_param, "A valid integer is required.")
        if size < 1:
            self._invalid(self.page_size_query_param, "A positive integer is required.")
        return min(size, self.max_page_size)
