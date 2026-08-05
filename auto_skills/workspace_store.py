from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.core.workspace import (
    default_workspace_root,
    normalize_umo_for_workspace,
    resolve_workspace_root_for_umo,
)

from .models import PLUGIN_OWNER
from .skill_validator import (
    ValidationResult,
    normalize_skill_name,
    rewrite_frontmatter_name,
    validate_skill_markdown,
)
from .state_store import StateStore


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


class WorkspaceSkillStore:
    """Create and manage Skills under the current UMO workspace."""

    def __init__(
        self,
        state_store: StateStore,
        *,
        backup_root: str | Path | None = None,
        max_skill_chars: int = 100000,
        max_description_chars: int = 1024,
        max_backups_per_skill: int = 10,
        context: Any | None = None,
    ):
        self.state_store = state_store
        self.backup_root = Path(backup_root) if backup_root else state_store.path.parent / "backups"
        self.max_skill_chars = max_skill_chars
        self.max_description_chars = max_description_chars
        self.max_backups_per_skill = max_backups_per_skill if max_backups_per_skill > 0 else 10
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

    def validate(self, skill_name: str, markdown: str) -> ValidationResult:
        return validate_skill_markdown(
            skill_name,
            markdown,
            max_skill_chars=self.max_skill_chars,
            max_description_chars=self.max_description_chars,
        )

    def prepare_markdown(self, skill_name: str, markdown: str) -> str:
        return rewrite_frontmatter_name(markdown, skill_name)

    def _skill_md(self, skills_root: Path, skill_name: str) -> Path:
        return skills_root / skill_name / "SKILL.md"

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)

    def _backup_key(self, umo: str, skill_name: str) -> str:
        return f"{normalize_umo_for_workspace(umo)}/{skill_name}"

    def _backup_existing(self, umo: str, skill_name: str, skill_md: Path) -> Path | None:
        if not skill_md.exists():
            return None
        backup_dir = self.backup_root / self._backup_key(umo, skill_name)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{_now_stamp()}-SKILL.md"
        backup_path.write_text(skill_md.read_text(encoding="utf-8"), encoding="utf-8")
        return backup_path

    def _delete_backup_dir(self, umo: str, skill_name: str) -> None:
        backup_dir = self.backup_root / self._backup_key(umo, skill_name)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    def _prune_backups(self, umo: str, skill_name: str) -> None:
        record = self.state_store.get_skill(umo, skill_name)
        if not record:
            return
        backups = [str(path) for path in record.get("backups") or []]
        if len(backups) <= self.max_backups_per_skill:
            return
        keep = backups[-self.max_backups_per_skill :]
        for backup in backups[: -self.max_backups_per_skill]:
            try:
                Path(backup).unlink(missing_ok=True)
            except OSError:
                pass
        self.state_store.update_backups(umo, skill_name, keep)

    async def list_workspace_skill_names(self, umo: str) -> list[str]:
        skills_root = await self.skills_root(umo)
        if not skills_root.is_dir():
            return []
        names: list[str] = []
        try:
            for skill_dir in sorted(skills_root.iterdir(), key=lambda item: item.name):
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                    names.append(skill_dir.name)
        except OSError:
            return []
        return names

    async def read_skill_markdown(self, umo: str, skill_name: str) -> str:
        skill_md = self._skill_md(await self.skills_root(umo), skill_name)
        if not skill_md.is_file():
            raise FileNotFoundError(f"{skill_name}/SKILL.md does not exist in workspace")
        return skill_md.read_text(encoding="utf-8")

    async def skill_description(self, umo: str, skill_name: str) -> str:
        try:
            return _skill_description_from_markdown(await self.read_skill_markdown(umo, skill_name))
        except (OSError, FileNotFoundError):
            return "Read SKILL.md for details."

    async def create_or_patch(
        self,
        umo: str,
        skill_name: str,
        markdown: str,
        action: str,
        reason: str,
    ) -> dict[str, Any]:
        skill_name = normalize_skill_name(skill_name)
        markdown = self.prepare_markdown(skill_name, markdown)
        validation = self.validate(skill_name, markdown)
        if not validation.ok:
            raise ValueError(validation.error)
        if action not in {"create", "patch"}:
            raise ValueError("action must be create or patch")

        skills_root = await self.skills_root(umo)
        skills_root.mkdir(parents=True, exist_ok=True)
        skill_md = self._skill_md(skills_root, skill_name)
        exists = skill_md.exists()

        if action == "patch" and not self.state_store.is_owned(umo, skill_name):
            raise PermissionError(f"Skill {skill_name} is not owned by this plugin")

        # create may overwrite existing workspace skill (hand-written or previously owned).
        backup_path = self._backup_existing(umo, skill_name, skill_md)
        self._atomic_write(skill_md, markdown)
        workspace_root = await self.resolve_workspace_root(umo)
        recorded_action = action
        if action == "create" and exists:
            recorded_action = "create-overwrite"
        self.state_store.record_write(
            skill_name=skill_name,
            content_hash=_sha256_text(markdown),
            action=recorded_action,
            reason=reason,
            backup_path=backup_path,
            umo=umo,
            display_name=skill_name,
            workspace_path=str(skill_md),
            workspace_root=str(workspace_root),
        )
        self._prune_backups(umo, skill_name)
        return {
            "name": skill_name,
            "path": str(skill_md),
            "workspace_root": str(workspace_root),
            "overwrote": exists,
            "warnings": list(validation.warnings),
        }

    async def delete_owned(self, umo: str, skill_name: str, reason: str) -> None:
        _ = reason
        skill_name = normalize_skill_name(skill_name)
        if not self.state_store.is_owned(umo, skill_name):
            raise PermissionError(f"Skill {skill_name} is not owned by this plugin for current UMO")
        skill_dir = (await self.skills_root(umo)) / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        self._delete_backup_dir(umo, skill_name)
        self.state_store.remove_skill(umo, skill_name)

    async def rollback_latest(self, umo: str, skill_name: str) -> Path:
        skill_name = normalize_skill_name(skill_name)
        record = self.state_store.get_skill(umo, skill_name)
        if not record or record.get("created_by") != PLUGIN_OWNER:
            raise PermissionError(f"Skill {skill_name} is not owned by this plugin for current UMO")
        backups = list(record.get("backups") or [])
        if not backups:
            raise FileNotFoundError(f"No backup exists for {skill_name}")
        backup_path = Path(backups[-1])
        if not backup_path.exists():
            raise FileNotFoundError(str(backup_path))
        content = backup_path.read_text(encoding="utf-8")
        skill_md = self._skill_md(await self.skills_root(umo), skill_name)
        self._atomic_write(skill_md, content)
        self.state_store.record_write(
            skill_name=skill_name,
            content_hash=_sha256_text(content),
            action="rollback",
            reason=f"Rolled back from {backup_path}",
            backup_path=None,
            umo=umo,
            display_name=skill_name,
            workspace_path=str(skill_md),
            workspace_root=str(await self.resolve_workspace_root(umo)),
        )
        return backup_path
