# ── Scaffold dashboard ──
# Flask + Jinja + htmx. All state changes are POST + CSRF; the user's Manage
# Server permission is re-checked server-side (fresh, uncached) on every apply.
import json
import logging
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import (Flask, abort, redirect, render_template, request, session, url_for)

from shared import config, discord_api
from shared.db import (Draft, Guild, Job, License, SessionLocal, User, init_db,
                       is_premium, utcnow)
from shared.diff import build_plan
from shared.presets import list_presets, load_preset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("scaffold.web")

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.OAUTH_REDIRECT_URI.startswith("https"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

init_db()

# ponytail: per-process dict cache for the Discord guild list (60s TTL) — it's a
# rate-limited endpoint. Move to the DB only if you ever run >1 web worker.
_guild_cache: dict[str, tuple[float, list]] = {}


@app.context_processor
def _globals():
    return {
        "BRAND": config.BRAND,
        "user": {"id": session.get("user_id"), "name": session.get("username"),
                 "avatar": session.get("avatar")} if session.get("user_id") else None,
        "csrf_token": session.get("_csrf", ""),
    }


@app.before_request
def _csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf")
        if not token or request.form.get("_csrf") != token:
            abort(400, "Bad CSRF token — reload the page and try again.")


@app.errorhandler(discord_api.AuthExpired)
def _auth_expired(_):
    session.clear()
    return redirect(url_for("index"))


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("index"))
        return f(*a, **kw)
    return wrapper


def _my_guilds(fresh: bool = False) -> list[dict]:
    uid = session["user_id"]
    now = time.monotonic()
    if not fresh and uid in _guild_cache and now - _guild_cache[uid][0] < 60:
        return _guild_cache[uid][1]
    guilds = discord_api.manageable_guilds(session["access_token"])
    _guild_cache[uid] = (now, guilds)
    return guilds


def _require_guild(guild_id: str, fresh: bool = False) -> dict:
    for g in _my_guilds(fresh=fresh):
        if g["id"] == guild_id:
            return g
    abort(403, "You need Manage Server on that guild.")


def _bot_in(db, guild_id: str) -> bool:
    row = db.get(Guild, guild_id)
    return bool(row and row.bot_present)


def _limits(db, user_id: str) -> dict:
    premium = is_premium(db, user_id)
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    hour_ago = utcnow() - timedelta(hours=1)
    applies_today = db.query(Job).filter(Job.user_id == user_id, Job.created_at >= day_start).count()
    applies_hour = db.query(Job).filter(Job.user_id == user_id, Job.created_at >= hour_ago).count()
    ai_today = db.query(Draft).filter(Draft.user_id == user_id, Draft.source == "ai",
                                      Draft.created_at >= day_start).count()
    return {
        "premium": premium,
        "applies_today": applies_today,
        "applies_cap": config.PREMIUM_APPLIES_PER_DAY if premium else config.FREE_APPLIES_PER_DAY,
        "applies_hour": applies_hour,
        "hour_cap": config.APPLIES_PER_HOUR,
        "ai_today": ai_today,
        "ai_cap": config.PREMIUM_AI_PER_DAY if premium else 0,
    }


# ── Auth ──

