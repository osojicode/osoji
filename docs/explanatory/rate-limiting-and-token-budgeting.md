# Rate Limiting and Token Budgeting: Managing LLM API Constraints

LLM APIs enforce rate limits that are fundamentally different from traditional API rate limits. Osoji's rate limiting system is designed around these differences. This document explains the reservation pattern, adaptive profiling, and auto-tuning that make concurrent LLM requests work reliably within provider constraints.

## Why LLM rate limiting is different

Traditional API rate limiting typically involves one dimension: requests per unit time. LLM rate limiting involves at least three independent dimensions that must all be satisfied simultaneously:

- **RPM** -- requests per minute. A hard cap on how many API calls can be made.
- **Input TPM** -- input tokens per minute. Limits how much prompt text can be sent.
- **Output TPM** -- output tokens per minute. Limits how much response text can be generated.

Some providers enforce input and output TPM as a single combined budget; others (notably Anthropic) track them separately. The system must handle both models.

The deeper challenge is timing: input tokens are known before a request (they can be counted from the prompt), but output tokens are only known after the response arrives. With dozens of requests in flight concurrently -- as happens during shadow documentation generation -- the system cannot simply wait for each response before planning the next request. It must estimate, reserve, and reconcile.

## The reservation pattern

The core design in `rate_limiter.py` follows an acquire-before, finalize-after pattern:

```
t=0:  Request arrives
      -> estimate input tokens
      -> acquire ReservationTicket (deducts estimated tokens from budget)

t=1:  LLM call in flight
      (other requests can acquire from remaining budget concurrently)

t=2:  Response arrives
      -> finalize with actual token counts (budget adjusted for over/under-estimation)

t=3:  Token bucket refills over time
```

### `RateLimiterConfig`

Configuration for rate limits with separate input/output token budgets. Each provider has built-in defaults:

| Provider    | RPM   | Input TPM   | Output TPM  |
|-------------|-------|-------------|-------------|
| Anthropic   | 4,000 | 2,000,000   | 400,000     |
| OpenAI      | 500   | 500,000     | 500,000     |
| Google      | 300   | 5,000,000   | 5,000,000   |
| OpenRouter  | 300   | 500,000     | 500,000     |

These defaults can be overridden via environment variables (`ANTHROPIC_RPM`, `ANTHROPIC_TPM`, `ANTHROPIC_INPUT_TPM`, `ANTHROPIC_OUTPUT_TPM`, and equivalents for other providers). The `get_config_with_overrides()` function applies these overrides and clamps all values to a minimum of 1 to prevent division-by-zero in interval calculations.

### `ReservationTicket`

An immutable record created by `acquire()`:

- `ticket_id` -- monotonically increasing identifier
- `reservation_key` -- logical request type (e.g., `"shadow.file"`, `"shadow.directory"`, `"dead_code.verify"`)
- `reserved_input_tokens`, `reserved_output_tokens` -- the budget deducted at acquisition time
- `acquired_at` -- timestamp for timing calculations

### The `RateLimiter` class

`RateLimiter` in `rate_limiter.py` is an async class that manages three concurrent constraints:

**Request pacing.** Enforces minimum intervals between requests based on RPM. With 4,000 RPM, the minimum interval is 15ms.

**Token bucket refill.** Input and output token budgets refill continuously over time at their configured rates. The `_refill_tokens()` method calculates elapsed time since the last refill and adds the proportional amount, capping at the per-minute maximum.

**Reservation tracking.** The `_inflight` dict maps ticket IDs to active `ReservationTicket` objects. When a request acquires a reservation, its estimated tokens are deducted from the allowance and tracked as in-flight. When the request completes, `finalize_success()` reconciles:

- If the actual tokens were less than reserved: the difference is returned to the allowance
- If the actual tokens were more than reserved: the allowance goes negative (effectively borrowing from future refill)

### The acquire/finalize flow

`acquire()` is an async method that may wait before returning:

