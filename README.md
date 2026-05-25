# astrbot_plugin_auto_skills

Auto Skills is a standalone AstrBot plugin that automatically creates and updates reusable `SKILL.md` files after completed Agent turns.

## Install

Place this directory under AstrBot's plugin directory:

```text
data/plugins/astrbot_plugin_auto_skills
```

Then reload plugins from AstrBot WebUI or restart AstrBot.

## Behavior

- Listens to `on_agent_done`.
- Runs a background LLM review every configured number of completed turns.
- Writes generated Skills to `data/skills/<skill_name>/SKILL.md`.
- Calls `SkillManager().set_skill_active(skill_name, True)` after writing so `data/skills.json` records the generated Skill as active.
- Saves plugin state and backups under `data/plugin_data/astrbot_plugin_auto_skills`.
- Only auto-updates Skills created by this plugin.

## Commands

- `/autoskill status`
- `/autoskill list`
- `/autoskill view <name>`
- `/autoskill rollback <name>`

## Safety

The first version is full-auto publishing, but it does not delete Skills and does not modify user-authored or plugin-provided Skills.
