# ── ServerForge config ──
# All values from .env. Nothing here logs or prints secrets.
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BRAND = os.getenv("BRAND_NAME", "ServerForge")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:5000/callback")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")

SECRET_KEY = os.getenv("SECRET_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///serverforge.db")
PORT = int(os.getenv("PORT", "5000"))

# Dashboard origin, derived from the redirect URI (used by /setup and the bot).
BASE_URL = "{0.scheme}://{0.netloc}".format(urlparse(OAUTH_REDIRECT_URI))

# ── Limits ──
CAP_CHANNELS = 25
CAP_ROLES = 15
CAP_CATEGORIES = 8

FREE_APPLIES_PER_DAY = 2
PREMIUM_APPLIES_PER_DAY = 10
PREMIUM_AI_PER_DAY = 20
APPLIES_PER_HOUR = 3  # burst cooldown, every tier

# Bot invite: Manage Channels (0x10) + Manage Roles (0x10000000) + View Channels (0x400)
BOT_PERMISSIONS = 0x10 | 0x10000000 | 0x400


def require(*names: str) -> None:
    """Fail fast at process start when a required env var is missing."""
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)} (see .env.example)")
