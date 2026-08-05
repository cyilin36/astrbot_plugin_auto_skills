from __future__ import annotations

from pathlib import Path
from typing import Any

from astrbot.core.workspace import default_workspace_root, resolve_workspace_root_for_umo


def _skill_description_from_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return "Read SKILL.md for details."
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.lstrip().startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'") or "Read SKILL.md for details."
    return "Read SKILL.md for details."


class WorkspaceSkillsReader:
    """Read-only access to the current UMO workspace skills/ directory."""

    def __init__(self, context: Any | None = None):
        self.context = context

    async def resolve_workspace_root(self, umo: str) -> Path:
        db = None
        if self.context is not None and hasattr(self.context, "get_db"):
            try:
                db = self.context.get_db()
            except Exception:
                db = None
        try:
            if db is not None:
                return await resolve_workspace_root_for_umo(umo, db)
        except Exception:
            pass
        return default_workspace_root(umo)

    async def skills_root(self, umo: str) -> Path:
        return (await self.resolve_workspace_root(umo)) / "skills"

    async def list_skills(self, umo: str) -> list[dict[str, str]]:
        skills_root = await self.skills_root(umo)
        if not skills_root.is_dir():
            return []
        result: list[dict[str, str]] = []
        try:
            for skill_dir in sorted(skills_root.iterdir(), key=lambda item: item.name):
                skill_md = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not skill_md.is_file():
                    continue
                try:
                    description = _skill_description_from_markdown(
                        skill_md.read_text(encoding="utf-8")
                    )
                except OSError:
                    description = "Read SKILL.md for details."
                result.append(
                    {
                        "name": skill_dir.name,
                        "description": description,
                        "path": str(skill_md),
                    }
                )
        except OSError:
            return []
        return result
