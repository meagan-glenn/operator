"""Safe-by-default permissions for Operator.

Operator can use its own CRM tools plus a few read-only abilities (web search,
reading files you point it at). Anything that could change your machine — running
shell commands, writing or editing arbitrary files — is denied. To loosen this,
add tool names to ALLOWED. This keeps your first agent useful but contained.
"""
from __future__ import annotations

from typing import Any

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

# Built-in Claude tools Operator is allowed to use freely.
ALLOWED = {
    "WebSearch",
    "WebFetch",
    "Read",
    "Glob",
    "Grep",
    "TodoWrite",
    "NotebookRead",
}

# Read-only browser abilities Operator may use WHEN a browser bridge is connected —
# so it can look at Meagan's LinkedIn (her feed, a profile, a post) and draft from
# real context. Matched by the tool-name suffix (after mcp__<server>__), since the
# server prefix's casing varies. Two vocabularies are covered: the Claude-in-Chrome
# extension's names AND the standalone Playwright-MCP server's "browser_*" names
# (the bridge we actually wire — see agent.py:_external_mcp_servers / .env.example).
#
# NOTE the deliberate omissions: anything that ACTS on a page — click, type, form
# fill, key presses, hover, drag/drop, file upload, dialog handling, evaluate/run-
# code (arbitrary JS), close/resize/tabs, computer/javascript_tool — is NOT here and
# stays denied by the catch-all. With no input tool allowed, the bridge CANNOT
# connect, comment, DM, post, or like: read-only is enforced here, not just in the
# prompt. Meagan keeps her hand on the button (R11) — that includes connection
# requests: OPERATOR_LINKEDIN_CONNECT only enables the vet/cap/log governor in
# tools/linkedin.py, never a browser click path. The chrome gate is read-only
# regardless of that flag. Navigation (moving to a URL, going back) is reading;
# interaction is not.
CHROME_READ_SUFFIXES = {
    # Claude-in-Chrome extension (read-only abilities)
    "navigate",
    "read_page",
    "get_page_text",
    "find",
    "read_console_messages",
    "read_network_requests",
    "list_connected_browsers",
    "select_browser",
    "switch_browser",
    "tabs_context_mcp",
    # Playwright-MCP server (read-only abilities; "browser_*"). Verified against the
    # live server's tools/list. Everything that submits input is intentionally absent.
    "browser_navigate",
    "browser_navigate_back",
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_console_messages",
    "browser_network_requests",
    "browser_network_request",
    "browser_wait_for",
}


def _is_chrome_tool(tool_name: str) -> bool:
    n = tool_name.lower()
    return n.startswith("mcp__") and "chrome" in n


async def can_use_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    # Operator's own tools (the CRM/signals/drafts server) are always allowed.
    if tool_name.startswith("mcp__operator__"):
        return PermissionResultAllow()
    if tool_name in ALLOWED:
        return PermissionResultAllow()
    # Browser bridge: allow READ-only abilities. Everything that acts on a page —
    # click, type, submit — stays denied, regardless of OPERATOR_LINKEDIN_CONNECT
    # (that flag only enables the vet/cap/log governor in tools/linkedin.py).
    if _is_chrome_tool(tool_name):
        suffix = tool_name.split("__")[-1].lower()
        if suffix in CHROME_READ_SUFFIXES:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=(
                "That Chrome action is off-limits. Operator may only READ LinkedIn pages — "
                "never connect, comment, DM, post, or like. Vet connection requests with "
                "linkedin_connect_check and draft everything else; Meagan does all sending."
            )
        )
    return PermissionResultDeny(
        message=(
            f"'{tool_name}' is off-limits for now. Operator is scoped to its own "
            "CRM/signal/draft tools plus web search and reading files. "
            "Do the task another way, or tell Meagan if you genuinely need this."
        )
    )
