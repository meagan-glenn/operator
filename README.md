# Operator — your "second me"

Your first AI agent: a fractional-product-operator sidekick that finds signals,
tracks a BD pipeline, and drafts outreach + content in your voice. Built on the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

It's a **foundation, not a finished product** — today it does the BD + signals +
outreach loop end-to-end. Calendar, social scheduling, and ops bolt on as new
tools (see *Growing your agent* below).

## Run it

From a clone of this repo:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m second_me
```

That's it. Because the Agent SDK reuses your existing Claude Code login, you
don't need to paste an API key to start. (Want to use a raw key or change the
model? Copy `.env.example` → `.env`.)

Then just talk to it:

```
you › Run a discovery pass — find me 5 seed–Series B SaaS founders showing
      churn pain and 3 VCs who'd refer me in.
you › Import my LinkedIn connections and show me the founders.
you › Promote the top 3 and draft warm openers in my voice.
you › Show me today's prospects, then my pipeline.
```

## What it can do today

- **Discover prospects (no list to maintain)** — actively hunts seed–Series B SaaS
  founders and referral-source VCs across funding news + Reddit complaint passes,
  scores fit against your offer, dedups, and hands you a fresh batch
  (`save_candidate`, `list_candidates`, `promote_candidate`).
- **Mine your own LinkedIn network** — ingests your exported connections/follows
  CSV and surfaces the warm, in-network founders + VCs worth reaching out to
  (`import_linkedin_connections`).
- **Run BD outreach in your voice** — grounded in your real offer + brand voice
  from the vault, it drafts emails / DMs / connection notes and tracks the
  pipeline (`read_playbook`, `find_person`, `add_outreach`, `save_outreach_draft`).
- **Grow LinkedIn connections (opt-in)** — vets + queues no-note connection
  requests to verified ICP people, hard-capped + deduped + audited, and hands
  you the batch to send yourself — it never sends. Comments and DMs stay
  draft-only too. Off by default (see [Safety](#safety)).
- **Schedule** — `suggest_call_slots` proposes open times (shown in **both PT and
  ET**), `create_event` books the call. With Google connected it's two-way: checks
  **all your calendars** for conflicts and books directly. Setup:
  [`SETUP_GOOGLE.md`](SETUP_GOOGLE.md).
- **Get better over time** — when you correct it or state a preference, it writes a
  rule (`remember_rule`) that loads into every future session.

Everything it remembers is plain files you own under `data/` (pipeline,
candidates, drafts, learned rules). Your Obsidian vault stays the source of truth —
it reads your offer/voice/People notes but never edits them.

## Make it sound like you

Open [`second_me/identity.md`](second_me/identity.md) and edit it. That file *is*
the agent's personality, voice, ICP, and priorities — no code changes needed.
The more specific you make it, the more it feels like a second you.

## Growing your agent (the fun part)

Each capability is just a tool. To add one:

1. Write a new `@tool(...)` function (in `second_me/tools/crm.py` or a new file).
2. Add it to the `OPERATOR_TOOLS` list.
3. If it's a built-in Claude tool you want to allow, add the name to `ALLOWED`
   in [`second_me/permissions.py`](second_me/permissions.py).

Natural next modules:
- **BDR engine (shipped)** — discovery + LinkedIn-network mining + voice-grounded
  outreach + a connect governor.
- **Calendar (shipped)** — proposes slots, checks real Google busy times, books
  directly (see [`SETUP_GOOGLE.md`](SETUP_GOOGLE.md)).
- **Social** — a tool that drafts + schedules LinkedIn/newsletter/TikTok.
- **Ops** — a weekly review tool that reads the pipeline and tells you where to
  focus as the market shifts.

## Project map

```
second_me/
  identity.md        ← who your agent is (edit this!)
  availability.json  ← generic example of scheduling rules — copy it to
                       data/availability.json (gitignored) and edit that copy
                       with your real timezone, hours, and protected time
  config.py          ← paths + model + vault location
  agent.py           ← assembles identity + tools + guardrails
  permissions.py     ← safe-by-default: own tools + read-only abilities (+ opt-in connect)
  cli.py             ← the interactive chat loop
  google_auth.py     ← Google OAuth + service builder (lazy-loaded)
  connect_google.py  ← one-time `python -m second_me.connect_google` setup
  tools/discovery.py ← hunt + dedup fresh prospects; import LinkedIn network
  tools/bdr.py       ← outreach pipeline + voice-grounded drafting (reads the vault)
  tools/linkedin.py  ← connect governor (daily cap + dedup + audit)
  tools/crm.py       ← leads, signals, drafts (the agent's "hands")
  tools/calendar.py  ← propose call slots + create events (Google or .ics)
  tools/gcal.py      ← Google Calendar read/freebusy/insert helpers + tools
  tools/memory.py    ← learned rules (self-improvement loop)
data/                ← the agent's workbench (gitignored): crm.json, outreach.json,
                       candidates.json, drafts/, learned_rules.json, linkedin/, …
```

## Safety

By design, Operator uses its own tools plus web search and reading files; it
**cannot** run shell commands or write arbitrary files, and it **never edits your
Obsidian vault**. On LinkedIn it drafts and you send — everything, including
connection requests: with `OPERATOR_LINKEDIN_CONNECT` on (off by default) it can
vet + queue no-note connection requests to verified ICP people (daily-capped,
deduped, audited), but the batch is yours to send — the browser bridge stays
read-only, so it never clicks. Comments, DMs, and posts always stay draft-only.
Loosen any of this deliberately in
[`second_me/permissions.py`](second_me/permissions.py).
