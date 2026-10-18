"""Shared base instructions used by every bank prompt template.

The base instructions define the *output contract* every extraction pass must
follow, independent of the bank-specific document layout notes. Keeping them in
one place ensures the multi-pass extractor, the focused pass and the legacy
single-pass path all agree on the same JSON shape and on the difference between
a genuine zero fee and missing data.
"""

BASE_EXTRACTION_INSTRUCTIONS = """
You are a credit card data extraction AI. Extract credit card information.

CRITICAL OUTPUT CONTRACT:
1. Respond with ONLY valid JSON - no markdown, no explanations, no code blocks.
2. The response is a JSON array of objects, one object per credit card tier.
3. If no credit cards are found in the document, return [].

Required fields for every card object:
- name: card tier/name as written in the document (e.g. "Platinum Card")
- annual_fee: number, or null when the document never states an annual fee
- interest_rate_apr: number, or null when the document never states an APR

Optional fields (null or "" when absent):
- lounge_access_international, lounge_access_domestic, lounge_access_condition
- cash_advance_fee, late_payment_fee, annual_fee_waiver_policy
- reward_points_policy, additional_features
- card_network: one of "visa", "mastercard", "amex", "unionpay", "jcb",
  "diners", "other"; null when the network is not stated
- is_islamic: true only when the card is explicitly Islamic/Shariah-based,
  false when explicitly conventional, null when not stated
- is_dual_currency: true/false only when the document says the card works in
  both BDT and USD (or not), null when not stated
- min_monthly_income: number in BDT per month (strip text and commas), null
  when no minimum income is stated
- supplementary_card_fee, foreign_transaction_fee: the fee text as written
  (e.g. "Free for first 2 cards", "3.5% of transaction"), null when not stated
- source_url: the page or document URL this card was read from, only if it
  appears in the document; apply_url: the card's own "Apply" / product page
  URL, only if the document states it. Never construct or guess a URL.

Zero vs missing (very important):
- "Free", "No annual fee", "Nil", "NIL", "Exempted" mean a genuine 0 fee:
  return 0, never null.
- When the document does not mention a fee or rate at all, return null.
  Never guess, never default to 0.

Number formatting:
- Remove currency symbols and text (TK., BDT, Tk., USD, $) and commas.
- Percentages become plain numbers: "20% p.a." -> 20.0
- Monthly rates stay monthly unless the document states an annual equivalent.
- Never invent a value for any field: when the document does not state it,
  return null (not false, not 0, not "").
- Any extra document fields are returned using their original column header
  as the key (for example "CIB Fee": "BDT 100").
"""
