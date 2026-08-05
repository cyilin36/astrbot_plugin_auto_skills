---
name: auto-skill-authoring
description: Use when creating, updating, deleting, reviewing, or discussing AstrBot workspace Skills, Auto Skills, SKILL.md, or files under the current session workspace skills directory.
---

# Auto Skill Authoring

Use this skill whenever the task involves AstrBot workspace Skills, Auto Skills, or `SKILL.md` files under the current session workspace.

## Where Skills live

- Auto Skills writes to the **current UMO workspace**: `skills/<skill-name>/SKILL.md`.
- AstrBot injects workspace Skills automatically on each request when `computer_use_runtime=local`.
- Do **not** write global `data/skills/` through this plugin. Global installation is outside Auto Skills scope.

## Rules

1. Prefer the Auto Skills tools for managed lifecycle changes:
   - `auto_skill_create` to create or overwrite a workspace Skill
   - `auto_skill_patch` to update a Skill already owned by Auto Skills
   - `auto_skill_delete_request` to request deletion with confirmation
   - `auto_skill_read` to inspect current workspace Skills
2. Follow AstrBot skill-creator conventions:
   - Name: lowercase letters, digits, single hyphens only (`my-skill`)
   - Directory name equals frontmatter `name`
   - Frontmatter needs `name` and `description`
   - `description` must include capability **and** concrete trigger conditions
   - Body uses imperative operational instructions
3. Capture durable procedural knowledge only: reusable workflows, debugging paths, verification steps, constraints, and pitfalls.
4. Do not create Skills for one-off facts, secrets, temporary environment failures, or private user details.
5. Prefer patching an existing class-level Skill over creating many narrow one-session Skills.
6. Generic filesystem tools may still touch the current workspace. That is allowed, but managed create/update/delete should use Auto Skills tools so backups and ownership are recorded.

## After writing

AstrBot discovers workspace Skills on the next local-runtime request. No global activation or sandbox sync is required for workspace Skills.
