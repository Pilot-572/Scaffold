# ── Discord REST (web-process side) ──
# User-token calls for OAuth + guild listing; bot-token calls for live guild
# snapshots so preview never needs the gateway.
import requests

from shared import config

API = "https://discord.com/api/v10"
MANAGE_GUILD = 0x20


class AuthExpired(Exception):
    pass


class DiscordAPIError(Exception):
    pass


def _check(resp: requests.Response) -> dict | list:
    if resp.status_code == 401:
        raise AuthExpired()
    if resp.status_code == 429:
        raise DiscordAPIError("Discord is rate limiting us — try again in a moment.")
    if not resp.ok:
        # Never include tokens/headers in the raised text.
        raise DiscordAPIError(f"Discord API error {resp.status_code}")
    return resp.json()


# ── OAuth ──

def authorize_url(state: str) -> str:
    return (f"{API}/oauth2/authorize?client_id={config.DISCORD_CLIENT_ID}"
            f"&response_type=code&scope=identify%20guilds"
            f"&redirect_uri={requests.utils.quote(config.OAUTH_REDIRECT_URI, safe='')}"
            f"&state={state}")


def exchange_code(code: str) -> dict:
    resp = requests.post(f"{API}/oauth2/token", data={
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.OAUTH_REDIRECT_URI,
    }, timeout=15)
    return _check(resp)


def fetch_user(access_token: str) -> dict:
    resp = requests.get(f"{API}/users/@me",
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    return _check(resp)


def fetch_user_guilds(access_token: str) -> list[dict]:
    resp = requests.get(f"{API}/users/@me/guilds",
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    return _check(resp)


def manageable_guilds(access_token: str) -> list[dict]:
    out = []
    for g in fetch_user_guilds(access_token):
        if g.get("owner") or int(g.get("permissions", 0)) & MANAGE_GUILD:
            out.append(g)
    return out


# ── Bot-token snapshot for preview ──

def _bot_get(path: str):
    resp = requests.get(f"{API}{path}",
                        headers={"Authorization": f"Bot {config.DISCORD_TOKEN}"}, timeout=15)
    return _check(resp)


def guild_snapshot(guild_id: str) -> dict:
    """Live names for the diff: roles, categories, channels with parent names."""
    roles = _bot_get(f"/guilds/{guild_id}/roles")
    channels = _bot_get(f"/guilds/{guild_id}/channels")
    cats = {c["id"]: c["name"] for c in channels if c["type"] == 4}
    return {
        "roles": [r["name"] for r in roles],
        "categories": list(cats.values()),
        "channels": [
            {"name": c["name"], "type": "voice" if c["type"] == 2 else "text",
             "parent": cats.get(c.get("parent_id"))}
            for c in channels if c["type"] in (0, 2, 5)  # text, voice, announcement
        ],
    }


def invite_url(guild_id: str | None = None) -> str:
    url = (f"https://discord.com/oauth2/authorize?client_id={config.DISCORD_CLIENT_ID}"
           f"&scope=bot%20applications.commands&permissions={config.BOT_PERMISSIONS}")
    if guild_id:
        url += f"&guild_id={guild_id}&disable_guild_select=true"
    return url
