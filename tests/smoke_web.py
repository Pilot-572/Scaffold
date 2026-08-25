# ── Web smoke: renders every page/partial with mocked Discord, no network ──
# Run: python -m tests.smoke_web
import os
import pathlib
import sys

os.environ.update(
    SECRET_KEY="smoke-test-key",
    DATABASE_URL="sqlite:///smoke_test.db",
    DISCORD_CLIENT_ID="123",
    OAUTH_REDIRECT_URI="http://localhost:5000/callback",
)
db_file = pathlib.Path("smoke_test.db")
for f in (db_file, *pathlib.Path(".").glob("smoke_test.db-*")):
    f.unlink(missing_ok=True)

from shared import discord_api  # noqa: E402

FAKE_GUILD = {"id": "42", "name": "Test Guild", "icon": None, "owner": True, "permissions": "32"}
discord_api.manageable_guilds = lambda token: [FAKE_GUILD]
discord_api.guild_snapshot = lambda gid: {
    "roles": ["Member"], "categories": [],
    "channels": [{"name": "general", "type": "text", "parent": None}]}

from web.app import app  # noqa: E402
from shared.db import Guild, Job, License, SessionLocal  # noqa: E402

import bot.main  # noqa: E402,F401  (import = syntax/wiring check for the bot too)

with SessionLocal() as db:
    db.merge(Guild(guild_id="42", name="Test Guild", bot_present=True))
    db.merge(License(key="SF-TEST-TEST-TEST"))
    db.commit()

client = app.test_client()
with client.session_transaction() as s:
    s.update(user_id="u1", username="Fabian", avatar=None,
             access_token="fake", _csrf="tok")

def get(path, expect=200):
    r = client.get(path)
    assert r.status_code == expect, f"GET {path} -> {r.status_code}"
    return r.data.decode()

def post(path, data, expect=200):
    r = client.post(path, data={"_csrf": "tok", **data}, follow_redirects=True)
    assert r.status_code == expect, f"POST {path} -> {r.status_code}"
    return r.data.decode()

get("/servers")
html = get("/guild/42")
assert "Start from a preset" in html and "Describe your community" in html

# preset preview -> draft + diff partial
html = post("/guild/42/preview", {"preset": "gaming_clan"})
assert "to create" in html and "Apply to server" in html
assert "skip" in html  # Member role exists in the fake snapshot

# CSRF is actually enforced
r = client.post("/guild/42/preview", data={"preset": "gaming_clan"})
assert r.status_code == 400, "CSRF bypass!"

# AI locked for free tier
html = post("/guild/42/preview", {"description": "a milsim clan"})
assert "premium feature" in html

# apply -> job queued -> status partial
import re
draft_id = re.search(r'name="draft_id" value="(\d+)"',
                     post("/guild/42/preview", {"preset": "small_team"})).group(1)
html = post("/guild/42/apply", {"draft_id": draft_id})
assert "Waiting for the bot" in html
with SessionLocal() as db:
    job = db.query(Job).first()
    assert job and job.status == "queued"
    job_id = job.id
get(f"/guild/42/jobs/{job_id}")

# account + redeem
html = post("/account/redeem", {"key": "sf-test-test-test"})
assert "Premium unlocked" in html
assert "Premium" in get("/account")

# premium user now sees the AI path unlocked (limits recomputed)
assert "generations left today" in get("/guild/42")

get("/guild/999", expect=403)  # not one of the user's guilds
print("web smoke passed")
