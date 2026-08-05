# Changelog

## 2.0.0

适配 AstrBot **>= 4.27.1**。与 1.x 不兼容。

### 定位

本版本把插件收敛为：

> **自动复盘对话，并提醒主 Agent 用内置 skill-creator 更新当前 workspace Skills。**

真正创建 / 更新 / 校验 Skill 由 AstrBot 内置 **skill-creator** 完成。本插件不写 `SKILL.md`。

### 重大变更

- Skill 目标从全局 `data/skills/` 改为当前 UMO workspace：
  `data/workspaces/{normalized_umo}/skills/<skill-name>/SKILL.md`
- 删除全部写 Skill 的 LLM 工具：
  - `auto_skill_create`
  - `auto_skill_patch`
  - `auto_skill_read`
  - `auto_skill_delete_request`
- 删除插件自建 authoring skill 与备份/回滚写链路
- 后台复盘结果改为「待处理建议」：
  - 写入 `data/plugin_data/astrbot_plugin_auto_skills/state.json`
  - 在随后若干轮 `on_llm_request` 中注入 skill-creator 提醒和草稿
- 去掉全局激活、sandbox 同步、`data/skills` 工具拦截
- 最低 AstrBot 版本：`>=4.27.1`

### 保留能力

- `on_agent_done` 按频率后台复盘
- 只读扫描当前 workspace `skills/`
- 管理命令：
  - `/autoskill status`
  - `/autoskill list`
  - `/autoskill pending`
  - `/autoskill clear`

### 配置

保留：

- `enabled`
- `review_admin_only`
- `review_every_turns`
- `review_provider_id`
- `max_concurrent_reviews`
- `review_timeout_seconds`

新增：

- `pending_inject_turns`：建议提醒注入轮数，默认 `3`
- `notify_on_suggestion`：是否给用户发提示消息，默认 `false`

删除：

- `llm_tool_write_admin_only`
- `delete_admin_only`
- `max_skill_chars`
- `max_description_chars`
- `max_backups_per_skill`
- `global_activate_generated_skills`
- `protect_skills_from_general_tools`
- `auto_sync_sandbox`

### 不做的迁移

- 不迁移 1.x 的 `data/skills/auto-...`
- 不接管或改写用户/skill-creator 已写入的 workspace Skills

## 1.x

1.x 会在复盘后直接写全局 `data/skills/`，并提供 `auto_skill_*` 工具管理生命周期。该模式已废弃。
