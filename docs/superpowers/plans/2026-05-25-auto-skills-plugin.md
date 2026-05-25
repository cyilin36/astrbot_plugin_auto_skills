# AstrBot Auto Skills Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone AstrBot plugin that automatically creates and updates AstrBot Skills after completed Agent turns, without modifying AstrBot core code, docs, or configuration.

**Architecture:** The plugin listens to `on_agent_done`, schedules a background LLM review, validates the review JSON, writes generated Skills under AstrBot's `data/skills`, updates AstrBot's `data/skills.json` through `SkillManager().set_skill_active(name, True)`, and keeps plugin-owned provenance plus rollback backups under `data/plugin_data/astrbot_plugin_auto_skills`. It never edits AstrBot source files and never writes generated output into plugin-provided read-only `skills/`.

**Tech Stack:** Python, AstrBot plugin API (`Star`, `filter`, `Context`, `AstrMessageEvent`), AstrBot `SkillManager`, AstrBot path helpers, `pytest`, `asyncio`, `json`, `yaml`, `pathlib`.

---

## Hard Constraints

- Do not modify any file under `/Users/cyilin/dev/AstrBot`.
- All produced implementation files must live under `/Users/cyilin/dev/astrbot_plugin_auto_skills`.
- The plugin may import AstrBot APIs at runtime, but must not patch or monkeypatch AstrBot internals.
- Generated skills must be written to the active AstrBot data directory via `get_astrbot_skills_path()`.
- After creating or updating a generated skill, the plugin must call `SkillManager().set_skill_active(skill_name, True)` so Docker-mounted `data/skills.json` records the skill as active.
- The plugin may only auto-update skills recorded as plugin-owned in its own `state.json`.

## File Structure

- Create: `metadata.yaml` — AstrBot plugin metadata.
- Create: `_conf_schema.json` — WebUI-configurable plugin options.
- Create: `main.py` — AstrBot `Star` entry point, event hook, commands, background task orchestration.
- Create: `auto_skills/__init__.py` — internal package marker.
- Create: `auto_skills/models.py` — dataclasses for review decisions, state records, backups, and validation errors.
- Create: `auto_skills/state_store.py` — plugin state persistence under `data/plugin_data/astrbot_plugin_auto_skills/state.json`.
- Create: `auto_skills/skill_store.py` — skill validation, atomic writes, backups, rollback, and `SkillManager().set_skill_active(...)` integration.
- Create: `auto_skills/review_runner.py` — review prompt construction, provider invocation, and strict JSON parsing.
- Create: `auto_skills/config.py` — config defaults and typed access helpers.
- Create: `skills/auto-skill-authoring/SKILL.md` — optional read-only plugin-provided guidance skill explaining the mechanism to AstrBot's main Agent.
- Create: `tests/test_skill_store.py` — TDD tests for validation, writing, `skills.json` updates, and rollback.
- Create: `tests/test_state_store.py` — TDD tests for state persistence.
- Create: `tests/test_review_runner.py` — TDD tests for JSON parsing and prompt contract.
- Create: `tests/test_plugin_flow.py` — TDD tests for non-blocking scheduling and command behavior using lightweight fakes.
- Create: `README.md` — install path, behavior, safety notes, and Docker `data/skills.json` note.

## Task 1: Plugin Skeleton And Metadata

**Files:**
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/metadata.yaml`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/_conf_schema.json`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/main.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/auto_skills/__init__.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/auto_skills/config.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
from auto_skills.config import AutoSkillsConfig


def test_config_uses_safe_defaults():
    config = AutoSkillsConfig.from_mapping({})

    assert config.enabled is True
    assert config.admin_only is True
    assert config.review_every_turns == 10
    assert config.review_provider_id == ""
    assert config.max_concurrent_reviews == 1
    assert config.review_timeout_seconds == 60
    assert config.max_skill_chars == 100000
    assert config.max_description_chars == 1024
    assert config.auto_sync_sandbox is True


def test_config_coerces_invalid_numbers_to_defaults():
    config = AutoSkillsConfig.from_mapping(
        {
            "review_every_turns": "bad",
            "max_concurrent_reviews": 0,
            "review_timeout_seconds": -5,
        }
    )

    assert config.review_every_turns == 10
    assert config.max_concurrent_reviews == 1
    assert config.review_timeout_seconds == 60
