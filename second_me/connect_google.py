"""Google Calendar connector (run once per account).

Run after completing the Cloud Console steps in SETUP_GOOGLE.md:

    python -m second_me.connect_google

Opens your browser to approve access for ONE Google account, stores its token,
then lists every connected account and its calendars. Run it again and sign in
with a different account to ADD that account — existing connections are kept.
"""
from __future__ import annotations

from .google_auth import (
    connect_interactive,
    get_service,
    has_credentials,
    list_accounts,
)


def _print_account(email: str) -> None:
    service = get_service(email)
    if service is None:
        print(f"  {email}: (could not build calendar client)")
        return
    cals = service.calendarList().list().execute().get("items", [])
    print(f"  {email} — {len(cals)} calendar(s):")
    for c in cals:
        flags = []
        if c.get("primary"):
            flags.append("PRIMARY")
        if c.get("accessRole"):
            flags.append(c["accessRole"])
        tag = f"  [{', '.join(flags)}]" if flags else ""
        print(f"    • {c.get('summary', '(no name)')}{tag}")
        print(f"        id: {c['id']}")


def main() -> None:
    if not has_credentials():
        print(
            "✗ No credentials.json found in the project root.\n"
            "  Follow SETUP_GOOGLE.md to download your OAuth client secrets first."
        )
        return

    print("Opening your browser to approve Google Calendar access…")
    try:
        email = connect_interactive()
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    print(f"✓ Connected {email}. Token saved.\n")

    accounts = list_accounts()
    print(f"Connected account(s) ({len(accounts)}):")
    for acct in accounts:
        _print_account(acct)

    print(
        "\nAll set. The agent checks ALL of these for conflicts. To add another Google "
        "account, run this command again and sign in with that account. To choose where "
        'calls are booked, set "default_booking_account" in second_me/availability.json.'
    )


if __name__ == "__main__":
    main()
