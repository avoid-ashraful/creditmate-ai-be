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

Each call runs `claude -p --model haiku --output-format json` with the prompt on **stdin**, in an empty temp
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