```

- [ ] **Step 2: Run tests and verify RED**

Run from `/Users/cyilin/dev/astrbot_plugin_auto_skills`:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_config.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'auto_skills'`.

- [ ] **Step 3: Add metadata and config schema**

Create `metadata.yaml`:

```yaml
name: astrbot_plugin_auto_skills
desc: Automatically creates and updates AstrBot Skills after successful Agent turns.
version: 0.1.0
repo: ""
astrbot_version: ">=4.23.1"
```

Create `_conf_schema.json`:

```json
{
  "enabled": {
    "description": "Enable automatic background skill review.",
    "type": "bool",
    "default": true
  },
  "admin_only": {
    "description": "Only run automatic review and management commands for AstrBot administrators.",
    "type": "bool",
    "default": true
  },
  "review_every_turns": {
    "description": "Run review after this many completed Agent turns per session.",
    "type": "int",
    "default": 10
  },
  "review_provider_id": {
    "description": "Optional provider ID for background reviews. Leave empty to use the current session provider.",
    "type": "string",
    "default": ""
  },
  "max_concurrent_reviews": {
    "description": "Maximum background reviews running at the same time.",
    "type": "int",
    "default": 1
  },
  "review_timeout_seconds": {
    "description": "Timeout for one background review LLM call.",
    "type": "int",
    "default": 60
  },
  "max_skill_chars": {
    "description": "Maximum generated SKILL.md length.",
    "type": "int",
    "default": 100000
  },
  "max_description_chars": {
    "description": "Maximum SKILL.md frontmatter description length.",
    "type": "int",
    "default": 1024
  },
  "auto_sync_sandbox": {
    "description": "Best-effort sync generated skills to active sandboxes after writes.",
    "type": "bool",
    "default": true
  }
}
```

- [ ] **Step 4: Implement config helper**

Create `auto_skills/__init__.py`:

```python
"""Internal helpers for astrbot_plugin_auto_skills."""
```

Create `auto_skills/config.py`:

```python
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
            auto_sync_sandbox=_bool_value(raw, "auto_sync_sandbox", True),
        )
```

- [ ] **Step 5: Add minimal plugin entry point**

Create `main.py`:

```python
from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.config.astrbot_config import AstrBotConfig

from auto_skills.config import AutoSkillsConfig


class AutoSkillsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.raw_config = config or {}
        self.config = AutoSkillsConfig.from_mapping(self.raw_config)
        logger.info("Auto Skills plugin loaded")

    @filter.on_agent_done()
    async def on_agent_done(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
        resp: LLMResponse,
    ) -> None:
        _ = (event, run_context, resp)
        return None

    async def terminate(self) -> None:
        logger.info("Auto Skills plugin unloaded")
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_config.py -q`

Expected: PASS.

## Task 2: State Store

**Files:**
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/auto_skills/models.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/auto_skills/state_store.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/tests/test_state_store.py`

- [ ] **Step 1: Write failing state persistence tests**

Create `tests/test_state_store.py`:

```python
from auto_skills.state_store import StateStore


def test_state_store_records_plugin_owned_skill(tmp_path):
    store = StateStore(tmp_path / "state.json")

    store.record_write(
        skill_name="daily-report",
        content_hash="abc123",
        action="create",
        reason="Reusable daily report workflow",
        backup_path=None,
    )

    record = store.get_skill("daily-report")
    assert record is not None
    assert record["created_by"] == "astrbot_plugin_auto_skills"
    assert record["content_hash"] == "abc123"
    assert record["version"] == 1
    assert record["last_action"] == "create"


def test_state_store_increments_version_and_tracks_backup(tmp_path):
    store = StateStore(tmp_path / "state.json")

    store.record_write("daily-report", "v1", "create", "initial", None)
    store.record_write(
        "daily-report",
        "v2",
        "patch",
        "improved",
        tmp_path / "backup.md",
    )

    record = store.get_skill("daily-report")
    assert record is not None
    assert record["version"] == 2
    assert record["content_hash"] == "v2"
    assert record["backups"] == [str(tmp_path / "backup.md")]


