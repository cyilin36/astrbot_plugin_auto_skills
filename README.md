# astrbot_plugin_auto_skills

Auto Skills 是一个独立的 AstrBot 插件，用于在 Agent 对话结束后自动复盘，把可复用的流程、规则和经验沉淀成 AstrBot `SKILL.md`。

仓库地址：<https://github.com/cyilin36/astrbot_plugin_auto_skills>

## 用途

这个插件适合把长期有用的对话经验自动整理成 Skill，例如：

- 固定工作流：日报、周报、排查步骤、常用操作流程。
- 可复用规则：某个群或私聊里的固定回复风格、触发条件、注意事项。
- 避坑经验：环境限制、工具使用顺序、验证命令和失败处理方式。

插件不会修改 AstrBot 源码。生成的 Skill 写入 AstrBot 运行数据目录 `data/skills/`，插件自己的状态和备份写入 `data/plugin_data/astrbot_plugin_auto_skills/`。

## 安装

把本目录放到 AstrBot 插件目录：

```text
data/plugins/astrbot_plugin_auto_skills
```

然后在 AstrBot WebUI 重新加载插件，或重启 AstrBot。

## metadata.yaml

本插件使用 AstrBot 文档要求的标准元数据字段：

```yaml
name: astrbot_plugin_auto_skills
desc: Automatically creates and updates AstrBot Skills after successful Agent turns.
version: 1.0.0
author: cyilin36
repo: https://github.com/cyilin36/astrbot_plugin_auto_skills
astrbot_version: ">=4.23.1"
```

其中 `name`、`desc`、`version`、`author` 是 AstrBot 必需字段，GitHub 仓库地址放在 `repo` 字段。

## 工作方式

- 监听 `on_agent_done`，在 Agent 回合结束后按配置频率后台复盘。
- 调用配置的模型提供商判断是否需要创建、更新或删除自动 Skill。
- 通过 `auto_skill_create`、`auto_skill_patch`、`auto_skill_delete_request` 管理自动 Skill。
- 生成的 Skill 写入 `data/skills/<internal_skill_name>/SKILL.md`。
- 每个自动 Skill 都记录所属 UMO，默认只在当前 UMO 会话动态注入。
- 默认不把自动生成的 Skill 激活到 AstrBot 全局 active Skills，避免其他会话看到或使用。
- 更新或删除前会备份旧 `SKILL.md`，并按配置清理过旧备份。

## UMO 隔离

UMO 使用 AstrBot 的 `event.unified_msg_origin`，例如：

```text
Alice:GroupMessage:374027358
Alice:FriendMessage:2491577028
```

插件会把自动 Skill 的归属记录到 state 中。当前 UMO 只能动态注入、查看、回滚和删除自己拥有的自动 Skill。其他 UMO 即使知道内部 Skill 名，也会被插件拒绝。

## Skill 命名规则

新生成的 Skill 使用更容易识别的内部名：

```text
auto-<umo_label>-<umo_hash>-<display_slug>
```

- `umo_label` 从 UMO 中提取短标签，例如 `Alice:GroupMessage:374027358` 会变成 `group-374027358`，`Alice:FriendMessage:2491577028` 会变成 `friend-2491577028`。
- `umo_hash` 是 UMO 的 8 位短哈希，用于降低标签重复或格式异常时的冲突风险。
- `display_slug` 是模型或用户提供的 Skill 名称规范化后的可读短名。

例如 `Alice:GroupMessage:374027358` 中创建的 `daily-report` 会生成类似：

```text
auto-group-374027358-50c48fe8-daily-report
```

旧版本已经生成的 Skill 不会自动重命名，避免破坏已有文件、备份和状态记录。

## 配置项

常用配置在 AstrBot WebUI 中显示，字段来自 `_conf_schema.json`。

- `enabled`：启用或关闭后台自动复盘。
- `review_admin_only`：仅管理员对话可触发后台自动复盘，默认开启。
- `llm_tool_write_admin_only`：仅管理员可通过 LLM 工具创建或更新 Skill，默认开启。
- `delete_admin_only`：仅管理员可删除自动 Skill，默认开启。
- `review_every_turns`：同一会话每多少轮 Agent 完成后复盘一次，默认 `10`。
- `review_provider_id`：后台复盘使用的模型提供商，留空时使用当前会话提供商。
- `global_activate_generated_skills`：是否全局激活自动生成的 Skill，默认关闭。
- `protect_skills_from_general_tools`：是否阻止通用工具直接访问 `data/skills/`，默认开启。
- `max_backups_per_skill`：每个 Skill 最多保留多少份备份，默认 `10`。

## 使用后的副作用与限制

启用本插件后，`data/skills/` 会被视为 AstrBot 的受控 Skill 存储区。为了维持 UMO 隔离，Agent 不应再通过通用文件读取、grep、Shell、Python 或其他直接文件操作访问、搜索、创建、编辑、覆盖、移动、重命名或删除 `data/skills/` 下的内容。

当 `protect_skills_from_general_tools` 开启时，插件会尽力拦截明显针对 `data/skills` 的通用工具访问，包括：

- `astrbot_file_read_tool`
- `astrbot_grep_tool`
- `astrbot_execute_shell`
- `astrbot_execute_python`
- `astrbot_execute_ipython`
- `astrbot_file_write_tool`
- `astrbot_file_edit_tool`

因此，使用本插件后，模型可能无法直接用这些通用工具查看或搜索 `data/skills/`。这是预期副作用，不是 AstrBot 故障。

如需新增、更新或删除由本插件管理的 Skill，应使用插件提供的受控工具：`auto_skill_create`、`auto_skill_patch` 和 `auto_skill_delete_request`。直接绕过插件改动 `data/skills/` 可能破坏归属记录、备份、激活状态和 UMO 隔离语义。

这些保护主要用于防止误操作，并不等同于完整安全沙箱。管理员仍应避免手动绕过插件直接改动 `data/skills/`。

## 命令

- `/autoskill status`：查看插件状态和最近一次复盘结果。
- `/autoskill list`：列出当前 UMO 的自动 Skill。
- `/autoskill view <name>`：查看当前 UMO 中某个自动 Skill 的状态。
- `/autoskill rollback <name>`：回滚当前 UMO 中某个自动 Skill 到最近备份。
- `/autoskill delete <name>`：删除当前 UMO 中某个自动 Skill，删除前自动备份。

## 安全边界

本插件只管理自己创建并记录到 state 的自动 Skill，不会主动修改用户手写或其他插件提供的 Skill。

插件级通用工具拦截是防误操作机制，不是强安全边界。真正阻止任意 Python、Shell 或文件工具访问 `data/skills/`，需要 AstrBot 核心工具权限或运行环境权限配合。
