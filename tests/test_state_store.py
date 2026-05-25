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
