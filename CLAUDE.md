# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Operator** ("second me") is a personal AI agent built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). It's a fractional-product-operator sidekick that finds BD signals, tracks a pipeline, drafts outreach in the user's voice, and schedules calls. It runs as an interactive terminal REPL.

## Honesty (non-negotiable)

These override everything else, including the desire to be helpful or to look competent.

- **Never lie to the user. Always tell the truth, even if you think they'll be upset.**
- **If you break something, tell the user immediately and take full responsibility.**
- **If you don't know something, say so — never guess and present it as fact.**
- **If a sub-agent makes a mistake, report it honestly rather than cover for it.**
- **Never blame a problem on something you know is not the cause.**

## Project Rules

These are the repo-specific rules that keep edits safe and consistent. **They are meant to accumulate:** when you make a mistake here and the user corrects it (or you discover a non-obvious gotcha), add a new numbered rule so future sessions don't repeat it. Over time this list grows and edit-errors shrink. Keep each rule short, concrete, and paired with its *why*. More-specific instructions (a Skill or the user's inline prompt) override these on conflict.

- **R1 — Change behavior in `identity.md`, not Python.** The agent's persona, voice, ICP, and priorities live in `second_me/identity.md` (loaded verbatim as the system prompt). Reach for Python only for new *capabilities* (tools), not new *behavior*.
- **R2 — Never broaden `permissions.py` `ALLOWED` without an explicit request.** Safe-by-default (own tools + read-only abilities; no shell, no arbitrary writes) is a core design property, not an oversight. Adding a write/exec tool is a security decision — confirm with the user first.
- **R3 — Tools return SDK content dicts, never raw strings.** Use the module's `_ok()` / `_err()` helpers: `{"content": [{"type": "text", "text": ...}]}`, with `"is_error": True` for failures.
- **R4 — Keep Google library imports lazy.** Import `google.*` / `googleapiclient` *inside* functions, never at module top level. The agent must run when those packages aren't installed and no account is connected (see `google_auth.py`).
- **R5 — Registering a new tool is two steps, easy to half-finish.** (1) Add the `@tool` function to its module's tool list so it flows into `OPERATOR_TOOLS`; (2) if it relies on a built-in Claude tool, add that tool's name to `ALLOWED` in `permissions.py`. Miss either and the tool silently won't work.
- **R6 — Don't hardcode paths or the model.** Reference the constants in `second_me/config.py` (`CRM_FILE`, `DATA_DIR`, `MODEL`, …) and call `ensure_dirs()` before writing.
- **R7 — Preserve graceful degradation.** Missing Google libs, no connected account, or an unreadable JSON file must never crash the agent — fall back (rules-only scheduling, `.ics` files, empty lists), don't raise.
- **R8 — Scheduling is Pacific-in, both-zones-out.** `create_event` start times are parsed as `America/Los_Angeles`; times shown to the user must appear in **both PT and ET**. Don't change timezone handling casually.
- **R9 — `LEAD_STATUSES` (in `crm.py`) is the single source of truth for pipeline stages.** Add new stages there; it's validated on update and injected into the system prompt.
- **R10 — Project rules vs. user memory.** Repo-specific rules go *here* (Level 2 / Project CLAUDE.md). User-wide facts and preferences that span all projects go to the auto-memory under `~/.claude/.../memory/` — don't conflate the two.
- **R11 — The agent drafts, Meagan sends — everything, including connection requests.** Comments, DMs, posts, likes, and emails are always draft-only; never auto-send them. Connection requests get one extra workflow, not an exception to sending: with `OPERATOR_LINKEDIN_CONNECT` on (off by default), the agent may **vet + log connection-request candidates** (verified ICP, no note) through the `linkedin_connect_check` governor (`tools/linkedin.py` — daily cap via `OPERATOR_LINKEDIN_DAILY_CAP`, deduped, audited) and hand Meagan the approved batch **to send herself**. There is NO browser click path: the permission layer (`permissions.py`) keeps the browser bridge strictly read-only regardless of that flag. LinkedIn is her #1 channel, so keep this boundary tight — don't add any send/click/type capability without an explicit new instruction.
- **R12 — The vault is read-only to the agent.** Read Meagan's Obsidian vault for knowledge; never write into it. To get a note into Obsidian, stage it in `data/vault_inbox/` (`draft_person_note`) for her to file. Keeps her hand-curated notes from being polluted by agent output.
- **R13 — Ground outreach in the vault, not memory.** Drafts must pull her real offer + voice via `read_playbook` (and `find_person` to avoid cold-pitching a known contact). Never invent her offer, proof points, or voice from the model's memory. Distilled guardrails in `_bdr_block()` are a floor, not a substitute for reading the live docs.
- **R14 — JSON state goes through `tools/_common.py`'s store helpers.** `load_json_store`/`save_json_store` give every `data/*.json` file atomic writes (temp file + `os.replace`) and corrupt-file quarantine (rename to `.corrupt-<stamp>` instead of silently overwriting) — these files ARE the agent's memory, so don't bypass them with raw `read_text`/`write_text`. (`config.py` keeps a tiny private copy of the quarantine logic because it can't import from `tools/` — keep them in sync.)
- **R15 — Shared tool-module helpers live in `tools/_common.py`, not per module.** `_ok`/`_err`/`_now`/`_short_id`/`_slug` are imported from there; don't re-paste them into a new tool module — copy-pasted helpers drift.
- **R16 — The LinkedIn daily cap counts Meagan's day (America/Los_Angeles), not UTC.** And its log records *approvals to connect* (she sends), so all wording must say "approved", never imply "sent" — the agent can't truthfully claim something was sent (Honesty).
- **R17 — Showing a candidate is an event; record it.** `list_candidates` auto-marks everything it returns `surfaced` and defaults to serving only `new` (never-shown) people. *Why:* v1 assumed Meagan would manually triage each candidate she saw; she didn't (567 of 575 stayed `new`), so the same top-ranked people were re-served multiple times a day — the reason she stopped using the tool. Never re-serve surfaced candidates unless she explicitly asks, and don't add a new "show people" path that skips the surfaced-marking.
- **R18 — `second_me/availability.json` is a committed generic EXAMPLE; the real schedule lives in gitignored `data/availability.json`.** `config.load_availability()` prefers the personal copy; a corrupt personal copy falls to built-in defaults, never through to the example (wrong schedule silently swapped in). *Why:* the repo is meant to be publishable — never put personal data (emails, calendar names, real hours) in the packaged file, and edit the personal copy to change actual scheduling.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the interactive agent (the main entrypoint)
python -m second_me