@app.get("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("servers"))
    return render_template("login.html")


@app.get("/login")
def login():
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    return redirect(discord_api.authorize_url(state))


@app.get("/callback")
def callback():
    if not request.args.get("code") or request.args.get("state") != session.pop("oauth_state", None):
        abort(400, "OAuth state mismatch — start the login again.")
    token = discord_api.exchange_code(request.args["code"])
    me = discord_api.fetch_user(token["access_token"])
    session.clear()
    session.permanent = True
    session.update(
        user_id=me["id"],
        username=me.get("global_name") or me["username"],
        avatar=me.get("avatar"),
        access_token=token["access_token"],
        _csrf=secrets.token_urlsafe(24),
    )
    with SessionLocal() as db:
        db.merge(User(discord_id=me["id"], username=session["username"], avatar=me.get("avatar")))
        db.commit()
    log.info("login user=%s", me["id"])
    return redirect(url_for("servers"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ── Server picker ──

@app.get("/servers")
@login_required
def servers():
    guilds = _my_guilds()
    with SessionLocal() as db:
        for g in guilds:
            g["bot_present"] = _bot_in(db, g["id"])
            g["invite"] = discord_api.invite_url(g["id"])
    return render_template("servers.html", guilds=guilds)


# ── Guild: generate / preview / apply ──

@app.get("/guild/<guild_id>")
@login_required
def guild_page(guild_id):
    g = _require_guild(guild_id)
    with SessionLocal() as db:
        bot_present = _bot_in(db, guild_id)
        limits = _limits(db, session["user_id"])
        history = (db.query(Job).filter(Job.guild_id == guild_id)
                   .order_by(Job.created_at.desc()).limit(10).all())
        for job in history:
            ledger = json.loads(job.ledger_json or "[]")
            job.n_created = sum(1 for e in ledger if e["action"] == "created")
            job.n_skipped = sum(1 for e in ledger if e["action"] == "skipped")
            job.n_failed = sum(1 for e in ledger if e["action"] == "failed")
    return render_template("guild.html", g=g, bot_present=bot_present,
                           invite=discord_api.invite_url(guild_id),
                           presets=list_presets(), limits=limits, history=history)


def _error_partial(message: str, hint: str = ""):
    return render_template("_error.html", message=message, hint=hint)


@app.post("/guild/<guild_id>/preview")
@login_required
def preview(guild_id):
    _require_guild(guild_id)
    with SessionLocal() as db:
        if not _bot_in(db, guild_id):
            return _error_partial("The bot isn't in this server yet.",
                                  "Use the Add bot button up top, then try again.")
        limits = _limits(db, session["user_id"])

        notice = None
        preset_id = request.form.get("preset", "").strip()
        description = request.form.get("description", "").strip()
        if preset_id:
            try:
                structure = load_preset(preset_id)
            except KeyError:
                abort(400)
            source = f"preset:{preset_id}"
        elif description:
            if not limits["premium"]:
                return _error_partial("AI generation is a premium feature.",
                                      "Redeem a license key on your account page to unlock it.")
            if limits["ai_today"] >= limits["ai_cap"]:
                return _error_partial(f"You've used all {limits['ai_cap']} AI generations for today.",
                                      "Presets are always available, or try again tomorrow.")
            from shared.llm import generate  # deferred: keeps web boot LLM-free
            structure, notice = generate(description)
            source = "ai"
        else:
            return _error_partial("Pick a preset or describe your community first.")

        draft = Draft(user_id=session["user_id"], guild_id=guild_id, source=source,
                      structure_json=structure.model_dump_json())
        db.add(draft)
        db.commit()

        try:
            snap = discord_api.guild_snapshot(guild_id)
        except discord_api.DiscordAPIError as e:
            return _error_partial(str(e))
        plan = build_plan(structure, snap)

    return render_template("_preview.html", structure=structure, plan=plan,
                           draft_id=draft.id, guild_id=guild_id, notice=notice)


@app.post("/guild/<guild_id>/apply")
@login_required
def apply_structure(guild_id):
    # Fresh permission check against Discord — never trust the client or the cache.
    _require_guild(guild_id, fresh=True)
    draft_id = request.form.get("draft_id", type=int)
    with SessionLocal() as db:
        draft = db.get(Draft, draft_id) if draft_id else None
        if not draft or draft.user_id != session["user_id"] or draft.guild_id != guild_id:
            abort(400, "Unknown draft — generate a preview first.")
        if not _bot_in(db, guild_id):
            return _error_partial("The bot isn't in this server yet.")

        limits = _limits(db, session["user_id"])
        if limits["applies_hour"] >= limits["hour_cap"]:
            return _error_partial(f"Cooldown: max {limits['hour_cap']} applies per hour.",
                                  "Give it a little time, then try again.")
        if limits["applies_today"] >= limits["applies_cap"]:
            return _error_partial(f"Daily limit reached ({limits['applies_cap']} applies).",
                                  "Premium raises this to "
                                  f"{config.PREMIUM_APPLIES_PER_DAY}/day." if not limits["premium"]
                                  else "Resets at midnight UTC.")

        job = Job(guild_id=guild_id, user_id=session["user_id"], source=draft.source,
                  structure_json=draft.structure_json)
        db.add(job)
        db.commit()
        log.info("apply queued job=%s guild=%s user=%s", job.id, guild_id, session["user_id"])
        return render_template("_job.html", job=job, ledger=[], guild_id=guild_id)


@app.get("/guild/<guild_id>/jobs/<int:job_id>")
@login_required
def job_status(guild_id, job_id):
    _require_guild(guild_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.guild_id != guild_id:
            abort(404)
        ledger = json.loads(job.ledger_json or "[]")
    return render_template("_job.html", job=job, ledger=ledger, guild_id=guild_id)


# ── Account ──

@app.get("/account")
@login_required
def account():
    with SessionLocal() as db:
        limits = _limits(db, session["user_id"])
        lic = (db.query(License).filter(License.user_id == session["user_id"],
                                        License.revoked.is_(False)).first())
    return render_template("account.html", limits=limits, license=lic,
                           message=request.args.get("m"))


@app.post("/account/redeem")
@login_required
def redeem():
    key = request.form.get("key", "").strip().upper()
    with SessionLocal() as db:
        lic = db.get(License, key)
        if not lic or lic.revoked:
            return redirect(url_for("account", m="That key is invalid or revoked."))
        if lic.user_id and lic.user_id != session["user_id"]:
            return redirect(url_for("account", m="That key is already redeemed by another account."))
        lic.user_id = session["user_id"]
        lic.redeemed_at = lic.redeemed_at or utcnow()
        db.commit()
        log.info("license redeemed user=%s", session["user_id"])
    return redirect(url_for("account", m="Premium unlocked. Enjoy."))


if __name__ == "__main__":
    config.require("SECRET_KEY", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_TOKEN")
    app.run(host="127.0.0.1", port=config.PORT)
