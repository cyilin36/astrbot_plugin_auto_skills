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
