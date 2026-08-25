# ── ServerForge database ──
# SQLite by default; DATABASE_URL swap moves this to Postgres unchanged.
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from shared.config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 15} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        # WAL so the bot and web processes can share the file without locking wars.
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

Base = declarative_base()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    discord_id = Column(String(32), primary_key=True)
    username = Column(String(100), nullable=False)
    avatar = Column(String(64))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Guild(Base):
    __tablename__ = "guilds"
    guild_id = Column(String(32), primary_key=True)
    name = Column(String(120), nullable=False)
    icon = Column(String(64))
    bot_present = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Draft(Base):
    """A generated structure awaiting apply. Applies reference a draft so the
    client never round-trips the structure itself."""
    __tablename__ = "drafts"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(32), nullable=False, index=True)
    guild_id = Column(String(32), nullable=False, index=True)
    source = Column(String(60), nullable=False)  # "preset:<name>" or "ai"
    structure_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    guild_id = Column(String(32), nullable=False, index=True)
    user_id = Column(String(32), nullable=False, index=True)
    source = Column(String(60), nullable=False)
    structure_json = Column(Text, nullable=False)
    # queued -> running -> done | partial | failed
    status = Column(String(12), default="queued", nullable=False, index=True)
    ledger_json = Column(Text)   # per-item results: created / skipped / failed + detail
    error = Column(Text)         # human-readable summary when partial/failed
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)


class License(Base):
    __tablename__ = "licenses"
    key = Column(String(40), primary_key=True)
    user_id = Column(String(32), index=True)  # null until redeemed
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    redeemed_at = Column(DateTime)


def init_db() -> None:
    Base.metadata.create_all(engine)


def is_premium(session, user_id: str) -> bool:
    return (
        session.query(License)
        .filter(License.user_id == str(user_id), License.revoked.is_(False))
        .first()
        is not None
    )
