from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import PLUGIN_OWNER


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    """Track plugin-managed workspace skills, isolated per UMO."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _empty(self) -> dict[str, Any]:
        return {"version": 2, "skills_by_umo": {}, "last_review": None}

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()

        # Migrate legacy flat "skills" map if present.
        if "skills_by_umo" not in data and isinstance(data.get("skills"), dict):
            by_umo: dict[str, Any] = {}
            for name, record in data["skills"].items():
                if not isinstance(record, dict):
                    continue
                umo = str(record.get("umo") or "default")
                by_umo.setdefault(umo, {})[name] = record
            data["skills_by_umo"] = by_umo
            data.pop("skills", None)

        if not isinstance(data.get("skills_by_umo"), dict):
            data["skills_by_umo"] = {}
        data.setdefault("version", 2)
        data.setdefault("last_review", None)
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def get_skill(self, umo: str, skill_name: str) -> dict[str, Any] | None:
        record = self.load().get("skills_by_umo", {}).get(umo, {}).get(skill_name)
        return record if isinstance(record, dict) else None

    def is_owned(self, umo: str, skill_name: str) -> bool:
        record = self.get_skill(umo, skill_name)
        return bool(record and record.get("created_by") == PLUGIN_OWNER)

    def list_skills(self, umo: str | None = None) -> list[dict[str, Any]]:
        by_umo = self.load().get("skills_by_umo", {})
        result: list[dict[str, Any]] = []
        umos = [umo] if umo is not None else sorted(by_umo.keys())
        for current_umo in umos:
            skills = by_umo.get(current_umo, {})
            if not isinstance(skills, dict):
                continue
            for name, record in sorted(skills.items()):
                if (
                    isinstance(record, dict)
                    and record.get("created_by") == PLUGIN_OWNER
                    and record.get("last_action") != "delete"
                ):
                    result.append({"name": name, "umo": current_umo, **record})
        return result

    def resolve_skill_name(self, umo: str, name: str) -> str | None:
        requested = str(name or "").strip()
        if not requested:
            return None
        record = self.get_skill(umo, requested)
        if record and record.get("created_by") == PLUGIN_OWNER:
            return requested
        for skill in self.list_skills(umo):
            if skill.get("display_name") == requested or skill.get("name") == requested:
                return str(skill["name"])
        return None

    def update_backups(self, umo: str, skill_name: str, backups: list[str]) -> None:
        data = self.load()
        record = data.get("skills_by_umo", {}).get(umo, {}).get(skill_name)
        if not isinstance(record, dict):
            return
        record["backups"] = backups
        self.save(data)

    def remove_skill(self, umo: str, skill_name: str) -> None:
        data = self.load()
        by_umo = data.setdefault("skills_by_umo", {})
        skills = by_umo.get(umo)
        if not isinstance(skills, dict) or skill_name not in skills:
            return
        skills.pop(skill_name, None)
        if not skills:
            by_umo.pop(umo, None)
        data["last_review"] = _now_iso()
        self.save(data)

    def record_write(
        self,
        skill_name: str,
        content_hash: str,
        action: str,
        reason: str,
        backup_path: str | Path | None,
        umo: str = "",
        display_name: str | None = None,
        workspace_path: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        data = self.load()
        by_umo = data.setdefault("skills_by_umo", {})
        skills = by_umo.setdefault(umo or "default", {})
        previous = skills.get(skill_name)
        if not isinstance(previous, dict):
            previous = {}
        backups = list(previous.get("backups") or [])
        if backup_path is not None:
            backups.append(str(backup_path))
        version = int(previous.get("version") or 0) + 1
        skills[skill_name] = {
            "created_by": PLUGIN_OWNER,
            "umo": umo,
            "display_name": display_name or previous.get("display_name") or skill_name,
            "content_hash": content_hash,
            "version": version,
            "last_action": action,
            "last_reason": reason,
            "updated_at": _now_iso(),
            "backups": backups,
            "workspace_path": workspace_path or previous.get("workspace_path") or "",
            "workspace_root": workspace_root or previous.get("workspace_root") or "",
        }
        data["last_review"] = _now_iso()
        self.save(data)
