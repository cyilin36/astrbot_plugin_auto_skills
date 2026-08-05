from __future__ import annotations

import re
from dataclasses import dataclass

# Align with AstrBot builtin skill-creator scripts.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""
    warnings: tuple[str, ...] = ()


def normalize_skill_name(skill_name: str) -> str:
    """Normalize a free-form name into a skill-creator compatible slug."""
    raw = str(skill_name or "").strip().lower()
    raw = raw.replace("_", "-").replace(".", "-").replace(" ", "-")
    raw = re.sub(r"[^a-z0-9-]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if not raw:
        raw = "skill"
    if not raw[0].isalnum():
        raw = f"skill-{raw}".strip("-")
    raw = raw[:64].rstrip("-") or "skill"
    if not _SKILL_NAME_RE.fullmatch(raw):
        # Last-resort collapse to alnum segments.
        parts = [part for part in re.split(r"[^a-z0-9]+", raw) if part]
        raw = "-".join(parts)[:64].strip("-") or "skill"
    return raw


def is_valid_skill_name(skill_name: str) -> bool:
    name = str(skill_name or "")
    return bool(name) and len(name) <= 64 and bool(_SKILL_NAME_RE.fullmatch(name))


def _parse_frontmatter(text: str) -> tuple[dict[str, object], int, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, -1, "SKILL.md must start with YAML frontmatter"
    end_idx = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_idx = index
            break
    if end_idx is None:
        return {}, -1, "SKILL.md frontmatter is not closed"

    # Prefer PyYAML when available (AstrBot runtime has it); fall back to simple parse.
    frontmatter_text = "\n".join(lines[1:end_idx])
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(payload, dict):
            return {}, end_idx, "frontmatter must be a YAML mapping"
        return payload, end_idx, None
    except Exception:
        result: dict[str, object] = {}
        for raw_line in frontmatter_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                return {}, end_idx, f"Invalid frontmatter line: {raw_line}"
            key, value = line.split(":", 1)
            key = key.strip()
            if not key:
                return {}, end_idx, f"Invalid frontmatter line: {raw_line}"
            result[key] = value.strip().strip("\"'")
        return result, end_idx, None


def rewrite_frontmatter_name(markdown: str, skill_name: str) -> str:
    """Force frontmatter name to match the skill directory name."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return (
            f"---\nname: {skill_name}\ndescription: Auto-generated AstrBot Skill.\n---\n\n"
            f"{markdown.lstrip()}"
        )
    end_idx = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_idx = index
            break
    if end_idx is None:
        return markdown
    replaced = False
    for index in range(1, end_idx):
        if lines[index].lstrip().startswith("name:"):
            lines[index] = f"name: {skill_name}"
            replaced = True
            break
    if not replaced:
        lines.insert(1, f"name: {skill_name}")
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


def validate_skill_markdown(
    skill_name: str,
    markdown: str,
    *,
    max_skill_chars: int = 100000,
    max_description_chars: int = 1024,
) -> ValidationResult:
    if not is_valid_skill_name(skill_name):
        return ValidationResult(
            False,
            "Skill name must be at most 64 characters and use lowercase letters, "
            "digits, and single hyphen separators",
        )
    if len(markdown) > max_skill_chars:
        return ValidationResult(False, "SKILL.md exceeds maximum length")

    frontmatter, end_idx, parse_error = _parse_frontmatter(markdown)
    if parse_error:
        return ValidationResult(False, parse_error)

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if name != skill_name:
        return ValidationResult(False, "Frontmatter name must match skill name")
    if not isinstance(description, str) or not description.strip():
        return ValidationResult(False, "Frontmatter must include a non-empty description")
    if len(description.strip()) > max_description_chars:
        return ValidationResult(False, "Description exceeds maximum length")

    body = "\n".join(markdown.splitlines()[end_idx + 1 :]).strip()
    if not body:
        return ValidationResult(False, "SKILL.md body cannot be empty")

    warnings: list[str] = []
    extra_keys = sorted(set(frontmatter) - {"name", "description"})
    if extra_keys:
        warnings.append(
            "frontmatter contains optional keys not used for AstrBot discovery: "
            + ", ".join(str(key) for key in extra_keys)
        )
    return ValidationResult(True, warnings=tuple(warnings))
