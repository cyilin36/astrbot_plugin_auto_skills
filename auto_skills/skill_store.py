from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import PLUGIN_OWNER, ValidationResult
from .state_store import StateStore

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_simple_frontmatter(text: str) -> dict[str, str]:
    result = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Invalid frontmatter line: {raw_line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid frontmatter line: {raw_line}")
        result[key] = value.strip().strip('"\'')
    return result


class SkillStore:
    def __init__(
        self,
        skills_root: str | Path,
        state_store: StateStore,
        *,
        set_active: Callable[[str, bool], None] | None = None,
        backup_root: str | Path | None = None,
        max_skill_chars: int = 100000,
        max_description_chars: int = 1024,
    ):
        self.skills_root = Path(skills_root)
        self.state_store = state_store
        self.set_active = set_active
        self.backup_root = Path(backup_root) if backup_root else state_store.path.parent / "backups"
        self.max_skill_chars = max_skill_chars
        self.max_description_chars = max_description_chars

    def validate(self, skill_name: str, markdown: str) -> ValidationResult:
        if not _SKILL_NAME_RE.fullmatch(skill_name):
            return ValidationResult(False, f"Invalid skill name: {skill_name}")
        if len(markdown) > self.max_skill_chars:
            return ValidationResult(False, "SKILL.md exceeds maximum length")
        lines = markdown.splitlines()
        if not lines or lines[0].strip() != "---":
            return ValidationResult(False, "SKILL.md must start with YAML frontmatter")
        end_idx = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end_idx = index
                break
        if end_idx is None:
            return ValidationResult(False, "SKILL.md frontmatter is not closed")
        try:
            frontmatter = _parse_simple_frontmatter("\n".join(lines[1:end_idx]))
        except ValueError as exc:
            return ValidationResult(False, f"YAML frontmatter parse error: {exc}")
        if str(frontmatter.get("name") or "").strip() != skill_name:
            return ValidationResult(False, "Frontmatter name must match skill name")
        description = str(frontmatter.get("description") or "").strip()
        if not description:
            return ValidationResult(False, "Frontmatter must include description")
        if len(description) > self.max_description_chars:
            return ValidationResult(False, "Description exceeds maximum length")
        body = "\n".join(lines[end_idx + 1 :]).strip()
        if not body:
            return ValidationResult(False, "SKILL.md body cannot be empty")
        return ValidationResult(True)

    def _skill_md(self, skill_name: str) -> Path:
        return self.skills_root / skill_name / "SKILL.md"

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)

    def _backup_existing(self, skill_name: str, skill_md: Path) -> Path | None:
        if not skill_md.exists():
            return None
        backup_dir = self.backup_root / skill_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{_now_stamp()}-SKILL.md"
        backup_path.write_text(skill_md.read_text(encoding="utf-8"), encoding="utf-8")
        return backup_path

    def create_or_patch(self, skill_name: str, markdown: str, action: str, reason: str) -> None:
        validation = self.validate(skill_name, markdown)
        if not validation.ok:
            raise ValueError(validation.error)
        if action not in {"create", "patch"}:
            raise ValueError("action must be create or patch")
        skill_md = self._skill_md(skill_name)
        exists = skill_md.exists()
        if action == "create" and exists and not self.state_store.is_owned(skill_name):
            raise FileExistsError(f"Skill {skill_name} already exists and is not owned by this plugin")
        if action == "patch" and not self.state_store.is_owned(skill_name):
            raise PermissionError(f"Skill {skill_name} is not owned by this plugin")

        backup_path = self._backup_existing(skill_name, skill_md)
        self._atomic_write(skill_md, markdown)
        if self.set_active is not None:
            self.set_active(skill_name, True)
        self.state_store.record_write(
            skill_name=skill_name,
            content_hash=_sha256_text(markdown),
            action=action,
            reason=reason,
            backup_path=backup_path,
        )

    def rollback_latest(self, skill_name: str) -> Path:
        record = self.state_store.get_skill(skill_name)
        if not record or record.get("created_by") != PLUGIN_OWNER:
            raise PermissionError(f"Skill {skill_name} is not owned by this plugin")
        backups = list(record.get("backups") or [])
        if not backups:
            raise FileNotFoundError(f"No backup exists for {skill_name}")
        backup_path = Path(backups[-1])
        if not backup_path.exists():
            raise FileNotFoundError(str(backup_path))
        skill_md = self._skill_md(skill_name)
        self._atomic_write(skill_md, backup_path.read_text(encoding="utf-8"))
        if self.set_active is not None:
            self.set_active(skill_name, True)
        self.state_store.record_write(
            skill_name=skill_name,
            content_hash=_sha256_text(skill_md.read_text(encoding="utf-8")),
            action="rollback",
            reason=f"Rolled back from {backup_path}",
            backup_path=None,
        )
        return backup_path
