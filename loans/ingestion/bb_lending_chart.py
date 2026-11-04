"""Deterministic ingestion of the Bangladesh Bank lending-rate chart.

Source: https://www.bb.org.bd/en/index.php/financialactivity/interestlending
("Interest Rate on Advance by Types and by Banks" — min/max bands per
category per bank, in TWO sub-rows per bank: SC.1 and SC.2).

Chart layout (verified live, October 2026 edition): one table whose data
rows have 14 cells — [0] bank code, [1] sub-category, [2] Agriculture,
[3] Term loan (large/medium), [4] Term loan (small), [5] Working capital
(large/medium), [6] Working capital (small), [7] Export, [8] Trade
financing, [9] HOUSING LOAN, [10] CONSUMER CREDIT, [11] Credit card,
[12] Credit to NBFIs, [13] Others. SC.2 rows have a blank code cell and
belong to the bank row above them.

Only Housing and Consumer credit map to loan-comparison categories; a
bank's announced band for a category is the union of its SC.1/SC.2 bands
(min of mins, max of maxes). The full raw rows are preserved in the
snapshot because BB serves only the current month.

The chart is regulator-published and parsed deterministically, so its
bands auto-verify (Phase 2 decision #3). Re-running an unchanged edition
writes nothing; if BB revises an edition in-month (same edition label,
changed HTML), the snapshot and bands are refreshed in place.
"""

import datetime
import hashlib
import re
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

from django.db import transaction

from banks.models import Bank

from ..constants import ChartCategory
from ..models import LendingChartSnapshot, LoanChartBand
from .bank_codes import BB_BANK_CODES

CHART_URL = "https://www.bb.org.bd/en/index.php/financialactivity/interestlending"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Column indexes of the mappable categories within a 14-cell data row.
CATEGORY_COLUMNS = {
    ChartCategory.HOUSING: 9,
    ChartCategory.CONSUMER_CREDIT: 10,
}

_MONTHS = {
    name: idx
    for idx, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}


def fetch_chart_html(session=None):
    """Fetch the chart page; BB rejects bare clients, so send browser headers."""
    session = session or requests.Session()
    last_error = None
    for _attempt in range(3):
        try:
            response = session.get(CHART_URL, headers=_BROWSER_HEADERS, timeout=60)
            response.raise_for_status()
            html = response.text
            if "Housing loan" not in html:
                raise ValueError("Response does not look like the BB lending chart")
            return html
        except requests.RequestException as exc:  # flaky egress proxy: retry
            last_error = exc
    raise last_error


def _to_decimal(text):
    if text is None:
        return None
    text = text.strip()
    if not text or text in {"-", "—"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_band(cell):
    """'9.22-11.22' -> (Decimal, Decimal); single value -> (v, v); '' -> None."""
    text = (cell or "").strip()
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"[-–]", text) if p.strip()]
    values = [v for v in (_to_decimal(p) for p in parts) if v is not None]
    if not values:
        return None
    return (min(values), max(values))


def parse_lending_chart(html):
    """Parse the chart HTML into (edition_label, edition_month, banks, anomalies).

    ``banks`` is a list of dicts: {code, categories: {category: (min, max)}}.
    """
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(" ", strip=True)
    match = re.search(r"(\w+),\s*(\d{4})", text)
    edition_label = ""
    edition_month = None
    if match and match.group(1).lower() in _MONTHS:
        edition_label = f"{match.group(1)}, {match.group(2)}"
        edition_month = datetime.date(
            int(match.group(2)), _MONTHS[match.group(1).lower()], 1
        )

    table = None
    for candidate in soup.find_all("table"):
        if "Housing loan" in candidate.get_text():
            table = candidate
            break
    if table is None:
        raise ValueError("Lending chart table not found in page")

    banks, skipped_sc_rows = _extract_bank_rows(table)
    parsed = [
        {"code": entry["code"], "categories": _merge_categories(entry["rows"])}
        for entry in banks
    ]
    anomalies = _detect_anomalies(parsed)
    if skipped_sc_rows:
        anomalies.append(
            f"{skipped_sc_rows} SC-marked chart row(s) skipped: expected 14 cells"
        )
    if not parsed:
        raise ValueError("No bank rows parsed from the lending chart")
    return edition_label, edition_month, parsed, anomalies


def _extract_bank_rows(table):
    """Group the table's data rows by bank (SC.2 rows join the bank above).

    Returns ``(banks, skipped_sc_rows)``: rows marked SC.1/SC.2 whose
    cell count is not the expected 14 are skipped AND counted, so a BB
    layout change (e.g. rowspan'd bank-code cells collapsing a row)
    surfaces as a snapshot anomaly instead of silently dropping banks.
    """
    banks = []
    current = None
    skipped = 0
    for row in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        is_sc_row = len(cells) >= 2 and cells[1].strip().upper().startswith("SC")
        if len(cells) != 14:
            if is_sc_row:
                skipped += 1
            continue
        # Data rows are marked SC.1 / SC.2 in the sub-category cell; this
        # also skips the 14-cell header rows.
        if not is_sc_row:
            continue
        code = cells[0].strip()
        if code:
            current = {"code": code, "rows": []}
            banks.append(current)
        if current is None:
            continue
        current["rows"].append(cells)
    return banks, skipped


