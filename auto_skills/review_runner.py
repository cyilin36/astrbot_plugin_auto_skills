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
        "You review completed AstrBot Agent turns and decide whether the current "
        "session should update its workspace Skill library.\n\n"
        "Important: you do NOT write files yourself. You only recommend an action "
        "that the main agent should later apply with the built-in skill-creator skill.\n\n"
        "Target location: current UMO workspace skills/<skill-name>/SKILL.md.\n"
        "Do not recommend writing global data/skills or plugin skills.\n\n"
        "Follow AstrBot skill-creator rules when drafting recommendations:\n"
        "- Skill names must match ^[a-z0-9]+(?:-[a-z0-9]+)*$ and be <= 64 chars.\n"
        "- Directory name equals frontmatter name.\n"
        "- Frontmatter only needs name and description.\n"
        "- description must state capability AND concrete trigger conditions.\n"
        "- Body uses imperative, operational instructions.\n"
        "- Include only durable procedural knowledge: reusable workflows, debugging "
        "paths, verification steps, constraints, and pitfalls.\n"
        "- Do not recommend skills for secrets, private facts, one-off narratives, or "
        "temporary environment failures.\n"
        "- Prefer patching an existing class-level skill over creating narrow one-session artifacts.\n\n"
        "Return JSON only. Allowed actions: noop, create, patch, delete.\n"
        "For create and patch, include a full skill_markdown draft the main agent can "
        "apply via skill-creator. For delete, only recommend removal of clearly obsolete "
        "workspace skills; the main agent must confirm with the user before deleting."
    )


def build_review_user_prompt(
    *,
    user_message: str,
    assistant_response: str,
    tool_summaries: Iterable[str],
    workspace_skills: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "user_message": user_message,
        "assistant_response": assistant_response,
        "tool_summaries": list(tool_summaries),
        "workspace_skills": list(workspace_skills),
        "response_schema": {
            "action": "noop | create | patch | delete",
            "skill_name": "lowercase-hyphen-name",
            "reason": "short explanation",
            "skill_markdown": "full SKILL.md draft for create or patch",
            "patch_notes": "short change summary",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_skill_creator_nudge(suggestion: Mapping[str, Any]) -> str:
    """Build a system-prompt reminder that routes work to skill-creator."""
    action = str(suggestion.get("action") or "noop")
    skill_name = str(suggestion.get("skill_name") or "").strip() or "<skill-name>"
    reason = str(suggestion.get("reason") or "").strip() or "No reason provided."
    patch_notes = str(suggestion.get("patch_notes") or "").strip()
    draft = str(suggestion.get("skill_markdown") or "").strip()
    remaining = suggestion.get("remaining_injects")

    lines = [
        "## Auto Skills review reminder",
        "",
        "A background review of recent turns found durable knowledge worth capturing "
        "in the current workspace Skill library.",
        "",
        "Do NOT invent a custom skill-management workflow. Apply this with the built-in "
        "**skill-creator** skill and normal workspace file tools.",
        "",
        f"- Recommended action: `{action}`",
        f"- Skill name: `{skill_name}`",
        f"- Target path: `skills/{skill_name}/SKILL.md` in the current workspace",
        f"- Reason: {reason}",
    ]
    if patch_notes:
        lines.append(f"- Patch notes: {patch_notes}")
    if remaining is not None:
        lines.append(f"- Reminder remaining turns: {remaining}")
    lines.extend(
        [
            "",
            "### How to apply",
            "",
            "1. Read the skill-creator skill first.",
            "2. Inspect existing `skills/` in the current workspace.",
            f"3. { _action_instruction(action, skill_name) }",
            "4. Validate against skill-creator rules before finishing.",
            "5. If the recommendation is wrong or already applied, ignore it.",
            "",
        ]
    )
    if draft and action in {"create", "patch"}:
        lines.extend(
            [
                "### Draft SKILL.md to adapt",
                "",
                "Use this as a starting draft. Edit freely to match skill-creator quality bars:",
                "",
                "```markdown",
                draft,
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _action_instruction(action: str, skill_name: str) -> str:
    if action == "create":
        return (
            f"Create `skills/{skill_name}/` with a valid `SKILL.md` "
            "(or overwrite only if that is clearly intended)."
        )
    if action == "patch":
        return f"Update the existing workspace skill `skills/{skill_name}/SKILL.md`."
    if action == "delete":
        return (
            f"Only if the user confirms, remove the obsolete workspace skill "
            f"`skills/{skill_name}/`."
        )
    return "No file change is required."
