from __future__ import annotations

from dataclasses import dataclass


PLUGIN_OWNER = "astrbot_plugin_auto_skills"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""