def _merge_categories(rows):
    """Union of the SC.1/SC.2 bands per category: (min of mins, max of maxes).

    Union semantics: the chart splits each bank's lending into two
    sub-rows (SC.1 and SC.2) that our product taxonomy does not
    distinguish, so the bank's announced band for a category is the
    union of the two. This can produce wide bands when the sub-rows
    price very differently (e.g. City Bank's consumer-credit rows union
    to 6.00-19.00) — that width is the bank's own announced range across
    its sub-schemes, not a parse artefact, and the payload labels the
    category so consumers know it is the blended consumer-credit band.
    """
    categories = {}
    for category, column in CATEGORY_COLUMNS.items():
        lows, highs = [], []
        for cells in rows:
            band = _parse_band(cells[column])
            if band:
                lows.append(band[0])
                highs.append(band[1])
        if lows:
            categories[category] = (min(lows), max(highs))
    return categories


def _detect_anomalies(parsed):
    """Identical bands across many banks look like a copy/paste in the
    source; very high bands are suspect (mirrors the deposits scan)."""
    from collections import Counter

    anomalies = []
    for category in CATEGORY_COLUMNS:
        ladder_counts = Counter(
            str(b["categories"][category]) for b in parsed if category in b["categories"]
        )
        for ladder, count in ladder_counts.items():
            if count >= 4:
                anomalies.append(
                    f"{count} banks share the identical {category} band {ladder}"
                )
        for b in parsed:
            band = b["categories"].get(category)
            if band and band[1] > Decimal("20"):
                anomalies.append(f"{b['code']} {category} band tops out at {band[1]}%")
    return anomalies


def _resolve_bank(code):
    """-> (Bank|None, display_name). Unknown codes fall back to the raw code."""
    entry = BB_BANK_CODES.get(code)
    if entry is None:
        return None, code
    bank_name, display_name, _is_islamic = entry
    bank = None
    if bank_name:
        bank = Bank.objects.filter(name=bank_name).first()
    return bank, display_name


def _html_digest(html):
    return hashlib.sha256((html or "").encode("utf-8")).hexdigest()


@transaction.atomic
def ingest_lending_chart(html):
    """Snapshot the edition and upsert chart bands.

    Idempotent per edition: re-running an UNCHANGED edition (same HTML
    hash as the stored snapshot) writes nothing. If BB revises an
    edition in-month — same edition label, changed HTML — the snapshot
    and bands are refreshed instead of staying stale until the next
    edition arrives.
    """
    edition_label, edition_month, parsed, anomalies = parse_lending_chart(html)
    raw_rows = [
        {
            "code": b["code"],
            "categories": {k: [str(v[0]), str(v[1])] for k, v in b["categories"].items()},
        }
        for b in parsed
    ]

    snapshot = LendingChartSnapshot.objects.filter(edition_label=edition_label).first()
    created = snapshot is None
    refreshed = False
    if created:
        snapshot = LendingChartSnapshot.objects.create(
            edition_label=edition_label,
            edition_month=edition_month,
            source_url=CHART_URL,
            raw_html=html,
            raw_rows=raw_rows,
            anomalies=anomalies,
        )
    elif _html_digest(snapshot.raw_html) != _html_digest(html):
        snapshot.edition_month = edition_month
        snapshot.source_url = CHART_URL
        snapshot.raw_html = html
        snapshot.raw_rows = raw_rows
        snapshot.anomalies = anomalies
        snapshot.save(
            update_fields=[
                "edition_month",
                "source_url",
                "raw_html",
                "raw_rows",
                "anomalies",
            ]
        )
        refreshed = True

    stats = {
        "edition": edition_label,
        "snapshot_created": created,
        "snapshot_refreshed": refreshed,
        "banks_seen": len(parsed),
        "bands_written": 0,
        "bands_created": 0,
        "bands_updated": 0,
        "bands_removed": 0,
        "anomalies": anomalies,
    }
    if not created and not refreshed:
        return stats

    seen_keys = set()
    for entry in parsed:
        bank, display_name = _resolve_bank(entry["code"])
        for category, (low, high) in entry["categories"].items():
            lookup = (
                {"bank": bank, "category": category}
                if bank is not None
                else {
                    "bank": None,
                    "institution_name": display_name,
                    "category": category,
                }
            )
            band, was_created = LoanChartBand.objects.update_or_create(
                defaults={
                    "institution_name": "" if bank is not None else display_name,
                    "rate_min": low,
                    "rate_max": high,
                    "edition_label": edition_label,
                    "edition_month": edition_month,
                    "source_url": CHART_URL,
                },
                **lookup,
            )
            seen_keys.add((band.bank_id, band.institution_name, band.category))
            stats["bands_written"] += 1
            stats["bands_created" if was_created else "bands_updated"] += 1

    if refreshed:
        # Bands whose bank/category vanished from the revised edition
        # are stale — drop them so the store mirrors the latest parse.
        stale_pks = [
            band.pk
            for band in LoanChartBand.objects.all()
            if (band.bank_id, band.institution_name, band.category) not in seen_keys
        ]
        if stale_pks:
            LoanChartBand.objects.filter(pk__in=stale_pks).delete()
            stats["bands_removed"] = len(stale_pks)
    return stats
