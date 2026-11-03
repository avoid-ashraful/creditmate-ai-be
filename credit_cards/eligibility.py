"""Income-based eligibility estimates for public credit cards.

Bangladesh has no consumer credit score, and the cards in this catalogue
publish exactly one per-card eligibility criterion: ``min_monthly_income``.
Verdicts here are therefore driven ONLY by that published number and the
applicant's self-declared CIB status:

- ``eligible``  — income meets the published minimum and the applicant
  declares a clean CIB status.
- ``likely``    — income meets the published minimum but CIB status is not
  declared clean, OR income is close to the minimum (within the
  ``LIKELY_INCOME_BAND`` below it).
- ``unknown``   — the card publishes no minimum income; the bank decides
  from the full application. We do not guess a verdict for these cards.
- ``not_yet``   — income is below the published minimum (beyond the likely
  band), or the applicant declares CIB issues.

Age, employment type and TIN are NOT verdict inputs: no card publishes
per-card requirements for them, so inventing rules would be fabrication.
They only produce the general guidance notes in :func:`profile_notes`.

The word choices matter: nothing here (or in API copy built on it) may
claim an applicant is "pre-approved" or "guaranteed" a card. Banks make
the final decision after CIB and document checks.
"""

from decimal import Decimal

#: Income at or above this fraction of a card's published minimum counts
#: as "likely" rather than "not_yet" — the applicant is close enough that
#: a conversation with the bank is realistic, without pretending the
#: published requirement is met.
LIKELY_INCOME_BAND = Decimal("0.8")

DISCLAIMER = (
    "This is an estimate based on each card's published criteria and the "
    "answers you provided. It is not an offer or a lending decision. The "
    "issuing bank makes the final decision after checking your CIB report, "
    "documents, and its own policies."
)

METHOD = (
    "Verdicts use only each card's published minimum monthly income and "
    "your self-declared CIB status. Cards do not publish per-card age, "
    "employment, or document requirements, so those answers never change "
    "a verdict — they only add the guidance notes below."
)

VERDICT_ELIGIBLE = "eligible"
VERDICT_LIKELY = "likely"
VERDICT_UNKNOWN = "unknown"
VERDICT_NOT_YET = "not_yet"

#: Display order: strongest verdicts first, "not yet" last.
VERDICT_ORDER = {
    VERDICT_ELIGIBLE: 0,
    VERDICT_LIKELY: 1,
    VERDICT_UNKNOWN: 2,
    VERDICT_NOT_YET: 3,
}

CIB_CLEAN = "clean"
CIB_HAS_ISSUES = "has_issues"
CIB_UNKNOWN = "unknown"


def format_bdt(amount):
    """Format a Decimal BDT amount with thousands separators.

    Parameters
    ----------
    amount : Decimal
        The amount in BDT.

    Returns
    -------
    str
        e.g. ``"BDT 30,000"`` (whole amounts drop the decimal part).
    """
    if amount == amount.to_integral_value():
        return f"BDT {amount:,.0f}"
    return f"BDT {amount:,.2f}"


def evaluate_card(min_monthly_income, monthly_income, cib_status):
    """Return ``(verdict, reasons)`` for one card and applicant profile.

    Parameters
    ----------
    min_monthly_income : Decimal or None
        The card's published minimum monthly income, or None when the
        card publishes none.
    monthly_income : Decimal
        The applicant's self-declared monthly income in BDT.
    cib_status : str
        One of ``"clean"``, ``"has_issues"``, ``"unknown"``.

    Returns
    -------
    tuple of (str, list of str)
        The verdict and human-readable reasons that reference the actual
        published and declared numbers.
    """
    if cib_status == CIB_HAS_ISSUES:
        reasons = [
            "You told us your CIB status has issues. Banks in Bangladesh "
            "check the Credit Information Bureau (CIB) report, and "
            "unresolved issues usually stop a new card until they are "
            "cleared with the reporting bank."
        ]
        if min_monthly_income is not None and monthly_income < min_monthly_income:
            reasons.append(
                f"Published minimum income is {format_bdt(min_monthly_income)}; "
                f"yours is {format_bdt(monthly_income)}."
            )
        return VERDICT_NOT_YET, reasons

    if min_monthly_income is None:
        return VERDICT_UNKNOWN, [
            "No published income requirement — the bank decides based on "
            "your full application, documents, and CIB check."
        ]

    if monthly_income >= min_monthly_income:
        if cib_status == CIB_CLEAN:
            return VERDICT_ELIGIBLE, [
                f"Your income of {format_bdt(monthly_income)} meets the "
                f"published minimum of {format_bdt(min_monthly_income)}, "
                "and you declared a clean CIB status."
            ]
        return VERDICT_LIKELY, [
            f"Your income of {format_bdt(monthly_income)} meets the "
            f"published minimum of {format_bdt(min_monthly_income)}.",
            "You did not confirm a clean CIB status, so treat this as "
            "likely rather than certain — the bank will run a CIB check.",
        ]

    if monthly_income >= min_monthly_income * LIKELY_INCOME_BAND:
        return VERDICT_LIKELY, [
            f"Published minimum income is {format_bdt(min_monthly_income)}; "
            f"yours is {format_bdt(monthly_income)} — within 20% below the "
            "published minimum, so you are close. The bank makes the final "
            "call and may weigh your overall banking relationship."
        ]

    return VERDICT_NOT_YET, [
        f"Published minimum income is {format_bdt(min_monthly_income)}; "
        f"yours is {format_bdt(monthly_income)}, which is below the "
        "published minimum."
    ]


def profile_notes(employment_type, age, has_tin):
    """General application guidance that does NOT affect verdicts.

    Parameters
    ----------
    employment_type : str
        ``"salaried"``, ``"self_employed"`` or ``"other"``.
    age : int or None
        Applicant age when provided.
    has_tin : bool or None
        Whether the applicant has an e-TIN certificate, when answered.

    Returns
    -------
    list of str
        Advisory notes, in display order.
    """
    notes = []
    if has_tin is False:
        notes.append(
            "Most banks in Bangladesh ask for an e-TIN certificate when "
            "you apply for a credit card. Arranging one before you apply "
            "can save a return trip."
        )
    if employment_type == "self_employed":
        notes.append(
            "Self-employed applicants are usually asked for a trade "
            "licence and recent bank statements instead of a salary "
            "certificate."
        )
    elif employment_type == "other":
        notes.append(
            "Banks usually ask for proof of your income source; the exact "
            "documents vary by bank."
        )
    if age is not None and age < 21:
        notes.append(
            "Many banks set a minimum applicant age (often 21). These "
            "cards do not publish age limits, so check with the bank "
            "before applying."
        )
    return notes