def test_state_store_lists_only_owned_skills(tmp_path):
    store = StateStore(tmp_path / "state.json")

    store.record_write("a", "1", "create", "reason", None)

    assert [item["name"] for item in store.list_skills()] == ["a"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_state_store.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'auto_skills.state_store'`.

- [ ] **Step 3: Add models and state store**

Create `auto_skills/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


PLUGIN_OWNER = "astrbot_plugin_auto_skills"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""
```

Create `auto_skills/state_store.py`:

```python
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auto_skills.models import PLUGIN_OWNER


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
        skills = data.get("skills")
        if not isinstance(skills, dict):
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

    def is_owned(self, skill_name: str) -> bool:
        record = self.get_skill(skill_name)
        return bool(record and record.get("created_by") == PLUGIN_OWNER)

    def list_skills(self) -> list[dict[str, Any]]:
        skills = self.load().get("skills", {})
        result = []
        for name, record in sorted(skills.items()):
            if isinstance(record, dict) and record.get("created_by") == PLUGIN_OWNER:
                result.append({"name": name, **record})
        return result

    def record_write(
        self,
        skill_name: str,
        content_hash: str,
        action: str,
        reason: str,
        backup_path: str | Path | None,
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
            "content_hash": content_hash,
            "version": version,
            "last_action": action,
            "last_reason": reason,
            "updated_at": _now_iso(),
            "backups": backups,
        }
        self.save(data)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_state_store.py -q`

Expected: PASS.

## Task 3: Skill Store Validation And `skills.json` Update

**Files:**
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/auto_skills/skill_store.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/tests/test_skill_store.py`

- [ ] **Step 1: Write failing skill store tests**

Create `tests/test_skill_store.py`:

```python
import json

from auto_skills.skill_store import SkillStore
from auto_skills.state_store import StateStore


VALID_MARKDOWN = """---
name: daily-report
description: Write structured daily reports from work notes.
---

# Daily Report

Use this skill when the user asks to write a daily report.
"""


def test_validate_rejects_bad_skill_name(tmp_path):
    store = SkillStore(tmp_path / "skills", StateStore(tmp_path / "state.json"))

    result = store.validate("bad/name", VALID_MARKDOWN)

    assert result.ok is False
    assert "Invalid skill name" in result.error


def test_validate_requires_frontmatter_description(tmp_path):
    store = SkillStore(tmp_path / "skills", StateStore(tmp_path / "state.json"))

    result = store.validate("daily-report", "---\nname: daily-report\n---\n\nBody")

    assert result.ok is False
    assert "description" in result.error


def test_create_writes_skill_and_updates_skills_json(tmp_path):
    skills_root = tmp_path / "skills"
    state = StateStore(tmp_path / "state.json")
    skills_json = tmp_path / "skills.json"
    calls = []

    def set_active(name: str, active: bool) -> None:
        calls.append((name, active))
        skills_json.write_text(
            json.dumps({"skills": {name: {"active": active}}}, ensure_ascii=False),
            encoding="utf-8",
        )

    store = SkillStore(skills_root, state, set_active=set_active)

    store.create_or_patch("daily-report", VALID_MARKDOWN, "create", "new workflow")

    assert (skills_root / "daily-report" / "SKILL.md").read_text(encoding="utf-8") == VALID_MARKDOWN
    assert calls == [("daily-report", True)]
    assert json.loads(skills_json.read_text(encoding="utf-8"))["skills"]["daily-report"] == {"active": True}
    assert state.is_owned("daily-report") is True


def test_patch_refuses_non_plugin_owned_existing_skill(tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "daily-report"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_MARKDOWN, encoding="utf-8")
    store = SkillStore(skills_root, StateStore(tmp_path / "state.json"), set_active=lambda _n, _a: None)

    try:
        store.create_or_patch("daily-report", VALID_MARKDOWN, "patch", "update")
    except PermissionError as exc:
        assert "not owned" in str(exc)
    else:
        raise AssertionError("Expected PermissionError")


def test_patch_creates_backup_for_owned_skill(tmp_path):
    skills_root = tmp_path / "skills"
    state = StateStore(tmp_path / "state.json")
    store = SkillStore(skills_root, state, set_active=lambda _n, _a: None)
    store.create_or_patch("daily-report", VALID_MARKDOWN, "create", "initial")

    updated = VALID_MARKDOWN.replace("Daily Report", "Daily Report Writer")
    store.create_or_patch("daily-report", updated, "patch", "rename heading")

    record = state.get_skill("daily-report")
    assert record is not None
    assert record["version"] == 2
    assert len(record["backups"]) == 1
    backup_path = record["backups"][0]
    assert "daily-report" in backup_path
```

- [ ] **Step 2: Run tests and verify RED**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_skill_store.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'auto_skills.skill_store'`.

- [ ] **Step 3: Implement skill store**

Create `auto_skills/skill_store.py`:

```python
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from auto_skills.models import ValidationResult
from auto_skills.state_store import StateStore

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        if not markdown.startswith("---"):
            return ValidationResult(False, "SKILL.md must start with YAML frontmatter")
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
            frontmatter = yaml.safe_load("\n".join(lines[1:end_idx])) or {}
        except yaml.YAMLError as exc:
            return ValidationResult(False, f"YAML frontmatter parse error: {exc}")
        if not isinstance(frontmatter, dict):
            return ValidationResult(False, "Frontmatter must be a YAML mapping")
        if not str(frontmatter.get("name") or "").strip():
            return ValidationResult(False, "Frontmatter must include name")
        description = str(frontmatter.get("description") or "").strip()
        if not description:
            return ValidationResult(False, "Frontmatter must include description")
        if len(description) > self.max_description_chars:
            return ValidationResult(False, "Description exceeds maximum length")
        body = "\n".join(lines[end_idx + 1 :]).strip()
        if not body:
            return ValidationResult(False, "SKILL.md body cannot be empty")
        return ValidationResult(True)

    def _skill_dir(self, skill_name: str) -> Path:
        return self.skills_root / skill_name

    def _skill_md(self, skill_name: str) -> Path:
        return self._skill_dir(skill_name) / "SKILL.md"

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
        if not record or record.get("created_by") != "astrbot_plugin_auto_skills":
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
        return backup_path
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_skill_store.py -q`

Expected: PASS.

## Task 4: Review Runner JSON Parsing And Prompt

**Files:**
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/auto_skills/review_runner.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/tests/test_review_runner.py`

- [ ] **Step 1: Write failing review runner tests**

Create `tests/test_review_runner.py`:

```python
from auto_skills.review_runner import ReviewDecision, parse_review_decision


def test_parse_review_decision_accepts_json_code_fence():
    text = '''```json
    {
      "action": "create",
      "skill_name": "daily-report",
      "reason": "Reusable workflow",
      "skill_markdown": "---\\nname: daily-report\\ndescription: Write reports.\\n---\\n\\n# Daily Report\\nBody",
      "patch_notes": "initial"
    }
    ```'''

    decision = parse_review_decision(text)

    assert decision.action == "create"
    assert decision.skill_name == "daily-report"
    assert decision.reason == "Reusable workflow"


def test_parse_review_decision_turns_bad_json_into_noop():
    decision = parse_review_decision("not json")

    assert decision == ReviewDecision(action="noop", reason="Invalid review JSON")


def test_parse_review_decision_rejects_unknown_action():
    decision = parse_review_decision('{"action":"delete","skill_name":"x"}')

    assert decision.action == "noop"
    assert "Unknown action" in decision.reason
```

- [ ] **Step 2: Run tests and verify RED**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_review_runner.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'auto_skills.review_runner'`.

- [ ] **Step 3: Implement review parsing and prompt builder**

Create `auto_skills/review_runner.py`:

```python
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
    if action not in {"noop", "create", "patch"}:
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
        "the local Skill library. Return JSON only. Prefer updating an existing "
        "class-level skill over creating narrow one-session artifacts. Create or "
        "patch only durable procedural knowledge: reusable workflows, debugging "
        "paths, verification steps, user-corrected process, or operational pitfalls. "
        "Do not save secrets, private facts, one-off narratives, transient setup "
        "failures, or claims that a tool is permanently broken. Allowed actions: "
        "noop, create, patch. For create and patch, include full skill_markdown "
        "with YAML frontmatter name and description."
    )


