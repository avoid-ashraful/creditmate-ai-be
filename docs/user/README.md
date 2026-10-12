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
3. **Keep the qualifications.** A paraphrase may not drop a condition that
   changes the meaning. For example section 16(c) of the guideline gives the
   7 working day closure deadline *only if no outstanding balance exists*, and
   section 7(f) says a cash advance *may* have no interest free period. Restate
   the condition, not just the headline. Section references used in review:
   5 (eligibility), 6(e)-(g) (secured card, retirees, cash advance), 7(f)-(m)
   (interest and fees), 10 (billing), 11(e) (overdue reporting), 12 (consent and
   lost cards), 16 (closure and dormancy).
4. **Only real UI.** Describe what the app actually does. The filter panel -
   including `Has Fee Waiver Policy`, `Any Lounge Access`, `International Lounge
   Access`, `Domestic Lounge Access` and the two "Min" fields - lives on the home
   page `/` (`src/components/FilterPanel.tsx`, rendered by
   `src/pages/HomePage.tsx`). A reader selects up to four cards on `/` and then
   presses **Compare Cards**; `/compare` only renders those already selected
   cards (`src/pages/ComparisonPage.tsx` shows an empty state otherwise). Guides
   must therefore start on `/` and must **not** link `/compare` as a browse or
   filter screen. `readability_check.py` fails the build if a guide does.
5. **Plain English.** Every guide must stay below a Flesch-Kincaid grade of 8.0,
   checked per file and never as an average.
6. **Both copies stay in step.** If you edit a Markdown guide, edit the matching
   entry in `src/content/guides.ts` as well.

## Readability check (the CI gate)

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
above the 8.0 threshold, or when a guide links to `/compare`, so it is safe to
use in CI. `--csv` prints a machine-readable table.

Measured on 12 October 2026 with `python3 docs/user/readability_check.py
--fe ../creditmate-ai-fe/src/content/guides.ts`, exit `0` (words / sentences /
syllables / Flesch-Kincaid grade / Flesch reading ease / Gunning Fog):

| File | Words | Sent | Syl | FK grade | Reading ease | Fog |
|------|------:|-----:|----:|---------:|-------------:|----:|
| choosing-your-first-credit-card.md | 743 | 80 | 914 | 2.55 | 93.34 | 5.65 |
| understanding-annual-fee-waivers.md | 732 | 82 | 913 | 2.61 | 92.26 | 5.32 |
| maximizing-lounge-access-benefits.md | 581 | 60 | 732 | 3.05 | 90.42 | 5.80 |
| credit-card-vs-debit-card.md | 691 | 56 | 855 | 3.82 | 89.63 | 6.61 |
| frontend `src/content/guides.ts` | 2669 | 345 | 3297 | 2.00 | 94.48 | 4.68 |

Worst file: 3.82, i.e. 4.18 points of headroom under the 8.0 requirement.

`readability_check.py` uses its own syllable counter, so on its own it is weak
*independent* proof. That is why a second script exists.

## Independent cross-check (textstat + CMU)

```bash
uv venv .venv-readability --python 3.12
uv pip install --python .venv-readability/bin/python textstat cmudict
cd creditmate-ai-be
.venv-readability/bin/python docs/user/readability_textstat.py \
  --fe ../creditmate-ai-fe/src/content/guides.ts
```

Exact output of that command on 12 October 2026, exit `0`:

```
scorer A: textstat 0.7.13 (flesch_kincaid_grade, its own lexicon/sentence/syllable counters)
scorer B: CMU Pronouncing Dictionary syllables (available)
scorer C: readability_check.py own counter (the CI gate)
threshold: Flesch-Kincaid grade < 8.0, evaluated per file

file                                  chars  words  sent    syl     A_fk     B_fk   B_cov     C_fk      FRE     Fog
-------------------------------------------------------------------------------------------------------------------
choosing-your-first-credit-card.md     3864    750    80    926   2.6353   2.6399   0.996   2.5500  92.8666  5.2433  OK
understanding-annual-fee-waivers.md    3788    738    82    917   2.5821   2.5235   0.992   2.6100  92.5805  5.0092  OK
maximizing-lounge-access-benefits.m    3150    586    60    744   3.2006   3.0788   0.974   3.0500  89.5116  5.3401  OK
credit-card-vs-debit-card.md           3569    696    56    856   3.7698   3.8373   0.990   3.8200  90.1717  6.0059  OK
../../../creditmate-ai-fe/src/conte   13926   2674   335   3305   2.1075   2.0986   0.986   2.0000  94.1696  4.4494  OK

exact inputs (SHA-256 of the normalised prose fed to every scorer):
  choosing-your-first-credit-card.md   c7e19fb83f1a516cc932e8d1e11e14682ae93e80b802a41932bdc3a9f964a65a  (3864 chars)
  understanding-annual-fee-waivers.md  db2212847c1f8b81ff3d49f28f19f8bc0f525e8afbeaa81bf6dc289096b7c697  (3788 chars)
  maximizing-lounge-access-benefits.m  680e0d520dbe10c44b140fd71ab6948fbb20103d6885bee23d3cf624c71853a1  (3150 chars)
  credit-card-vs-debit-card.md         81af3c602ffe81abf9bcc7c9c229523cd3d03d6672c442142f40d48e2d0fe48b  (3569 chars)
  ../../../creditmate-ai-fe/src/conte  84ca79441868bee9bd53a8937a3ca070a22ea742f663d2fe644d52acac0753a1  (13926 chars)

all 5 file(s) below grade 8.0 under every scorer that ran
```

How to read this:

- **A** is `textstat.flesch_kincaid_grade`, a third-party scorer with its own
  word, sentence and syllable counters. Formula from its docstring:
  `(.39 * avg sentence length) + (11.8 * avg syllables per word) - 15.59`.
- **B** counts syllables from the CMU Pronouncing Dictionary (ARPAbet stress
  digits), which shares no code with any heuristic here. `B_cov` is the share of
  tokens CMU knew; it is 0.974-0.996, so the column is measured, not guessed.
  Missing tokens are excluded rather than guessed at, and coverage is printed so
  a thin match cannot flatter the result.
- **C** is the CI gate's own counter, shown next to A and B so any divergence is
  visible. The three agree to within 0.16 grade points on every file, and all
  three are far below 8.0.
- Every file is scored on its own. There is no average and no combined figure.
- The input to all three scorers is byte-identical: `readability_textstat.py`
  imports the normalisers from `readability_check.py` instead of re-implementing
  them, and prints the SHA-256 of that text so the run can be reproduced.
- Stripped before scoring: code blocks, link/image syntax (label kept, URL
  dropped), heading/list/blockquote markers, emphasis markers, table pipes, HTML
  tags and bare URLs. A URL is not prose a reader sounds out, and all guides
  carry the same source URLs, so including them would shift every score equally
  and prove nothing.
- Nothing in either script tunes the scoring rules.

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
