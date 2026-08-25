# ── Core self-check: schema sanitizing, caps, diff engine, presets ──
# Run: python -m tests.test_core   (plain asserts, no framework)
import pydantic

from shared.diff import build_plan
from shared.presets import closest_preset, list_presets, load_preset
from shared.schema import Channel, Role, Structure, channel_slug, clean_text


def expect_invalid(payload, why):
    try:
        Structure.model_validate(payload)
    except pydantic.ValidationError:
        return
    raise AssertionError(f"should have been invalid: {why}")


# ── sanitizing ──
assert channel_slug("General  Chat!") == "general-chat"
assert channel_slug("__weird__NAME__") == "weird-name"
assert clean_text("join https://discord.gg/abc now", 100) == "join now"
assert clean_text("hey @everyone and @here", 100) == "hey and"
assert clean_text("a" * 3000, 1024) == "a" * 1024

# forbidden/unknown role perms are dropped, allowlisted ones kept
r = Role(name="X", permissions=["administrator", "manage_guild", "send_messages", "bogus"])
assert r.permissions == ["send_messages"]
assert Role(name="X", color="not-a-color").color == "#99aab5"

# voice channels lose topics and can't be announcements
v = Channel(name="War Room", type="voice", topic="secret", mode="announcement")
assert v.topic is None and v.mode == "public" and v.name == "War Room"

# ── validation rules ──
expect_invalid({"channels": [{"name": "a", "category": "Ghost"}], "categories": []},
               "unknown category")
expect_invalid({"channels": [{"name": "ops", "mode": "role_gated", "gate_roles": []}]},
               "role_gated without gate_roles")
expect_invalid({"roles": [{"name": "A"}] * 16}, "role cap")
expect_invalid({"channels": [{"name": "same", "category": None}] * 2}, "duplicate channels")

# ── diff: channels match per-category, roles/categories globally ──
s = Structure.model_validate({
    "categories": [{"name": "Ops"}, {"name": "Social"}],
    "roles": [{"name": "Member"}],
    "channels": [
        {"name": "general", "category": "Ops"},
        {"name": "general", "category": "Social"},
    ],
})
snap = {"roles": ["Member"], "categories": ["Ops"],
        "channels": [{"name": "general", "type": "text", "parent": "Ops"}]}
plan = build_plan(s, snap)
assert plan["roles"][0]["action"] == "skip"
assert [c["action"] for c in plan["categories"]] == ["skip", "create"]
by_cat = {c["item"]["category"]: c["action"] for c in plan["channels"]}
assert by_cat == {"Ops": "skip", "Social": "create"}  # same name, different category
assert plan["counts"] == {"create": 2, "skip": 3}

# ── presets load, validate, and fall back sensibly ──
assert {p["id"] for p in list_presets()} == {"gaming_clan", "study_group",
                                             "creator_community", "small_team"}
for p in list_presets():
    load_preset(p["id"])  # raises if any preset breaks the schema
assert closest_preset("a milsim squad playing arma") == "gaming_clan"
assert closest_preset("exam revision for university") == "study_group"
assert closest_preset("complete gibberish zzz") == "small_team"

print("all core checks passed")
