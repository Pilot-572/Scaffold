# ── Apply executor ──
# Additive only: creates what the plan says, skips exact matches, never touches
# an existing object. No rollback on failure — created items stay and the
# per-item ledger reports exactly what happened (re-running is safe because
# skips are idempotent).
import asyncio
import json
import logging

import discord

from shared import config
from shared.db import Job, SessionLocal, utcnow
from shared.diff import build_plan
from shared.schema import Structure

log = logging.getLogger("serverforge.apply")

PERMISSION_HINT = (
    "Fix: open Server Settings → Roles, make sure the bot's role has Manage Channels, "
    "Manage Roles and View Channels, and drag it ABOVE the roles it should manage."
)


def _snapshot(guild: discord.Guild) -> dict:
    return {
        "roles": [r.name for r in guild.roles],
        "categories": [c.name for c in guild.categories],
        "channels": [
            {"name": ch.name, "type": "voice" if isinstance(ch, discord.VoiceChannel) else "text",
             "parent": ch.category.name if ch.category else None}
            for ch in list(guild.text_channels) + list(guild.voice_channels)
        ],
    }


def _fail(session, job: Job, message: str, ledger: list | None = None) -> None:
    job.status = "failed"
    job.error = message
    job.ledger_json = json.dumps(ledger or [])
    job.finished_at = utcnow()
    session.commit()


async def run_job(bot: discord.Client, job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        structure = Structure.model_validate_json(job.structure_json)
        guild = bot.get_guild(int(job.guild_id))
        if guild is None:
            _fail(session, job, "The bot is no longer in this server. Re-invite it and try again.")
            return

        perms = guild.me.guild_permissions
        missing = [n for n in ("manage_channels", "manage_roles", "view_channel")
                   if not getattr(perms, n)]
        if missing:
            _fail(session, job,
                  f"The bot is missing: {', '.join(m.replace('_', ' ') for m in missing)}. {PERMISSION_HINT}")
            return

        plan = build_plan(structure, _snapshot(guild))
        ledger: list[dict] = []
        reason = f"{config.BRAND} apply #{job.id} (user {job.user_id})"

        def flush():
            job.ledger_json = json.dumps(ledger)
            session.commit()

        async def create(kind: str, name: str, coro):
            try:
                obj = await coro
                ledger.append({"kind": kind, "name": name, "action": "created"})
                return obj
            except discord.Forbidden:
                ledger.append({"kind": kind, "name": name, "action": "failed",
                               "detail": f"Bot lacks permission. {PERMISSION_HINT}"})
            except discord.HTTPException as e:
                ledger.append({"kind": kind, "name": name, "action": "failed",
                               "detail": f"Discord refused it: {e.text or e.status}"})
            flush()
            return None

        role_map = {r.name: r for r in guild.roles}
        for entry in plan["roles"]:
            r = entry["item"]
            if entry["action"] == "skip":
                ledger.append({"kind": "role", "name": r["name"], "action": "skipped"})
                continue
            role = await create("role", r["name"], guild.create_role(
                name=r["name"],
                colour=discord.Colour(int(r["color"].lstrip("#"), 16)),
                hoist=r["hoist"], mentionable=r["mentionable"],
                permissions=discord.Permissions(**{p: True for p in r["permissions"]}),
                reason=reason))
            if role:
                role_map[role.name] = role
            flush()
            await asyncio.sleep(0.5)  # gentle on top of discord.py's own rate limiting

        cat_map = {c.name: c for c in guild.categories}
        for entry in plan["categories"]:
            c = entry["item"]
            if entry["action"] == "skip":
                ledger.append({"kind": "category", "name": c["name"], "action": "skipped"})
                continue
            cat = await create("category", c["name"], guild.create_category(c["name"], reason=reason))
            if cat:
                cat_map[cat.name] = cat
            flush()
            await asyncio.sleep(0.5)

        for entry in plan["channels"]:
            ch = entry["item"]
            if entry["action"] == "skip":
                ledger.append({"kind": "channel", "name": ch["name"], "action": "skipped"})
                continue

            overwrites: dict = {}
            note = ""
            if ch["mode"] == "announcement":
                overwrites[guild.default_role] = discord.PermissionOverwrite(
                    send_messages=False, send_messages_in_threads=False, create_public_threads=False)
            elif ch["mode"] == "role_gated":
                overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                unresolved = []
                for role_name in ch["gate_roles"]:
                    role = role_map.get(role_name)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(view_channel=True)
                    else:
                        unresolved.append(role_name)
                if unresolved:
                    note = f" (gate role(s) not found: {', '.join(unresolved)})"

            category = cat_map.get(ch["category"]) if ch["category"] else None
            if ch["type"] == "voice":
                coro = guild.create_voice_channel(ch["name"], category=category,
                                                  overwrites=overwrites, reason=reason)
            else:
                coro = guild.create_text_channel(ch["name"], category=category, topic=ch["topic"],
                                                 overwrites=overwrites, reason=reason)
            obj = await create("channel", ch["name"], coro)
            if obj and note:
                ledger[-1]["detail"] = note.strip()
            flush()
            await asyncio.sleep(0.5)

        failed = sum(1 for e in ledger if e["action"] == "failed")
        created = sum(1 for e in ledger if e["action"] == "created")
        if failed == 0:
            job.status = "done"
        elif created > 0:
            job.status = "partial"
            job.error = f"{created} item(s) created, {failed} failed — details below. Created items were kept; re-running skips them."
        else:
            job.status = "failed"
            job.error = f"All {failed} item(s) failed. {PERMISSION_HINT}"
        job.finished_at = utcnow()
        flush()
        log.info("job %s finished: %s (%d created, %d failed)", job.id, job.status, created, failed)
    except Exception:
        log.exception("job %s crashed", job_id)
        job = session.get(Job, job_id)
        if job and job.status == "running":
            _fail(session, job, "Internal error while applying. Nothing was deleted; check the ledger and retry.")
    finally:
        session.close()
