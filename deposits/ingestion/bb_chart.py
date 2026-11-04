"""Deterministic parser + ingestion for the Bangladesh Bank deposit chart.

The BB announced-rate charts (conventional + Islamic window) are plain
HTML tables at stable URLs. This module parses them without any LLM:
bank code -> catalogue bank (see bank_codes), each fixed-deposit cell ->
a :class:`DepositRate` range on one generic FDR product per bank.

Ingestion is idempotent: re-running on an unchanged edition creates no
products, no rates and no history rows. Every rate change writes a
DepositFieldHistory row; every fetched edition is stored as a
DepositChartSnapshot (BB serves only the current month, so history must
be snapshotted by us).

Fetch note: bb.org.bd sits behind a bot check that rejects bare HTTP
clients; a requests session with ordinary browser headers passes (the
site sets its cookies on the first response). If the response contains
no chart table we raise instead of ingesting a challenge page.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from deposits.constants import (
    BB_FD_TENURE_BANDS,
    ChartSource,
    Compounding,
    DepositKind,
    InstitutionType,
    RateType,
    SourceKind,
)
from deposits.ingestion.bank_codes import BB_BANK_CODES
from deposits.models import (
    DepositChartSnapshot,
    DepositFieldHistory,
    DepositProduct,
    DepositRate,
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTHS = {
    name: i
    for i, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}

SECTION_HEADERS = {"SCBs", "DFIs", "PCBs", "FBs"}


class ChartFetchError(RuntimeError):
    pass


def fetch_chart_html(url, timeout=60):
    """Fetch a BB chart page, returning HTML that contains the chart table."""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    html = response.text
    if "<table" not in html.lower() or "Name of the Banks" not in html:
        raise ChartFetchError(
            f"No chart table in response from {url} " "(bot challenge or layout change?)"
        )
    return html


def parse_rate_cell(text):
    """Parse one chart cell -> (Decimal min, Decimal max) or None if blank."""
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    parts = re.split(r"\s*[-–]\s*", text)
    try:
        values = [Decimal(p) for p in parts if p != ""]
    except InvalidOperation:
        return None
    if not values:
        return None
    return (min(values), max(values))


class ParsedChart:
    def __init__(self, edition_label, edition_month, rows):
        self.edition_label = edition_label
        self.edition_month = edition_month
        self.rows = rows  # [{code, category, savings, snd[5], fd[5]}]


def parse_chart(html):  # noqa: C901
    """Parse one BB chart page (either variant) into a ParsedChart."""
    soup = BeautifulSoup(html, "html.parser")
    table = None
    for candidate in soup.find_all("table"):
        if "Name of the Banks" in candidate.get_text():
            table = candidate
            break
    if table is None:
        raise ValueError("No deposit chart table found in HTML")

    edition_label, edition_month = None, None
    rows = []
    category = ""
    for tr in table.find_all("tr"):
        cells = [
            c.get_text(" ", strip=True)
            for c in tr.find_all(["td", "th"], recursive=False)
        ]
        if not cells:
            continue
        if len(cells) == 1:
            text = cells[0]
            m = re.match(r"([A-Za-z]+),\s*(\d{4})", text)
            if m and m.group(1) in MONTHS:
                edition_label = text
                edition_month = date(int(m.group(2)), MONTHS[m.group(1)], 1)
            elif text in SECTION_HEADERS:
                category = text
            continue
        if len(cells) != 12 or cells[0] == "Name of the Banks":
            continue
        rows.append(
            {
                "code": cells[0],
                "category": category,
                "savings": parse_rate_cell(cells[1]),
                "snd": [parse_rate_cell(c) for c in cells[2:7]],
                "fd": [parse_rate_cell(c) for c in cells[7:12]],
            }
        )
    if edition_label is None:
        raise ValueError("Chart edition month not found")
    return ParsedChart(edition_label, edition_month, rows)


def detect_anomalies(rows):
    """Flag chart data-quality smells for human review (never auto-fix)."""
    anomalies = []
    ladders = {}
    for row in rows:
        key = tuple(row["fd"])
        if any(v is not None for v in row["fd"]):
            ladders.setdefault(key, []).append(row["code"])
    for codes in ladders.values():
        if len(codes) >= 3:
            anomalies.append(
                {
                    "type": "identical_fd_ladder",
                    "banks": codes,
                    "note": "Three or more banks report an identical FD ladder; "
                    "implausible — flagged for human review.",
                }
            )
    for row in rows:
        values = [v for v in row["fd"] if v is not None]
        if values and all(v[0] >= Decimal("11.5") for v in values):
            anomalies.append(
                {
                    "type": "suspiciously_high_flat_rates",
                    "banks": [row["code"]],
                    "note": "All published FD bands are >= 11.5%; verify "
                    "against the bank before trusting.",
                }
            )
    return anomalies


def _rate_payload(rate_min, rate_max):
    return {"rate_min": str(rate_min), "rate_max": str(rate_max)}


def _cell_json(value):
    """Serialise a parsed (min, max) cell (or None) for the snapshot JSON."""
    if value is None:
        return None
    return [str(value[0]), str(value[1])]


@transaction.atomic
def ingest_chart(html, source, source_url):  # noqa: C901
    """Ingest one chart edition. Returns a report dict. Idempotent."""
    parsed = parse_chart(html)
    anomalies = detect_anomalies(parsed.rows)
    snapshot, snapshot_created = DepositChartSnapshot.objects.get_or_create(
        source=source,
        edition_label=parsed.edition_label,
        defaults={
            "edition_month": parsed.edition_month,
            "source_url": source_url,
            "raw_html": html,
            "raw_rows": [
                {
                    "code": r["code"],
                    "category": r["category"],
                    "savings": _cell_json(r["savings"]),
                    "snd": [_cell_json(v) for v in r["snd"]],
                    "fd": [_cell_json(v) for v in r["fd"]],
                }
                for r in parsed.rows
            ],
            "anomalies": anomalies,
        },
    )
    if not snapshot_created and snapshot.raw_html != html:
        snapshot.raw_html = html
        snapshot.anomalies = anomalies
        snapshot.save(update_fields=["raw_html", "anomalies"])

    is_window_chart = source == ChartSource.ISLAMIC_WINDOW
    report = {
        "edition": parsed.edition_label,
        "source": source,
        "snapshot_created": snapshot_created,
        "banks_seen": len(parsed.rows),
        "products_created": 0,
        "products_updated": 0,
        "rates_created": 0,
        "rates_updated": 0,
        "rates_deleted": 0,
        "history_rows": 0,
        "unmatched_codes": [],
        "anomalies": anomalies,
    }

    banks_by_name = {b.name: b for b in Bank.objects.all()}
    for row in parsed.rows:
        code = row["code"]
        mapping = BB_BANK_CODES.get(code)
        if mapping is None:
            report["unmatched_codes"].append(code)
            continue
        bank_name, display_name, code_is_islamic = mapping
        bank = banks_by_name.get(bank_name) if bank_name else None
        is_islamic = True if is_window_chart else code_is_islamic

        if is_window_chart:
            name = "Mudaraba Term Deposit (Islamic Window)"
            institution_type = InstitutionType.ISLAMIC_WINDOW
        elif is_islamic:
            name = "Mudaraba Term Deposit (BB announced rates)"
            institution_type = InstitutionType.ISLAMIC_BANK
        else:
            name = "Fixed Deposit (BB announced rates)"
            institution_type = InstitutionType.BANK
        display = bank.name if bank else display_name
        slug = slugify(f"{display} {name}")[:280]

        product, created = DepositProduct.objects.get_or_create(
            slug=slug,
            defaults={
                "bank": bank,
                "institution_name": "" if bank else display_name,
                "institution_type": institution_type,
                "kind": DepositKind.FDR,
                "name": name,
                "rate_type": (
                    RateType.EXPECTED_PROFIT if is_islamic else RateType.INTEREST
                ),
                "is_islamic": is_islamic,
                "is_generic": True,
                "compounding": Compounding.ANNUAL,
                "source_url": source_url,
                "source_kind": SourceKind.BB_CHART,
                "rate_effective_date": parsed.edition_month,
                "verification_status": VerificationStatus.VERIFIED,
                "verified_at": timezone.now(),
                "eligibility_notes": (
                    "Headline announced rates from the Bangladesh Bank "
                    f"deposit chart ({parsed.edition_label}). Bands are the "
                    "bank's reported minimum–maximum across its own "
                    "sub-products; the exact rate for a given amount/tenure "
                    "is set by the bank."
                ),
            },
        )
        if created:
            report["products_created"] += 1

        changed = False
        seen_bands = set()
        for (t_min, t_max), value in zip(BB_FD_TENURE_BANDS, row["fd"]):
            seen_bands.add((t_min, t_max))
            field_name = f"rate_{t_min}_{t_max or 'open'}"
            existing = DepositRate.objects.filter(
                product=product,
                tenure_months_min=t_min,
                tenure_months_max=t_max,
                amount_min=0,
                amount_max__isnull=True,
            ).first()
            if value is None:
                if existing is not None:
                    DepositFieldHistory.objects.create(
                        product=product,
                        field_name=field_name,
                        old_value=_rate_payload(existing.rate_min, existing.rate_max),
                        new_value=None,
                    )
                    existing.delete()
                    report["rates_deleted"] += 1
                    report["history_rows"] += 1
                    changed = True
                continue
            rate_min, rate_max = value
            if existing is None:
                DepositRate.objects.create(
                    product=product,
                    tenure_months_min=t_min,
                    tenure_months_max=t_max,
                    rate_min=rate_min,
                    rate_max=rate_max,
                )
                report["rates_created"] += 1
                changed = True
            elif existing.rate_min != rate_min or existing.rate_max != rate_max:
                DepositFieldHistory.objects.create(
                    product=product,
                    field_name=field_name,
                    old_value=_rate_payload(existing.rate_min, existing.rate_max),
                    new_value=_rate_payload(rate_min, rate_max),
                )
                if abs(rate_min - existing.rate_min) > Decimal("3"):
                    anomalies.append(
                        {
                            "type": "large_rate_jump",
                            "banks": [code],
                            "note": f"{field_name} moved more than 300bp "
                            "between editions; verify before trusting.",
                        }
                    )
                existing.rate_min = rate_min
                existing.rate_max = rate_max
                existing.save(update_fields=["rate_min", "rate_max"])
                report["rates_updated"] += 1
                report["history_rows"] += 1
                changed = True
        if changed and not created:
            report["products_updated"] += 1
            product.rate_effective_date = parsed.edition_month
            product.verified_at = timezone.now()
            product.save(update_fields=["rate_effective_date", "verified_at"])
    return report
