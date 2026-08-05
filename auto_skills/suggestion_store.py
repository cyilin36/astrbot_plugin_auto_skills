from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SuggestionStore:
    """Persist pending skill-creator reminders per UMO."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _empty(self) -> dict[str, Any]:
        return {"version": 3, "pending_by_umo": {}, "last_review": None}

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        if not isinstance(data.get("pending_by_umo"), dict):
            data["pending_by_umo"] = {}
        data.setdefault("version", 3)
        data.setdefault("last_review", None)
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def get_pending(self, umo: str) -> dict[str, Any] | None:
        pending = self.load().get("pending_by_umo", {}).get(umo)
        return pending if isinstance(pending, dict) else None

    def set_pending(self, umo: str, suggestion: dict[str, Any]) -> None:
        data = self.load()
        data.setdefault("pending_by_umo", {})[umo] = suggestion
        data["last_review"] = _now_iso()
        self.save(data)

    def clear_pending(self, umo: str) -> bool:
        data = self.load()
        by_umo = data.setdefault("pending_by_umo", {})
        if umo not in by_umo:
            return False
        by_umo.pop(umo, None)
        data["last_review"] = _now_iso()
        self.save(data)
        return True

    def consume_inject(self, umo: str) -> dict[str, Any] | None:
        """Return pending suggestion and decrement remaining injects.

        Clears the suggestion when remaining injects reach zero.
        """
        data = self.load()
        by_umo = data.setdefault("pending_by_umo", {})
        pending = by_umo.get(umo)
        if not isinstance(pending, dict):
            return None
        remaining = int(pending.get("remaining_injects") or 0)
        if remaining <= 0:
            by_umo.pop(umo, None)
            self.save(data)
            return None
        view = dict(pending)
        view["remaining_injects"] = remaining
        remaining -= 1
        if remaining <= 0:
            by_umo.pop(umo, None)
        else:
            pending["remaining_injects"] = remaining
            pending["last_injected_at"] = _now_iso()
            by_umo[umo] = pending
        data["last_review"] = _now_iso()
        self.save(data)
        return view

    def record_review(self, status: dict[str, Any]) -> None:
        data = self.load()
        data["last_review"] = _now_iso()
        data["last_review_status"] = status
        self.save(data)
