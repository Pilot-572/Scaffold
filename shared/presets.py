# ── Presets ──
# JSON files in /templates, same schema as AI output.
import json
from pathlib import Path

from shared.schema import Structure

PRESET_DIR = Path(__file__).resolve().parent.parent / "templates"

# Keyword scoring for the AI-failure fallback ("closest preset").
_KEYWORDS = {
    "gaming_clan": {"game", "gaming", "clan", "milsim", "squad", "guild", "fps", "raid",
                    "military", "faction", "esports", "pvp", "ops", "mission"},
    "study_group": {"study", "school", "class", "exam", "homework", "university", "course",
                    "learning", "students", "tutor", "college"},
    "creator_community": {"creator", "youtube", "twitch", "stream", "content", "fans",
                          "subscribers", "video", "art", "music", "podcast"},
    "small_team": {"team", "work", "startup", "project", "company", "business", "dev",
                   "colleagues", "office"},
}


def list_presets() -> list[dict]:
    out = []
    for f in sorted(PRESET_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": f.stem, "name": data.get("name", f.stem),
                    "description": data.get("description", "")})
    return out


def load_preset(preset_id: str) -> Structure:
    path = PRESET_DIR / f"{preset_id}.json"
    if not path.is_file() or path.parent != PRESET_DIR:
        raise KeyError(preset_id)
    return Structure.model_validate_json(path.read_text(encoding="utf-8"))


def closest_preset(description: str) -> str:
    words = set(description.lower().split())
    scores = {pid: len(words & kw) for pid, kw in _KEYWORDS.items()}
    # ponytail: bag-of-words scoring; upgrade to embeddings if fallbacks ever feel wrong
    return max(scores, key=lambda p: scores[p]) if any(scores.values()) else "small_team"
