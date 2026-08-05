# Changelog

## 2.0.0

适配 AstrBot **>= 4.27.1**。与 1.x 不兼容。

### 重大变更

- Skill 写入目标从全局 `data/skills/` 改为当前 UMO **workspace**：
  `data/workspaces/{normalized_umo}/skills/<skill-name>/SKILL.md`
- 去掉 UMO hash 前缀命名；Skill 名直接使用 skill-creator 规范名
- 去掉 `on_llm_request` 手工注入；改由 AstrBot 原生 `list_workspace_skills` 在 local runtime 下自动注入
- 去掉对 `data/skills/` 的通用工具拦截与托管策略文案
- 去掉全局激活与 sandbox 同步
- 插件状态改为按 UMO 隔离存储（`skills_by_umo`）
- 最低 AstrBot 版本要求：`>=4.27.1`

### 新增

- `auto_skills/workspace_store.py`：workspace 级 create / patch / delete / rollback
- `auto_skills/skill_validator.py`：对齐 skill-creator 的命名与 SKILL.md 校验
- `/autoskill status` 显示当前 workspace / skills 路径，并提示仅 local runtime 会注入

### 行为调整

- `auto_skill_create`：同名 workspace Skill 允许覆盖；覆盖前备份，并纳入插件管理
- `auto_skill_read` / `list`：只看当前 workspace，不读全局 `data/skills/`
- 后台复盘 prompt 改为 skill-creator 导向，只参考当前 workspace Skills
- 命名规则改为 `^[a-z0-9]+(?:-[a-z0-9]+)*$`（最长 64）
- 备份路径：`data/plugin_data/astrbot_plugin_auto_skills/backups/{normalized_umo}/{name}/`

### 删除的配置项

- `global_activate_generated_skills`
- `protect_skills_from_general_tools`
- `auto_sync_sandbox`

### 删除的文件 / 依赖路径

- `auto_skills/skill_store.py`
- 不再写入或依赖 `get_astrbot_skills_path()` / `SkillManager.set_skill_active`

### 不做的迁移

- 不自动迁移 1.x 写在 `data/skills/auto-...` 下的旧 Skill
- 如需保留，请手动复制到对应 workspace 的 `skills/`

### 使用注意

- workspace Skills 目前仅在 `computer_use_runtime=local` 时由 AstrBot 注入请求
- sandbox / none 下文件仍会落盘，但不会自动进入 Skills 清单
- 通用文件工具仍可直接改当前 workspace；需要备份与归属记录时请走 `auto_skill_*`

## 1.x

1.x 将自动 Skill 写入全局 `data/skills/`，通过 state 记录 UMO 归属，并在 `on_llm_request` 中手工注入；同时尽力拦截通用工具直接访问 `data/skills/`。该模式已废弃。
