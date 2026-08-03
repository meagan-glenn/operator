---
description: Scaffold and fully register a new Operator @tool (the easy-to-half-finish two-step from R5)
---

You are adding a new capability (a `@tool`) to Operator. Registering a tool is a
**two-step** process and it's easy to half-finish — miss either step and the tool
silently won't work (this is repo rule **R5**). Follow this checklist exactly.

## Context the user gave you

$ARGUMENTS

If the user hasn't said what the tool should do, ask before writing any code:
- What's the tool's name (snake_case) and one-line purpose?
- What inputs does it take?
- Does it need a built-in Claude tool (e.g. `WebSearch`, `WebFetch`, `Read`) to do its job?
- Which module does it belong in — an existing one (`crm`, `calendar`, `bdr`,
  `discovery`, `linkedin`, `memory`, `gcal`) or a new module?

## Before you write

1. **Decide: is this really a new *capability*, or just new *behavior*?** Per **R1**,
   persona/voice/ICP/priorities live in `second_me/identity.md`, not Python. If the
   ask is "make Operator phrase things differently" or "prioritize X," that's an
   `identity.md` edit, NOT a tool. Push back and stop here if so.
2. Read the target module and an existing `@tool` in it to match the local style
   (e.g. `second_me/tools/crm.py`). Reuse that module's `_ok()` / `_err()` helpers.
3. Reference path/model constants from `second_me/config.py` — never hardcode (**R6**).
   Call `ensure_dirs()` before writing any file.

## Step 1 — Write the tool and add it to the module's tool list

- Write an `async def` decorated with `@tool(name, description, schema)`.
- **Return SDK content dicts, never raw strings** (**R3**): `_ok("…")` for success,
  `_err("…")` for failure (which sets `"is_error": True`).
- **Preserve graceful degradation** (**R7**): a missing Google lib, no connected
  account, or an unreadable JSON file must fall back — never raise/crash the agent.
- Keep any `google.*` / `googleapiclient` imports **inside the function** (**R4**).
- Add the new function to that module's exported tool list (e.g. `CRM_TOOLS`) so it
  flows into `OPERATOR_TOOLS` via `second_me/tools/__init__.py`. If you created a new
  module, also import its tool list in `__init__.py` and add it to the
  `OPERATOR_TOOLS` sum and `__all__`.

## Step 2 — Permissions (only if the tool uses a built-in Claude tool)

- Operator's own `mcp__operator__*` tools are allowed automatically — **no permission
  change needed** for a tool that only touches local files via its own logic.
- If (and only if) the tool relies on a **built-in** Claude tool, add that tool's name
  to `ALLOWED` in `second_me/permissions.py`.
- **Do NOT broaden `ALLOWED` with shell/write/exec abilities without an explicit
  request from Meagan** (**R2** — this is a security decision). If the tool seems to
  need one, stop and confirm with the user first. Same for any LinkedIn *action*
  beyond reading (**R11**): drafting is fine, auto-sending is not (except the opted-in
  no-note connect, already governed by `linkedin.py`).

## Step 3 — Verify the wiring

- Confirm the tool name will reach the model as `mcp__operator__<name>`.
- Sanity-check it's in `OPERATOR_TOOLS` (trace the import chain through `__init__.py`).
- There's no test suite — do a quick import check:
  `python -c "from second_me.tools import OPERATOR_TOOLS; print(len(OPERATOR_TOOLS))"`
  and confirm the count went up by one.

## Step 4 — Report honestly

Tell the user exactly what you changed (files + the two registration points), and
flag anything you were unsure about rather than presenting a guess as done (**Honesty**).
If you discovered a non-obvious gotcha, suggest adding a numbered Project Rule to
`CLAUDE.md` so the next session doesn't repeat it.
