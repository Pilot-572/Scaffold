# ── LLM structure generation ──
# One OpenAI-compatible chat call. Invalid JSON: retry once with the validation
# error fed back, then fall back to the closest preset with a visible notice.
import json
import logging
import re

import requests
from pydantic import ValidationError

from shared import config
from shared.presets import closest_preset, load_preset
from shared.schema import ALLOWED_PERMS, Structure

log = logging.getLogger("serverforge.llm")

SYSTEM_PROMPT = f"""You design Discord server structures. Reply with ONLY a JSON object, no prose, no markdown fences.

Schema:
{{
  "name": "short structure name",
  "description": "one sentence",
  "roles": [{{"name": str, "color": "#rrggbb", "hoist": bool, "mentionable": bool, "permissions": [str]}}],
  "categories": [{{"name": str}}],
  "channels": [{{"name": str, "type": "text"|"voice", "topic": str|null, "category": str|null,
                 "mode": "public"|"announcement"|"role_gated", "gate_roles": [str]}}]
}}

Hard rules:
- Max {config.CAP_ROLES} roles, {config.CAP_CATEGORIES} categories, {config.CAP_CHANNELS} channels.
- role permissions may ONLY come from: {", ".join(sorted(ALLOWED_PERMS))}. Most roles should have [].
- Every channel's "category" must exactly match a name in "categories" (or be null).
- "announcement" = everyone reads, nobody but staff posts. "role_gated" = only "gate_roles" (which must name roles you defined) can see it; use sparingly.
- Text channel names: lowercase-with-dashes. Voice channels: normal casing, no topic.
- No duplicate names. No invite links, no @everyone/@here anywhere.
- Fit the community described; sensible topics on text channels."""


class GenerationFailed(Exception):
    pass


def _extract_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return text[start:end + 1]


def _call(messages: list[dict]) -> str:
    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": 0.7,
            # Generous on purpose: some providers (Groq gpt-oss) return EMPTY
            # content when max_tokens is small.
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    if not content:
        raise ValueError("empty completion")
    return content


def generate(description: str) -> tuple[Structure, str | None]:
    """Returns (structure, notice). notice is set when we fell back to a preset."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": description[:2000]},
    ]
    last_err = None
    raw = ""
    for attempt in range(2):
        try:
            raw = _call(messages)
            return Structure.model_validate_json(_extract_json(raw)), None
        except (requests.RequestException, ValueError, ValidationError, KeyError) as e:
            last_err = e
            log.warning("generation attempt %d failed: %s", attempt + 1, type(e).__name__)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                             "content": f"That was invalid: {e}. Reply again with ONLY the corrected JSON object."})
    pid = closest_preset(description)
    log.warning("falling back to preset %s after: %s", pid, type(last_err).__name__)
    structure = load_preset(pid)
    notice = ("AI generation didn't produce a valid layout, so we loaded the closest "
              f"preset ({structure.name}) instead. You can tweak your description and try again.")
    return structure, notice
