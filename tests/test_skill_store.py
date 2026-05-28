import json
from pathlib import Path

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


def test_rollback_restores_latest_backup_and_keeps_skill_active(tmp_path):
    skills_root = tmp_path / "skills"
    state = StateStore(tmp_path / "state.json")
    calls = []
    store = SkillStore(skills_root, state, set_active=lambda name, active: calls.append((name, active)))
    store.create_or_patch("daily-report", VALID_MARKDOWN, "create", "initial")
    updated = VALID_MARKDOWN.replace("Daily Report", "Daily Report Writer")
    store.create_or_patch("daily-report", updated, "patch", "rename heading")

    restored_from = store.rollback_latest("daily-report")

    assert restored_from.exists()
    assert (skills_root / "daily-report" / "SKILL.md").read_text(encoding="utf-8") == VALID_MARKDOWN
    assert calls[-1] == ("daily-report", True)


def test_patch_prunes_old_backups_to_configured_limit(tmp_path):
    skills_root = tmp_path / "skills"
    state = StateStore(tmp_path / "state.json")
    store = SkillStore(skills_root, state, set_active=lambda _n, _a: None, max_backups_per_skill=2)
    store.create_or_patch("daily-report", VALID_MARKDOWN, "create", "initial")

    for index in range(3):
        updated = VALID_MARKDOWN.replace("Body", f"Body {index}")
        store.create_or_patch("daily-report", updated, "patch", f"update {index}")

    record = state.get_skill("daily-report")
    assert record is not None
    assert len(record["backups"]) == 2
    assert all(Path(path).exists() for path in record["backups"])


def test_delete_owned_skill_deletes_skill_state_and_backup_dir(tmp_path):
    skills_root = tmp_path / "skills"
    state = StateStore(tmp_path / "state.json")
    deleted = []

    def delete_skill(name: str) -> None:
        deleted.append(name)
        skill_dir = skills_root / name
        for child in skill_dir.iterdir():
            child.unlink()
        skill_dir.rmdir()

    store = SkillStore(skills_root, state, delete_skill=delete_skill)
    store.create_or_patch("daily-report", VALID_MARKDOWN, "create", "initial")
    updated = VALID_MARKDOWN.replace("Daily Report", "Daily Report Writer")
    store.create_or_patch("daily-report", updated, "patch", "rename heading")
    backup_dir = tmp_path / "backups" / "daily-report"
    assert backup_dir.exists()

    backup_path = store.delete_owned("daily-report", "admin command")

    assert backup_path is None
    assert deleted == ["daily-report"]
    assert not (skills_root / "daily-report").exists()
    assert state.get_skill("daily-report") is None
    assert "daily-report" not in state.load()["skills"]
    assert not backup_dir.exists()
