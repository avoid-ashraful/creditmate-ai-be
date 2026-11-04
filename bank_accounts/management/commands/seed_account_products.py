"""Seed the BB fee schedule and the v1 account-product catalogue.

Data provenance (all figures transcribed 2026-11-04 from the banks' own
published documents — see the per-bank ``soc``/``rates`` URLs in the
data below):

* BRAC Bank — Retail Deposits SOC eff. 13 Oct 2026 + ALCO deposit rate
  sheet w.e.f. 02 Dec 2025.
* City Bank — Retail SOC eff. 14 Oct 2025 + deposit rate page w.e.f.
  01 Nov 2026.
* Eastern Bank — Retail SOC eff. 15 Oct 2026 (Bengali) + deposit rate
  sheet eff. 01 Nov 2026. EBL's cards SOC is a scanned PDF; its debit
  card annual fee could not be extracted and is stored as null
  ("not published"), never guessed.
* Bank Asia — Schedule of Charges 2026 (eff. July 2026); Islamic
  provisional profit rates from the bank's ISR page. Bank Asia does not
  publish a conventional savings rate in the sources found, so its
  conventional savings product carries no rate slabs.
* ONE Bank — SOC eff. 15 Mar 2026. ONE Bank's rates page is JS-driven
  and did not yield figures; rates are null, not invented.
* Standard Bank — SOC updated 30 Jun 2026 (Islamic: Mudaraba/Al-Wadiah).
* Premier Bank — SOC 2026 + interest rates on deposits w.e.f.
  01 Apr 2026.
* Meghna Bank — SOC eff. 01 Nov 2024 + deposit rate circular w.e.f.
  01 Jun 2026 (the circular's slab table is partially illegible OCR;
  only its legible headline savings rate, 2.50%, is used, and the
  affected products say so).
* Islami Bank — product terms from IBBL product pages (read via the
  banksbd.org mirror; islamibankbd.com was unreachable through the
  egress proxy). IBBL publishes no product-level fee figures there;
  its savings figure is the BB announced expected-profit range.
* Dutch-Bangla Bank — DBBL publishes no current SOC on its website.
  Fees are from a published customer statement (Dec 2025, VAT-inclusive
  figures converted to ex-VAT) and the BB maintenance schedule the
  statement confirms; flagged ``bank_statement_evidence``.
* Pubali Bank — no SOC found; savings rate is the current BB announced
  figure (2.50% flat, Oct 2026 chart), which supersedes the 4.00% on
  Pubali's legacy page (noted on the product).

The BB deposit chart itself could not be re-fetched live during
seeding (bb.org.bd timed out / bot-challenged through the egress
proxy); the cross-check below uses the Oct 2026 chart figures verified
in the Phase 2 research pass earlier the same day.

Fees are stored excluding VAT. ``None`` always means "not published in
the sources we hold" — never zero. Idempotent: products are
update-or-created by slug.
"""

from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from bank_accounts.constants import (
    SCHEDULE_CURRENT_MAINTENANCE_CAP,
    SCHEDULE_SAVINGS_MAINTENANCE,
)
from bank_accounts.models import AccountFeeSchedule, AccountProduct
from banks.models import Bank
from credit_cards.constants import VerificationStatus

VERIFIED_AT = timezone.make_aware(datetime(2026, 11, 4, 12, 0))

# --- source documents -------------------------------------------------------
BRAC_SOC = "https://brackweb.s3.ap-southeast-1.amazonaws.com/uploads/all/SoC_Retail_Deposits_13-10-20266ace161e868c6.pdf"
BRAC_RATES = "https://brackweb.s3.ap-southeast-1.amazonaws.com/uploads/all/BRAC_Bank_Deposit_Interest_Rate_w.e.f._December_02,_2025692d3233ab87e.pdf"
CITY_SOC = "https://www.citybankplc.com/upload/Retail-SOC-14-October-2025.pdf"
CITY_RATES = "https://www.citybankplc.com/gsi/conventional-banking-products"
EBL_SOC = "https://www.ebl.com.bd/assets/home/schedule/Retail-SOC-15th-Oct-26.pdf"
EBL_RATES = "https://www.ebl.com.bd/assets/home/interest/Deposit_Rate_sheet-ED_01_November_2026_EBL_WEB_Version_Final.pdf"
EBL_CLASSIC_PAGE = "https://www.ebl.com.bd/retail-deposit/EBL-Classic-Savings"
EBL_CAMPUS_PAGE = "https://ebl.com.bd/student-banking/EBL-Campus-Account"
EBL_JUNIOR_PAGE = "https://www.ebl.com.bd/student-banking/EBL-Junior"
BANKASIA_SOC = (
    "https://bankasia-bd.com/assets/home/schedule/Schedule_of_Charge_2026_FINAL.pdf"
)
BANKASIA_ISR = "https://www.bankasia-bd.com/islamic/islamicdetails/32"
ONEBANK_SOC = (
    "https://www.onebank.com.bd/Schedule-of-Charges/Schedul-of-Charges-15032026.pdf"
)
STANDARD_SOC = (
    "https://www.standardbankbd.com/file?id=ea925f44-523b-4c7c-9a9d-2590008c34f5.pdf"
)
PREMIER_SOC = "https://thepremierbankplc.com/wp-content/uploads/2025/04/Schedule-of-Charges-Commissions-Conventional-2026.pdf"
PREMIER_RATES = "https://thepremierbankplc.com/wp-content/uploads/2025/10/Interest-Rates-on-Deposit-Products-as-on-01-April-2026v2.pdf"
MEGHNA_SOC = "https://www.meghnabank.com.bd/public/images/871422_Schedule%20of%20charge_1st%20November%202024.pdf"
MEGHNA_RATES = (
    "https://meghnabank.com.bd/public/images/427005_Deposits%20Rate%20Circular.pdf"
)
IBBL_MSA_TERMS = "https://www.banksbd.org/ibbl/accounts/msa.html"
BB_CHART = "https://www.bb.org.bd/en/index.php/financialactivity/interestdeposit"
PUBALI_MUDARABA_PAGE = "https://new.pubalibangla.com/MudarabahSavingsAccount"

FEE_SCHEDULES = [
    {
        "key": SCHEDULE_SAVINGS_MAINTENANCE,
        "effective_from": date(2019, 10, 1),
        "params": {
            "period": "half_yearly",
            "slabs": [
                {"up_to": "10000", "fee": "0"},
                {"up_to": "25000", "fee": "100"},
                {"up_to": "200000", "fee": "200"},
                {"up_to": "1000000", "fee": "250"},
                {"up_to": None, "fee": "300"},
            ],
        },
        "description": "Savings account maintenance fee (half-yearly) fixed "
        "by Bangladesh Bank by weighted average balance: free up to "
        "Tk 10,000; Tk 100 to Tk 25,000; Tk 200 to Tk 2 lakh; Tk 250 to "
        "Tk 10 lakh; Tk 300 above. Banks may charge less, never more.",
        "source_note": "Bangladesh Bank instruction (October 2019), "
        "recorded in BB Annual Report FY2019-20, Appendix 1 (chronology "
        "of monetary/credit policy measures); confirmed verbatim in the "
        "current SOCs of City, Bank Asia, ONE Bank, Standard, Premier "
        "and Meghna banks.",
    },
    {
        "key": SCHEDULE_CURRENT_MAINTENANCE_CAP,
        "effective_from": date(2019, 10, 1),
        "params": {"period": "half_yearly", "max_fee": "300"},
        "description": "Current account maintenance fee capped at "
        "Tk 300 half-yearly for every bank.",
        "source_note": "Same BB instruction (October 2019), recorded in "
        "BB Annual Report FY2019-20, Appendix 1.",
    },
]