def build_review_user_prompt(
    *,
    user_message: str,
    assistant_response: str,
    tool_summaries: Iterable[str],
    active_skills: Iterable[Mapping[str, Any]],
    owned_skills: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "user_message": user_message,
        "assistant_response": assistant_response,
        "tool_summaries": list(tool_summaries),
        "active_skills": list(active_skills),
        "plugin_owned_skills": list(owned_skills),
        "response_schema": {
            "action": "noop | create | patch",
            "skill_name": "lowercase-name",
            "reason": "short explanation",
            "skill_markdown": "full SKILL.md for create or patch",
            "patch_notes": "short change summary",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_review_runner.py -q`

Expected: PASS.

## Task 5: Plugin Event Flow And Commands

**Files:**
- Modify: `/Users/cyilin/dev/astrbot_plugin_auto_skills/main.py`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/tests/test_plugin_flow.py`

- [ ] **Step 1: Write failing plugin flow tests**

Create `tests/test_plugin_flow.py`:

```python
import asyncio
from types import SimpleNamespace

from main import AutoSkillsPlugin


class FakeContext:
    async def llm_generate(self, **kwargs):
        self.last_llm_kwargs = kwargs
        return SimpleNamespace(completion_text='{"action":"noop","reason":"none"}')

    def get_using_provider(self, umo=None):
        _ = umo
        return SimpleNamespace(id="provider-1")


class FakeEvent:
    unified_msg_origin = "platform:private:user"
    message_str = "write a daily report"

    def get_sender_id(self):
        return "admin"

    def plain_result(self, text):
        return text


async def _wait_for_tasks(plugin):
    tasks = list(plugin._review_tasks)
    if tasks:
        await asyncio.gather(*tasks)


def test_on_agent_done_schedules_background_review(monkeypatch):
    plugin = AutoSkillsPlugin(FakeContext(), {"review_every_turns": 1, "admin_only": False})
    event = FakeEvent()
    resp = SimpleNamespace(completion_text="Here is the report.", role="assistant")
    run_context = SimpleNamespace()

    asyncio.run(plugin.on_agent_done(event, run_context, resp))
    asyncio.run(_wait_for_tasks(plugin))

    assert plugin.last_review_status["action"] == "noop"


def test_disabled_plugin_does_not_schedule_review():
    plugin = AutoSkillsPlugin(FakeContext(), {"enabled": False, "admin_only": False})

    asyncio.run(plugin.on_agent_done(FakeEvent(), SimpleNamespace(), SimpleNamespace(completion_text="ok")))

    assert plugin._review_tasks == set()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_plugin_flow.py -q`

Expected: FAIL because `AutoSkillsPlugin` has no `_review_tasks` or background review behavior.

- [ ] **Step 3: Implement background scheduling and status command foundation**

Modify `main.py` to include:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.computer.computer_client import sync_skills_to_active_sandboxes
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path, get_astrbot_skills_path

from auto_skills.config import AutoSkillsConfig
from auto_skills.review_runner import (
    build_review_system_prompt,
    build_review_user_prompt,
    parse_review_decision,
)
from auto_skills.skill_store import SkillStore
from auto_skills.state_store import StateStore


class AutoSkillsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.raw_config = config or {}
        self.config = AutoSkillsConfig.from_mapping(self.raw_config)
        data_root = Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_auto_skills"
        self.state_store = StateStore(data_root / "state.json")
        self.skill_store = SkillStore(
            get_astrbot_skills_path(),
            self.state_store,
            set_active=lambda name, active: SkillManager().set_skill_active(name, active),
            backup_root=data_root / "backups",
            max_skill_chars=self.config.max_skill_chars,
            max_description_chars=self.config.max_description_chars,
        )
        self._review_tasks: set[asyncio.Task] = set()
        self._session_turns: dict[str, int] = {}
        self._review_semaphore = asyncio.Semaphore(self.config.max_concurrent_reviews)
        self.last_review_status: dict[str, Any] = {"action": "none", "error": ""}
        logger.info("Auto Skills plugin loaded")

    def _should_review(self, event: AstrMessageEvent, resp: LLMResponse) -> bool:
        if not self.config.enabled:
            return False
        if not str(getattr(resp, "completion_text", "") or "").strip():
            return False
        umo = getattr(event, "unified_msg_origin", "") or "default"
        count = self._session_turns.get(umo, 0) + 1
        self._session_turns[umo] = count
        return count % self.config.review_every_turns == 0

    def _track_task(self, task: asyncio.Task) -> None:
        self._review_tasks.add(task)
        task.add_done_callback(self._review_tasks.discard)

    @filter.on_agent_done()
    async def on_agent_done(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
        resp: LLMResponse,
    ) -> None:
        if not self._should_review(event, resp):
            return None
        task = asyncio.create_task(self._run_review(event, run_context, resp))
        self._track_task(task)
        return None

    async def _run_review(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
        resp: LLMResponse,
    ) -> None:
        _ = run_context
        async with self._review_semaphore:
            try:
                active_skills = [
                    {"name": skill.name, "description": skill.description}
                    for skill in SkillManager().list_skills(active_only=True)
                ]
                user_prompt = build_review_user_prompt(
                    user_message=str(getattr(event, "message_str", "") or ""),
                    assistant_response=str(getattr(resp, "completion_text", "") or ""),
                    tool_summaries=[],
                    active_skills=active_skills,
                    owned_skills=self.state_store.list_skills(),
                )
                llm_resp = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=self.config.review_provider_id
                        or getattr(self.context.get_using_provider(getattr(event, "unified_msg_origin", None)), "id", ""),
                        prompt=user_prompt,
                        system_prompt=build_review_system_prompt(),
                    ),
                    timeout=self.config.review_timeout_seconds,
                )
                decision = parse_review_decision(str(getattr(llm_resp, "completion_text", "") or ""))
                if decision.action in {"create", "patch"}:
                    self.skill_store.create_or_patch(
                        decision.skill_name,
                        decision.skill_markdown,
                        decision.action,
                        decision.reason,
                    )
                    if self.config.auto_sync_sandbox:
                        try:
                            await sync_skills_to_active_sandboxes()
                        except Exception as exc:
                            logger.warning("Auto Skills sandbox sync failed: %s", exc)
                self.last_review_status = {
                    "action": decision.action,
                    "skill_name": decision.skill_name,
                    "reason": decision.reason,
                    "error": "",
                }
            except Exception as exc:
                self.last_review_status = {"action": "error", "error": str(exc)}
                logger.warning("Auto Skills review failed: %s", exc)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command_group("autoskill")
    def autoskill(self):
        pass

    @autoskill.command("status")
    async def autoskill_status(self, event: AstrMessageEvent):
        yield event.plain_result(
            "Auto Skills: "
            f"enabled={self.config.enabled}, "
            f"review_every_turns={self.config.review_every_turns}, "
            f"last={self.last_review_status}"
        )

    async def terminate(self) -> None:
        for task in list(self._review_tasks):
            task.cancel()
        logger.info("Auto Skills plugin unloaded")
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_plugin_flow.py -q`

Expected: PASS.

## Task 6: Management Commands And Rollback

**Files:**
- Modify: `/Users/cyilin/dev/astrbot_plugin_auto_skills/main.py`
- Modify: `/Users/cyilin/dev/astrbot_plugin_auto_skills/tests/test_plugin_flow.py`

- [ ] **Step 1: Add failing command tests**

Append to `tests/test_plugin_flow.py`:

```python
def test_list_owned_skills_returns_names():
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    plugin.state_store.record_write("daily-report", "hash", "create", "reason", None)

    names = [item["name"] for item in plugin.state_store.list_skills()]

    assert names == ["daily-report"]
