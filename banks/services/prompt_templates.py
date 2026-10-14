"""Bank-specific prompt templates for credit card data extraction.

Phase 2.2 of ``docs/improvements.md``. A single generic prompt cannot handle the
very different document layouts used by Bangladeshi banks (state-owned banks
publish long "schedule of charges" PDFs, private banks publish web tables, and
foreign banks publish per-card PDFs). This module maps a bank to a template that
tells the LLM where to look in that bank's document.

The templates intentionally share one set of *base instructions* so that every
bank still produces the same output contract:

* respond with a JSON array of credit-card objects;
* ``annual_fee`` / ``interest_rate_apr`` are numbers or ``null``;
* a genuine zero fee ("Free", "No annual fee") is ``0`` and **must not** be
  confused with missing data, which is ``null``;
* anything not stated in the document stays ``null`` instead of being guessed.
"""

from banks.services.prompt_templates_base import BASE_EXTRACTION_INSTRUCTIONS

# Placeholder used in every template; ``str.format`` is intentionally avoided for
# the document body because bank documents contain curly braces.
CONTENT_PLACEHOLDER = "{content}"

SONALI_BANK_TEMPLATE = """
This is a Sonali Bank PLC "schedule of charges" document (state-owned bank).

Look for:
- The "Credit Card" section, usually split into sub-tables per card tier
  (Visa Classic, Visa Gold, Visa Platinum).
- Annual Fee rows, normally expressed in "TK." or "BDT" with comma separators
  (e.g. "TK. 5,000"). "Free"/"Nil" means a genuine 0 fee.
- Interest Rate rows, normally expressed as "% p.a." (e.g. "20% p.a.").
- Supplementary charge rows (cash advance, late payment, card replacement) that
  should be captured with their original column header as the key.

Return one object per card tier found in the document.
"""

JANATA_BANK_TEMPLATE = """
This is a Janata Bank PLC "schedule of charges" document (state-owned bank).

Look for:
- The credit card fee schedule, which lists card types down the left column and
  charge descriptions across the top row.
- Annual Fee values, usually written as "Tk. 1,500" or "Nil" (Nil = 0).
- Finance/Interest charges expressed as "% p.a." or "per annum".
- Any profit-sharing (Islami banking) wording; keep it in the original field
  name rather than forcing it into annual_fee.

Return one object per card tier found in the document.
"""

AGRANI_BANK_TEMPLATE = """
This is an Agrani Bank PLC "schedule of charges" document.

Look for:
- The credit card section with per-tier fee tables (Classic / Gold / Platinum).
- Annual fee amounts in Taka ("Tk.", "BDT"); "Exempted"/"Free" means a genuine 0.
- Interest rates on revolving credit, usually "% p.a." and may be split into
  "Purchase" and "Cash Advance" rates.
- Card-level benefits (lounge access, reward points) that appear as extra rows.

Return one object per card tier found in the document.
"""

RUPALI_BANK_TEMPLATE = """
This is a Rupali Bank PLC "schedule of charges" document.

Look for:
- The credit card table, which often merges multiple card tiers in a single
  grid with merged header cells.
- Annual fee rows ("TK 500", "NIL" - NIL is a genuine 0 fee).
- Interest rate rows ("20%", "2.5% per month" - convert monthly to p.a. only
  when the document explicitly says "per annum"; otherwise keep the stated
  figure and note the period in the raw fields).
- Any "one time" or "joining fee" rows are NOT the annual fee; keep them as
  separate keys.

Return one object per card tier found in the document.
"""

BRAC_BANK_TEMPLATE = """
This is a BRAC Bank PLC schedule of charges / card disclosure document.

Look for:
- The card comparison table: card names across the top, charge descriptions
  down the left column (annual fee, interest rate, cash advance fee, ...).
- Annual fee amounts in "BDT" or "TK"; "Waived"/"Free" means a genuine 0.
- Interest rates as "% p.a." (e.g. "20% p.a."), sometimes split retail/corporate.
- Tier-specific benefit rows (lounge visits, reward points, insurance) that
  should be preserved with their original column header.

Return one object per card tier found in the document.
"""

CITY_BANK_TEMPLATE = """
This is a City Bank PLC schedule of charges / card page document.

Look for:
- The credit card fee section, which is usually a two-column layout
  ("Particulars" | "Charges") repeated per card tier.
- Annual fee values in Taka ("Tk. 4,500"); "NIL" or "Not applicable" means 0.
- APR / interest rows expressed as "% per annum" and may include both retail
  purchase and cash advance rates.
- Supplementary card and re-issue fees are separate keys, not the annual fee.

Return one object per card tier found in the document.
"""

