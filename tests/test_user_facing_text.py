import json
from pathlib import Path


def test_config_schema_uses_chinese_descriptions():
    schema = json.loads(Path("_conf_schema.json").read_text(encoding="utf-8"))

    for key, item in schema.items():
        text = item.get("description", "") + item.get("hint", "")
        assert text, key
        assert any("\u4e00" <= char <= "\u9fff" for char in text), key


def test_autoskill_commands_have_docstrings():
    source = Path("main.py").read_text(encoding="utf-8")

    for command_name in [
        "autoskill",
        "autoskill_status",
        "autoskill_list",
        "autoskill_view",
        "autoskill_rollback",
    ]:
        assert f"def {command_name}" in source
    assert "查看 Auto Skills 插件状态" in source
    assert "列出本插件自动创建并拥有的 Skill" in source
