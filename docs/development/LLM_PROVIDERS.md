# LLM providers and fallback

The crawler talks to LLMs through `common.llm.LLMOrchestrator`. Providers:

| Name | Backend | Needs |
|------|---------|-------|
| `gemini` | Google Gemini API | `GEMINI_API_KEY` |
| `claude_code` | Local Claude Code CLI, `claude -p --model haiku` | `claude` binary on `PATH`, logged in |
| `openrouter` | OpenRouter API | `OPENROUTER_API_KEY` |

## How fallback works

- Order comes from `LLM_PROVIDER_ORDER` (comma separated, default `gemini,claude_code,openrouter`).
- Providers that are not available (no key, CLI missing, `CLAUDE_CODE_ENABLED=False`) are skipped.
- A quota / rate-limit (`LLMRateLimitError`) or auth (`LLMAuthenticationError`) failure moves to the next provider
  immediately, with no retries. Other errors are retried `max_retries` times, then fall through.
- `preferred_provider` still moves that provider to the front.
- Every attempt (retries and fallbacks) counts against `LLM_MAX_CALLS_PER_RUN`.
- The provider that served each call is logged (`Successfully generated response using <name>`) and returned
  in the result's `provider` field.

## Claude Code CLI provider

Each text call runs `claude -p --model haiku --output-format json` with the prompt on **stdin**, in an empty temp
directory, with tools, MCP servers, settings sources, slash commands and the default system prompt removed
(`--tools "" --strict-mcp-config --setting-sources "" --no-session-persistence --system-prompt ...`). This keeps
overhead to a few hundred tokens instead of loading your hooks, `CLAUDE.md` files and MCP servers.

Settings (env): `CLAUDE_CODE_ENABLED` (default `True`), `CLAUDE_CODE_BIN` (default `claude`, resolved with
`PATH`), `CLAUDE_CODE_MODEL` (`haiku`), `CLAUDE_CODE_TIMEOUT_SECONDS` (`180`), `CLAUDE_CODE_MAX_CONCURRENCY`
(`1`, enforced across processes with file locks in `$TMPDIR/creditmate-claude-code/`, so Celery workers do not
fire parallel CLI calls) and `CLAUDE_CODE_USE_API_KEY` (`False`: `ANTHROPIC_API_KEY` is removed from the child
environment so the subscription login is used; `--bare` is not usable because it requires an API key).

Error mapping: usage/rate limit text -> `LLMRateLimitError`; not logged in / auth -> `LLMAuthenticationError`;
timeout, OS error, API error before a model call -> `LLMNetworkError`; malformed or empty output ->
`LLMResponseError`.

### Logging in on a machine that runs Celery

