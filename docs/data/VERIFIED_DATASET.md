# Verified card dataset (2026-10-18)

`credit_cards/fixtures/verified_cards_2026-10-18.json` holds 135 cards from 9 Bangladeshi
issuers in the `import_cards` format: 105 `verified` (public) and 30 `draft` (held, not
public). Every value comes from a bank's own schedule of charges (SoC), fee PDF or product
page, read 2026-10-18. Each bank's SoC was checked to be the latest version linked from the
bank's site. An independent verifier re-read 87 of the cards (all 68 medium/low confidence
ones plus ~25% of the high confidence ones) and its 27 corrections are applied.

## Sources and effective dates

| Bank (name in DB) | Primary source (`source_url`) | Effective / updated |
|---|---|---|
| BRAC Bank PLC | Credit-card SoC PDF on `brackweb.s3...` linked from `bracbank.com/en/page/schedule-of-charges-for-credit-cards` | 1 Aug 2026 |
| City Bank PLC (The City Bank PLC, incl. Amex) | Per-family fee PDFs linked from `citybankplc.com/df/fees-and-charges`: Visa (11 Jun 2026), American Express (1 Jun 2026; Gold/Blue fee from 1 Jul 2026), Mastercard World Elite (1 Feb 2026), Islamic Amex (1 Jun 2026), Islamic Visa Infinite (15 Sep 2026). Platinum Reserve: product page fee images (undated, not in the PDF) | as listed |
| Dutch-Bangla Bank PLC | `schedule_charge/credit-cards-charges.pdf` + Credit Card Features PDF (created 21 Jul 2026) + product pages | 9 Nov 2025 |
| Eastern Bank PLC | `SOC-Cards_Effective_from_25May2026.pdf` (image-only; read by eye by two readers) | 25 May 2026 |
| LankaBangla Finance PLC (NBFI) | `lankabangla.com/fees-charge/` HTML table; STS/BDF co-brands: application form PDF (16 Mar 2025) + brochures | 1 Jan 2025 (21 months old, no newer schedule found) |
| Mutual Trust Bank PLC | Conventional + Islamic card SoC PDFs; co-brand fees are not published | 15 Oct 2026 |
| Prime Bank PLC | Credit-card SoC PDF (image-only; read by eye) | 1 Aug - 31 Dec 2026 |
| Standard Chartered Bank | Consolidated credit-card SoC; Saadiq SoC | 1 Aug 2026; Aug 2026 |
| United Commercial Bank PLC | Conventional SoC PDF (card table printed p.7) | 11 May 2026 |
| HSBC | none: retail business is closing, no credit cards on the site or in its SoCs; bank set `is_active=false` | - |

Raw downloads and hashes live in the research workspace (`bank-sources/<bank>/sources.json`),
not in this repo. Bank names follow the existing seed (`all_banks.json`), e.g. "City Bank PLC",
"Standard Chartered Bank", so the import does not create duplicate banks.

## Conventions

- **Fees are as printed, VAT-exclusive** (15% VAT and excise duty are extra). The one SoC fee
  printed VAT-inclusive (EBL Wander Woman, BDT 1,725) is stored VAT-exclusive (1,500).
- **`annual_fee` is the recurring (2nd year onwards) primary-card fee in BDT.** The first-year fee,
  tiers and waivers stay in `additional_features` ("Annual fee details: ...") and
  `annual_fee_waiver_policy.conditions`. LankaBangla uses the renewal fee.
- **`annual_fee` is null** where the fee is limit-tiered (DBBL Gold/Platinum/Titanium), in USD
  (FC / ERQ cards, MTB FC Signature) or affiliation-dependent (City DU Amex); the printed text is in
  `additional_features`.
- **`interest_rate_apr` is null for Islamic cards** (monthly maintenance fee, no interest) and for
  LankaBangla (only "2.083% per month" is printed); the printed text is in `additional_features`.
  The maximum APR in the set is 25%.
