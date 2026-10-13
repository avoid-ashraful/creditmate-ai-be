from rest_framework.throttling import UserRateThrottle


class ReviewUserThrottle(UserRateThrottle):
    scope = "review_write"