DUTCH_BANGLA_TEMPLATE = """
This is a Dutch-Bangla Bank PLC schedule of charges document. Focus on table
structures.

Look for:
- Card types: Visa Classic, Visa Gold, Visa Platinum, plus any co-branded cards.
- Annual Fee column, usually in TK ("TK 2,000"); "Free" is a genuine 0.
- Interest Rate column, usually as "% p.a.".
- Separate rows for supplementary cards, card re-issue and cash advance.

Return one object per card tier found in the document.
"""

ISLAMI_BANK_TEMPLATE = """
This is an Islami Bank Bangladesh Limited schedule of charges document.

Look for:
- The credit card section; fees may be described as "profit rate" instead of
  "interest rate" - keep the original wording in the raw fields and only fill
  interest_rate_apr when the document states a numeric percentage.
- Annual/ membership fee rows in Taka; "Exempt" or "Nil" means a genuine 0.
- Any installment/lease related percentage, which is NOT the card APR.

Return one object per card tier found in the document.
"""

GENERIC_TEMPLATE = """
This is a Bangladeshi bank schedule of charges document.

Look for:
- The credit card section (per-tier tables or a card comparison grid).
- Annual fee / membership fee rows; "Free", "Nil", "N/A fee" mean a genuine 0.
- Interest rate / APR rows expressed as "% p.a.".
- All other charge rows, captured with their original column header as key.

Return one object per card tier found in the document.
"""

# Bank name (canonical, as stored in the Bank model / all_banks.json) -> template.
BANK_TEMPLATES = {
    "Sonali Bank Limited": SONALI_BANK_TEMPLATE,
    "Sonali Bank PLC": SONALI_BANK_TEMPLATE,
    "Janata Bank Limited": JANATA_BANK_TEMPLATE,
    "Janata Bank PLC": JANATA_BANK_TEMPLATE,
    "Agrani Bank Limited": AGRANI_BANK_TEMPLATE,
    "Agrani Bank PLC": AGRANI_BANK_TEMPLATE,
    "Rupali Bank Limited": RUPALI_BANK_TEMPLATE,
    "Rupali Bank PLC": RUPALI_BANK_TEMPLATE,
    "BRAC Bank PLC": BRAC_BANK_TEMPLATE,
    "BRAC Bank Limited": BRAC_BANK_TEMPLATE,
    "City Bank PLC": CITY_BANK_TEMPLATE,
    "City Bank Limited": CITY_BANK_TEMPLATE,
    "Dutch-Bangla Bank PLC": DUTCH_BANGLA_TEMPLATE,
    "Dutch-Bangla Bank Limited": DUTCH_BANGLA_TEMPLATE,
    "Islami Bank Bangladesh Limited": ISLAMI_BANK_TEMPLATE,
    "Islami Bank Bangladesh PLC": ISLAMI_BANK_TEMPLATE,
}

# Extra aliases (short brand names, abbreviations, common misspellings) that are
# resolved to a canonical key before template lookup.
BANK_ALIASES = {
    "sonali": "Sonali Bank Limited",
    "sonalibank": "Sonali Bank Limited",
    "janata": "Janata Bank Limited",
    "janatabank": "Janata Bank Limited",
    "agrani": "Agrani Bank Limited",
    "agranibank": "Agrani Bank Limited",
    "rupalibank": "Rupali Bank Limited",
    "rupali": "Rupali Bank Limited",
    "brac": "BRAC Bank PLC",
    "bracbank": "BRAC Bank PLC",
    "citybank": "City Bank PLC",
    "city bank": "City Bank PLC",
    "the city bank": "City Bank PLC",
    "dutchbangla": "Dutch-Bangla Bank PLC",
    "dutch-bangla": "Dutch-Bangla Bank PLC",
    "dutch bangla": "Dutch-Bangla Bank PLC",
    "dbbl": "Dutch-Bangla Bank PLC",
    "islami": "Islami Bank Bangladesh Limited",
    "islamibank": "Islami Bank Bangladesh Limited",
    "ibl": "Islami Bank Bangladesh Limited",
}


