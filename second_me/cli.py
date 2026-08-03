"""Interactive REPL for the Operator agent.

Run with:  python -m second_me
Type your message, press enter. Operator remembers the whole conversation for
the session. Type 'exit' or Ctrl-D to quit.
"""
from __future__ import annotations

import asyncio
import os
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from .agent import build_options
from .config import (
    MODEL,
    availability_source,
    linkedin_connect_enabled,
    linkedin_daily_cap,
    load_availability,
)

# Tiny ANSI helpers so the conversation is readable in a terminal.
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RESET = "\033[0m"

BANNER = f"""{BOLD}Operator{RESET} — Meagan's second me
{DIM}model: {MODEL} · tools: prospect discovery, BDR outreach, drafts, calendar, learned rules, web search
type 'exit' or Ctrl-D to quit{RESET}
"""


def _startup_status() -> str:
    """One line each for the bits that are silently on/off, so Meagan can see state.

    'configured' (not 'connected') is deliberate: a set URL means the bridge is
    wired, but we don't probe the server here — don't overstate what we know.
    """
    url = os.environ.get("OPERATOR_CHROME_MCP_URL", "").strip()
    if url:
        chrome = f"{GREEN}configured (read-only){RESET} {DIM}→ {url}{RESET}"
    else:
        chrome = f"{DIM}not configured — paste LinkedIn content in{RESET}"
    if linkedin_connect_enabled():
        connect = f"{GREEN}ON{RESET} {DIM}(cap {linkedin_daily_cap()}/day){RESET}"
    else:
        connect = f"{DIM}OFF{RESET}"
    # Which schedule is live matters: the packaged example would propose wrong
    # hours and book to the wrong account, so say it out loud when it's not the
    # personal copy.
    load_availability()
    src = availability_source()
    if src.startswith("personal"):
        avail = f"{GREEN}{src}{RESET}"
    else:
        avail = f"{src} {DIM}— copy your schedule to data/availability.json{RESET}"
    return (
        f"{DIM}browser bridge:{RESET} {chrome}\n"
        f"{DIM}linkedin connect-vetting:{RESET} {connect}\n"
        f"{DIM}schedule:{RESET} {avail}"
    )


def _print_tool_use(block: ToolUseBlock) -> None:
    name = block.name.replace("mcp__operator__", "")
    # Show a compact hint of what the tool is doing.
    hint = ""
    if isinstance(block.input, dict):
        for key in ("name", "company", "org", "summary", "title", "status", "query", "lead_id", "target_id", "rule"):
            if block.input.get(key):
                hint = f" {key}={block.input[key]!r}"
                break
    print(f"{DIM}   ↳ using {name}{hint}{RESET}")


async def _converse(client: ClaudeSDKClient, message: str) -> None:
    await client.query(message)
    printed_label = False
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    if not printed_label:
                        print(f"{CYAN}operator ›{RESET} ", end="")
                        printed_label = True
                    print(block.text, end="", flush=True)
                elif isinstance(block, ToolUseBlock):
                    if printed_label:
                        print()
                        printed_label = False
                    _print_tool_use(block)
        elif isinstance(msg, ResultMessage):
            if printed_label:
                print()
            cost = getattr(msg, "total_cost_usd", None)
            if cost:
                print(f"{DIM}   (turn cost ≈ ${cost:.4f}){RESET}")


async def main() -> None:
    print(BANNER)
    print(_startup_status())
    print()
    options = build_options()
    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                user_input = await asyncio.to_thread(input, f"{GREEN}you ›{RESET} ")
            except (EOFError, KeyboardInterrupt):
                print("\nbye 👋")
                return
            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", ":q"}:
                print("bye 👋")
                return
            try:
                await _converse(client, user_input)
            except Exception as e:  # keep the session alive on a transient error
                print(f"\n{DIM}[error: {e}]{RESET}", file=sys.stderr)
            print()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
