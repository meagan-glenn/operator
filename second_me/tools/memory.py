"""Operator's self-improvement loop: rules it learns about how Meagan works.

This is the agent's own version of "knowledge accumulation over sessions." When
Meagan corrects Operator or states a preference ("always do X", "stop doing Y",
"from now on, when Z…"), Operator calls remember_rule to write it down. Saved
rules are loaded into Operator's system prompt at the start of every future
session (see agent.py), so the same correction never has to be made twice —
mistakes trend down as rules trend up.

Rules live in data/learned_rules.json — a plain file Meagan owns and can edit or
delete by hand. These tools are the agent's "learning hands":

    remember_rule  → capture a new rule (call this whenever you're corrected)
    list_rules     → review what you've learned
    forget_rule    → drop a rule that's outdated or wrong
"""
from __future__ import annotations

from claude_agent_sdk import tool

from ..config import RULES_FILE, ensure_dirs, load_rules
from ._common import _err, _now, _ok, _short_id, save_json_store


def _save_rules(rules: list) -> None:
    ensure_dirs()
    save_json_store(RULES_FILE, rules)


@tool(
    "remember_rule",
    "Record a lasting rule about how Meagan wants you to work. Call this whenever she corrects you, "
    "states a preference, or says 'always/never/from now on…'. Saved rules load into your system prompt "
    "every future session, so you never need the same correction twice. Optionally give a 'trigger' — the "
    "situation the rule applies to (e.g. 'when drafting LinkedIn posts').",
    {"rule": str, "trigger": str},
)
async def remember_rule(args: dict) -> dict:
    rule_text = (args.get("rule") or "").strip()
    if not rule_text:
        return _err("Nothing to remember — pass the rule text.")
    rules = load_rules()
    # De-dupe: don't store the same rule twice.
    if any(r.get("rule", "").strip().lower() == rule_text.lower() for r in rules):
        return _ok(f"Already remembered: {rule_text}")
    entry = {
        "id": _short_id(),
        "rule": rule_text,
        "trigger": (args.get("trigger") or "").strip(),
        "created_at": _now(),
    }
    rules.append(entry)
    _save_rules(rules)
    return _ok(f"Got it — I'll remember this from now on (rule {entry['id']}): {rule_text}")


@tool(
    "list_rules",
    "List the rules you've learned about how Meagan wants you to work, newest last.",
    {},
)
async def list_rules(args: dict) -> dict:
    rules = load_rules()
    if not rules:
        return _ok("No learned rules yet. I'll add one whenever you correct me or state a preference.")
    lines = []
    for r in rules:
        when = f"  (when {r['trigger']})" if r.get("trigger") else ""
        lines.append(f"[{r['id']}] {r['rule']}{when}")
    return _ok(f"{len(rules)} learned rule(s):\n" + "\n".join(lines))


@tool(
    "forget_rule",
    "Remove a learned rule by id (use when a rule is outdated or wrong). Use list_rules to see ids.",
    {"rule_id": str},
)
async def forget_rule(args: dict) -> dict:
    rule_id = (args.get("rule_id") or "").strip()
    rules = load_rules()
    kept = [r for r in rules if r.get("id") != rule_id]
    if len(kept) == len(rules):
        return _err(f"No rule with id '{rule_id}'. Use list_rules to see ids.")
    _save_rules(kept)
    return _ok(f"Forgotten rule {rule_id}.")


# Self-improvement tools. The agent learns Meagan's preferences over time.
MEMORY_TOOLS = [remember_rule, list_rules, forget_rule]
