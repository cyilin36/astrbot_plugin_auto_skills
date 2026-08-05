from __future__ import annotations

import re

# Align with AstrBot builtin skill-creator scripts.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_skill_name(skill_name: str) -> str:
    """Normalize a free-form name into a skill-creator compatible slug."""
    raw = str(skill_name or "").strip().lower()
    raw = raw.replace("_", "-").replace(".", "-").replace(" ", "-")
    raw = re.sub(r"[^a-z0-9-]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if not raw:
        raw = "skill"
    if not raw[0].isalnum():
        raw = f"skill-{raw}".strip("-")
    raw = raw[:64].rstrip("-") or "skill"
    if not _SKILL_NAME_RE.fullmatch(raw):
        parts = [part for part in re.split(r"[^a-z0-9]+", raw) if part]
        raw = "-".join(parts)[:64].strip("-") or "skill"
    return raw


def is_valid_skill_name(skill_name: str) -> bool:
    name = str(skill_name or "")
    return bool(name) and len(name) <= 64 and bool(_SKILL_NAME_RE.fullmatch(name))
