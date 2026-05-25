# astrbot_plugin_auto_skills 交接文档

## 当前目标

开发一个独立 AstrBot 插件 `astrbot_plugin_auto_skills`，参考 Hermes Agent 的后台 self-improvement review 思路，在 AstrBot Agent 回合结束后自动判断是否需要创建或更新 AstrBot Skill。

插件必须是独立插件，不能修改 AstrBot 主仓库。

## 绝对约束

- 不能修改 `/Users/cyilin/dev/AstrBot` 下任何源码、文档、配置。
- 所有插件实现文件只能放在 `/Users/cyilin/dev/astrbot_plugin_auto_skills`。
- 生成的 Skill 不能写入插件自身的 `skills/` 目录。
- 生成的 Skill 必须写入 AstrBot 运行时数据目录：`data/skills/<skill_name>/SKILL.md`。
- 写入或更新 Skill 后必须调用 `SkillManager().set_skill_active(skill_name, True)`。
- 这样 Docker 场景下挂载的 `data/skills.json` 会记录该 Skill 为 active。
- 插件只能自动更新自己创建、并记录在插件 `state.json` 中的 Skill。
- v1 不做自动删除。
- v1 不做自动合并。
- v1 不依赖 Shipyard Neo。

## 已完成调研

### Hermes Agent

已调研 `NousResearch/hermes-agent`，临时 clone 路径是：

`/var/folders/n8/kj63fr3j00n1078pgzh8g17h0000gn/T/opencode/hermes-agent`

关键参考点：

- `agent/conversation_loop.py`：触发 background review。
- `agent/background_review.py`：后台 review agent 和 review prompt。
- `tools/skill_manager_tool.py`：创建、更新 Skill 的实现参考。
- `tools/skill_provenance.py`：标记 background review 来源。
- `tools/skill_usage.py`：记录 agent-created skill。
- `agent/curator.py`：后续合并、归档思路。v1 不实现这部分。

### AstrBot

已调研 `/Users/cyilin/dev/AstrBot`。

关键结论：

- AstrBot 支持 `data/skills` 作为用户可写 Skill 目录。
- 插件内置 `skills/` 是只读说明来源，不能作为生成结果目录。
- `SkillManager` 负责读取、维护 `skills.json`。
- `SkillManager().set_skill_active(name, True)` 可主动把 Skill 写入 `data/skills.json` 并设为 active。
- `on_agent_done` 可用于 Agent 回合完成后触发后台 review。
- 插件内可用 `self.context.llm_generate(...)` 调用 LLM。
- active skills 会注入 AstrBot 主 Agent prompt。

相关 AstrBot 文件：

- `/Users/cyilin/dev/AstrBot/astrbot/core/skills/skill_manager.py`
- `/Users/cyilin/dev/AstrBot/astrbot/core/utils/astrbot_path.py`
- `/Users/cyilin/dev/AstrBot/astrbot/core/astr_main_agent.py`
- `/Users/cyilin/dev/AstrBot/docs/zh/dev/star/plugin.md`
- `/Users/cyilin/dev/AstrBot/docs/zh/dev/star/plugin-new.md`
- `/Users/cyilin/dev/AstrBot/docs/zh/use/skills.md`
- `/Users/cyilin/dev/AstrBot/docs/zh/use/computer.md`

## 设计决策

- 使用独立插件方案，不改 AstrBot core。
- 自动创建、自动更新，不需要人工审批。
- 只更新插件自己创建且在 `state.json` 标记 owned 的 Skill。
- 写入目标是 AstrBot 数据目录 `data/skills`。
- 写入后调用 `SkillManager().set_skill_active(skill_name, True)`，确保 Docker 数据卷里的 `data/skills.json` 立即更新。
- 插件自带 `skills/auto-skill-authoring/SKILL.md` 只做说明，不作为生成输出。
- v1 使用 full-file replacement 更新 `SKILL.md`，避免模型 diff 解析复杂度。
- 保留 backup 和 rollback 能力。

## 用户明确要求

- “无论那个版本都不能更改astrbot的代码，只允许生产插件。”
- “实际使用中，尤其是docker使用中，data目录下会有一个skills.josn的文件，是记录着astrbot上的skils。是不是生产的skills也得记录到这里？”
- 用户确认选择“全自动发布”。
- 后来用户明确要求停止继续实现，改为把代码、项目进度、对话总结写成交接文档，方便新开对话继续。

注意：用户写过 `skills.josn`，实际文件名应为 `skills.json`。

## 当前仓库状态

插件目录：

`/Users/cyilin/dev/astrbot_plugin_auto_skills`

该目录已经初始化为独立 git 仓库：

`/Users/cyilin/dev/astrbot_plugin_auto_skills/.git`

AstrBot 主仓库状态已检查过，未被修改：

```bash
git -C /Users/cyilin/dev/AstrBot status --short
```

输出为空。

插件仓库当前文件基本都是未跟踪文件，未提交 commit。

## 已创建文件

当前已创建这些文件：

- `metadata.yaml`
- `_conf_schema.json`
- `main.py`
- `auto_skills/__init__.py`
- `auto_skills/config.py`
- `tests/test_config.py`
- `docs/superpowers/plans/2026-05-25-auto-skills-plugin.md`
- `HANDOFF.md`