```

- [ ] **Step 2: Run tests and verify RED if command surface is incomplete**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_plugin_flow.py -q`

Expected: Current tests may pass if state behavior exists; continue by implementing command handlers because runtime command surface is still incomplete.

- [ ] **Step 3: Add command handlers**

Extend `main.py` with these methods inside `AutoSkillsPlugin`:

```python
    @autoskill.command("list")
    async def autoskill_list(self, event: AstrMessageEvent):
        skills = self.state_store.list_skills()
        if not skills:
            yield event.plain_result("No auto-created skills yet.")
            return
        lines = [f"- {item['name']} v{item.get('version', 0)}: {item.get('last_action', '')}" for item in skills]
        yield event.plain_result("Auto-created skills:\n" + "\n".join(lines))

    @autoskill.command("view")
    async def autoskill_view(self, event: AstrMessageEvent, name: str):
        record = self.state_store.get_skill(name)
        if not record or record.get("created_by") != "astrbot_plugin_auto_skills":
            yield event.plain_result(f"Skill {name} is not owned by Auto Skills.")
            return
        yield event.plain_result(
            f"{name}\n"
            f"version: {record.get('version')}\n"
            f"last_action: {record.get('last_action')}\n"
            f"updated_at: {record.get('updated_at')}\n"
            f"reason: {record.get('last_reason')}"
        )

    @autoskill.command("rollback")
    async def autoskill_rollback(self, event: AstrMessageEvent, name: str):
        try:
            backup_path = self.skill_store.rollback_latest(name)
        except Exception as exc:
            yield event.plain_result(f"Rollback failed for {name}: {exc}")
            return
        yield event.plain_result(f"Rolled back {name} from {backup_path}")
```