def s(low, high, rate, rate_max=None):
    """One rate slab ([low, high) balance band)."""
    slab = {
        "balance_min": str(low),
        "balance_max": None if high is None else str(high),
        "rate": str(rate),
    }
    if rate_max is not None:
        slab["rate_max"] = str(rate_max)
    return slab


def fs(low, high, fee):
    """One maintenance-fee band, stored as printed (inclusive ceiling)."""
    return {
        "balance_min": str(low),
        "balance_max": None if high is None else str(high),
        "fee": str(fee),
    }


def bb_maint(free_above=None):
    """The BB savings maintenance slab as most banks publish it."""
    slabs = [
        fs(0, 10000, 0),
        fs(10001, 25000, 100),
        fs(25001, 200000, 200),
        fs(200001, 1000000, 250),
        fs(1000001, None, 300),
    ]
    if free_above is not None:
        slabs[-1] = fs(1000001, None, 0)
    return slabs


MAINT_CURRENT = [fs(0, None, 300)]
MAINT_FREE = [fs(0, None, 0)]

BRAC_DORMANCY = (
    "Dormant if no customer-induced transaction for 2 years (savings) "
    "or 1 year (current); activation free (BRAC SOC)."
)

# BB deposit chart (Oct 2026 edition) savings column, verified in the
# Phase 2 research pass 2026-11-04 — used only as a cross-check.
BB_SAVINGS_RANGES = {
    "BRAC Bank PLC": ("0.50", "5.00"),
    "City Bank PLC": ("1.17", "2.79"),
    "Eastern Bank PLC": ("1.75", "2.00"),
    "Dutch-Bangla Bank PLC": ("0.50", "3.25"),
    "Pubali Bank PLC": ("2.50", "2.50"),
    "Islami Bank Bangladesh Limited": ("2.50", "3.85"),
}

P = []  # product dicts; keys map to AccountProduct fields (+ bank, variant_of)


def add(bank, **kwargs):
    kwargs["bank"] = bank
    P.append(kwargs)