1. Increments `_queue_size` to track pending requests
2. In a loop, under a lock:
   - Refreshes the 60-second sliding window
   - Refills token buckets based on elapsed time
   - Selects output reservation (adaptive or explicit)
   - Calculates wait time considering RPM interval, cooldown, input budget, and output budget
   - If wait time is zero, claims the reservation and returns the ticket
   - Otherwise, releases the lock, sleeps for the wait duration, and retries

`finalize_success()` is called after a successful LLM response:

1. Pops the ticket from the in-flight set
2. Adjusts input and output allowances based on reserved vs. actual tokens
3. Updates the `ReservationProfile` for this request type with actual output tokens
4. Updates peak utilization metrics

`finalize_failure()` handles errors:

- For rate-limit errors: records the hit in the profile, sets a cooldown timer (using the `retry_after` duration if provided), and does not refund tokens
- For non-rate-limit errors: refunds the full reservation back to the allowance

## Adaptive output reservation profiling

Output tokens are the hardest dimension to manage. The system cannot know how many tokens the LLM will generate before the request completes, but it must reserve an estimate upfront to avoid exceeding the TPM budget.

`ReservationProfile` in `rate_limiter.py` tracks per-request-type output token history:

- `output_history` -- a bounded deque (last 20 observations) of actual output token counts
- `conservative_remaining` -- a countdown that forces conservative (max) reservations during warmup or after errors
- `under_reserved_count` -- how often actual output exceeded the reservation
- `rate_limit_hits` -- how often this request type triggered a rate limit error

### The selection algorithm

`_select_output_reservation()` uses this profile to choose how many output tokens to reserve:

1. **Explicit override:** If the caller provides `reserved_output_tokens` in `CompletionOptions`, use that (capped at `max_output_tokens`).
2. **Conservative mode:** During warmup (fewer than 5 observations) or after rate limit hits or under-reservations, reserve `max_output_tokens` -- the safe maximum.
3. **Adaptive mode:** After warmup, compute the P90 of recent output history, multiply by 1.20. Also compute the mean and multiply by 1.35. Take the larger of these two values, floored at 128 tokens. This balances between wasting budget (over-reservation) and triggering rate limits (under-reservation).

When actual output exceeds the reservation, `conservative_remaining` is reset to force conservative reservations before returning to adaptive mode. The reset value depends on the cause: after a rate limit hit (HTTP 429), it resets to 5 conservative reservations (a longer recovery period), whereas a simple under-reservation resets to 2.

## The `RateLimitedProvider` decorator

`RateLimitedProvider` in `llm/rate_limited.py` wraps any `LLMProvider` to integrate rate limiting transparently. Its `complete()` method:

1. **Estimates input tokens** via three strategies in priority order:
   - `CompletionOptions.estimated_input_tokens` if the caller provided an explicit estimate
   - `TokenCounter.count_tokens_async()` for provider-specific accurate counting (Anthropic API counting for Anthropic, LiteLLM tokenizer for others)
   - `estimate_tokens_offline()` as a fallback heuristic (character count / 4)

2. **Applies a safety multiplier** (1.15x, `_INPUT_SAFETY_MULTIPLIER` in `rate_limiter.py`, accessed via `RateLimiter.input_safety_multiplier`) to the input estimate to account for tokenizer inaccuracies.

3. **Acquires a reservation** from the shared `RateLimiter`.

4. **Delegates** to the wrapped provider's `complete()`.

5. **On success:** finalizes the reservation with actual token counts from the response, populates `RateLimitMetadata` on the result, and conditionally auto-tunes from response headers.

6. **On retryable error:** finalizes as a rate-limit failure, waits for `retry_after` (from response headers) or exponential backoff (2^n seconds, capped at 30s), and retries up to 3 times.

### Retryable error detection

`_is_retryable_error()` checks for:
- LiteLLM's `RateLimitError` and `APIConnectionError`
- LiteLLM's `APIError` or `InternalServerError` with HTTP status codes 500, 502, 503, 504, 529
- Anthropic SDK errors: `RateLimitError`, `ServiceUnavailableError`, `OverloadedError`, `InternalServerError`

### Retry-after extraction

`_extract_retry_after()` checks response headers for `retry-after-ms` (milliseconds), `retry-after` (seconds or HTTP date), parsing each format defensively.

