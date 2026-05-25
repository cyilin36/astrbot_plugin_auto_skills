from auto_skills.config import AutoSkillsConfig


def test_config_uses_safe_defaults():
    config = AutoSkillsConfig.from_mapping({})

    assert config.enabled is True
    assert config.review_admin_only is True
    assert config.llm_tool_write_admin_only is True
    assert config.delete_admin_only is True
    assert config.review_every_turns == 10
    assert config.review_provider_id == ""
    assert config.max_concurrent_reviews == 1
    assert config.review_timeout_seconds == 60
    assert config.max_skill_chars == 100000
    assert config.max_description_chars == 1024
    assert config.max_backups_per_skill == 10
    assert config.auto_sync_sandbox is True
    assert config.global_activate_generated_skills is False


def test_permission_config_splits_review_tools_and_delete():
    config = AutoSkillsConfig.from_mapping(
        {
            "review_admin_only": False,
            "llm_tool_write_admin_only": False,
            "delete_admin_only": False,
        }
    )

    assert config.review_admin_only is False
    assert config.llm_tool_write_admin_only is False
    assert config.delete_admin_only is False


def test_legacy_admin_only_only_controls_review_default():
    config = AutoSkillsConfig.from_mapping({"admin_only": False})

    assert config.review_admin_only is False
    assert config.llm_tool_write_admin_only is True
    assert config.delete_admin_only is True


def test_config_coerces_invalid_numbers_to_defaults():
    config = AutoSkillsConfig.from_mapping(
        {
            "review_every_turns": "bad",
            "max_concurrent_reviews": 0,
            "review_timeout_seconds": -5,
            "max_backups_per_skill": -1,
        }
    )

    assert config.review_every_turns == 10
    assert config.max_concurrent_reviews == 1
    assert config.review_timeout_seconds == 60
    assert config.max_backups_per_skill == 10