# ===========================================================================
# BRAC Bank — SOC eff. 2026-10-13; ALCO rate sheet w.e.f. 2025-12-02
# ===========================================================================
B = "BRAC Bank PLC"
BRAC_COMMON = dict(
    source_soc_url=BRAC_SOC,
    source_rate_url=BRAC_RATES,
    soc_effective_date=date(2026, 10, 13),
    rate_effective_date=date(2025, 12, 2),
    source_kind="bank_soc",
    dormancy_terms=BRAC_DORMANCY,
    statement_duplicate_fee="100",
    balance_confirmation_extra_fee="100",
    online_banking_fee_annual="0",
)
TBS_SLABS = [
    s(100000, 2500000, "0.50"),
    s(2500000, 5000000, "0.75"),
    s(5000000, 10000000, "1.00"),
    s(10000000, 50000000, "2.00"),
    s(50000000, None, "2.50"),
]
add(
    B,
    name="Triple Benefits Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=TBS_SLABS,
    rate_conditions_text="BRAC's ALCO rate sheet publishes no rate below "
    "Tk 1 lakh for this product.",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="600",
    debit_card_waiver_text="Waived from the 2nd year if average balance "
    "is Tk 50,000 or above (BRAC SOC).",
    debit_card_waiver_min_balance="50000",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="TARA Triple Benefits Savings Account",
    account_type="savings",
    segment="women",
    variant_of="Triple Benefits Savings Account",
    rate_slabs=[
        s(100000, 2500000, "0.75"),
        s(2500000, 5000000, "1.25"),
        s(5000000, 10000000, "1.50"),
        s(10000000, 50000000, "2.50"),
        s(50000000, None, "3.00"),
    ],
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="500",
    debit_card_first_year_fee="0",
    debit_card_waiver_text="Waived from the 2nd year if average balance "
    "is Tk 50,000 or above (BRAC SOC).",
    debit_card_waiver_min_balance="50000",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Savings Classic Account",
    account_type="savings",
    segment="general",
    rate_slabs=TBS_SLABS,
    rate_conditions_text="BRAC's ALCO sheet applies the Triple Benefits "
    "slab table to Savings Classic.",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="600",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Golden Benefit Savings Account",
    account_type="savings",
    segment="senior",
    rate_slabs=[
        s(100000, 2500000, "1.50"),
        s(2500000, 5000000, "2.00"),
        s(5000000, 10000000, "2.50"),
        s(10000000, 50000000, "3.00"),
        s(50000000, None, "3.50"),
    ],
    maintenance_fee_slabs=bb_maint(free_above=1000000),
    debit_card_fee_annual="600",
    debit_card_waiver_text="Waived from the 2nd year if average balance "
    "is Tk 100,000 or above (BRAC SOC).",
    debit_card_waiver_min_balance="100000",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
AGAMI_MAINT = [
    fs(0, 10000, 0),
    fs(10001, 25000, 50),
    fs(25001, 200000, 100),
    fs(200001, 1000000, 125),
    fs(1000001, None, 150),
]
AGAMI_SLABS = [
    s(0, 100000, "0.50"),
    s(100000, 500000, "1.00"),
    s(500000, 2500000, "1.50"),
    s(2500000, None, "2.00"),
]
add(
    B,
    name="AGAMI Savers Account",
    account_type="savings",
    segment="student",
    rate_slabs=AGAMI_SLABS,
    min_balance_to_earn="0",
    maintenance_fee_slabs=AGAMI_MAINT,
    debit_card_fee_annual="300",
    debit_card_replacement_fee="150",
    sms_fee_annual="125",
    cheque_per_leaf="10",
    closure_fee="200",
    eligibility_notes="For students aged 18–25 (BRAC ALCO sheet).",
    **BRAC_COMMON,
)
add(
    B,
    name="TARA AGAMI Savers Account",
    account_type="savings",
    segment="women",
    variant_of="AGAMI Savers Account",
    rate_slabs=[
        s(0, 100000, "1.00"),
        s(100000, 500000, "1.50"),
        s(500000, 2500000, "2.00"),
        s(2500000, None, "2.50"),
    ],
    min_balance_to_earn="0",
    maintenance_fee_slabs=AGAMI_MAINT,
    debit_card_fee_annual="300",
    debit_card_first_year_fee="0",
    debit_card_replacement_fee="150",
    sms_fee_annual="125",
    cheque_per_leaf="10",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Happy Savers Account",
    account_type="savings",
    segment="general",
    rate_slabs=AGAMI_SLABS,
    rate_conditions_text="BRAC's ALCO sheet publishes one slab table for "
    "AGAMI and Happy Savers.",
    min_balance_to_earn="0",
    maintenance_fee_slabs=[
        fs(0, 10000, 0),
        fs(10001, 25000, 50),
        fs(25001, 200000, 100),
        fs(200001, 1000000, 150),
        fs(1000001, None, 300),
    ],
    debit_card_fee_annual="300",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_book_available=False,
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Future Star Account",
    account_type="savings",
    segment="minor",
    rate_slabs=[s(0, None, "3.50")],
    min_balance_to_earn="0",
    opening_deposit="0",
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="0",
    debit_card_replacement_fee="100",
    sms_fee_annual="0",
    cheque_book_available=False,
    closure_fee="200",
    eligibility_notes="For children and students under 18 (BRAC SOC).",
    **BRAC_COMMON,
)
add(
    B,
    name="Digital Savings Account",
    account_type="savings",
    segment="digital",
    rate_slabs=[],
    rate_conditions_text="BRAC's ALCO savings sheet does not publish a "
    "rate for Digital Savings; no rate is shown rather than a guessed one.",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="300",
    debit_card_waiver_text="Virtual card free; plastic + virtual card "
    "BDT 300/year (BRAC SOC).",
    debit_card_replacement_fee="300",
    sms_fee_annual="0",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Virtual Savings Account",
    account_type="savings",
    segment="digital",
    rate_slabs=[
        s(0, 100000, "1.00"),
        s(100000, 2500000, "2.00"),
        s(2500000, 10000000, "3.00"),
        s(10000000, None, "3.50"),
    ],
    maintenance_fee_slabs=[
        fs(0, 10000, 100),
        fs(10001, 25000, 100),
        fs(25001, 50000, 200),
        fs(50001, None, 0),
    ],
    maintenance_waiver_text="Maintenance free above Tk 50,000 average "
    "balance (BRAC SOC).",
    debit_card_fee_annual="200",
    debit_card_replacement_fee="200",
    sms_fee_annual="250",
    cheque_book_available=False,
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="EZEE Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[],
    rate_conditions_text="BRAC's ALCO savings sheet does not publish a "
    "rate for EZEE Savings; no rate is shown rather than a guessed one.",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="300",
    debit_card_waiver_text="Waived from the 2nd year if average balance "
    "is Tk 50,000 or above (BRAC SOC).",
    debit_card_waiver_min_balance="50000",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="TARA EZEE Savings Account",
    account_type="savings",
    segment="women",
    variant_of="EZEE Savings Account",
    rate_slabs=[],
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="300",
    debit_card_first_year_fee="0",
    debit_card_waiver_text="Waived from the 2nd year if average balance "
    "is Tk 50,000 or above (BRAC SOC).",
    debit_card_waiver_min_balance="50000",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="TARA Homemakers Savings Account",
    account_type="savings",
    segment="women",
    rate_slabs=[s(0, 100000, "1.50"), s(100000, 500000, "2.50")],
    rate_conditions_text="Monthly interest on any balance up to "
    "BDT 500,000 (BRAC product page); the ALCO sheet publishes no rate "
    "above Tk 5 lakh for this product.",
    interest_payout_frequency="monthly",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="500",
    debit_card_first_year_fee="0",
    debit_card_waiver_text="Waived if average balance is Tk 10,000 or "
    "above (BRAC SOC).",
    debit_card_waiver_min_balance="10000",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Farmers Savings Account",
    account_type="savings",
    segment="inclusion",
    rate_slabs=[],
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="600",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="200",
    **BRAC_COMMON,
)
add(
    B,
    name="Probashi Savings Account",
    account_type="savings",
    segment="nrb",
    rate_slabs=[
        s(5000, 100000, "0.50"),
        s(100000, 2500000, "0.75"),
        s(2500000, 5000000, "1.25"),
        s(5000000, 10000000, "1.50"),
        s(10000000, 50000000, "2.50"),
        s(50000000, None, "3.00"),
    ],
    rate_conditions_text="Probashi (NRB) fees sit in BRAC's separate "
    "Remittance SOC, which was not part of this pass; fee lines are "
    "left unpublished rather than borrowed from the retail SOC.",
    source_soc_url="",
    source_rate_url=BRAC_RATES,
    rate_effective_date=date(2025, 12, 2),
    source_kind="bank_rate_sheet",
    dormancy_terms=BRAC_DORMANCY,
)
add(
    B,
    name="Probashi Paribar Savings Account",
    account_type="savings",
    segment="nrb",
    rate_slabs=[s(0, None, "3.00")],
    source_soc_url="",
    source_rate_url=BRAC_RATES,
    rate_effective_date=date(2025, 12, 2),
    source_kind="bank_rate_sheet",
)
add(
    B,
    name="TARA Probashi Paribar Savings Account",
    account_type="savings",
    segment="women",
    variant_of="Probashi Paribar Savings Account",
    rate_slabs=[s(0, None, "3.50")],
    source_soc_url="",
    source_rate_url=BRAC_RATES,
    rate_effective_date=date(2025, 12, 2),
    source_kind="bank_rate_sheet",
)
add(
    B,
    name="Employee Banking Savings Salary Account",
    account_type="savings",
    segment="salary",
    rate_slabs=[
        s(50000, 100000, "1.00"),
        s(100000, 500000, "1.50"),
        s(500000, 2500000, "2.00"),
    ],
    rate_conditions_text="Employee Banking slab rows transcribed from "
    "BRAC's ALCO sheet (50,000–25 lakh published).",
    opening_deposit="0",
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="300",
    debit_card_first_year_fee="0",
    debit_card_replacement_fee="300",
    sms_fee_annual="0",
    cheque_per_leaf="15",
    closure_fee="200",
    statement_duplicate_fee="0",
    eligibility_notes="Requires an employer salary agreement with BRAC "
    "Bank; charges may be discounted per agreement (BRAC SOC).",
    **{k: v for k, v in BRAC_COMMON.items() if k != "statement_duplicate_fee"},
)
add(
    B,
    name="Current Classic Account",
    account_type="current",
    segment="general",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="No interest — BRAC's ALCO sheet marks Current "
    "Classic 'Not Applicable' for interest.",
    maintenance_fee_slabs=MAINT_CURRENT,
    debit_card_fee_annual="600",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_per_leaf="20",
    closure_fee="300",
    **BRAC_COMMON,
)
add(
    B,
    name="Ezee Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="No interest — BRAC's ALCO sheet marks Ezee "
    "Current 'Not Applicable' for interest. The retail SOC's Ezee "
    "Current section publishes no maintenance fee, so it is left "
    "unpublished here.",
    debit_card_fee_annual="600",
    debit_card_replacement_fee="300",
    sms_fee_annual="250",
    cheque_book_available=False,
    closure_fee="300",
    **BRAC_COMMON,
)

# ===========================================================================
# City Bank — SOC eff. 2025-10-14; rates w.e.f. 2026-11-01
# ===========================================================================
B = "City Bank PLC"
CITY_COMMON = dict(
    source_soc_url=CITY_SOC,
    source_rate_url=CITY_RATES,
    soc_effective_date=date(2025, 10, 14),
    rate_effective_date=date(2026, 11, 1),
    source_kind="bank_soc",
    statement_duplicate_fee="100",
    balance_confirmation_extra_fee="100",
    online_banking_fee_annual="0",
    sms_fee_annual="300",
    debit_card_fee_annual="600",
)
CITY_GENERAL_SLABS = [s(0, 100000, "0"), s(100000, None, "0.25")]
add(
    B,
    name="General Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=CITY_GENERAL_SLABS,
    rate_conditions_text="Pays no interest below Tk 1 lakh average "
    "balance (City rate page, w.e.f. 01 Nov 2026).",
    maintenance_fee_slabs=bb_maint(),
    cheque_per_leaf="20",
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="City Alo General Savings Account",
    account_type="savings",
    segment="women",
    variant_of="General Savings Account",
    rate_slabs=CITY_GENERAL_SLABS,
    maintenance_fee_slabs=bb_maint(),
    cheque_per_leaf="20",
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="Basic Savings Account",
    account_type="savings",
    segment="inclusion",
    rate_slabs=[s(0, None, "3.00")],
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual=None,
    cheque_per_leaf="20",
    closure_fee="0",
    **{k: v for k, v in CITY_COMMON.items() if k != "debit_card_fee_annual"},
)
add(
    B,
    name="High Value Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, 100000, "0"), s(100000, None, "0.50")],
    maintenance_fee_slabs=bb_maint(),
    cheque_per_leaf="20",
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="City Alo High Value Savings Account",
    account_type="savings",
    segment="women",
    variant_of="High Value Savings Account",
    rate_slabs=[s(0, 100000, "0"), s(100000, None, "0.50")],
    maintenance_fee_slabs=bb_maint(),
    debit_card_waiver_text="Cheque book renewals free if average balance "
    "is Tk 25,000 or above (City SOC) — a cheque waiver, shown as text.",
    cheque_per_leaf="20",
    cheque_first_book_free=True,
    closure_fee="200",
    **CITY_COMMON,
)
DELIGHT_SLABS = [
    s(0, 500000, "0"),
    s(500000, 1000000, "0.50"),
    s(1000000, 2000000, "0.75"),
    s(2000000, 3000000, "1.00"),
    s(3000000, 10000000, "2.00"),
    s(10000000, None, "2.25"),
]
add(
    B,
    name="Savings Delight Account",
    account_type="savings",
    segment="general",
    rate_slabs=DELIGHT_SLABS,
    maintenance_fee_slabs=bb_maint(),
    cheque_per_leaf="20",
    cheque_first_book_free=True,
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="City Alo Savings Delight Account",
    account_type="savings",
    segment="women",
    variant_of="Savings Delight Account",
    rate_slabs=[
        s(0, 500000, "0"),
        s(500000, 1000000, "0.50"),
        s(1000000, 2000000, "0.75"),
        s(2000000, 3000000, "1.00"),
        s(3000000, 10000000, "1.50"),
        s(10000000, None, "1.75"),
    ],
    maintenance_fee_slabs=bb_maint(),
    debit_card_waiver_text="Cheque book renewals free if average balance "
    "is Tk 100,000 or above (City SOC) — a cheque waiver, shown as text.",
    cheque_per_leaf="20",
    cheque_first_book_free=True,
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="Green Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[
        s(0, 100000, "0"),
        s(100000, 1000000, "0.50"),
        s(1000000, 2000000, "0.75"),
        s(2000000, 3000000, "1.00"),
        s(3000000, 10000000, "1.25"),
        s(10000000, None, "1.75"),
    ],
    maintenance_fee_slabs=bb_maint(),
    cheque_per_leaf="20",
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="Seniors' Savings Account",
    account_type="savings",
    segment="senior",
    rate_slabs=[
        s(0, 25000, "0"),
        s(25000, 100000, "0.50"),
        s(100000, 500000, "0.75"),
        s(500000, 2500000, "1.00"),
        s(2500000, None, "1.50"),
    ],
    maintenance_fee_slabs=bb_maint(),
    cheque_per_leaf="20",
    cheque_first_book_free=True,
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="Student Savings – School Plan",
    account_type="savings",
    segment="student",
    rate_slabs=[s(0, None, "3.00")],
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="0",
    sms_fee_annual="0",
    closure_fee="0",
    **{
        k: v
        for k, v in CITY_COMMON.items()
        if k not in ("debit_card_fee_annual", "sms_fee_annual")
    },
)
# OPEN QUESTION (checked against the live SOC, 2026-11-04): the student
# section of City's Retail SOC (eff. 14 Oct 2025) says the College Plan
# debit card is "First year Free" — unlike the School Plan's unqualified
# "Free for Minor" — but publishes no College-Plan-specific card fee for
# year 2 onwards. The steady-state figure below therefore keeps the
# general Tk 600 card charge from the same SOC's DEBIT CARD ISSUE
# CHARGE table (inherited via CITY_COMMON), with the first year at 0.
# Whether City actually charges College Plan cards from year 2 is not
# stated in the SOC and needs confirmation from the bank; do not treat
# the 600 as plan-published until then.
add(
    B,
    name="Student Savings – College Plan",
    account_type="savings",
    segment="student",
    rate_slabs=[s(0, None, "1.75")],
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_first_year_fee="0",
    sms_fee_annual="0",
    closure_fee="0",
    **{k: v for k, v in CITY_COMMON.items() if k != "sms_fee_annual"},
)
add(
    B,
    name="RMG Workers' Account",
    account_type="savings",
    segment="inclusion",
    rate_slabs=[s(0, None, "3.00")],
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual=None,
    sms_fee_annual=None,
    cheque_book_available=False,
    closure_fee="0",
    **{
        k: v
        for k, v in CITY_COMMON.items()
        if k not in ("debit_card_fee_annual", "sms_fee_annual")
    },
)
FREELANCER_SLABS = [
    s(0, 10000, "0"),
    s(10000, 50000, "0.50"),
    s(50000, 500000, "0.75"),
    s(500000, None, "1.00"),
]
add(
    B,
    name="Freelancer Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=FREELANCER_SLABS,
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_first_year_fee="0",
    cheque_per_leaf="20",
    closure_fee="200",
    **CITY_COMMON,
)
add(
    B,
    name="Mariners' Savings Account",
    account_type="savings",
    segment="nrb",
    rate_slabs=FREELANCER_SLABS,
    rate_conditions_text="City's SOC does not publish a Mariners'-"
    "specific maintenance or closing fee; those lines are unpublished.",
    cheque_per_leaf="20",
    **CITY_COMMON,
)
add(
    B,
    name="NRCTA Savings Account",
    account_type="savings",
    segment="nrb",
    rate_slabs=[s(0, 50000, "0"), s(50000, None, "3.00")],
    rate_conditions_text="City's SOC does not publish an NRCTA-specific "
    "maintenance or closing fee; those lines are unpublished.",
    cheque_per_leaf="20",
    **CITY_COMMON,
)
add(
    B,
    name="Easy Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[s(0, None, "1.00")],
    maintenance_fee_slabs=[fs(0, 50000, 300), fs(50001, None, 0)],
    maintenance_waiver_text="Maintenance waived above Tk 50,000 average "
    "balance (City SOC).",
    cheque_per_leaf="20",
    closure_fee="300",
    **CITY_COMMON,
)
add(
    B,
    name="Easy Plus Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[s(0, None, "1.50")],
    maintenance_fee_slabs=[fs(0, 200000, 300), fs(200001, None, 0)],
    maintenance_waiver_text="Maintenance waived above Tk 200,000 "
    "average balance (City SOC).",
    cheque_per_leaf="20",
    closure_fee="300",
    **CITY_COMMON,
)
add(
    B,
    name="Current Account (BDT)",
    account_type="current",
    segment="general",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="City's rate page lists only Easy and Easy "
    "Plus among current deposits, so the standard current account "
    "earns no interest.",
    maintenance_fee_slabs=MAINT_CURRENT,
    cheque_per_leaf="20",
    closure_fee="300",
    **CITY_COMMON,
)

