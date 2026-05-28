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
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "skills": {}, "last_review": None}

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        if not isinstance(data.get("skills"), dict):
            data["skills"] = {}
        data.setdefault("version", 1)
        data.setdefault("last_review", None)
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def get_skill(self, skill_name: str) -> dict[str, Any] | None:
        record = self.load().get("skills", {}).get(skill_name)
        return record if isinstance(record, dict) else None

    def is_owned(self, skill_name: str, umo: str | None = None) -> bool:
        record = self.get_skill(skill_name)
        if not record or record.get("created_by") != PLUGIN_OWNER:
            return False
        return umo is None or record.get("umo") == umo

    def list_skills(self, umo: str | None = None) -> list[dict[str, Any]]:
        skills = self.load().get("skills", {})
        result = []
        for name, record in sorted(skills.items()):
            if (
                isinstance(record, dict)
                and record.get("created_by") == PLUGIN_OWNER
                and record.get("last_action") != "delete"
                and (umo is None or record.get("umo") == umo)
            ):
                result.append({"name": name, **record})
        return result

    def resolve_skill_name(self, umo: str, name: str) -> str | None:
        record = self.get_skill(name)
        if record and record.get("created_by") == PLUGIN_OWNER and record.get("umo") == umo:
            return name
        for skill in self.list_skills(umo):
            if skill.get("display_name") == name:
                return str(skill["name"])
        return None

    def update_backups(self, skill_name: str, backups: list[str]) -> None:
        data = self.load()
        record = data.get("skills", {}).get(skill_name)
        if not isinstance(record, dict):
            return
        record["backups"] = backups
        self.save(data)

    def remove_skill(self, skill_name: str) -> None:
        data = self.load()
        skills = data.setdefault("skills", {})
        if skill_name not in skills:
            return
        skills.pop(skill_name, None)
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
    ) -> None:
        data = self.load()
        skills = data.setdefault("skills", {})
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
        }
        data["last_review"] = _now_iso()
        self.save(data)
