# Provider Selection in `osoji init`

## Context

The current `osoji init` flow hardcodes Anthropic as the default provider and
doesn't offer interactive selection. Users who want to use OpenAI, Google
Gemini, OpenRouter, or Claude Code must know to pass `--provider` or edit
config files manually. This doesn't advertise multi-provider support and gives
no guidance on switching providers or deferring API key setup.

**Goal:** Let users interactively choose from all supported providers during
init, see sensible model defaults, decide where config lives (shared vs
personal), and receive clear guidance on how to change things later.

## Design

### Phase Restructure

The init flow goes from 3 phases to 4:

| Phase | Name | Purpose |
|-------|------|---------|
| 1 | Git hygiene | .gitignore entries (unchanged) |
| 2 | **Provider setup** | **NEW** — provider selection, model defaults, config target |
| 3 | Secrets (.env) | API key for selected provider, OSOJI_TOKEN |
| 4 | Project config | .osoji.toml project slug (unchanged) |

### Phase 2: Provider Setup (interactive)

**Provider selection** — numbered list, default 1 (Anthropic):

```
2. Provider setup

   Choose your LLM provider:

     1. Anthropic         Claude models, built-in defaults
     2. OpenAI            GPT models, built-in defaults
     3. Google Gemini     Gemini models, built-in defaults
     4. OpenRouter        Multi-provider gateway, built-in defaults
     5. Claude Code CLI   Uses your Claude Code subscription (no API key needed)

   Provider [1]:
```

When `--provider` is passed on CLI, skip the selection prompt and use it
directly — print `Provider: {display_name} (from --provider flag)`.

**Model defaults display** — show the built-in tier defaults for the chosen
provider and let the user accept or override:

```
   Model defaults for Anthropic:
     small:  claude-haiku-4-5-20251001
     medium: claude-sonnet-4-6
     large:  claude-opus-4-6
   Accept defaults? [Y/n]:
```

If the user declines, prompt for each tier with the current default pre-filled:

```
   small model [claude-haiku-4-5-20251001]:
   medium model [claude-sonnet-4-6]:
   large model [claude-opus-4-6]:
```

For **Claude Code**: skip model defaults entirely — it manages models
internally. Print: `Claude Code manages model selection internally.`

**Config target** — ask where to save provider config:

```
   Save provider config to:
     1. .osoji.toml        Shared with team, committed to git (Recommended)
     2. .osoji.local.toml  Personal, gitignored

   Config target [1]:
```

Write the chosen provider to the selected file as `default_provider`:

```toml
default_provider = "anthropic"
```

Only write model overrides if the user changed a default (don't persist values
that match the built-in defaults — they'd just go stale):

```toml
default_provider = "openai"

[providers.openai]
small = "gpt-5-mini"
medium = "gpt-5.2"
large = "gpt-5.4"
```

**Post-setup guidance** — after Phase 2 completes:

```
   Tip: To switch providers later, set default_provider in your config file:
     default_provider = "openai"

   Or set OSOJI_PROVIDER and OSOJI_MODEL environment variables.
   Run `osoji config show` to see your current configuration.
```

### Phase 3: Secrets (.env)

Behavior adjusts based on the provider selected in Phase 2:

- **API-key providers** (anthropic, openai, google, openrouter): prompt for the
  provider's `api_key_env` as before. If skipped, print:
  ```
     Skipped. Add your API key later in .env:
       ANTHROPIC_API_KEY=sk-...
  ```

- **Claude Code**: skip API key prompt entirely, print:
  ```
     Claude Code uses your existing subscription. No API key needed.
  ```

- OSOJI_TOKEN prompt is unchanged (always shown).

### Non-interactive Mode (`--non-interactive`)

- Provider from `--provider` flag (default: anthropic)
- Built-in model defaults used, no prompts
- Provider config written to `.osoji.toml` (shared target)
- API key placeholder written to `.env`
- Summary: `Provider: Anthropic (built-in defaults)`

### Built-in Model Defaults

All providers now have built-in defaults in `BUILTIN_PROVIDER_MODELS`:

| Provider | Small | Medium | Large |
|----------|-------|--------|-------|
| anthropic | claude-haiku-4-5-20251001 | claude-sonnet-4-6 | claude-opus-4-6 |
| openai | gpt-5-mini | gpt-5.2 | gpt-5.4 |
| google | gemini-3.1-flash-lite-preview | gemini-3-flash-preview | gemini-3.1-pro-preview |
| openrouter | anthropic/claude-haiku-4.5 | anthropic/claude-sonnet-4.6 | anthropic/claude-opus-4.6 |
| claude-code | *(same as anthropic)* | | |

OpenRouter defaults to Anthropic models via the gateway for tool-use prompt
compatibility. Users can override with any OpenRouter-available model.

Google defaults use the 3.x preview series (latest as of April 2026). The 2.5
series is scheduled for deprecation June 2026.

## Files to Modify

- **`src/osoji/init.py`** — restructure into 4 phases; add provider selection
  (numbered list), model defaults display/override, config target choice; update
  guidance text; adjust Phase 3 to be provider-aware
- **`src/osoji/config.py`** — add `GOOGLE_MODEL_SMALL/MEDIUM/LARGE` and
  `OPENROUTER_MODEL_SMALL/MEDIUM/LARGE` constants; add google and openrouter
  entries to `BUILTIN_PROVIDER_MODELS`
- **`src/osoji/llm/registry.py`** — set `requires_explicit_model=False` for
  google and openrouter (they now have built-in defaults)
- **`tests/test_init.py`** — update existing tests for 4-phase structure; add
  tests for provider selection, model override, config target choice, claude-code
  path, non-interactive with provider flag
- **`.env.example`** — document all provider API key env vars

No new files. No new dependencies.

## Verification

1. `pytest tests/test_init.py -v` — all init tests pass
2. `osoji init .` interactive — walk through provider selection, model defaults,
   config target, API key, and project slug; verify `.osoji.toml` (or
   `.osoji.local.toml`) and `.env` contain correct values
3. `osoji init . --non-interactive` — verify defaults written correctly
4. `osoji init . --provider openai` — verify skips selection, shows OpenAI flow
5. `osoji init . --provider claude-code` — verify no API key prompt
6. Rerun `osoji init .` on an already-initialized project — verify idempotent
   (skips existing keys, merges cleanly)
7. `osoji config show` — verify provider config is read back correctly
