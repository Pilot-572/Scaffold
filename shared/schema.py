# ── Structure schema ──
# One schema for presets and AI output. Everything user- or LLM-supplied is
# sanitized here; nothing downstream trusts raw names or topics.
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.config import CAP_CATEGORIES, CAP_CHANNELS, CAP_ROLES

# Guild permissions a generated role may carry. Never management, moderation,
# webhooks, or mention-everyone — this is a public bot.
ALLOWED_PERMS = frozenset({
    "view_channel", "send_messages", "read_message_history", "add_reactions",
    "embed_links", "attach_files", "connect", "speak", "stream",
    "use_external_emojis", "change_nickname", "use_application_commands",
    "create_public_threads", "send_messages_in_threads",
})

_INVITE_RE = re.compile(r"(?:https?://)?(?:discord\.gg|discord(?:app)?\.com/invite)/\S+", re.I)
_MENTION_RE = re.compile(r"@(everyone|here)")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_text(text: str, limit: int) -> str:
    """Strip invite links and mass mentions, collapse whitespace, cap length."""
    text = _INVITE_RE.sub("", text)
    text = _MENTION_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def channel_slug(name: str) -> str:
    """Discord text-channel name rules: lowercase, dashes, no spaces."""
    name = clean_text(name, 100).lower()
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"[^a-z0-9-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:100]


class Role(BaseModel):
    name: str
    color: str = "#99aab5"
    hoist: bool = False
    mentionable: bool = False
    permissions: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = clean_text(v, 100)
        if not v:
            raise ValueError("role name is empty after sanitizing")
        return v

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        return v if _HEX_RE.match(v or "") else "#99aab5"

    @field_validator("permissions")
    @classmethod
    def _perms(cls, v: list[str]) -> list[str]:
        # ponytail: unknown/forbidden perms are silently dropped, not errors —
        # keeps LLM output usable while guaranteeing nothing outside the allowlist ships.
        return sorted({p for p in v if p in ALLOWED_PERMS})


class Category(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = clean_text(v, 100)
        if not v:
            raise ValueError("category name is empty after sanitizing")
        return v


class Channel(BaseModel):
    name: str
    type: Literal["text", "voice"] = "text"
    topic: Optional[str] = None
    category: Optional[str] = None
    # public: no overwrites. announcement: @everyone can read but not post.
    # role_gated: only gate_roles can see the channel.
    mode: Literal["public", "announcement", "role_gated"] = "public"
    gate_roles: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sanitize(self) -> "Channel":
        self.name = channel_slug(self.name) if self.type == "text" else clean_text(self.name, 100)
        if not self.name:
            raise ValueError("channel name is empty after sanitizing")
        if self.type == "voice":
            self.topic = None
            if self.mode == "announcement":
                self.mode = "public"
        if self.topic:
            self.topic = clean_text(self.topic, 1024) or None
        if self.category:
            self.category = clean_text(self.category, 100) or None
        self.gate_roles = [clean_text(r, 100) for r in self.gate_roles if clean_text(r, 100)]
        if self.mode == "role_gated" and not self.gate_roles:
            raise ValueError(f"channel '{self.name}' is role_gated but lists no gate_roles")
        if self.mode != "role_gated":
            self.gate_roles = []
        return self


class Structure(BaseModel):
    name: str = "Untitled"
    description: Optional[str] = None
    roles: list[Role] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "Structure":
        self.name = clean_text(self.name, 100) or "Untitled"
        if self.description:
            self.description = clean_text(self.description, 300) or None
        if len(self.roles) > CAP_ROLES:
            raise ValueError(f"too many roles ({len(self.roles)} > {CAP_ROLES})")
        if len(self.categories) > CAP_CATEGORIES:
            raise ValueError(f"too many categories ({len(self.categories)} > {CAP_CATEGORIES})")
        if len(self.channels) > CAP_CHANNELS:
            raise ValueError(f"too many channels ({len(self.channels)} > {CAP_CHANNELS})")

        role_names = [r.name for r in self.roles]
        if len(role_names) != len(set(role_names)):
            raise ValueError("duplicate role names")
        cat_names = [c.name for c in self.categories]
        if len(cat_names) != len(set(cat_names)):
            raise ValueError("duplicate category names")
        chan_keys = [(c.name, c.category) for c in self.channels]
        if len(chan_keys) != len(set(chan_keys)):
            raise ValueError("duplicate channel names within the same category")

        cats = set(cat_names)
        for ch in self.channels:
            if ch.category and ch.category not in cats:
                raise ValueError(f"channel '{ch.name}' references unknown category '{ch.category}'")
        return self