# ===========================================================================
# Eastern Bank — SOC eff. 2026-10-15; rate sheet eff. 2026-11-01
# ===========================================================================
B = "Eastern Bank PLC"
EBL_COMMON = dict(
    source_soc_url=EBL_SOC,
    source_rate_url=EBL_RATES,
    soc_effective_date=date(2026, 10, 15),
    rate_effective_date=date(2026, 11, 1),
    source_kind="bank_soc",
    maintenance_fee_slabs=bb_maint(),
    sms_fee_annual="400",
    online_banking_fee_annual="0",
    statement_duplicate_fee="100",
    balance_confirmation_extra_fee="100",
    closure_fee="200",
    dormancy_terms="Dormant activation charge: Nil (EBL SOC).",
)
CLASSIC_SLABS = [
    s(0, 50000, "0"),
    s(50000, 500000, "0.50"),
    s(500000, 2500000, "1.00"),
    s(2500000, None, "2.00"),
]
add(
    B,
    name="EBL Classic Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=CLASSIC_SLABS,
    rate_conditions_text="Interest is paid when weekly withdrawals stay "
    "within two and each withdrawal stays within 10% of the previous "
    "or current day's balance (EBL product page).",
    interest_basis="lowest_monthly_balance",
    interest_payout_frequency="half_yearly",
    min_balance_to_earn="50000",
    opening_deposit="500",
    min_balance_required="500",
    **EBL_COMMON,
)
add(
    B,
    name="EBL Insta Savings Account",
    account_type="savings",
    segment="digital",
    rate_slabs=CLASSIC_SLABS,
    opening_deposit="500",
    min_balance_required="500",
    **EBL_COMMON,
)
WOMENS_SLABS = [
    s(0, 25000, "0"),
    s(25000, 100000, "1.00"),
    s(100000, 500000, "1.50"),
    s(500000, None, "2.00"),
]
add(
    B,
    name="EBL Women's Savings Account",
    account_type="savings",
    segment="women",
    rate_slabs=WOMENS_SLABS,
    opening_deposit="1000",
    min_balance_required="1000",
    **EBL_COMMON,
)
add(
    B,
    name="EBL Green Account",
    account_type="savings",
    segment="general",
    rate_slabs=WOMENS_SLABS,
    opening_deposit="1000",
    min_balance_required="1000",
    **EBL_COMMON,
)
add(
    B,
    name="EBL 50 Plus Savings Account",
    account_type="savings",
    segment="senior",
    rate_slabs=[
        s(0, 50000, "0"),
        s(50000, 100000, "1.00"),
        s(100000, 500000, "1.50"),
        s(500000, None, "2.00"),
    ],
    opening_deposit="5000",
    min_balance_required="5000",
    **EBL_COMMON,
)
add(
    B,
    name="EBL Premium Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[
        s(0, 100000, "0"),
        s(100000, 1000000, "0.50"),
        s(1000000, 2500000, "1.00"),
        s(2500000, 5000000, "1.50"),
        s(5000000, None, "2.00"),
    ],
    opening_deposit="5000",
    min_balance_required="5000",
    **EBL_COMMON,
)
add(
    B,
    name="EBL Easy Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, 100000, "0"), s(100000, None, "1.50")],
    opening_deposit="5000",
    min_balance_required="5000",
    **EBL_COMMON,
)
add(
    B,
    name="EBL Campus Account",
    account_type="savings",
    segment="student",
    rate_slabs=[s(0, None, "2.00")],
    interest_basis="daily_balance",
    interest_payout_frequency="quarterly",
    min_balance_to_earn="10000",
    opening_deposit="100",
    min_balance_required="100",
    maintenance_fee_slabs=MAINT_FREE,
    sms_fee_annual="200",
    debit_card_first_year_fee="0",
    cheque_per_leaf=None,
    rate_conditions_text="Cheque book issued at a 50% charge waiver; "
    "EBL prices cheque books 'at actual cost', so no per-leaf figure "
    "is published (EBL Campus page + SOC).",
    closure_fee="100",
    source_rate_url=EBL_CAMPUS_PAGE,
    **{
        k: v
        for k, v in EBL_COMMON.items()
        if k
        not in (
            "maintenance_fee_slabs",
            "sms_fee_annual",
            "closure_fee",
            "source_rate_url",
        )
    },
)
add(
    B,
    name="EBL Junior Savings Account",
    account_type="savings",
    segment="minor",
    rate_slabs=[s(0, None, "2.00")],
    interest_basis="daily_balance",
    min_balance_to_earn="10000",
    opening_deposit="100",
    min_balance_required="100",
    maintenance_fee_slabs=MAINT_FREE,
    sms_fee_annual="0",
    debit_card_fee_annual="0",
    closure_fee="0",
    source_rate_url=EBL_JUNIOR_PAGE,
    **{
        k: v
        for k, v in EBL_COMMON.items()
        if k
        not in (
            "maintenance_fee_slabs",
            "sms_fee_annual",
            "closure_fee",
            "source_rate_url",
        )
    },
)
EBL_CURRENT_COMMON = dict(
    source_soc_url=EBL_SOC,
    soc_effective_date=date(2026, 10, 15),
    source_kind="bank_soc",
    maintenance_fee_slabs=MAINT_CURRENT,
    sms_fee_annual="400",
    online_banking_fee_annual="0",
    statement_duplicate_fee="100",
    balance_confirmation_extra_fee="100",
    closure_fee="300",
)
add(
    B,
    name="EBL Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[],
    rate_conditions_text="EBL's deposit rate sheet publishes no current-"
    "account rate; no rate is shown rather than a guessed one.",
    opening_deposit="1000",
    min_balance_required="1000",
    **EBL_CURRENT_COMMON,
)
add(
    B,
    name="EBL Current Plus Account",
    account_type="current",
    segment="general",
    rate_slabs=[],
    opening_deposit="5000",
    min_balance_required="5000",
    **EBL_CURRENT_COMMON,
)
add(
    B,
    name="EBL Insta Current Account",
    account_type="current",
    segment="digital",
    rate_slabs=[],
    opening_deposit="1000",
    min_balance_required="1000",
    **EBL_CURRENT_COMMON,
)

