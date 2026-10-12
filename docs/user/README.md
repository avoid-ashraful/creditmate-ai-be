# CreditMate AI user guides

Plain-language how-to guides for people who use credit cards in Bangladesh.
The same four guides are rendered in the web app at the `/guides` route
(`src/pages/GuidesPage.tsx` in the frontend repository).

## Guides

| Guide | File | Web route |
|-------|------|-----------|
| How to choose your first credit card | [choosing-your-first-credit-card.md](./choosing-your-first-credit-card.md) | `/guides/choosing-your-first-credit-card` |
| Understanding annual fee waivers | [understanding-annual-fee-waivers.md](./understanding-annual-fee-waivers.md) | `/guides/understanding-annual-fee-waivers` |
| Maximizing lounge access benefits | [maximizing-lounge-access-benefits.md](./maximizing-lounge-access-benefits.md) | `/guides/maximizing-lounge-access-benefits` |
| Credit card vs debit card in Bangladesh | [credit-card-vs-debit-card.md](./credit-card-vs-debit-card.md) | `/guides/credit-card-vs-debit-card` |

## Editorial rules

1. **Authoritative sources only.** Every financial claim is backed by a link in
   the guide's `Sources` section. The main reference is Bangladesh Bank's
   *Guidelines on Credit Card Operations of Banks*, BRPD-1 Circular No. 09,
   dated 15 March 2026:
   <https://www.bb.org.bd/mediaroom/circulars/brpd/mar152026brpd-19e.pdf>
   (HTTP 200 verified on 12 October 2026). Bank product pages are used for
   product-specific claims such as fee waivers and lounge access.
2. **No invented numbers.** Do not add a fee, interest rate, spending target or
   eligibility rule unless the linked source states it. When a bank's own terms
   apply, say so and link to that bank's schedule of charges.
3. **No unimplemented features.** Guides may only link to routes that exist in
   the app (today: `/`, `/compare`, `/glossary`, `/about`, `/guides`).
4. **Plain English.** Every guide must stay below a Flesch-Kincaid grade of 8.0.
5. **Both copies stay in step.** If you edit a Markdown guide, edit the matching
   entry in `src/content/guides.ts` as well.

## Readability check

```bash
# self test of the syllable counter and sentence splitting (from any directory)
python3 creditmate-ai-be/docs/user/readability_check.py --selftest

# measure the Markdown guides and the frontend content module
cd creditmate-ai-be
python3 docs/user/readability_check.py --selftest
python3 docs/user/readability_check.py --fe ../creditmate-ai-fe/src/content/guides.ts
```

The Markdown guide directory defaults to the directory of the script itself, so
the commands work from anywhere as long as `--fe` is given a path relative to
your current working directory. The check exits `1` when any guide scores at or
above the 8.0 threshold, so it is safe to use in CI. `--csv` prints a
machine-readable table.

Measured on 12 October 2026 (words / sentences / syllables / Flesch-Kincaid
grade / Flesch reading ease / Gunning Fog):

| File | Words | Sent | Syl | FK grade | Reading ease | Fog |
|------|------:|-----:|----:|---------:|-------------:|----:|
| choosing-your-first-credit-card.md | 683 | 75 | 839 | 2.46 | 93.67 | 5.46 |
| understanding-annual-fee-waivers.md | 699 | 79 | 871 | 2.56 | 92.44 | 5.37 |
| maximizing-lounge-access-benefits.md | 559 | 59 | 704 | 2.97 | 90.67 | 5.79 |
| credit-card-vs-debit-card.md | 677 | 55 | 836 | 3.78 | 89.87 | 6.52 |
| frontend `src/content/guides.ts` | 2521 | 333 | 3108 | 1.91 | 94.85 | 4.55 |

Cross-checked with the `textstat` 0.7.13 library on the same normalised prose:
2.57, 2.60, 3.10 and 3.75 for the four Markdown guides - within 0.2 of the
values above, so the self-written syllable counter is not flattered.

## Source link verification

The verification command used (each URL must return HTTP 200):

```bash
curl -sSL -o /dev/null -w "%{http_code} %{content_type} %{size_download}\n" \
  --max-time 25 -A "Mozilla/5.0" "$URL"
```

| URL | Status |
|-----|--------|
| <https://www.bb.org.bd/mediaroom/circulars/brpd/mar152026brpd-19e.pdf> | 200 |
| <https://www.bb.org.bd/en/index.php/financialactivity/schedule_charg> | 200 |
| <https://www.bb.org.bd/en/index.php> | 200 |
| <https://ebl.com.bd/retail/EBL-Cards> | 200 |
| <https://www.ebl.com.bd/charges> | 200 |
| <https://www.dutchbanglabank.com/electronic-banking/visadebitcard.html> | 200 |
| <https://www.dutchbanglabank.com/electronic-banking/mastercarddebit.html> | 200 |
| <https://www.mutualtrustbank.com/cards/debit-card/> | 200 |
| <https://www.mutualtrustbank.com/cards/credit-card/> | 200 |
| <https://www.mutualtrustbank.com/cards/mtb-lounge-key/> | 200 |
| <https://www.mutualtrustbank.com/mtb-air-lounge/> | 200 |
| <https://www.mutualtrustbank.com/cards/schedule-charges-mtb-credit-card/> | 200 |

URLs that returned 404 or redirected to a homepage on 12 October 2026 were
rejected and are **not** cited anywhere in these guides (for example
`bracbank.com/credit-cards`, `ucb.com.bd/schedule-of-charges`,
`citybankplc.com/credit-cards`, `mutualtrustbank.com/credit-cards`).

## Disclaimer

These guides are general information, not financial advice. Terms change.
Always check the bank's current schedule of charges before acting.
