# Auto Skills for AstrBot

Auto Skills 是一个 AstrBot 插件，用来在 Agent 对话结束后自动复盘，把可复用的流程、规则和经验沉淀成 AstrBot Skill。

仓库地址：<https://github.com/cyilin36/astrbot_plugin_auto_skills>

## 作用

这个插件适合让机器人逐步积累长期有用的上下文，例如：

- 固定工作流：日报、周报、排查步骤、常用操作流程。
- 可复用规则：某个会话里的固定回复风格、触发条件、注意事项。
- 避坑经验：环境限制、工具使用顺序、验证命令和失败处理方式。

插件不会修改 AstrBot 源码。生成的 Skill 写入 AstrBot 运行数据目录 `data/skills/`，插件自己的状态和备份写入 `data/plugin_data/astrbot_plugin_auto_skills/`。

## 安装

把本插件放到 AstrBot 插件目录：

```text
data/plugins/astrbot_plugin_auto_skills
```

然后在 AstrBot WebUI 重新加载插件，或重启 AstrBot。

## 使用方式

启用后，插件会在 Agent 回合结束后按配置频率后台复盘。模型判断当前对话中是否出现了值得长期保存的流程、规则或经验；如果需要，会通过受控工具创建、更新或删除自动 Skill。

默认情况下，自动生成的 Skill 不会作为 AstrBot 全局 active Skill 注入所有会话。插件会记录每个自动 Skill 的会话来源，并只在对应会话中动态注入，减少不同会话之间互相影响。

可用命令：

- `/autoskill status`：查看插件状态和最近一次复盘结果。
- `/autoskill list`：列出当前会话可管理的自动 Skill。
- `/autoskill view <name>`：查看当前会话中某个自动 Skill 的状态。
- `/autoskill rollback <name>`：回滚当前会话中某个自动 Skill 到最近备份。
- `/autoskill delete <name>`：删除当前会话中某个自动 Skill，并清理状态记录和对应备份目录。

插件也提供 LLM 工具给 Agent 使用：

- `auto_skill_read`：读取当前会话可访问的自动 Skill，或没有插件归属记录的全局 Skill。
- `auto_skill_create`：创建当前会话的自动 Skill。
- `auto_skill_patch`：更新当前会话拥有的自动 Skill。
- `auto_skill_delete_request`：请求删除当前会话拥有的自动 Skill，需要二次确认。

## 配置

常用配置可以在 AstrBot WebUI 中调整：

- `enabled`：启用或关闭后台自动复盘。
- `review_admin_only`：仅管理员对话可触发后台自动复盘，默认开启。
- `llm_tool_write_admin_only`：仅管理员可通过 LLM 工具创建或更新 Skill，默认开启。
- `delete_admin_only`：仅管理员可删除自动 Skill，默认开启。
- `review_every_turns`：同一会话每多少轮 Agent 完成后复盘一次，默认 `10`。
- `review_provider_id`：后台复盘使用的模型提供商，留空时使用当前会话提供商。
- `global_activate_generated_skills`：是否全局激活自动生成的 Skill，默认关闭。
- `protect_skills_from_general_tools`：是否尽力阻止通用工具直接访问 `data/skills/`，默认开启。
- `max_backups_per_skill`：每个 Skill 最多保留多少份更新备份，默认 `10`。

## 副作用与限制

启用本插件后，`data/skills/` 会被视为受控 Skill 存储区。为了维持会话隔离，Agent 不应再通过通用文件读取、grep、Shell、Python 或其他直接文件操作访问、搜索、创建、编辑、覆盖、移动、重命名或删除 `data/skills/` 下的内容。

当 `protect_skills_from_general_tools` 开启时，插件会尽力拦截明显针对 `data/skills/` 的通用工具访问，包括文件读取、搜索、Shell、Python、文件写入和文件编辑工具。因此，模型可能无法直接用这些通用工具查看或搜索 `data/skills/`。这是预期副作用，不是 AstrBot 故障。

如果需要让模型读取 Skill 内容，应使用 `auto_skill_read`。如果需要新增、更新或删除由本插件管理的 Skill，应使用 `auto_skill_create`、`auto_skill_patch` 和 `auto_skill_delete_request`。

更新自动 Skill 前会备份旧 `SKILL.md`，并按配置清理过旧备份。确认删除自动 Skill 后，会删除 Skill 文件、插件状态记录和对应备份目录；删除后不能再通过插件回滚。

插件只管理自己创建并记录到状态文件里的自动 Skill，不会主动修改用户手写或其他插件提供的 Skill。通用工具拦截主要用于防止误操作，不等同于完整安全沙箱；真正的强隔离仍需要 AstrBot 核心权限策略或运行环境权限配合。
