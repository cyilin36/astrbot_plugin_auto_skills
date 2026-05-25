from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ReviewDecision:
    action: str
    skill_name: str = ""
    reason: str = ""
    skill_markdown: str = ""
    patch_notes: str = ""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    return match.group(1).strip() if match else stripped


def parse_review_decision(text: str) -> ReviewDecision:
    try:
        data = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError:
        return ReviewDecision(action="noop", reason="Invalid review JSON")
    if not isinstance(data, dict):
        return ReviewDecision(action="noop", reason="Invalid review JSON")
    action = str(data.get("action") or "noop").strip().lower()
    if action not in {"noop", "create", "patch", "delete"}:
        return ReviewDecision(action="noop", reason=f"Unknown action: {action}")
    return ReviewDecision(
        action=action,
        skill_name=str(data.get("skill_name") or "").strip(),
        reason=str(data.get("reason") or "").strip(),
        skill_markdown=str(data.get("skill_markdown") or ""),
        patch_notes=str(data.get("patch_notes") or "").strip(),
    )


def build_review_system_prompt() -> str:
    return (
        "You review completed AstrBot Agent turns and decide whether to update "
        "the local Skill library. Return JSON only. Prefer updating an existing "
        "class-level skill over creating narrow one-session artifacts. Create or "
        "patch only durable procedural knowledge: reusable workflows, debugging "
        "paths, verification steps, user-corrected process, or operational pitfalls. "
        "Do not save secrets, private facts, one-off narratives, transient setup "
        "failures, or claims that a tool is permanently broken. Allowed actions: "
        "noop, create, patch, delete. Delete is only a request for user confirmation; "
        "never delete without an administrator confirming in a later turn. For create and patch, include full skill_markdown "
        "with YAML frontmatter name and description. Use lowercase skill names "
        "matching ^[a-z0-9][a-z0-9._-]{0,63}$."
    )


def build_review_user_prompt(
    *,
    user_message: str,
    assistant_response: str,
    tool_summaries: Iterable[str],
    active_skills: Iterable[Mapping[str, Any]],
    owned_skills: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "user_message": user_message,
        "assistant_response": assistant_response,
        "tool_summaries": list(tool_summaries),
        "active_skills": list(active_skills),
        "plugin_owned_skills": list(owned_skills),
        "response_schema": {
            "action": "noop | create | patch | delete",
            "skill_name": "lowercase-name",
            "reason": "short explanation",
            "skill_markdown": "full SKILL.md for create or patch",
            "patch_notes": "short change summary",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