# ===========================================================================
# Bank Asia — SOC eff. July 2026; Islamic provisional rates from ISR page
# ===========================================================================
B = "Bank Asia PLC"
BANKASIA_COMMON = dict(
    source_soc_url=BANKASIA_SOC,
    soc_effective_date=date(2026, 7, 1),
    source_kind="bank_soc",
    debit_card_fee_annual="500",
    sms_fee_annual="300",
    online_banking_fee_annual="0",
    cheque_per_leaf="6",
    balance_confirmation_extra_fee="100",
    dormancy_terms="Dormant account activation charge: free (Bank Asia SOC).",
)
add(
    B,
    name="Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[],
    rate_conditions_text="Bank Asia does not publish a conventional "
    "savings interest rate in the sources found; no rate is shown "
    "rather than a guessed one. (Cheque is charged 'at actual cost', "
    "minimum Tk 6 per leaf — the minimum is stored.)",
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **BANKASIA_COMMON,
)
add(
    B,
    name="Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[],
    maintenance_fee_slabs=MAINT_CURRENT,
    closure_fee="300",
    **BANKASIA_COMMON,
)
BANKASIA_ISLAMIC = dict(
    is_islamic=True,
    contract_type="mudaraba",
    rate_type="expected_profit",
    source_soc_url=BANKASIA_SOC,
    source_rate_url=BANKASIA_ISR,
    soc_effective_date=date(2026, 7, 1),
    source_kind="bank_soc",
    debit_card_fee_annual="500",
    sms_fee_annual="300",
    online_banking_fee_annual="0",
    cheque_per_leaf="6",
    balance_confirmation_extra_fee="100",
)
add(
    B,
    name="Mudaraba Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, None, "2.25")],
    rate_conditions_text="Provisional (expected) profit rate from Bank "
    "Asia's Islamic Banking ISR page; final profit is adjusted after "
    "the annual calculation, and the bank distributes at least 65% of "
    "investment income by weightage.",
    interest_payout_frequency="half_yearly",
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **BANKASIA_ISLAMIC,
)
add(
    B,
    name="Smart Junior Saver",
    account_type="savings",
    segment="student",
    rate_slabs=[s(0, None, "2.56")],
    rate_conditions_text="Provisional (expected) profit rate from Bank "
    "Asia's Islamic Banking ISR page.",
    interest_payout_frequency="half_yearly",
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **BANKASIA_ISLAMIC,
)
add(
    B,
    name="Al-Wadiah Current Account",
    account_type="current",
    segment="general",
    is_islamic=True,
    contract_type="al_wadiah",
    rate_type="expected_profit",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="Al-Wadiah current accounts pay no profit by "
    "contract; the principal is held as a safe deposit.",
    maintenance_fee_slabs=MAINT_CURRENT,
    closure_fee="300",
    source_soc_url=BANKASIA_SOC,
    soc_effective_date=date(2026, 7, 1),
    source_kind="bank_soc",
    debit_card_fee_annual="500",
    sms_fee_annual="300",
    online_banking_fee_annual="0",
    cheque_per_leaf="6",
    balance_confirmation_extra_fee="100",
)