- [ ] **Step 4: Run plugin tests**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest tests/test_plugin_flow.py tests/test_skill_store.py -q`

Expected: PASS.

## Task 7: Plugin Guidance Skill And README

**Files:**
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/skills/auto-skill-authoring/SKILL.md`
- Create: `/Users/cyilin/dev/astrbot_plugin_auto_skills/README.md`

- [ ] **Step 1: Create read-only guidance Skill**

Create `skills/auto-skill-authoring/SKILL.md`:

```markdown
---
name: auto-skill-authoring
description: Understand how the Auto Skills plugin creates and updates reusable AstrBot Skills after completed Agent turns.
---

# Auto Skill Authoring

Use this skill when discussing or operating the Auto Skills plugin.

## Rules

1. Generated skills are written to AstrBot's user skills directory, not this plugin's `skills/` directory.
2. The plugin's own `skills/` directory is read-only in AstrBot and exists only to explain this mechanism.
3. A generated skill should capture durable procedural knowledge: reusable workflows, debugging paths, verification steps, and pitfalls.
4. Do not create skills for one-off facts, secrets, temporary environment failures, or private user details.
5. The plugin only updates skills it previously created and recorded as plugin-owned.

## Docker Note

After writing `data/skills/<name>/SKILL.md`, the plugin calls AstrBot's `SkillManager().set_skill_active(name, True)`. This updates `data/skills.json`, which is important when `data/` is mounted as a Docker volume.
```

