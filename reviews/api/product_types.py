"""Registry mapping public product-type names to their review machinery.

Phase 3B generalises the original card-only review system. Cards keep
their historical model, endpoints and payloads untouched; deposits,
loans and bank accounts share one generic implementation driven by this
registry. Comments (and the summaries' ``community_reviewed`` flag) span
all four types.
"""

from django.contrib.contenttypes.models import ContentType

from bank_accounts.models import AccountProduct
from credit_cards.models import CreditCard
from deposits.models import DepositProduct
from loans.models import LoanProduct
from reviews.models import (
    AccountReview,
    CardReview,
    DepositReview,
    LoanReview,
    ProductReviewVote,
    ReviewVote,
)

# URL/query name -> config for the three generalised verticals.
PRODUCT_REVIEW_TYPES = {
    "deposit": {
        "review_model": DepositReview,
        "product_model": DepositProduct,
    },
    "loan": {
        "review_model": LoanReview,
        "product_model": LoanProduct,
    },
    "account": {
        "review_model": AccountReview,
        "product_model": AccountProduct,
    },
}

# Every reviewable product type, cards included (used by comments and
# moderation, which span all four).
ALL_REVIEW_TYPES = {
    "card": {
        "review_model": CardReview,
        "product_model": CreditCard,
        "vote_model": ReviewVote,
    },
    **{
        name: {**config, "vote_model": ProductReviewVote}
        for name, config in PRODUCT_REVIEW_TYPES.items()
    },
}


def review_content_type(review_model):
    return ContentType.objects.get_for_model(review_model)


def review_type_for_model(review_model):
    for name, config in ALL_REVIEW_TYPES.items():
        if config["review_model"] is review_model:
            return name
    return None