# ===========================================================================
# ONE Bank — SOC eff. 2026-03-15 (rates page is JS-driven: rates unpublished)
# ===========================================================================
B = "ONE Bank PLC"
ONE_COMMON = dict(
    source_soc_url=ONEBANK_SOC,
    soc_effective_date=date(2026, 3, 15),
    source_kind="bank_soc",
    rate_slabs=[],
    rate_conditions_text="ONE Bank's published rates page did not yield "
    "figures (it is JS-driven); rates are unpublished, not guessed.",
    sms_fee_annual="300",
    online_banking_fee_annual="0",
    cheque_per_leaf="11.25",
    statement_duplicate_fee="100",
    balance_confirmation_extra_fee="100",
    dormancy_terms="Dormant account activation: Nil (ONE Bank SOC).",
)
add(
    B,
    name="Savings Account",
    account_type="savings",
    segment="general",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="600",
    debit_card_replacement_fee="400",
    closure_fee="200",
    **ONE_COMMON,
)
add(
    B,
    name="OBL Youth Banking",
    account_type="savings",
    segment="student",
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="600",
    debit_card_replacement_fee="400",
    closure_fee="200",
    **ONE_COMMON,
)
add(
    B,
    name="OBL Women Savings",
    account_type="savings",
    segment="women",
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="400",
    debit_card_replacement_fee="400",
    closure_fee="200",
    **ONE_COMMON,
)
add(
    B,
    name="Current Account",
    account_type="current",
    segment="general",
    maintenance_fee_slabs=MAINT_CURRENT,
    debit_card_fee_annual="600",
    debit_card_replacement_fee="400",
    closure_fee="300",
    **ONE_COMMON,
)

# ===========================================================================
# Standard Bank (Islamic) — SOC updated 2026-06-30
# ===========================================================================
B = "Standard Bank PLC"
STANDARD_COMMON = dict(
    source_soc_url=STANDARD_SOC,
    soc_effective_date=date(2026, 6, 30),
    source_kind="bank_soc",
    is_islamic=True,
    rate_type="expected_profit",
    debit_card_fee_annual="400",
    debit_card_replacement_fee="200",
    cheque_per_leaf=None,
)
add(
    B,
    name="Mudaraba Savings Account",
    account_type="savings",
    segment="general",
    contract_type="mudaraba",
    rate_slabs=[],
    rate_conditions_text="Standard Bank's SOC does not publish "
    "provisional Mudaraba profit rates; rates are unpublished. Cheque "
    "books are charged 'at actual cost'; no per-leaf figure published.",
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **STANDARD_COMMON,
)
add(
    B,
    name="Mudaraba School Banking",
    account_type="savings",
    segment="student",
    contract_type="mudaraba",
    rate_slabs=[],
    rate_conditions_text="Cheque books are charged 'at actual cost'; no "
    "per-leaf figure is published (Standard Bank SOC).",
    maintenance_fee_slabs=MAINT_FREE,
    closure_fee="200",
    **STANDARD_COMMON,
)
add(
    B,
    name="Al-Wadiah Current Account",
    account_type="current",
    segment="general",
    contract_type="al_wadiah",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="Al-Wadiah current accounts pay no profit by "
    "contract. Cheque books are charged 'at actual cost'; no per-leaf "
    "figure is published (Standard Bank SOC).",
    maintenance_fee_slabs=MAINT_CURRENT,
    closure_fee="300",
    **STANDARD_COMMON,
)