- [ ] **Step 2: Create README**

Create `README.md`:

```markdown
# astrbot_plugin_auto_skills

Auto Skills is a standalone AstrBot plugin that automatically creates and updates reusable `SKILL.md` files after completed Agent turns.

## Install

Place this directory under AstrBot's plugin directory:

```text
data/plugins/astrbot_plugin_auto_skills
```

Then reload plugins from AstrBot WebUI or restart AstrBot.

## Behavior

- Listens to `on_agent_done`.
- Runs a background LLM review every configured number of completed turns.
- Writes generated Skills to `data/skills/<skill_name>/SKILL.md`.
- Calls `SkillManager().set_skill_active(skill_name, True)` after writing so `data/skills.json` records the generated Skill as active.
- Saves plugin state and backups under `data/plugin_data/astrbot_plugin_auto_skills`.
- Only auto-updates Skills created by this plugin.

## Commands

- `/autoskill status`
- `/autoskill list`
- `/autoskill view <name>`
- `/autoskill rollback <name>`

## Safety

The first version is full-auto publishing, but it does not delete Skills and does not modify user-authored or plugin-provided Skills.
```

- [ ] **Step 3: Verify no AstrBot files changed**

Run:

`git -C /Users/cyilin/dev/AstrBot status --short`

Expected: no output.

## Task 8: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run all plugin tests**

Run:

`PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills pytest /Users/cyilin/dev/astrbot_plugin_auto_skills/tests -q`

Expected: all tests PASS.

- [ ] **Step 2: Run formatting if available**

Run:

`python -m compileall /Users/cyilin/dev/astrbot_plugin_auto_skills`

Expected: no syntax errors.

- [ ] **Step 3: Verify AstrBot repo is untouched**

Run:

`git -C /Users/cyilin/dev/AstrBot status --short`

Expected: no output.

- [ ] **Step 4: Manual Docker data contract check**

In a test AstrBot runtime, create a generated skill through `SkillStore.create_or_patch(...)`, then verify the active data directory contains:

```json
{
  "skills": {
    "generated-skill-name": {
      "active": true
    }
  }
}
```

Expected: `data/skills.json` includes the generated skill with `active: true` because the plugin called `SkillManager().set_skill_active(name, True)`.

## Self-Review Checklist

- Spec coverage: plugin-only implementation, full-auto publishing, `data/skills` writes, `data/skills.json` updates, rollback, state, and no AstrBot modifications are covered.
- Placeholder scan: no placeholder markers or vague implementation steps remain.
- Type consistency: `AutoSkillsConfig`, `StateStore`, `SkillStore`, and `ReviewDecision` names match across tasks.
- Scope check: no Shipyard Neo candidate/release implementation and no AstrBot core changes are included.