## 已完成实现

只完成了配置和插件骨架。

### `metadata.yaml`

内容概要：

- `name: astrbot_plugin_auto_skills`
- `desc: Automatically creates and updates AstrBot Skills after successful Agent turns.`
- `version: 0.1.0`
- `repo: ""`
- `astrbot_version: ">=4.23.1"`

### `_conf_schema.json`

已定义配置项：

- `enabled`
- `admin_only`
- `review_every_turns`
- `review_provider_id`
- `max_concurrent_reviews`
- `review_timeout_seconds`
- `max_skill_chars`
- `max_description_chars`
- `auto_sync_sandbox`

### `auto_skills/config.py`

已实现：

- `AutoSkillsConfig`
- `AutoSkillsConfig.from_mapping(...)`
- bool 配置解析。
- 正整数配置解析。
- 默认值保护。

默认值：

- `enabled=True`
- `admin_only=True`
- `review_every_turns=10`
- `review_provider_id=""`
- `max_concurrent_reviews=1`
- `review_timeout_seconds=60`
- `max_skill_chars=100000`
- `max_description_chars=1024`
- `auto_sync_sandbox=True`

### `main.py`

目前只是最小插件入口：

- `AutoSkillsPlugin` 继承 `Star`。
- `__init__` 接收 `context` 和可选 `config`。
- 保存 `raw_config`。
- 构造 `AutoSkillsConfig`。
- `on_agent_done` 是空实现。
- `terminate` 只写 unload 日志。

## 已完成测试

测试文件：

`tests/test_config.py`

测试内容：

- 默认配置值正确。
- 非法数字配置会回退默认值。

一开始系统找不到 `pytest`：

```text
pytest: command not found
```

后来确认虚拟环境 pytest 在：

`/Users/cyilin/dev/.venv/bin/pytest`

正确测试命令：

```bash
PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills /Users/cyilin/dev/.venv/bin/pytest tests/test_config.py -q
```

结果：

```text
2 passed in 0.00s
```

## 尚未实现

- `auto_skills/models.py`
- `auto_skills/state_store.py`
- `auto_skills/skill_store.py`
- `auto_skills/review_runner.py`
- `tests/test_state_store.py`
- `tests/test_skill_store.py`
- `tests/test_review_runner.py`
- `tests/test_plugin_flow.py`
- 插件后台 review 调度。
- LLM review prompt 构造。
- review JSON 解析。
- 自动写入 `data/skills/<skill_name>/SKILL.md`。
- 调用 `SkillManager().set_skill_active(skill_name, True)` 更新 `data/skills.json`。
- 插件 state.json owned 记录。
- 备份。
- rollback。
- `/autoskill status`。
- `/autoskill list`。
- `/autoskill view <name>`。
- `/autoskill rollback <name>`。
- 插件说明 Skill：`skills/auto-skill-authoring/SKILL.md`。
- `README.md`。
- 全量测试。
- `python -m compileall`。
- git commit。

## 可继续使用的实施计划

完整计划在：

`/Users/cyilin/dev/astrbot_plugin_auto_skills/docs/superpowers/plans/2026-05-25-auto-skills-plugin.md`

这个计划拆成 8 个 Task，但用户后来表达不想再被频繁打断。新对话建议直接按计划快速实现，不要每个 Task 后长篇总结。

## 建议下一步

如果新对话继续开发，建议直接实现以下最小闭环：

1. `StateStore`：保存插件 owned Skill 元数据到 `state.json`。
2. `SkillStore`：校验 Skill 名称和 frontmatter，写入 `data/skills/<name>/SKILL.md`，调用 `SkillManager().set_skill_active(name, True)`，写 state，做备份。
3. `ReviewRunner`：构造 prompt，解析 LLM JSON，支持 `noop/create/patch`。
4. `main.py`：在 `on_agent_done` 中按 cadence 创建后台任务，调用 review，执行 create/patch。
5. 命令：`/autoskill status/list/view/rollback`。
6. `README.md` 和只读说明 Skill。
7. 跑测试和 compileall。
8. 最后确认 AstrBot 主仓库仍无改动。

## 后续测试命令

使用虚拟环境 pytest：

```bash
PYTHONPATH=/Users/cyilin/dev/AstrBot:/Users/cyilin/dev/astrbot_plugin_auto_skills /Users/cyilin/dev/.venv/bin/pytest /Users/cyilin/dev/astrbot_plugin_auto_skills/tests -q
```

语法检查：

```bash
python -m compileall /Users/cyilin/dev/astrbot_plugin_auto_skills
```

确认 AstrBot 主仓库未被修改：

```bash
git -C /Users/cyilin/dev/AstrBot status --short
```

## 当前情绪和协作备注

用户对执行过程非常不满，原因是实现被拆得过碎、频繁停下来总结和询问，没有按用户要求连续写完。

新对话继续时建议：

- 少解释。
- 不要反复总结。
- 不要频繁问确认。
- 直接改代码、跑测试、给最终结果。
- 牢记不要修改 `/Users/cyilin/dev/AstrBot`。