# ===========================================================================
# Premier Bank — SOC 2026; deposit rates w.e.f. 2026-04-01
# ===========================================================================
B = "Premier Bank PLC"
PREMIER_COMMON = dict(
    source_soc_url=PREMIER_SOC,
    source_rate_url=PREMIER_RATES,
    rate_effective_date=date(2026, 4, 1),
    source_kind="bank_soc",
    debit_card_fee_annual="500",
    sms_fee_annual="300",
    cheque_per_leaf="5",
    cheque_first_book_free=True,
)
add(
    B,
    name="Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, 100000, "2.50"), s(100000, None, "3.00")],
    min_balance_required="5000",
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **PREMIER_COMMON,
)
BANDS_50PLUS = [
    s(0, 1000000, "3.00"),
    s(1000000, 5000000, "4.00"),
    s(5000000, 10000000, "5.00"),
    s(10000000, None, "6.00"),
]
add(
    B,
    name="Premier 50+ Account",
    account_type="savings",
    segment="senior",
    rate_slabs=BANDS_50PLUS,
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **PREMIER_COMMON,
)
add(
    B,
    name="Premier Women's Savers Account",
    account_type="savings",
    segment="women",
    rate_slabs=BANDS_50PLUS,
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **PREMIER_COMMON,
)
add(
    B,
    name="Premier Genius Account",
    account_type="savings",
    segment="student",
    rate_slabs=[s(0, None, "2.00")],
    min_balance_required="500",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="0",
    closure_fee="200",
    eligibility_notes="Account closing is free below age 18 (Premier SOC).",
    **{k: v for k, v in PREMIER_COMMON.items() if k != "debit_card_fee_annual"},
)
add(
    B,
    name="Premier Excel Savers",
    account_type="savings",
    segment="general",
    rate_slabs=[
        s(0, 10000, "0"),
        s(10000, 100000, "3.00"),
        s(100000, 200000, "3.50"),
        s(200000, None, "4.00"),
    ],
    interest_basis="daily_balance",
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="0",
    sms_fee_annual="0",
    closure_fee="200",
    **{
        k: v
        for k, v in PREMIER_COMMON.items()
        if k not in ("debit_card_fee_annual", "sms_fee_annual")
    },
)
add(
    B,
    name="Premier Esteem Savers",
    account_type="savings",
    segment="general",
    rate_slabs=[
        s(0, 50000, "0"),
        s(50000, 200000, "3.00"),
        s(200000, 500000, "4.00"),
        s(500000, None, "4.50"),
    ],
    interest_basis="daily_balance",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="0",
    sms_fee_annual="0",
    closure_fee="200",
    **{
        k: v
        for k, v in PREMIER_COMMON.items()
        if k not in ("debit_card_fee_annual", "sms_fee_annual")
    },
)
add(
    B,
    name="Premier Supreme Savings",
    account_type="savings",
    segment="general",
    rate_slabs=[
        s(0, 50000, "0"),
        s(50000, 200000, "4.00"),
        s(200000, 500000, "5.00"),
        s(500000, None, "6.00"),
    ],
    interest_basis="daily_balance",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="300",
    closure_fee="200",
    **{k: v for k, v in PREMIER_COMMON.items() if k != "debit_card_fee_annual"},
)
add(
    B,
    name="Premier Shadhinota Account",
    account_type="savings",
    segment="inclusion",
    rate_slabs=[s(0, None, "4.00")],
    opening_deposit="10",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual=None,
    sms_fee_annual=None,
    closure_fee="200",
    **{
        k: v
        for k, v in PREMIER_COMMON.items()
        if k not in ("debit_card_fee_annual", "sms_fee_annual")
    },
)
add(
    B,
    name="Premier Payroll Account",
    account_type="savings",
    segment="salary",
    rate_slabs=[],
    rate_conditions_text="Premier's deposit rate sheet does not publish "
    "a payroll rate; unpublished, not guessed.",
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="0",
    closure_fee="200",
    eligibility_notes="Requires an employer payroll agreement with " "Premier Bank.",
    **{k: v for k, v in PREMIER_COMMON.items() if k != "debit_card_fee_annual"},
)
add(
    B,
    name="Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[],
    maintenance_fee_slabs=MAINT_CURRENT,
    closure_fee="300",
    **PREMIER_COMMON,
)
add(
    B,
    name="Al-Wadiah Current Account",
    account_type="current",
    segment="general",
    is_islamic=True,
    contract_type="al_wadiah",
    rate_type="expected_profit",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="Al-Wadiah current accounts pay no profit by " "contract.",
    maintenance_fee_slabs=MAINT_CURRENT,
    closure_fee="300",
    **PREMIER_COMMON,
)

# ===========================================================================
# Meghna Bank — SOC eff. 2024-11-01; rate circular w.e.f. 2026-06-01
# ===========================================================================
B = "Meghna Bank PLC"
MEGHNA_COMMON = dict(
    source_soc_url=MEGHNA_SOC,
    soc_effective_date=date(2024, 11, 1),
    source_kind="bank_soc",
    sms_fee_annual="200",
    cheque_per_leaf="10",
    statement_duplicate_fee="100",
    balance_confirmation_extra_fee="200",
    dormancy_terms="Dormant account activation charge: Nil (Meghna SOC).",
)
MEGHNA_RATE_NOTE = (
    "Meghna's deposit rate circular (w.e.f. 01 Jun 2026) is a scanned "
    "document whose slab table is only partially legible; the legible "
    "headline savings rate of 2.50% is stored as a flat slab and "
    "product-level slabs are left unpublished rather than guessed."
)
add(
    B,
    name="Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, None, "2.50")],
    rate_conditions_text=MEGHNA_RATE_NOTE,
    source_rate_url=MEGHNA_RATES,
    rate_effective_date=date(2026, 6, 1),
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **MEGHNA_COMMON,
)
add(
    B,
    name="Platinum Savers Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, None, "2.50")],
    rate_conditions_text=MEGHNA_RATE_NOTE,
    source_rate_url=MEGHNA_RATES,
    rate_effective_date=date(2026, 6, 1),
    maintenance_fee_slabs=bb_maint(),
    closure_fee="200",
    **MEGHNA_COMMON,
)
add(
    B,
    name="Sreyoshi Savings Account",
    account_type="savings",
    segment="women",
    rate_slabs=[],
    maintenance_fee_slabs=[
        fs(0, 10000, 0),
        fs(10001, 25000, 50),
        fs(25001, 200000, 100),
        fs(200001, 1000000, 125),
        fs(1000001, None, 150),
    ],
    closure_fee="200",
    **MEGHNA_COMMON,
)
add(
    B,
    name="Senior Citizen's Account",
    account_type="savings",
    segment="senior",
    rate_slabs=[],
    maintenance_fee_slabs=MAINT_FREE,
    closure_fee="200",
    **MEGHNA_COMMON,
)
add(
    B,
    name="Youngstar Savings Account",
    account_type="savings",
    segment="student",
    rate_slabs=[],
    maintenance_fee_slabs=MAINT_FREE,
    closure_fee="0",
    **MEGHNA_COMMON,
)
add(
    B,
    name="Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[],
    maintenance_fee_slabs=MAINT_CURRENT,
    closure_fee="300",
    **MEGHNA_COMMON,
)

# ===========================================================================
# Islami Bank — product terms (mirror read) + BB announced profit range
# ===========================================================================
B = "Islami Bank Bangladesh Limited"
add(
    B,
    name="Mudaraba Savings Account",
    account_type="savings",
    segment="general",
    is_islamic=True,
    contract_type="mudaraba",
    rate_type="expected_profit",
    rate_slabs=[s(0, None, "2.50", "3.85")],
    rate_conditions_text="Expected profit shown as the range Bangladesh "
    "Bank announces for Islami Bank savings deposits (Oct 2026 chart: "
    "2.50–3.85%). No profit is paid for a month with 4 or more "
    "withdrawals; provisional profit is credited twice a year and the "
    "final rate adjusted after the annual calculation (IBBL terms).",
    interest_basis="lowest_monthly_balance",
    interest_payout_frequency="half_yearly",
    min_balance_required="500",
    withdrawal_limit_for_interest=4,
    cheque_book_available=True,
    source_soc_url=IBBL_MSA_TERMS,
    source_rate_url=BB_CHART,
    source_kind="bank_product_page",
)
add(
    B,
    name="Students Mudaraba Savings Account",
    account_type="savings",
    segment="student",
    is_islamic=True,
    contract_type="mudaraba",
    rate_type="expected_profit",
    rate_slabs=[],
    rate_conditions_text="Profit follows the Mudaraba pool; IBBL "
    "publishes no student-specific rate, so none is shown.",
    min_balance_required="100",
    maintenance_fee_slabs=MAINT_FREE,
    debit_card_fee_annual="0",
    source_soc_url=IBBL_MSA_TERMS,
    source_kind="bank_product_page",
)
add(
    B,
    name="Mudaraba Farmers Savings Account",
    account_type="savings",
    segment="inclusion",
    is_islamic=True,
    contract_type="mudaraba",
    rate_type="expected_profit",
    rate_slabs=[],
    interest_basis="lowest_monthly_balance",
    min_balance_required="10",
    min_balance_to_earn="100",
    withdrawal_limit_for_interest=4,
    maintenance_fee_slabs=MAINT_FREE,
    source_soc_url=IBBL_MSA_TERMS,
    source_kind="bank_product_page",
)
add(
    B,
    name="Al-Wadiah Current Account",
    account_type="current",
    segment="general",
    is_islamic=True,
    contract_type="al_wadiah",
    rate_type="expected_profit",
    rate_slabs=[s(0, None, "0")],
    rate_conditions_text="Al-Wadiah current accounts pay no profit by " "contract.",
    source_soc_url=IBBL_MSA_TERMS,
    source_kind="bank_product_page",
)

