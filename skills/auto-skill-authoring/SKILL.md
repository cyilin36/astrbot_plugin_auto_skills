---
name: auto-skill-authoring
description: Use when creating, updating, deleting, reviewing, or discussing AstrBot Skills, Auto Skills, SKILL.md, or files under data/skills.
---

# Auto Skill Authoring

Use this skill whenever the task involves AstrBot Skills, Auto Skills, `SKILL.md`, or `data/skills`.

## Rules

1. `data/skills/` is managed storage. Do not directly create, edit, overwrite, move, rename, or delete files there.
2. Generic filesystem tools, shell commands, and Python code are not authorized for Skill lifecycle writes.
3. To create a Skill, call `auto_skill_create`.
4. To update a Skill owned by Auto Skills, call `auto_skill_patch`.
5. To request deletion, call `auto_skill_delete_request`.
6. Reading existing `SKILL.md` files is allowed for understanding and patch preparation.
7. Generated skills are written to AstrBot's user skills directory, not this plugin's `skills/` directory.
8. The plugin's own `skills/` directory is read-only in AstrBot and exists only to explain this mechanism.
9. A generated skill should capture durable procedural knowledge: reusable workflows, debugging paths, verification steps, and pitfalls.
10. Do not create skills for one-off facts, secrets, temporary environment failures, or private user details.
11. The plugin only updates skills it previously created and recorded as plugin-owned.

## Docker Note

After writing `data/skills/<name>/SKILL.md`, the plugin calls AstrBot's `SkillManager().set_skill_active(name, True)`. This updates `data/skills.json`, which is important when `data/` is mounted as a Docker volume.
