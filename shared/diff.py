# ── Diff engine ──
# Plans an apply against a live-guild snapshot. Additive only: every item is
# either "create" or "skip" — modify/delete do not exist here on purpose.
#
# Match rules (decided with Fabian 2026-08-25):
#   roles + categories: exact name match, guild-wide
#   channels: exact name match WITHIN the same category (Discord allows
#             duplicate channel names across categories)
from shared.schema import Structure

Snapshot = dict  # {"roles": [names], "categories": [names], "channels": [{"name","type","parent"}]}


def build_plan(structure: Structure, snap: Snapshot) -> dict:
    live_roles = set(snap.get("roles", []))
    live_cats = set(snap.get("categories", []))
    live_chans = {(c["name"], c.get("parent")) for c in snap.get("channels", [])}

    plan = {"roles": [], "categories": [], "channels": []}
    for r in structure.roles:
        plan["roles"].append({"item": r.model_dump(), "action": "skip" if r.name in live_roles else "create"})
    for c in structure.categories:
        plan["categories"].append({"item": c.model_dump(), "action": "skip" if c.name in live_cats else "create"})
    for ch in structure.channels:
        action = "skip" if (ch.name, ch.category) in live_chans else "create"
        plan["channels"].append({"item": ch.model_dump(), "action": action})

    plan["counts"] = {
        "create": sum(1 for kind in ("roles", "categories", "channels") for e in plan[kind] if e["action"] == "create"),
        "skip": sum(1 for kind in ("roles", "categories", "channels") for e in plan[kind] if e["action"] == "skip"),
    }
    return plan