# ===========================================================================
# Dutch-Bangla Bank — flagged entry: no public SOC (statement evidence)
# ===========================================================================
B = "Dutch-Bangla Bank PLC"
DBBL_NOTE = (
    "DBBL does not publish a current schedule of charges or savings "
    "slab rates on its website. Fees shown are from a published "
    "customer statement (Dec 2025), converted from VAT-inclusive to "
    "ex-VAT (Nexus debit card renewal Tk 460 incl. VAT; SMS Tk 230 "
    "incl. VAT), and the maintenance slab is the BB schedule the "
    "statement confirms. The savings figure is the BB announced range."
)
add(
    B,
    name="DBBL Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, None, "0.50", "3.25")],
    rate_conditions_text=DBBL_NOTE,
    maintenance_fee_slabs=bb_maint(),
    debit_card_fee_annual="400",
    sms_fee_annual="200",
    source_rate_url=BB_CHART,
    source_kind="bank_statement_evidence",
)
add(
    B,
    name="DBBL Current Account",
    account_type="current",
    segment="general",
    rate_slabs=[],
    rate_conditions_text=DBBL_NOTE,
    maintenance_fee_slabs=MAINT_CURRENT,
    debit_card_fee_annual="400",
    sms_fee_annual="200",
    source_kind="bank_statement_evidence",
)

# ===========================================================================
# Pubali Bank — BB announced rate; fees unpublished (no SOC found)
# ===========================================================================
B = "Pubali Bank PLC"
add(
    B,
    name="Pubali Savings Account",
    account_type="savings",
    segment="general",
    rate_slabs=[s(0, None, "2.50")],
    rate_conditions_text="Pubali's legacy page states 4.00% on the "
    "monthly minimum balance; the current BB announced figure "
    "(Oct 2026 chart) is 2.50% flat, which is used here. Pubali "
    "publishes no SOC in the sources found, so fee lines are "
    "unpublished.",
    interest_basis="monthly_minimum",
    source_rate_url=BB_CHART,
    source_kind="bb_chart",
)
add(
    B,
    name="Pubali Mudaraba Savings Account",
    account_type="savings",
    segment="general",
    is_islamic=True,
    contract_type="mudaraba",
    rate_type="expected_profit",
    rate_slabs=[],
    rate_conditions_text="Pubali's Mudaraba page publishes no "
    "provisional profit rate or fee figures in the sources found.",
    source_rate_url=PUBALI_MUDARABA_PAGE,
    source_kind="bank_product_page",
)


class Command(BaseCommand):
    help = "Seed BB account fee schedules and the v1 account catalogue."

    def handle(self, *args, **options):  # noqa: C901 — seed + report in one pass
        out = self.stdout.write
        for spec in FEE_SCHEDULES:
            obj, created = AccountFeeSchedule.objects.update_or_create(
                key=spec["key"],
                effective_from=spec["effective_from"],
                defaults={
                    "params": spec["params"],
                    "description": spec["description"],
                    "source_note": spec["source_note"],
                },
            )
            out(f"fee schedule {obj.key} ({'new' if created else 'updated'})")

        banks = {b.name: b for b in Bank.objects.all()}
        created = updated = 0
        products = []
        for spec in P:
            spec = dict(spec)
            bank_name = spec.pop("bank")
            variant_name = spec.pop("variant_of", None)
            bank = banks.get(bank_name)
            if bank is None:
                out(self.style.WARNING(f"SKIP {bank_name}: bank not in DB"))
                continue
            slug = slugify(f"{bank_name} {spec['name']}")
            fee_complete = (
                spec.get("maintenance_fee_slabs") is not None
                and (
                    spec.get("debit_card_fee_annual") is not None
                    or not spec.get("debit_card_included", True)
                )
                and spec.get("sms_fee_annual") is not None
                and spec.get("online_banking_fee_annual") is not None
            )
            defaults = {
                **spec,
                "bank": bank,
                "slug": slug,
                "fee_data_complete": fee_complete,
                "verification_status": VerificationStatus.VERIFIED,
                "verified_at": VERIFIED_AT,
                "last_verified_at": VERIFIED_AT,
                "is_active": True,
            }
            obj, was_created = AccountProduct.objects.update_or_create(
                slug=slug, defaults=defaults
            )
            obj._variant_name = variant_name
            products.append(obj)
            created += was_created
            updated += not was_created
        by_name = {(p.bank_id, p.name): p for p in products}
        for product in products:
            variant_name = getattr(product, "_variant_name", None)
            if variant_name:
                base = by_name.get((product.bank_id, variant_name))
                if base is not None and base.pk != product.pk:
                    product.variant_of = base
                    product.save(update_fields=["variant_of"])
        out(f"products: {len(products)} ({created} created, {updated} updated)")

        # --- completeness + BB cross-check report -------------------------
        total = len(products) or 1
        fields = {
            "rate_slabs (non-empty)": lambda p: bool(p.rate_slabs),
            "maintenance slabs": lambda p: p.maintenance_fee_slabs is not None,
            "debit card fee": lambda p: p.debit_card_fee_annual is not None,
            "sms fee": lambda p: p.sms_fee_annual is not None,
            "online fee": lambda p: p.online_banking_fee_annual is not None,
            "cheque per leaf": lambda p: p.cheque_per_leaf is not None,
            "closure fee": lambda p: p.closure_fee is not None,
            "interest basis known": lambda p: p.interest_basis != "unknown",
            "fee_data_complete": lambda p: p.fee_data_complete,
        }
        out("\nfield completeness:")
        for label, fn in fields.items():
            n = sum(1 for p in products if fn(p))
            out(f"  {label}: {n}/{total} ({100 * n / total:.0f}%)")

        out("\nBB cross-check (savings, published slabs vs BB chart range):")
        flags = 0
        for product in products:
            if product.account_type != "savings" or not product.rate_slabs:
                continue
            bb = BB_SAVINGS_RANGES.get(product.bank.name)
            if not bb:
                continue
            bb_lo, bb_hi = Decimal(bb[0]), Decimal(bb[1])
            rates = [Decimal(str(x["rate"])) for x in product.rate_slabs]
            rates += [
                Decimal(str(x["rate_max"]))
                for x in product.rate_slabs
                if x.get("rate_max") is not None
            ]
            pub_max, pub_min = max(rates), min(rates)
            if pub_max > bb_hi:
                out(
                    f"  FLAG {product.bank.name} / {product.name}: published "
                    f"max {pub_max}% > BB announced max {bb_hi}%"
                )
                flags += 1
            if pub_min > 0 and pub_min < bb_lo:
                out(
                    f"  FLAG {product.bank.name} / {product.name}: published "
                    f"min positive rate {pub_min}% < BB announced min {bb_lo}%"
                )
                flags += 1
        out(
            f"  ({flags} flags; premium-tier rates above the BB headline "
            "range and 0% entry slabs are expected — see report)"
        )

        out("\nmaintenance warnings (stored fee above the BB cap):")
        warned = 0
        for product in products:
            for warning in product.maintenance_warnings():
                out(f"  {product.bank.name} / {product.name}: {warning}")
                warned += 1
        out(f"  ({warned} warnings)")
        out(self.style.SUCCESS("seed complete"))
