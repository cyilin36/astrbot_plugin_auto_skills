import ast
from pathlib import Path


def _read_simple_yaml(path: Path) -> dict[str, str]:
    result = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"\'')
    return result


def test_metadata_contains_astrbot_required_fields():
    metadata = _read_simple_yaml(Path("metadata.yaml"))

    assert metadata["name"] == "astrbot_plugin_auto_skills"
    assert metadata["version"] == "1.0.0"
    assert metadata["author"] == "cyilin36"
    assert metadata["repo"] == "https://github.com/cyilin36/astrbot_plugin_auto_skills"
    for field in ["name", "desc", "version", "author"]:
        assert metadata.get(field)


def test_plugin_package_uses_relative_internal_imports():
    for path in [Path("main.py"), *Path("auto_skills").glob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.startswith("auto_skills")
            ):
                raise AssertionError(f"{path} uses top-level internal import: {node.module}")
