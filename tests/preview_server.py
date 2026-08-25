# ── Dev preview server: real UI, mocked Discord, auto-login ──
# Run: python -m tests.preview_server  (http://127.0.0.1:5099/dev-login)
# Never deployed; exists so the dashboard can be eyeballed without credentials.
import os
import pathlib

os.environ.update(
    SECRET_KEY="preview-key",
    DATABASE_URL="sqlite:///preview.db",
    DISCORD_CLIENT_ID="123",
    OAUTH_REDIRECT_URI="http://localhost:5099/callback",
)
for f in (pathlib.Path("preview.db"), *pathlib.Path(".").glob("preview.db-*")):
    f.unlink(missing_ok=True)

from shared import discord_api  # noqa: E402

GUILDS = [
    {"id": "42", "name": "Chartreuse Command", "icon": None, "owner": True, "permissions": "32"},
    {"id": "43", "name": "Milsim EU", "icon": None, "owner": True, "permissions": "32"},
]
discord_api.manageable_guilds = lambda token: GUILDS
discord_api.guild_snapshot = lambda gid: {
    "roles": ["Member"], "categories": ["Community"],
    "channels": [{"name": "general", "type": "text", "parent": "Community"}]}

import secrets  # noqa: E402
from flask import redirect, session  # noqa: E402
from web.app import app  # noqa: E402
from shared.db import Guild, License, SessionLocal  # noqa: E402

with SessionLocal() as db:
    db.merge(Guild(guild_id="42", name="Chartreuse Command", bot_present=True))
    db.merge(Guild(guild_id="43", name="Milsim EU", bot_present=False))
    db.merge(License(key="SF-TEST-TEST-TEST"))
    db.commit()


@app.get("/dev-login")
def dev_login():
    session.update(user_id="u1", username="Fabian", avatar=None,
                   access_token="fake", _csrf=secrets.token_urlsafe(16))
    return redirect("/servers")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5099)