class BankSpecificPrompts:
    """Resolve and build bank-specific extraction prompts.

    At least five banks ship with a dedicated template; every other bank falls
    back to the generic template so extraction never breaks for an unknown bank.
    """

    def __init__(self, templates=None, aliases=None, base_instructions=None):
        """Initialize the prompt template registry.

        Parameters
        ----------
        templates : dict, optional
            Mapping of canonical bank name to template text.
        aliases : dict, optional
            Mapping of normalized alias to canonical bank name.
        base_instructions : str, optional
            Shared extraction output contract appended to every template.
        """
        self.templates = dict(templates or BANK_TEMPLATES)
        self.aliases = dict(aliases or BANK_ALIASES)
        self.base_instructions = base_instructions or BASE_EXTRACTION_INSTRUCTIONS

    @staticmethod
    def normalize_bank_name(bank_name):
        """Normalize a bank name for lookup (lowercase, collapsed punctuation).

        Parameters
        ----------
        bank_name : str
            Raw bank name from the database, an operator or a URL.

        Returns
        -------
        str
            Normalized name suitable for alias lookups.
        """
        if not bank_name:
            return ""
        normalized = str(bank_name).strip().lower()
        for char in ".,-_/\\()":
            normalized = normalized.replace(char, " ")
        return " ".join(normalized.split())

    def get_template_for_bank(self, bank_name):
        """Return the template text configured for a bank.

        Parameters
        ----------
        bank_name : str
            Bank name in any of the supported spellings.

        Returns
        -------
        str
            Bank-specific template, or the generic template when unknown.
        """
        canonical = self.resolve_bank_key(bank_name)
        return self.templates.get(canonical, GENERIC_TEMPLATE)

    def resolve_bank_key(self, bank_name):
        """Resolve a bank name to a canonical template key.

        Parameters
        ----------
        bank_name : str
            Bank name in any of the supported spellings.

        Returns
        -------
        str or None
            Canonical bank name, or None when no template matches.
        """
        if not bank_name:
            return None

        raw_name = str(bank_name).strip()
        if raw_name in self.templates:
            return raw_name

        normalized = self.normalize_bank_name(raw_name)
        if normalized in self.aliases:
            return self.aliases[normalized]

        # Try normalizing the configured keys as well ("BRAC Bank PLC" -> "brac bank").
        normalized_templates = {self.normalize_bank_name(k): k for k in self.templates}
        return normalized_templates.get(normalized)

    def has_bank_specific_template(self, bank_name):
        """Check whether a dedicated (non-generic) template exists for a bank.

        Parameters
        ----------
        bank_name : str
            Bank name to check.

        Returns
        -------
        bool
            True when a dedicated template exists, False for the generic one.
        """
        return self.resolve_bank_key(bank_name) is not None

    def list_supported_banks(self):
        """List canonical bank names that have a dedicated template.

        Returns
        -------
        list of str
            Sorted canonical bank names.
        """
        return sorted(self.templates)

    def get_prompt_for_bank(self, bank_name, content):
        """Build the full extraction prompt for a bank document.

        Parameters
        ----------
        bank_name : str
            Bank name used to pick the template.
        content : str
            Document text to include in the prompt.

        Returns
        -------
        str
            The complete prompt (bank template + base instructions + content).
        """
        template = self.get_template_for_bank(bank_name)
        prompt = template.replace(CONTENT_PLACEHOLDER, "")
        prompt = (
            f"{prompt.strip()}\n\n"
            f"Bank: {bank_name or 'unknown bank'}\n\n"
            f"{self.base_instructions.strip()}\n\n"
            f"Document content:\n{content if content is not None else ''}"
        )
        return prompt

    def get_focused_prompt(self, bank_name, content):
        """Build the focused (pass 2) prompt for the two critical numeric fields.

        Parameters
        ----------
        bank_name : str
            Bank name for context.
        content : str
            Document text to analyze.

        Returns
        -------
        str
            The focused extraction prompt.
        """
        return (
            "You are extracting ONLY the two critical fee fields from a bank "
            "document. Ignore every other field.\n\n"
            f"Bank: {bank_name or 'unknown bank'}\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            '1. Annual Fee patterns: "TK 5,000", "Tk. 1,500", "BDT 500", '
            '"Free", "Nil", "NIL", "No annual fee"\n'
            '2. Interest rate patterns: "20% p.a.", "2.5% monthly", '
            '"24% per annum"\n'
            "3. Respond with ONLY this JSON shape: "
            '{"cards": [{"name": "card tier or empty string", '
            '"annual_fee": number_or_null, "interest_rate_apr": number_or_null}]}\n'
            "4. Use null only when the value is genuinely absent from the "
            'document. "Free"/"Nil"/"No annual fee" must be returned as 0, '
            "never null, and never guessed.\n"
            '5. Strip currency symbols and commas: "TK 5,000" -> 5000, '
            '"20% p.a." -> 20.0\n'
            "6. If the document has no card information at all, return "
            '{"cards": []}\n\n'
            f"Document content:\n{content if content is not None else ''}"
        )
