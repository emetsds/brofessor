# Ollama transport through Pydantic AI

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

On 07.11.2026, custom Ollama inference transport was replaced at the user's request.
`infrastructure/text/runners.py` uses the existing `OllamaModel` / `OllamaProvider`
and `pydantic_ai.direct.model_request_stream`. The SDK builds a native structured-output
request to `/v1/chat/completions` and parses SSE. The earlier `_ollama_chunk` and manual
NDJSON assembly were removed. The shared `generate(prompt, schema, ...)` contract was retained.

## Boundaries and dependencies

- `pydantic-ai-slim[openai]==2.66.0` is pinned. The lock added OpenAI SDK 3.46.0,
  tiktoken 0.14.0, and jiter 0.19.0. HTTPX2 2.16.0 is now declared as a direct dependency.
  Licenses were checked from installed distributions, and notices were updated.
- The SDK receives the selected Ollama's explicit IP:port and a dummy key. OpenAI/Ollama
  API variables, proxies, and redirects do not reroute sources. Subscription-based
  Codex/Claude adapters and their authorization were unchanged.
- Before text transfer, the existing preflight checks `/api/status`, `/api/tags`, and
  `/api/show`: cloud is disabled, the model is installed, and it does not point to remote weights.
  Existing model locking, cancellation, and the overall deadline cover the request.
- SDK retries are set to zero, and instrumentation telemetry is disabled. The bounded
  HTTP stream stops before accumulating a response beyond 8 MiB, including reasoning.
  Identity encoding is requested. Compressed responses are rejected before decoding
  so compression cannot bypass the limit. Rejection diagnostics do not expose source text.
- An explicit `finish_reason` is required. Only `stop` with text and no tool calls is accepted.
  The application still checks JSON, the output model, language, and source quotes.
- Models advertising `think=false` support receive compatible `reasoning_effort="none"`.
  Other models retain their default.
- The SDK JSON schema transformer is disabled: original titles, defaults, nullable/nested
  fields, and constraints are preserved. System/user messages come from the existing
  frozen prompts. The checkpoint-key algorithm and user revisions were unchanged.

Basis: [existing OllamaModel](https://pydantic.dev/docs/ai/models/ollama/),
[Direct API](https://pydantic.dev/docs/ai/core-concepts/direct/),
[Ollama compatible API and reasoning control](https://docs.ollama.com/api/openai-compatibility).
Actual contracts were also checked against the installed 2.66.0 source.

## Offline checks and the installed package

Tests use the real SDK, substituting only the HTTP transport. Existing preflight,
address, cloud/remote-model, and redirect checks are retained. Cancellation/deadline
checks now close the real SDK HTTP stream rather than substituting the entire request
function. Added controlled failures cover tool calls, truncated/invalid responses,
HTTP 503 without hidden retries, environment endpoint/key substitution, exceeding
limits before buffering, compressed responses, and r2 retention on replay without a
new request. Protection does not depend on the number of internal helper calls.

- Targeted runners/navigation/collections/pipeline/maintenance/prompts set:
  **241 passed / 27,25 s**.
- Full set before the last compression check: **752 passed / 61,79 s**.
- After adding compression checking, final runners set:
  **82 passed / 7,98 s**. The full set was not rerun.
- Ruff check/format (300 files) and `git diff --check` passed.
- The final wheel was built through standard `uv build --offline --wheel`. The wheel
  and pinned core/dev dependencies were installed in a new Python 3.12.13 environment.
  Checks covered importing the SDK and new module from `site-packages`, CLI `--help`,
  and **82 runner checks / 10,73 s** with cwd outside the checkout and `python -I`.
  The initial offline installation stopped because wheels were missing from cache.
  Missing public packages were downloaded through a normal installation. QA and tests
  are not included in the wheel.

## Real local check

Temporary Ollama **0.40.6** on `127.0.0.1:11436` ran with `OLLAMA_NO_CLOUD=1`,
context 32768, and one parallel request. Already installed weights
`qwen3.8:27b-q4_K_M` were used, digest
`25b843619e944cd0ae6069f94ff4e5e26a16e109ccbc0a66a0f05979ed70098e`.
No weights were downloaded. The persistent server, preferences, and credentials were unchanged.

Synthetic Markdown reports 12 ms at 48 requests/s on one node, the earlier
35 ms, and lack of support for cluster properties/power-loss resilience.
A real worker performed `ask` **a9c236ca3d3247cf** through the new transport in
**61,495 s**, including cold model loading. The server log contains one
`POST /v1/chat/completions`. The answer correctly conveyed the current conditions
and limitations. Two verbatim quotes and the unchanged source were checked.
JSON validity alone was not treated as evidence of content correctness.

After user r2 was saved, the temporary server was stopped. Pipeline replay
completed with the single existing checkpoint, without new inference or a change
to its SHA-256, retaining r2. The temporary server exited. Experiment data remains outside Git.

This checks one short question and model, not a speed benchmark,
whole-book acceptance, or acceptance of every Ollama model. Real generation was not
repeated after the final HTTP-compression rejection was added. The final code was
checked offline and from the installed wheel. Browser UI, TTS, PPTX, and cloud runners
were not actually launched in this work.
