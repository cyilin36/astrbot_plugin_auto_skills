from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _positive_int(data: Mapping[str, Any], key: str, default: int) -> int:
    try:
        value = int(data.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class AutoSkillsConfig:
    enabled: bool = True
    admin_only: bool = True
    review_every_turns: int = 10
    review_provider_id: str = ""
    max_concurrent_reviews: int = 1
    review_timeout_seconds: int = 60
    max_skill_chars: int = 100000
    max_description_chars: int = 1024
    max_backups_per_skill: int = 10
    auto_sync_sandbox: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "AutoSkillsConfig":
        raw = data or {}
        return cls(
            enabled=_bool_value(raw, "enabled", True),
            admin_only=_bool_value(raw, "admin_only", True),
            review_every_turns=_positive_int(raw, "review_every_turns", 10),
            review_provider_id=str(raw.get("review_provider_id") or "").strip(),
            max_concurrent_reviews=_positive_int(raw, "max_concurrent_reviews", 1),
            review_timeout_seconds=_positive_int(raw, "review_timeout_seconds", 60),
            max_skill_chars=_positive_int(raw, "max_skill_chars", 100000),
            max_description_chars=_positive_int(raw, "max_description_chars", 1024),
            max_backups_per_skill=_positive_int(raw, "max_backups_per_skill", 10),
            auto_sync_sandbox=_bool_value(raw, "auto_sync_sandbox", True),
        )
