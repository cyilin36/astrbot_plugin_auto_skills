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
        "the current session workspace Skill library.\n\n"
        "Target location: the current UMO workspace at skills/<skill-name>/SKILL.md. "
        "Do not write global data/skills or plugin skills.\n\n"
        "Follow AstrBot skill-creator rules:\n"
        "- Skill names must match ^[a-z0-9]+(?:-[a-z0-9]+)*$ and be <= 64 chars.\n"
        "- Directory name equals frontmatter name.\n"
        "- Frontmatter only needs name and description.\n"
        "- description must state capability AND concrete trigger conditions.\n"
        "- Body uses imperative, operational instructions. Prefer workflows over prose.\n"
        "- Include only task-specific procedures, constraints, verification steps, and pitfalls.\n"
        "- Do not add README, changelogs, secrets, private facts, one-off narratives, or claims "
        "that a tool is permanently broken.\n"
        "- Prefer patching an existing class-level skill over creating narrow one-session artifacts.\n\n"
        "Return JSON only. Allowed actions: noop, create, patch, delete. "
        "Delete is only a request for later administrator confirmation. "
        "For create and patch, include full skill_markdown with YAML frontmatter and non-empty body."
    )


def build_review_user_prompt(
    *,
    user_message: str,
    assistant_response: str,
    tool_summaries: Iterable[str],
    workspace_skills: Iterable[Mapping[str, Any]],
    owned_skills: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "user_message": user_message,
        "assistant_response": assistant_response,
        "tool_summaries": list(tool_summaries),
        "workspace_skills": list(workspace_skills),
        "plugin_owned_workspace_skills": list(owned_skills),
        "response_schema": {
            "action": "noop | create | patch | delete",
            "skill_name": "lowercase-hyphen-name",
            "reason": "short explanation",
            "skill_markdown": "full SKILL.md for create or patch",
            "patch_notes": "short change summary",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
