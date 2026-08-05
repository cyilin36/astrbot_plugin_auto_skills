# Auto Skills for AstrBot

Auto Skills 是一个 AstrBot 插件，用来在 Agent 对话结束后自动复盘，把可复用的流程、规则和经验沉淀成 **当前会话 workspace Skill**。

仓库地址：<https://github.com/cyilin36/astrbot_plugin_auto_skills>

> 要求 AstrBot **>= 4.27.1**。2.x 与 1.x 不兼容：Skill 不再写入全局 `data/skills/`。

## 作用

适合让机器人逐步积累长期有用的上下文，例如：

- 固定工作流：日报、周报、排查步骤、常用操作流程
- 可复用规则：某个会话里的固定回复风格、触发条件、注意事项
- 避坑经验：环境限制、工具使用顺序、验证命令和失败处理方式

插件不修改 AstrBot 源码。生成的 Skill 写入当前 UMO 的 workspace：

```text
data/workspaces/{normalized_umo}/skills/<skill-name>/SKILL.md
```

插件自己的状态和备份写入：

```text
data/plugin_data/astrbot_plugin_auto_skills/
```

## 与 AstrBot 4.27.1 的关系

AstrBot 4.27.1 已原生支持 workspace Skills：

- local 运行环境下，每次请求会扫描当前 workspace 的 `skills/`
- 合法 Skill 会自动注入本次请求的 Skills 清单
- 不同 UMO / project workspace 天然隔离
- 同名时，workspace Skill 优先于全局 / 插件 / sandbox Skill

因此本插件 **不再**：

- 写入 `data/skills/`
- 手工 `on_llm_request` 注入
- 全局激活 Skill
- 同步 sandbox
- 拦截通用工具访问 Skill 目录

Skill 的写作与校验对齐内置 **skill-creator** 规范。

## 安装

把本插件放到 AstrBot 插件目录：

```text
data/plugins/astrbot_plugin_auto_skills
```

然后在 AstrBot WebUI 重新加载插件，或重启 AstrBot。

## 使用方式

启用后，插件会在 Agent 回合结束后按配置频率后台复盘。模型判断当前对话中是否出现了值得长期保存的流程、规则或经验；如果需要，会在当前 workspace 的 `skills/` 下创建或更新 Skill。

可用命令（管理员）：

- `/autoskill status`：查看插件状态、当前 workspace 路径和最近一次复盘结果
- `/autoskill list`：列出当前 workspace 的 Skill，并标记本插件管理的项
- `/autoskill view <name>`：查看某个托管 Skill 的状态
- `/autoskill rollback <name>`：回滚到最近备份
- `/autoskill delete <name>`：删除托管 Skill、状态记录和对应备份

LLM 工具：

- `auto_skill_read`：读取当前 workspace Skill
- `auto_skill_create`：创建 workspace Skill；同名已存在时会覆盖并接管
- `auto_skill_patch`：更新本插件已托管的 Skill
- `auto_skill_delete_request`：请求删除，需要二次确认

## 配置

- `enabled`：启用或关闭后台自动复盘
- `review_admin_only`：仅管理员对话可触发后台自动复盘，默认开启
- `llm_tool_write_admin_only`：仅管理员可通过 LLM 工具创建或更新 Skill，默认开启
- `delete_admin_only`：仅管理员可删除自动 Skill，默认开启
- `review_every_turns`：同一会话每多少轮 Agent 完成后复盘一次，默认 `10`
- `review_provider_id`：后台复盘使用的模型提供商，留空时使用当前会话提供商
- `max_backups_per_skill`：每个 Skill 最多保留多少份更新备份，默认 `10`

## 重要限制

1. **注入依赖 local runtime**  
   AstrBot 目前只在 `computer_use_runtime=local` 时注入 workspace Skills。sandbox / none 下文件仍会写入，但不会自动进入请求 Skills 清单。

2. **只管当前 workspace**  
   插件不读、不写、不管理全局 `data/skills/`。

3. **覆盖策略**  
   `auto_skill_create` 允许覆盖 workspace 中已有同名 Skill（包括手写 Skill），覆盖前会备份旧 `SKILL.md`，并纳入插件管理。

4. **通用工具直写**  
   Agent 仍可用通用文件工具改当前 workspace。这与 skill-creator 一致。若希望有备份与归属记录，应优先使用 `auto_skill_*` 工具。

5. **旧版 1.x 数据**  
   旧版写在 `data/skills/auto-...` 下的 Skill 不会自动迁移。需要的话请手动复制到对应 workspace 的 `skills/`。

## Skill 规范摘要

- 名称：`^[a-z0-9]+(?:-[a-z0-9]+)*$`，最长 64
- 目录名 = frontmatter `name`
- frontmatter 至少包含 `name`、`description`
- `description` 要同时说明能力和触发条件
- 正文为可执行工作流，不要塞 secrets 或一次性事实
