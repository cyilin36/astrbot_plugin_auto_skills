import json
from pathlib import Path


def test_config_schema_uses_chinese_descriptions():
    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))

    for key, item in schema.items():
        text = item.get("description", "") + item.get("hint", "")
        assert text, key
        assert any("\u4e00" <= char <= "\u9fff" for char in text), key


def test_review_provider_uses_astrbot_provider_selector():
    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))

    provider = schema["review_provider_id"]
    assert provider["type"] == "string"
    assert provider["default"] == ""
    assert provider["_special"] == "select_provider"
    assert "留空" in provider["hint"]


def test_general_tool_protection_schema_describes_read_and_search_blocking():
    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))

    protection = schema["protect_skills_from_general_tools"]
    text = protection["description"] + protection["hint"]
    assert protection["type"] == "bool"
    assert protection["default"] is True
    assert "读取" in text
    assert "搜索" in text
    assert "astrbot_file_read_tool" in text
    assert "astrbot_grep_tool" in text


def test_readme_describes_purpose_side_effects_config_and_repository():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "自动" in readme
    assert "UMO" in readme
    assert "副作用" in readme
    assert "protect_skills_from_general_tools" in readme
    assert "auto_skill_read" in readme
    assert "https://github.com/cyilin36/astrbot_plugin_auto_skills" in readme


def test_autoskill_commands_have_docstrings():
    source = Path("main.py").read_text(encoding="utf-8")

    for command_name in [
        "autoskill",
        "autoskill_status",
        "autoskill_list",
        "autoskill_view",
        "autoskill_rollback",
        "autoskill_delete",
    ]:
        assert f"def {command_name}" in source
    assert "查看 Auto Skills 插件状态" in source
    assert "列出本插件自动创建并拥有的 Skill" in source
    assert "直接删除本插件自动创建并拥有的 Skill" in source


def test_auto_skill_llm_tools_have_docstrings():
    source = Path("main.py").read_text(encoding="utf-8")

    for tool_name in [
        "auto_skill_read",
        "auto_skill_create",
        "auto_skill_patch",
        "auto_skill_delete_request",
    ]:
        assert f'@filter.llm_tool(name="{tool_name}")' in source
        assert f"def {tool_name}" in source
    assert "创建一个新的 AstrBot Skill" in source
    assert "读取 AstrBot Skill" in source
    assert "更新本插件已经创建并拥有的 AstrBot Skill" in source
    assert "请求删除本插件自动创建并拥有的 AstrBot Skill" in source
    assert "skill_name(string):" in source
    assert "include_content(bool):" in source
    assert "skill_markdown(string):" in source
    assert "reason(string):" in source
