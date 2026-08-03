# Connecting Google Calendar

This is a **one-time setup** (~10 minutes). After it, your agent checks all your
calendars for conflicts and books calls for you automatically. You only do this
once — the agent remembers afterward.

You'll create a free "OAuth client" in Google Cloud — think of it as an ID badge
that lets *your own* code talk to *your own* calendar. Nothing is published; no
one else can use it.

---

## Step 1 — Create a Google Cloud project

1. Go to **https://console.cloud.google.com/projectcreate**
2. Name it something like `second-me` and click **Create**.
3. Make sure that project is selected (top bar) before continuing.

## Step 2 — Turn on the Calendar API

1. Go to **https://console.cloud.google.com/apis/library/calendar-json.googleapis.com**
2. Click **Enable**.

## Step 3 — Set up the consent screen

1. Go to **https://console.cloud.google.com/apis/credentials/consent**
2. Choose **External**, click **Create**.
3. Fill in:
   - **App name**: `second-me`
   - **User support email**: your email
   - **Developer contact**: your email
4. Click **Save and Continue** through the next screens (you can skip Scopes).
5. On **Test users**, click **+ Add Users**, add **your own Google email**, save.
   *(This keeps the app in "testing" mode — perfect for personal use. You don't
   need to publish or verify it.)*

## Step 4 — Create the credentials file

1. Go to **https://console.cloud.google.com/apis/credentials**
2. Click **+ Create Credentials → OAuth client ID**.
3. **Application type: Desktop app**. Name it `second-me`. Click **Create**.
4. In the popup, click **Download JSON**.
5. Rename the downloaded file to exactly **`credentials.json`** and move it into
   your project folder:
   ```
   ~/Desktop/operator/credentials.json
   ```
   *(This file is already gitignored — it will never be committed.)*

## Step 5 — Connect

In your terminal:

```bash
cd ~/Desktop/operator
source .venv/bin/activate
python -m second_me.connect_google
```

Your browser opens → pick your Google account → you'll see a "Google hasn't
verified this app" notice (expected, because it's your own test app) → click
**Advanced → Go to second-me (unsafe) → Continue → Allow**.

The script then prints **your calendars** to confirm everything works. Done. ✅

> **Note on the console UI:** Google now calls the consent screen the
> **"Google Auth Platform"** wizard (App info → Audience → Contact → Finish),
> and the OAuth client secret can only be downloaded at creation time. The steps
> above still map onto it 1:1.

---

## Connecting more than one Google account

The agent can hold **several Google accounts at once** (e.g. a personal gmail and
a work domain). To add another, just **run `python -m second_me.connect_google`
again and sign in with that account** — existing connections are kept. Each
account stores its own token under `data/google_tokens/<email>.json`.

- **Conflict-checking spans every calendar of every connected account**, so the
  agent never proposes a time you're busy on *any* of them.
- **Booking goes to one account** — set `google.default_booking_account` (the
  account's email) in [`second_me/availability.json`](second_me/availability.json).
  Leave it empty to use the first connected account.

## After connecting

- Just run `python -m second_me` and schedule normally. The agent now:
  - **Checks all your calendars across all accounts** before proposing call times.
  - **Books directly onto Google** (the `default_booking_account`'s primary
    calendar by default) and emails the attendee.
- To book into a different calendar by default, run `python -m second_me.connect_google`
  to see calendar IDs, then set `google.default_booking_account` and
  `google.default_booking_calendar` in
  [`second_me/availability.json`](second_me/availability.json).
- To check status anytime, ask the agent: *"Is my Google Calendar connected?"*

## Troubleshooting

- **"No credentials.json found"** — the file isn't in `~/Desktop/operator/`, or
  it's named something else. It must be exactly `credentials.json`.
- **"access_denied"** — add your Google email under **Test users** (Step 3.5).
- **Token expired / weird auth errors** — delete `data/google_token.json` and run
  `python -m second_me.connect_google` again.
