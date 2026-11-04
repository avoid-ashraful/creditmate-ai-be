"""Mapping from Bangladesh Bank chart bank codes to catalogue banks.

The BB lending chart identifies banks by short codes (``BRAC``,
``DUTCH-BANGLA`` ...). Each code maps to the catalogue ``Bank`` name where
one exists; codes with no catalogue bank (PKB, NBL, Padma — absent from
the card catalogue) map to ``None`` and the ingestion falls back to the
display name so the bank still appears with chart bands.

``is_islamic`` marks full-fledged Islamic banks in the *conventional*
chart; their BB numbers are expected (provisional) profit, never interest.
"""

# code -> (catalogue Bank.name or None, display name, is_islamic)
BB_BANK_CODES = {
    "AGRANI": ("Agrani Bank Limited", "Agrani Bank", False),
    "BASIC": ("BASIC Bank Limited", "BASIC Bank", False),
    "BDBL": ("Bangladesh Development Bank Limited", "Bangladesh Development Bank", False),
    "JANATA": ("Janata Bank Limited", "Janata Bank", False),
    "RUPALI": ("Rupali Bank Limited", "Rupali Bank", False),
    "SONALI": ("Sonali Bank Limited", "Sonali Bank", False),
    "BKB": ("Bangladesh Krishi Bank", "Bangladesh Krishi Bank", False),
    "PKB": (None, "Probashi Kallyan Bank", False),
    "RAKUB": ("Rajshahi Krishi Unnayan Bank", "Rajshahi Krishi Unnayan Bank", False),
    "AB-BANK": ("AB Bank PLC", "AB Bank", False),
    "AL-ARAFAH": ("Al-Arafah Islami Bank PLC", "Al-Arafah Islami Bank", True),
    "BANK ASIA": ("Bank Asia PLC", "Bank Asia", False),
    "BCBL": ("Bangladesh Commerce Bank Limited", "Bangladesh Commerce Bank", False),
    "Bengal": ("Bengal Commercial Bank Limited", "Bengal Commercial Bank", False),
    "BRAC": ("BRAC Bank PLC", "BRAC Bank", False),
    "CBBL": ("Community Bank Bangladesh PLC", "Community Bank Bangladesh", False),
    "Citizens": ("Citizens Bank PLC", "Citizens Bank", False),
    "DHAKA": ("Dhaka Bank PLC", "Dhaka Bank", False),
    "DUTCH-BANGLA": ("Dutch-Bangla Bank PLC", "Dutch-Bangla Bank", False),
    "EBL": ("Eastern Bank PLC", "Eastern Bank", False),
    "EXIM": ("Export Import Bank of Bangladesh Limited", "EXIM Bank", True),
    "FIRST SECU": ("First Security Islami Bank PLC", "First Security Islami Bank", True),
    "GIBL": ("Global Islami Bank PLC", "Global Islami Bank", True),
    "ICB": ("ICB Islamic Bank Limited", "ICB Islamic Bank", True),
    "IFIC": ("IFIC Bank PLC", "IFIC Bank", False),
    "ISLAMI": ("Islami Bank Bangladesh Limited", "Islami Bank Bangladesh", True),
    "JAMUNA": ("Jamuna Bank Limited", "Jamuna Bank", False),
    "MDBL": ("Midland Bank Limited", "Midland Bank", False),
    "MERCANTILE": ("Mercantile Bank PLC", "Mercantile Bank", False),
    "MGBL": ("Meghna Bank PLC", "Meghna Bank", False),
    "MMBL": ("Modhumoti Bank Limited", "Modhumoti Bank", False),
    "MUTUAL TRUST": ("Mutual Trust Bank PLC", "Mutual Trust Bank", False),
    "NBL": (None, "National Bank", False),
    "NCCBL": ("National Credit & Commerce Bank PLC", "NCC Bank", False),
    "NRBBL": ("NRB Bank Limited", "NRB Bank", False),
    "NRBCBL": ("NRBC Bank PLC", "NRBC Bank", False),
    "ONE BANK": ("ONE Bank PLC", "ONE Bank", False),
    "Padma": (None, "Padma Bank", False),
    "PREMIER": ("Premier Bank PLC", "Premier Bank", False),
    "PRIME": ("Prime Bank PLC", "Prime Bank", False),
    "PUBALI": ("Pubali Bank PLC", "Pubali Bank", False),
    "SBACBL": (
        "South Bangla Agriculture and Commerce Bank Limited",
        "SBAC Bank",
        False,
    ),
    "SHAHJALAL": ("Shahjalal Islami Bank PLC", "Shahjalal Islami Bank", True),
    "SHIMANTO": ("Shimanto Bank Limited", "Shimanto Bank", False),
    "SIBL": ("Social Islami Bank PLC", "Social Islami Bank", True),
    "SOUTHEAST": ("Southeast Bank Limited", "Southeast Bank", False),
    "STANDARD": ("Standard Bank PLC", "Standard Bank", True),
    "THE CITY": ("City Bank PLC", "City Bank", False),
    "TRUST BANK": ("Trust Bank PLC", "Trust Bank", False),
    "UCBL": ("United Commercial Bank PLC", "United Commercial Bank", False),
    "UNBL": ("Union Bank PLC", "Union Bank", True),
    "UTTARA": ("Uttara Bank PLC", "Uttara Bank", False),
    "AL FALAH": ("Bank Al-Falah Limited", "Bank Alfalah", False),
    "CITI N.A.": ("Citibank, N.A", "Citibank N.A.", False),
    "COMMERCIAL B.": (
        "Commercial Bank of Ceylon PLC",
        "Commercial Bank of Ceylon",
        False,
    ),
    "HABIB": ("Habib Bank Limited", "Habib Bank", False),
    "HSBC": ("HSBC", "HSBC", False),
    "NBP": ("National Bank of Pakistan", "National Bank of Pakistan", False),
    "SBI": ("State Bank of India", "State Bank of India", False),
    "STAN.CHART": ("Standard Chartered Bank", "Standard Chartered", False),
    "WOORI": ("Woori Bank", "Woori Bank", False),
}