- Fee fields (`cash_advance_fee`, `late_payment_fee`, `supplementary_card_fee`,
  `foreign_transaction_fee`, `lounge_access_*`) are the SoC wording. Lounge fields were widened to 1000
  characters (migration `0009`) because some are longer than 255.
- `min_monthly_income` is the salaried figure where a page lists both salaried and business.
- `source_url` is the primary SoC/fee document (product page when a card has no published fees or
  its fee table exists only on the product page). `apply_url` is filled only where the URL answered
  HTTP 200 on 2026-10-18 (not for UCB or LankaBangla: those hosts refused connections).
- `verified_at` is 2026-10-18 for verified rows; `import_cards` now keeps a `verified_at` given in the
  file (and still defaults to now if absent).
- "Unsampled" cards: 32 of the 105 public cards (high confidence, read from an official text SoC) were
  not in the verifier's sample and carry no independent confirmation; the sample had no wrong
  annual fee, APR, late fee or cash-advance number. They are: BRAC Signature, World, Diners Emerald,
  Platinum Flexi, TARA World, TARA Platinum; City Visa Infinite, Islamic Visa Infinite; DBBL Gold
  International/Local (Visa, Mastercard), Titanium; LankaBangla Gold, Classic, Visa Platinum, Visa
  Classic, Shikha Gold, Shikha Classic; MTB Classic, Gold, Visa Platinum, Mastercard Titanium, Visa
  Signature, UnionPay Diamond, Islamic Gold/Platinum Ujrah; SCB Silver, Platinum, Smart, Rewards,
  Saadiq Visa Platinum. To publish only independently confirmed cards, set these to `draft`.

## Held as `draft` (30 cards, not public)

| Bank | Held | Why |
|---|---|---|
| BRAC | Visa/Mastercard Gold | May be discontinued: absent from the live Aug 2026 web SoC table; confidence low; hold until the bank confirms |
| LankaBangla | PriyoShop Co-Branded Titanium | Fees inferred from the generic co-brand column, not stated for PriyoShop |
| UCB | ERQ/RFCD | Lien-secured USD-only product with no product page; not a consumer comparison card |
| EBL | 14 co-brand/special cards (Meena Bazar, Shwapno, Basis, ShareTrip, Lavender, Daraz, Banglalink x2, Pickaboo x2, Stellar x2, Diners Vroom, World Elite Biometric Metal) | All fee fields null: SoC note 9 says co-brand fees follow their agreements |
| MTB | 13 co-brand cards (BMA x2, NotreDamians, Grameenphone, IEB, Novoair, Apex Rewards, Baridhara, Cadet College, Chittagong Club, Sylhet Club, Sylhet Station Club, Univ. of Dhaka) | No fees published in the SoC; only lounge/network details sourced |

## Other notes

- Prime Classic is included as a current card: the 1 Aug 2026 SoC prices it and its (unlisted)
  product page returns 200.
- Source conflicts left as printed: BRAC/MTB product pages quote USD 27/29 lounge fees against USD 35 in the SoC
  (SoC used); DBBL Signature/World pages contradict themselves on Priority Pass (8 free visits per the Features
  PDF vs "unlimited"; 8 used); LankaBangla's fee page and application form disagree on the first-year membership
  fee (renewal fee identical).
- Full list of field changes with evidence: `CHANGELOG.md` in the research workspace.

## Reload locally

```bash
python manage.py migrate
python manage.py loaddata all_banks.json                      # 65 banks incl. LankaBangla; HSBC inactive
python manage.py import_cards credit_cards/fixtures/verified_cards_2026-10-18.json
```

`import_cards` is an upsert by bank name + card name (re-running is safe) and aborts on any invalid
row. Only `verification_status=verified` cards appear in the public API. After loading, the public API
should list 105 cards: BRAC 10, City 18, DBBL 8, EBL 16, LankaBangla 11, MTB 12, Prime 11, SCB 11, UCB 8.
To re-export the verified cards: `python manage.py export_verified_cards out.json`.