## Token budget computation: `llm/budgets.py`

The `input_budget_for_config()` function returns a conservative per-request input token budget based on the provider:

- Anthropic: 150,000 tokens
- All others: 100,000 tokens

This budget is used by `LiteLLMProvider._enforce_input_token_budget()` to raise `PromptTooLargeError` before sending a request that would exceed the model's practical context window. The estimate uses `estimate_completion_input_tokens_offline()` from `llm/tokens.py`, which serializes the full request payload (messages, system prompt, tools, tool_choice) to JSON and divides character count by 4.

## Token counting: `llm/tokens.py`

The `TokenCounter` class provides provider-aware token counting:

- **Anthropic:** Uses the Anthropic SDK's `messages.count_tokens()` API for exact counts. This is an API call that returns the precise token count the model will see.
- **Other providers:** Uses LiteLLM's `token_counter()` function, which applies the appropriate tokenizer for the model. This runs in a thread pool via `asyncio.to_thread()` to avoid blocking the event loop.
- **Offline fallback:** `estimate_tokens_offline(text)` divides character length by 4 -- a rough but zero-cost heuristic used when neither API counting nor tokenizer counting is available.

The `TokenCounter` also provides `count_text_async()` with an in-memory cache (up to 10,000 entries) for repeated text measurements during doc-prompts analysis.

## Auto-tuning from response headers

After the first successful LLM response, `RateLimitedProvider._auto_tune_from_headers()` extracts rate limit capacity from response headers:

- Anthropic headers: `anthropic-ratelimit-requests-limit`, `anthropic-ratelimit-tokens-limit`
- Standard headers: `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`

If the discovered limits are higher than the configured defaults, `RateLimiter.update_limits()` increases the limits upward. This auto-tune happens at most once per `RateLimiter` instance (guarded by the `_auto_tuned` flag) to avoid oscillation.

Note: auto-tuning applies the same TPM value to both input and output token limits, since most provider headers report a single combined token limit rather than separate input/output values.

This matters because different API tiers have different limits. A user on Anthropic's high-volume tier might have 4x the default RPM. Auto-tuning discovers the actual capacity without requiring manual configuration.

## Design trade-offs

**Why reservation-based rather than a simple semaphore?** A semaphore limits concurrent requests but cannot account for the fact that a single large-prompt request consumes more budget than a small one. The reservation pattern tracks token-level budgets, allowing many small requests to run concurrently while throttling large ones. This is essential for shadow generation, where file sizes vary by orders of magnitude.

**Why separate input and output TPM tracking?** Anthropic enforces input and output limits independently. A system that tracked only combined TPM would either over-restrict (treating all tokens as the scarcer type) or risk limit violations. Separate tracking also enables the adaptive output profiling, which specifically targets the unpredictable dimension.

**Why adaptive profiling rather than fixed reservations?** Output token counts vary dramatically by request type. Shadow docs for small utility files might generate 500 tokens; large service files might generate 8,000. A fixed reservation of 8,000 would waste 15x budget on small files, severely limiting concurrency. Adaptive profiling converges to accurate estimates within 5 observations, then tracks shifts over time via the rolling P90.

**The cost of over-reservation vs. under-reservation.** Over-reservation wastes budget headroom, meaning fewer concurrent requests and slower overall throughput. Under-reservation risks exceeding the TPM limit, triggering rate-limit errors and retry delays. The system biases toward over-reservation during warmup (conservative mode) and gradually shifts toward tighter estimates as it collects data. The 1.15x input safety multiplier and the P90 * 1.20 output formula both embed a deliberate margin of safety.

**Diagnosing rate-limiting issues.** If requests are slow, the `get_summary()` method on `RateLimiter` reports reservation efficiency (actual/reserved ratio), peak utilization across all three dimensions, rate-limit retry count, and under-reserved request types. The `LoggingProvider` in verbose mode prints per-request headroom percentages. These diagnostics help identify whether the bottleneck is RPM, input TPM, or output TPM, and whether the adaptive profiles have converged.

For how the `RateLimitedProvider` integrates with the provider decorator stack, see the [LLM provider abstraction](llm-provider-abstraction.md) document.
