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
- Writes generated Skills to `data/skills/<internal_skill_name>/SKILL.md`.
- Records each generated Skill's owning UMO and injects it only for that UMO by default.
- Keeps generated Skills inactive in AstrBot's global Skill list by default. Set `global_activate_generated_skills` only if you explicitly want global activation.
- Saves plugin state and backups under `data/plugin_data/astrbot_plugin_auto_skills`.
- Only auto-updates Skills created by this plugin.

## 使用后的副作用与限制

启用本插件后，`data/skills/` 会被视为 AstrBot 的受控 Skill 存储区。为了维持 UMO 隔离，Agent 不应再通过通用文件读取、grep、Shell、Python 或其他直接文件操作访问、搜索、创建、编辑、覆盖、移动、重命名或删除 `data/skills/` 下的内容。

插件会尽力拦截明显针对 `data/skills` 的通用工具访问，包括读取、搜索、写入、编辑、Shell 和 Python 操作。因此，使用本插件后，模型可能无法直接用 `astrbot_file_read_tool`、`astrbot_grep_tool`、`astrbot_execute_shell` 或 `astrbot_execute_python` 查看 `data/skills/`。这是预期副作用，不是 AstrBot 故障。

如需新增、更新或删除由本插件管理的 Skill，应使用插件提供的受控工具：`auto_skill_create`、`auto_skill_patch` 和 `auto_skill_delete_request`。直接绕过插件改动 `data/skills/` 可能破坏归属记录、备份、激活状态和 UMO 隔离语义。

这些保护主要用于防止误操作，并不等同于完整安全沙箱。管理员仍应避免手动绕过插件直接改动 `data/skills/`。

## Commands

- `/autoskill status`
- `/autoskill list`
- `/autoskill view <name>`
- `/autoskill rollback <name>`

## Safety

The first version is full-auto publishing, but it does not delete Skills and does not modify user-authored or plugin-provided Skills.
