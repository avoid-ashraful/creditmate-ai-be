from rest_framework.permissions import SAFE_METHODS
from rest_framework.settings import api_settings
from rest_framework.throttling import UserRateThrottle


class ReviewUserThrottle(UserRateThrottle):
    scope = "review_write"


class ReviewWriteThrottleMixin:
    """Apply the review write rate limit to mutating requests only.

    Public review reads (list/retrieve) must not be governed by the 5/hour
    ``review_write`` scope, so safe requests fall back to the project-wide
    default throttles (anonymous/user/burst) instead.
    """

    def get_throttles(self):
        if self.request.method in SAFE_METHODS:
            return [throttle() for throttle in api_settings.DEFAULT_THROTTLE_CLASSES]
        return super().get_throttles()
