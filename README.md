# Scaffold

A Discord bot + web dashboard that designs server structures and applies them.
Describe your community in plain words (or pick a preset), preview the layout as
a diff against your live server, then let the bot build it. **Additive only:
nothing that already exists is ever modified or deleted.**

Rename the product by setting `BRAND_NAME` in `.env` — it flows through the
dashboard and the bot.

## Layout

```
bot/        gateway worker: job consumer, apply executor, /setup + /status
web/        Flask dashboard (Jinja + Tailwind + htmx)
shared/     config, SQLAlchemy models, structure schema, diff engine, LLM client
templates/  the 4 preset structures (same JSON schema as AI output)
manage.py   license key CLI
```

Two processes, one SQLite database (WAL). Swap `DATABASE_URL` to Postgres when
you outgrow it — nothing else changes.

## Discord application setup

1. <https://discord.com/developers/applications> → **New Application**.
2. **Bot** tab: create the bot, copy the token → `DISCORD_TOKEN`.
   No privileged intents are needed.
3. **OAuth2** tab: copy Client ID → `DISCORD_CLIENT_ID` and Client Secret →
   `DISCORD_CLIENT_SECRET`. Under **Redirects**, add your public callback,
   e.g. `https://forge.example.com/callback`, and put the exact same value in
   `OAUTH_REDIRECT_URI`.
4. The dashboard builds the bot invite link itself, requesting only
   **Manage Channels, Manage Roles, View Channels** (never Administrator).

## Running

```
python -m venv .venv && .venv\Scripts\activate    # or source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                             # then fill it in
python -m web.app        # dashboard on 127.0.0.1:5000
python -m bot.main       # bot worker, in a second terminal
```

Order doesn't matter; they meet in the database. Sanity check without any
credentials: `python -m tests.test_core`.

## Reverse proxy (Nginx Proxy Manager + Cloudflare Tunnel)

- Point the tunnel/proxy host at the web process (`127.0.0.1:5000`).
  The bot process needs **no** inbound ports — it only dials out to Discord.
- The OAuth callback must be the public HTTPS domain, and it must match the
  portal redirect **exactly** (scheme, host, path).
- Session cookies are set `Secure` automatically when `OAUTH_REDIRECT_URI`
  is https. NPM's default `X-Forwarded-*` headers are fine; no Flask
  proxy-fix needed since the app never builds absolute URLs from the request.
- Run one web worker. The 60s guild-list cache is in-process; going
  multi-worker means moving it to the DB first.

## LLM endpoint

Any OpenAI-compatible `/chat/completions` works: OpenRouter, Groq, whatever.
Set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. On invalid output the app
retries once with the validation error fed back, then falls back to the
closest preset with a visible notice. Heads-up if you pick Groq: they retire
model IDs without warning — when generation suddenly breaks, list their
`/models` first.

## Licensing

No payments in v1 — keys are issued by hand and redeemed on the Account page,
tied to the redeemer's Discord user id (premium follows the user across all
their servers).

```
python manage.py gen 5        # print 5 fresh keys
python manage.py list
python manage.py revoke SF-XXXX-XXXX-XXXX
```

| | Free | Premium |
|---|---|---|
| Presets | yes | yes |
| AI generation | 2/day | 20/day |
| Applies | 2/day | 10/day |
| Burst | 3/hour | 3/hour |

## Safety model

- Applies are **create-or-skip only**, idempotent by exact name (channels match
  per-category, roles and categories guild-wide). Re-running is always safe.
- Partial failures keep what was created and show a per-item ledger; there is
  no rollback because there is nothing destructive to roll back.
- Generated roles carry only allowlisted permissions (view/send/connect-class);
  management, moderation and mention-everyone bits are stripped no matter what
  the LLM says. Names and topics are sanitized; invite links and mass mentions
  are removed.
- The user's Manage Server permission is re-verified against Discord,
  uncached, on every apply. All POSTs are CSRF-protected. The bot token and
  client secret never reach the client or the logs.
