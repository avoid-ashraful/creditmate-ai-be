"""Bounded page-number pagination.

Supports the real frontend's `page_size` requests while protecting the API
from unbounded result sets: default page size 20, hard maximum 100.
"""

import os

from rest_framework.pagination import PageNumberPagination


class BoundedPageNumberPagination(PageNumberPagination):
    """PageNumberPagination honoring `page_size` with a hard upper bound."""

    page_size = int(os.getenv("PAGE_SIZE_DEFAULT", "20"))
    page_size_query_param = "page_size"
    max_page_size = int(os.getenv("PAGE_SIZE_MAX", "100"))
