# ── Scaffold bot worker ──
# Gateway presence + job consumer. The dashboard is the main surface; slash
# commands are deliberately thin.
import asyncio
import json
import logging

import discord
from discord import app_commands

from bot.apply import run_job
from shared import config
from shared.db import Guild, Job, SessionLocal, init_db, utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("scaffold.bot")

intents = discord.Intents.default()  # guilds only; no privileged intents needed


class Forge(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        init_db()
        await self.tree.sync()
        asyncio.create_task(self._consume_jobs())

    async def on_ready(self):
        log.info("logged in as %s (%d guilds)", self.user, len(self.guilds))
        self._sync_guilds()

    async def on_guild_join(self, guild):
        self._upsert_guild(guild, present=True)
        log.info("joined guild %s", guild.id)

    async def on_guild_remove(self, guild):
        self._upsert_guild(guild, present=False)
        log.info("left guild %s", guild.id)

    # ── guilds table = the dashboard's "is the bot here?" source ──

    def _upsert_guild(self, guild, present: bool):
        with SessionLocal() as s:
            row = s.get(Guild, str(guild.id)) or Guild(guild_id=str(guild.id), name=guild.name)
            row.name = guild.name
            row.icon = guild.icon.key if guild.icon else None
            row.bot_present = present
            s.merge(row)
            s.commit()

    def _sync_guilds(self):
        live = {str(g.id) for g in self.guilds}
        with SessionLocal() as s:
            for row in s.query(Guild).all():
                row.bot_present = row.guild_id in live
            s.commit()
        for g in self.guilds:
            self._upsert_guild(g, present=True)

    # ── job consumer ──

    async def _consume_jobs(self):
        await self.wait_until_ready()
        log.info("job consumer running")
        while not self.is_closed():
            try:
                with SessionLocal() as s:
                    job = (s.query(Job).filter(Job.status == "queued")
                           .order_by(Job.created_at).first())
                    if job:
                        job.status = "running"
                        job.started_at = utcnow()
                        s.commit()
                        job_id = job.id
                    else:
                        job_id = None
                if job_id:
                    log.info("running job %s", job_id)
                    await run_job(self, job_id)
            except Exception:
                log.exception("job consumer tick failed")
            await asyncio.sleep(3)


bot = Forge()


@bot.tree.command(name="setup", description=f"Open the {config.BRAND} dashboard")
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Design and apply your server structure here: {config.BASE_URL}", ephemeral=True)


@bot.tree.command(name="status", description="Last apply result for this server")
@app_commands.guild_only()
async def status_cmd(interaction: discord.Interaction):
    with SessionLocal() as s:
        job = (s.query(Job).filter(Job.guild_id == str(interaction.guild_id))
               .order_by(Job.created_at.desc()).first())
    if not job:
        msg = f"No applies yet. Start one at {config.BASE_URL}"
    else:
        ledger = json.loads(job.ledger_json or "[]")
        created = sum(1 for e in ledger if e["action"] == "created")
        skipped = sum(1 for e in ledger if e["action"] == "skipped")
        failed = sum(1 for e in ledger if e["action"] == "failed")
        msg = (f"Last apply: **{job.status}** ({job.created_at:%Y-%m-%d %H:%M} UTC) — "
               f"{created} created, {skipped} skipped, {failed} failed.")
        if job.error:
            msg += f"\n{job.error}"
    await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    config.require("DISCORD_TOKEN")
    bot.run(config.DISCORD_TOKEN, log_handler=None)