# Connect a Google account (run once per account; opens a browser OAuth flow)
python -m second_me.connect_google

# Run tests: python -m pytest
```

There is no linter or build step configured; a small pytest suite lives in `tests/` (pure logic only — no network, no Google, no SDK client). Auth comes from the existing Claude Code login by default — no API key needed. Override the model with `OPERATOR_MODEL` (default `claude-sonnet-4-6`) or supply `ANTHROPIC_API_KEY` via `.env` (copy from `.env.example`). Other env overrides — `OPERATOR_VAULT` (vault location), `OPERATOR_LINKEDIN_CONNECT` / `OPERATOR_LINKEDIN_DAILY_CAP` (opt-in connect + cap), `OPERATOR_CHROME_MCP_URL` (Chrome bridge) — are all documented in `.env.example`.

## Architecture

The agent is assembled in `second_me/agent.py:build_options()`, which produces a `ClaudeAgentOptions` and is the hub wiring four things together:

1. **Identity (the system prompt)** — `second_me/identity.md` is loaded verbatim and prepended to a runtime context block. **This file IS the agent's personality, voice, ICP, and priorities; it is editable prose, not code.** Changing behavior usually means editing `identity.md`, not Python. The runtime block appended in `_system_prompt()` injects today's date, file paths, valid lead statuses, scheduling rules from `availability.json`, and whether Google Calendar is connected.

2. **Tools** — defined with the SDK's `@tool` decorator and exposed via an in-process MCP server named `operator` (`create_sdk_mcp_server`). They are grouped per module and combined into `OPERATOR_TOOLS` in `second_me/tools/__init__.py`. Tool names reach the model namespaced as `mcp__operator__<name>`.

3. **Permissions** — `second_me/permissions.py:can_use_tool` is a safe-by-default gate: Operator's own `mcp__operator__*` tools plus a small read-only allowlist (`WebSearch`, `WebFetch`, `Read`, `Glob`, `Grep`, `TodoWrite`, `NotebookRead`) are allowed; **everything else (shell, arbitrary writes) is denied.** When the Chrome extension is connected, a read-only set of Chrome abilities is also allowed, matched by tool-name suffix in `CHROME_READ_SUFFIXES` (`navigate`, `read_page`, `get_page_text`, `find`, …) — page-*reading* only; anything that acts on a page stays denied (see R11). Separately, `_PREAPPROVED` in `agent.py` is the *narrower* set that skips the permission round-trip entirely (`_MCP_TOOL_NAMES` + `WebSearch`, `WebFetch`, `Read`) — note this is not the full `ALLOWED` list, so `Glob`/`Grep`/`TodoWrite`/`NotebookRead` are permitted but still pass through the gate.

4. **The REPL** — `second_me/cli.py` runs a `ClaudeSDKClient` chat loop, streaming `AssistantMessage`/`ToolUseBlock`/`ResultMessage` and printing compact tool-use hints. `__main__.py` just calls `cli.run()`.

### Tool modules (`second_me/tools/`)

- **`crm.py`** — the agent's memory/"hands": `save_lead`, `list_leads`, `update_lead`, `log_signal`, `list_signals`, `save_draft`. All state persists to a single `data/crm.json` (leads + signals) and markdown files in `data/drafts/`. Lead pipeline stages are the `LEAD_STATUSES` list — validated on update and surfaced in the system prompt.
- **`calendar.py`** — `suggest_call_slots`, `create_event`, `list_events`. Scheduling logic respects `availability.json` (working hours, buffers, protected blocks, no-meeting days). **Dual-mode:** when Google is connected, slots are filtered against real busy times and events book directly onto Google; otherwise slots come from rules only and `create_event` writes a `.ics` file to `data/calendar/`. Times are always shown in **both PT and ET**. Created events are indexed in `data/events.json`.
- **`gcal.py`** — Google Calendar helpers + tools (`gcal_status`, `gcal_list_calendars`, `gcal_list_events`). Internal async helpers (`get_busy_all`, `insert_event`, `list_calendars_raw`) are consumed by `calendar.py`. All Google API calls are wrapped in `asyncio.to_thread` so they don't block the event loop.
- **`memory.py`** — the agent's self-improvement loop: `remember_rule`, `list_rules`, `forget_rule`. When Meagan corrects the agent or states a preference, it calls `remember_rule`; rules persist to `data/learned_rules.json` and are injected into the system prompt every session by `agent.py:_learned_rules_block()` (appended last, so learned rules win over generic defaults on conflict). This is the runtime-agent analogue of CLAUDE.md's accumulating Project Rules — errors trend down as rules trend up. **This is distinct from the user-wide auto-memory** under `~/.claude/.../memory/`: `memory.py` learns *Operator's* working rules for Meagan; the auto-memory holds cross-project facts for Claude Code.
- **`bdr.py`** — the BDR (business development) engine, the front of the funnel that gives the calendar its purpose. Current focus is **Motion 1: VC / referral-source outreach** (the partners in Meagan's `VC-Fractional-Outreach-25-Funds` vault doc, who refer her into portfolio founders). Tools split into **read** (`read_playbook`, `read_vc_targets`, `find_person` — pull offer/voice/target-list/People-history live from the vault) and **pipeline** (`add_outreach`, `list_outreach`, `update_outreach`, `save_outreach_draft`, `draft_person_note`). Pipeline state lives in `data/outreach.json`; drafts go to `data/drafts/`. **Hard boundary: the agent drafts, Meagan sends** — no auto-acting on LinkedIn (it's her #1 sales channel). Voice/pitch non-negotiables (e.g. "executive for rent," never "advisor/consultant") are baked into `agent.py:_bdr_block()`; full depth comes from `read_playbook`. `read_playbook` returns four layers: offer (`OFFER.md`) + voice (`BRAND-VOICE.md`) + strategy (`GIVE-FIRST-METHOD.md` — circles/beats/opener) + **message construction** (`second_me/outreach_framework.md` — subject lines, word counts, channel blueprints, follow-up cadence, the swap test; editable prose like `identity.md`). The framework loads via `config.load_outreach_framework()`, which prefers a vault copy at `Just Fractional/COLD-OUTREACH-FRAMEWORK.md` if Meagan files one (vault = source of truth), and degrades to the `_bdr_block()` floor if neither is readable. The pipeline hands off to the calendar: a VC reply → `status=call_booked` → `create_event`.

- **`discovery.py`** — the prospecting front end. Instead of a static list (curating one is "too much work" for Meagan), the agent actively hunts for fresh prospects on demand. Breaking it down:
  - **What it does** — *the searching is the agent's job*: built-in `WebSearch`/`WebFetch` over funding news + Reddit complaint passes in r/saas, r/startups, r/entrepreneur. (LinkedIn-via-Chrome is staged but not wired.)
  - **Warmest source — her own LinkedIn network** — `import_linkedin_connections` ingests her exported connections/follows CSV (dropped in `data/linkedin/`), role-matches founders/execs + VCs by job title (`_classify_role`), and stages them as warm candidates (`relationship` = connection/follow). These are role-matched but **stage-unverified**, so the agent web-verifies seed–Series B before drafting.
  - **Persist + dedup** — `save_candidate` and `import_linkedin_connections` both funnel through `_add_candidate`, which skips anyone already discovered or already in the outreach pipeline, and flags people with an existing vault `People/` note via `known`. `list_candidates` returns the review batch (best-fit-first, only never-shown `new` people by default) and auto-marks everyone it returns `surfaced` so batches don't repeat (R17); `update_candidate` edits one.
  - **Promotion** — `promote_candidate` drops a chosen candidate into the outreach pipeline by reusing `bdr.create_target` (the shared, single-source target-creation function, also used by `add_outreach`). Lens auto-sets vc→referral_source, founder→prospect; channel defaults by relationship — a `connection` → `linkedin_dm` directly, a `follow` → `connect_note` first.
  - **Scope & boundary** — the net is **seed–Series B** (wider than `OFFER.md`'s late-Seed–early-A, per Meagan's instruction). State lives in `data/candidates.json`; exports in `data/linkedin/` (gitignored — contact PII). Same hard rule: discovery never reaches out — it surfaces, she decides.

- **`linkedin.py`** — the governor for the one LinkedIn workflow Meagan opted into: **vetting + queueing connection requests (no note, verified ICP) for HER to send**. `linkedin_connect_check` (call before handing her each person) hard-enforces the daily cap (`OPERATOR_LINKEDIN_DAILY_CAP`, default 50, counted on Meagan's Pacific day), refuses duplicates, requires a stated ICP fit, and logs the *approval* to `data/linkedin_connects.json`; `linkedin_connect_status` reports approved-today headroom. The whole capability is gated by `OPERATOR_LINKEDIN_CONNECT` (off by default). There is **no browser click path**: the bridge in `permissions.py` is read-only regardless of the flag, so the agent never sends — it produces a vetted batch Meagan sends by hand. See **R11**.

### Two homes: the vault vs. the repo

Meagan's **Obsidian vault** (`OPERATOR_VAULT` env var, default `~/Documents/Obsidian Vault`) is her hand-curated **source of truth** — the offer (`Just Fractional/OFFER.md`), voice (`BRAND-VOICE.md`), the VC target list, and `People/` relationship notes. The agent **reads** the vault (paths + `read_vault_file()`/`vault_available()` in `config.py`, all degrading gracefully if the vault is absent) but **never edits her notes**. The **repo's `data/`** is the agent's own workbench (pipeline, drafts). Anything destined for Obsidian is staged in `data/vault_inbox/` by `draft_person_note` for Meagan to file herself — the agent does not write into the vault.

### Google auth (`google_auth.py`, `connect_google.py`)

Multi-account by design. Google libraries are imported **lazily inside functions** so the agent runs even when they aren't installed or no account is connected. Each connected account stores a token at `data/google_tokens/<email>.json` (a legacy single-account `data/google_token.json` is auto-migrated). Conflict-checking spans **all calendars of all connected accounts**; booking targets the single account/calendar set in `availability.json` under `google.default_booking_account` / `default_booking_calendar`, with `exclude_calendars` to ignore (e.g. Family, Holidays). Setup steps are in `SETUP_GOOGLE.md`.

## Key conventions

- **Config & paths are centralized in `second_me/config.py`** (`PROJECT_ROOT`, `DATA_DIR`, `CRM_FILE`, `MODEL`, etc.). Reference these constants rather than hardcoding paths. `ensure_dirs()` creates the data dirs on demand.
- **Tools return SDK content dicts**, not plain strings: `{"content": [{"type": "text", "text": ...}]}`, with `"is_error": True` for failures. The shared `_ok()`/`_err()` helpers live in `tools/_common.py` (along with `_now`/`_short_id`/`_slug` and the atomic JSON store helpers — see R14/R15).
- **Graceful degradation** is a core pattern: missing Google libs, no connected account, or an unreadable JSON file should never crash the agent — fall back (`.ics` files, empty lists, rules-only scheduling).
- **All persisted state is plain user-owned files** under `data/` (gitignored): `crm.json` (pipeline), `events.json` (calendar index), `learned_rules.json` (learned preferences), `outreach.json` (BDR pipeline), `candidates.json` (discovered prospects), plus `drafts/`, `calendar/`, and `vault_inbox/` (notes staged for Obsidian). There is no database.

## Adding a capability

To extend Operator (per the README's "Growing your agent"):
1. Write a new `@tool(name, description, schema)` async function (in `tools/crm.py` or a new module).
2. Add it to that module's tool list so it flows into `OPERATOR_TOOLS`.
3. If it needs a built-in Claude tool, add that tool's name to `ALLOWED` in `permissions.py`.
