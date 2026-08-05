# Auto Skills for AstrBot

Auto Skills 会在 Agent 对话结束后自动复盘，并在需要时**提醒主 Agent 用内置 skill-creator 更新当前 workspace Skills**。

仓库地址：<https://github.com/cyilin36/astrbot_plugin_auto_skills>

> 要求 AstrBot **>= 4.27.1**。2.x 与 1.x 不兼容。

## 一句话分工

| 角色 | 做什么 |
|---|---|
| **本插件** | 后台复盘 → 判断要不要沉淀 → 生成建议草稿 → 提醒主 Agent |
| **skill-creator** | 真正创建 / 更新 / 校验 workspace `skills/<name>/SKILL.md` |
| **AstrBot 核心** | local runtime 下自动发现并注入 workspace Skills |

本插件 **不写** Skill 文件，也 **不提供** `auto_skill_create` 一类写文件工具。

## 工作流程

```text
Agent 回合结束
    → 每 N 轮后台复盘一次
    → 若有可复用流程/规则/坑点
    → 写入待处理建议（含 SKILL.md 草稿）
    → 接下来若干轮对话的 system prompt 注入提醒
    → 主 Agent 读取 skill-creator，按提醒创建或更新 workspace Skill
```

目标路径始终是当前 UMO workspace：

```text
data/workspaces/{normalized_umo}/skills/<skill-name>/SKILL.md
```

插件状态写入：

```text
data/plugin_data/astrbot_plugin_auto_skills/state.json
```

## 安装

```text
data/plugins/astrbot_plugin_auto_skills
```

在 AstrBot WebUI 重新加载插件，或重启 AstrBot。

## 命令（管理员）

- `/autoskill status`：复盘配置、当前 workspace、最近一次复盘、待处理建议
- `/autoskill list`：只读列出当前 workspace 已有 Skills
- `/autoskill pending`：查看待处理的 skill-creator 建议和草稿预览
- `/autoskill clear`：清除当前会话待处理建议

## 配置

- `enabled`：启用后台复盘提醒
- `review_admin_only`：仅管理员对话触发复盘，默认开启
- `review_every_turns`：同一会话每多少轮复盘一次，默认 `10`
- `review_provider_id`：复盘模型提供商，留空用当前会话提供商
- `pending_inject_turns`：建议产生后，提醒注入多少轮 LLM 请求，默认 `3`
- `notify_on_suggestion`：产生建议时是否给用户发一条提示，默认关闭
- `max_concurrent_reviews` / `review_timeout_seconds`：并发与超时

## 重要限制

1. **真正写 Skill 的是 skill-creator**，不是本插件。
2. workspace Skills 仅在 `computer_use_runtime=local` 时由 AstrBot 自动注入。
3. 本插件不读、不写全局 `data/skills/`。
4. 1.x 写在 `data/skills/auto-...` 的旧数据不会迁移。
5. 复盘是后台任务，失败不影响主对话回复。

## 和 1.x / 早期 2.0 草稿的区别

- 不再把 Skill 写到 `data/skills/`
- 不再提供 `auto_skill_create` / `patch` / `read` / `delete_request`
- 不再做全局激活、sandbox 同步、通用工具拦截
- 只做：复盘 + 提醒 skill-creator 更新当前 workspace