1. The Celery worker's **OS user** must have logged in once: run `claude` and complete `/login`, or run
   `claude setup-token` for a long-lived token (export it as `CLAUDE_CODE_OAUTH_TOKEN` in the worker's env).
2. The worker's `PATH` must include the binary (e.g. `~/.local/bin`), or set `CLAUDE_CODE_BIN` to its full path.
3. Verify as that user: `python manage.py llm_status --ping`.

The production server needs its own login; credentials are never shared through the repo.

### Limits and terms

This uses a Claude **subscription**, so subscription usage limits and Anthropic's terms apply. It is intended for
development and low-volume crawling, not high-volume production traffic. Once the limit is hit the provider raises
a rate-limit error and the orchestrator falls through to the next provider.

## `llm_status`

```bash
python manage.py llm_status          # order + availability
python manage.py llm_status --ping   # one tiny call per available provider (uses quota)
LLM_PROVIDER_ORDER=claude_code python manage.py llm_status --ping   # test only the CLI path
```
Keys are never printed.

## Image schedules (vision)

`LLMOrchestrator.generate_from_images(prompt, image_paths, **options)` accepts local
images and returns the same response/provider/attempts/errors mapping as text
calls. `system_prompt`, `preferred_provider`, `max_retries` and tuning options work
as for text. Only available providers explicitly declaring `supports_images=True`
are tried: currently `gemini` and `claude_code`; OpenRouter remains text-only.
Quota/auth fallback and retries share the **same per-run call budget** with text
extraction. Missing image providers raise `LLMConfigurationError`; a spent budget
raises `LLMBudgetExhaustedError` before another provider call.

Gemini sends the image bytes as `google.genai.types.Part.from_bytes(data=...,
mime_type=...)` inline alongside the prompt, using the installed `google-genai`
SDK (validated against 2.31.0). PNG, JPEG and WebP are accepted. Image paths are
never passed as generation configuration.

For image requests, Claude Code copies each image to a fresh temporary working
directory, names it `page-N.png` (preserving its format extension), and receives
explicit absolute paths to read. These calls use `--tools Read`,
`--allowedTools 'Read(//absolute/temp/path/**)'`, `--add-dir <tempdir>` and
`--permission-mode dontAsk`: only Read is exposed, automatic read approval is
scoped to that directory, and other permission requests are denied. The strict
MCP/settings/system-prompt flags from text calls still apply. Text requests have
no tools. Both modes clean up their request directory even on timeout; the
shared file-lock directory contains only concurrency locks. Subscription auth
still strips `ANTHROPIC_API_KEY` unless explicitly opted in with
`CLAUDE_CODE_USE_API_KEY=True`. Flags were checked with the installed
`claude --help`; pytest mocks every CLI invocation.

When PDF/image OCR lacks usable fee evidence, the crawler tries vision before
creating the existing `needs_multimodal` manual-review item. It reuses the fetched
binary source (no second download), capped at 20 MiB. PDF rendering uses
`pdftoppm` from the OS `poppler-utils` package when installed, with 200 dpi,
a maximum 4000-pixel edge, a 90-second timeout and at most the **first four
pages**. Without Poppler, the already-required PyMuPDF renderer applies the same
page/edge limits; no new Python dependency is needed. Direct images are converted
to bounded RGB PNGs. Pages wider/taller than 2000 pixels also include overlapping
1600-pixel detail tiles in reading order, preserving dense Bengali fee tables
when a provider downscales a page overview. The bound is 40 images (four
overviews and at most nine tiles per page). PNG output totals at most 20 MiB,
and all intermediate files
are temporary. Large/unsupported/corrupt sources, unavailable providers, failed
vision or exhausted budgets retain manual review without penalizing the source.
The model is told that only the supplied pages are available and unknown values
must remain null. Schedules longer than four pages need separate sources or
manual review for the remaining pages.

Successful vision parses store `extraction_method="vision"` and provider
provenance, then use the existing sanitizer, quality scoring and card data
service. New cards stay drafts, verified cards get review proposals instead of
being overwritten, and invalid values retain sanity flags. Binary source hashes
prevent different posters with identical empty/noisy OCR from being mistaken for
unchanged content. No database migration is required.

### EBL proof, 2026-10-19

The real subscription-backed `claude_code`/Haiku proof used the downloaded
`soc_cards_25May2026.pdf` and no Gemini provider/key. Source bytes were read using
isolated Python (`python3 -I`), never executed. Two real generation calls were
made outside pytest: the first full-page-only call recovered no annual/late
fees; the final call used one overview plus six detail tiles and returned
14 product groups. No fixture values were sent to the model.

[Parsed cards and row-by-row comparison](vision_ebl_proof_2026-10-19.json) include
all 16 verified EBL fixture rows. With **manual group-to-product mapping** (some
source columns cover multiple fixture products), annual fees matched 14 rows,
mismatched one and were absent for one; APR matched 15 and was absent for one;
late-fee amounts matched 14 and were absent for two. Diners' annual fee was read
as BDT 1,480 versus fixture BDT 1,740, and its late fee was missing. Wander Woman
was not extracted. The Signature/Acci-shield label was read as "Signature Access";
combined military and Signature groups are not exact product-name matches.
Corporate Platinum and FX Express have no verified fixture counterparts. This
proves the vision route works but does not establish complete or error-free
extraction; the normal draft/review safeguards remain necessary.
