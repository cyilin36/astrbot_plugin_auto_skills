from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .auto_skills.config import AutoSkillsConfig
from .auto_skills.models import PLUGIN_OWNER
from .auto_skills.review_runner import (
    build_review_system_prompt,
    build_review_user_prompt,
    parse_review_decision,
)
from .auto_skills.skill_validator import normalize_skill_name
from .auto_skills.state_store import StateStore
from .auto_skills.workspace_store import WorkspaceSkillStore


class AutoSkillsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.raw_config = config or {}
        self.config = AutoSkillsConfig.from_mapping(self.raw_config)
        data_root = Path(get_astrbot_plugin_data_path()) / PLUGIN_OWNER
        self.state_store = StateStore(data_root / "state.json")
        self.skill_store = WorkspaceSkillStore(
            self.state_store,
            backup_root=data_root / "backups",
            max_skill_chars=self.config.max_skill_chars,
            max_description_chars=self.config.max_description_chars,
            max_backups_per_skill=self.config.max_backups_per_skill,
            context=context,
        )
        self._review_tasks: set[asyncio.Task] = set()
        self._session_turns: dict[str, int] = {}
        self._review_semaphore: asyncio.Semaphore | None = None
        self._pending_deletes: dict[str, str] = {}
        self.last_review_status: dict[str, Any] = {"action": "none", "error": ""}
        logger.info("Auto Skills plugin loaded (workspace skills mode)")

    def _umo(self, event: AstrMessageEvent) -> str:
        return getattr(event, "unified_msg_origin", "") or "default"

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        return bool(hasattr(event, "is_admin") and event.is_admin())

    def _llm_tool_write_allowed(self, event: AstrMessageEvent) -> bool:
        return not self.config.llm_tool_write_admin_only or self._is_admin(event)

    def _delete_allowed(self, event: AstrMessageEvent) -> bool:
        return not self.config.delete_admin_only or self._is_admin(event)

    def _resolve_current_skill_name(self, event: AstrMessageEvent, skill_name: str) -> str | None:
        requested = str(skill_name or "").strip()
        if not requested:
            return None
        resolved = self.state_store.resolve_skill_name(self._umo(event), requested)
        if resolved:
            return resolved
        normalized = normalize_skill_name(requested)
        return self.state_store.resolve_skill_name(self._umo(event), normalized)

    def _should_review(self, event: AstrMessageEvent, resp: LLMResponse) -> bool:
        if not self.config.enabled:
            return False
        if self.config.review_admin_only and not self._is_admin(event):
            return False
        if not str(getattr(resp, "completion_text", "") or "").strip():
            return False
        umo = self._umo(event)
        count = self._session_turns.get(umo, 0) + 1
        self._session_turns[umo] = count
        return count % self.config.review_every_turns == 0

    def _track_task(self, task: asyncio.Task) -> None:
        self._review_tasks.add(task)
        task.add_done_callback(self._review_tasks.discard)

    def _get_review_semaphore(self) -> asyncio.Semaphore:
        if self._review_semaphore is None:
            self._review_semaphore = asyncio.Semaphore(self.config.max_concurrent_reviews)
        return self._review_semaphore

    def _skill_read_metadata(
        self,
        name: str,
        record: dict[str, Any] | None,
        description: str,
        *,
        path: str = "",
    ) -> str:
        lines = [f"Skill: {name}"]
        if record:
            lines.extend(
                [
                    f"UMO: {record.get('umo')}",
                    f"Version: {record.get('version')}",
                    f"Last action: {record.get('last_action')}",
                    f"Updated at: {record.get('updated_at')}",
                    f"Reason: {record.get('last_reason')}",
                    f"Managed by: {PLUGIN_OWNER}",
                ]
            )
            if record.get("workspace_path"):
                lines.append(f"Path: {record.get('workspace_path')}")
        elif path:
            lines.append(f"Path: {path}")
            lines.append("Managed by: workspace (untracked)")
        lines.append(f"Description: {description}")
        return "\n".join(lines)

    async def _workspace_skills_for_review(self, umo: str) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for name in await self.skill_store.list_workspace_skill_names(umo):
            result.append(
                {
                    "name": name,
                    "description": await self.skill_store.skill_description(umo, name),
                }
            )
        return result

    @filter.on_agent_done()
    async def on_agent_done(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
        resp: LLMResponse,
    ) -> None:
        if not self._should_review(event, resp):
            return None
        task = asyncio.create_task(self._run_review(event, run_context, resp))
        self._track_task(task)
        return None

    async def _run_review(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
        resp: LLMResponse,
    ) -> None:
        _ = run_context
        async with self._get_review_semaphore():
            try:
                umo = self._umo(event)
                workspace_skills = await self._workspace_skills_for_review(umo)
                user_prompt = build_review_user_prompt(
                    user_message=str(getattr(event, "message_str", "") or ""),
                    assistant_response=str(getattr(resp, "completion_text", "") or ""),
                    tool_summaries=[],
                    workspace_skills=workspace_skills,
                    owned_skills=self.state_store.list_skills(umo),
                )
                provider_id = self.config.review_provider_id
                if not provider_id and hasattr(self.context, "get_using_provider"):
                    provider = self.context.get_using_provider(
                        getattr(event, "unified_msg_origin", None)
                    )
                    provider_id = str(getattr(provider, "id", "") or "")
                llm_resp = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=user_prompt,
                        system_prompt=build_review_system_prompt(),
                    ),
                    timeout=self.config.review_timeout_seconds,
                )
                decision = parse_review_decision(
                    str(getattr(llm_resp, "completion_text", "") or "")
                )
                if decision.action in {"create", "patch"}:
                    skill_name = normalize_skill_name(decision.skill_name)
                    if decision.action == "patch":
                        resolved = self._resolve_current_skill_name(event, skill_name)
                        if not resolved:
                            # Fall back to create/overwrite when not owned yet.
                            decision_action = "create"
                        else:
                            skill_name = resolved
                            decision_action = "patch"
                    else:
                        decision_action = "create"
                    result = await self.skill_store.create_or_patch(
                        umo,
                        skill_name,
                        decision.skill_markdown,
                        decision_action,
                        decision.reason,
                    )
                    self.last_review_status = {
                        "action": decision_action,
                        "skill_name": result["name"],
                        "path": result["path"],
                        "overwrote": result.get("overwrote", False),
                        "reason": decision.reason,
                        "error": "",
                    }
                elif decision.action == "delete":
                    await self._handle_review_delete(event, decision.skill_name, decision.reason)
                    self.last_review_status = {
                        "action": "delete",
                        "skill_name": decision.skill_name,
                        "reason": decision.reason,
                        "error": "",
                    }
                else:
                    self.last_review_status = {
                        "action": decision.action,
                        "skill_name": decision.skill_name,
                        "reason": decision.reason,
                        "error": "",
                    }
            except Exception as exc:
                self.last_review_status = {"action": "error", "error": str(exc)}
                logger.warning("Auto Skills review failed: %s", exc)

    async def _handle_review_delete(
        self, event: AstrMessageEvent, skill_name: str, reason: str
    ) -> None:
        if not self._delete_allowed(event):
            raise PermissionError("Only administrators can delete auto-created skills")
        internal_name = self._resolve_current_skill_name(event, skill_name)
        if not internal_name:
            raise PermissionError(f"Skill {skill_name} is not owned by Auto Skills")
        pending_key = self._umo(event)
        if self._pending_deletes.get(pending_key) == internal_name:
            await self.skill_store.delete_owned(
                pending_key, internal_name, reason or "confirmed natural language delete"
            )
            self._pending_deletes.pop(pending_key, None)
            if hasattr(event, "send"):
                await event.send(event.plain_result(f"已删除 workspace Skill：{internal_name}"))
            return
        self._pending_deletes[pending_key] = internal_name
        if hasattr(event, "send"):
            await event.send(
                event.plain_result(f"请再次确认是否删除 workspace Skill：{internal_name}")
            )

    @filter.llm_tool(name="auto_skill_read")
    async def auto_skill_read(
        self, event: AstrMessageEvent, skill_name: str, include_content: bool = True
    ) -> str:
        """读取当前 UMO workspace 下的 Skill。

        Args:
            skill_name(string): 要读取的 Skill 名称。留空时列出当前 workspace 可读取的 Skill。
            include_content(bool): 是否返回完整 SKILL.md 内容。false 时只返回元数据。
        """
        umo = self._umo(event)
        requested = str(skill_name or "").strip()
        try:
            skills_root = await self.skill_store.skills_root(umo)
            if not requested:
                names = await self.skill_store.list_workspace_skill_names(umo)
                if not names:
                    return "当前 workspace 没有 Skill。"
                lines = [f"当前 workspace Skills（{skills_root}）："]
                for name in names:
                    record = self.state_store.get_skill(umo, name)
                    owned = (
                        "managed"
                        if record and record.get("created_by") == PLUGIN_OWNER
                        else "untracked"
                    )
                    lines.append(f"- {name} ({owned})")
                return "\n".join(lines)

            name = normalize_skill_name(requested)
            # Prefer owned alias resolution, but still allow reading untracked workspace skills.
            resolved = self._resolve_current_skill_name(event, requested)
            if resolved:
                name = resolved
            content = await self.skill_store.read_skill_markdown(umo, name)
            record = self.state_store.get_skill(umo, name)
            path = str(skills_root / name / "SKILL.md")
            metadata = self._skill_read_metadata(
                name,
                record if record and record.get("created_by") == PLUGIN_OWNER else None,
                await self.skill_store.skill_description(umo, name),
                path=path,
            )
        except Exception as exc:
            return f"读取 Skill {requested or skill_name} 失败：{exc}"
        if not include_content:
            return metadata
        return f"{metadata}\n\n```markdown\n{content}\n```"

    @filter.llm_tool(name="auto_skill_create")
    async def auto_skill_create(
        self,
        event: AstrMessageEvent,
        skill_name: str,
        skill_markdown: str,
        reason: str,
    ) -> str:
        """在当前 UMO workspace 创建一个 Skill。若同名已存在则覆盖并纳入插件管理。

        Args:
            skill_name(string): Skill 名称，必须与 SKILL.md frontmatter 中的 name 一致，使用小写字母、数字和连字符。
            skill_markdown(string): 完整的 SKILL.md 内容，必须包含 YAML frontmatter 和正文。
            reason(string): 创建这个 Skill 的原因。
        """
        if not self._llm_tool_write_allowed(event):
            return "只有管理员可以创建自动 Skill。"
        try:
            result = await self.skill_store.create_or_patch(
                self._umo(event),
                skill_name,
                skill_markdown,
                "create",
                reason,
            )
        except Exception as exc:
            return f"创建 workspace Skill {skill_name} 失败：{exc}"
        action = "覆盖并接管" if result.get("overwrote") else "创建"
        return f"已{action} workspace Skill：{result['name']}\n路径：{result['path']}"

    @filter.llm_tool(name="auto_skill_patch")
    async def auto_skill_patch(
        self,
        event: AstrMessageEvent,
        skill_name: str,
        skill_markdown: str,
        reason: str,
    ) -> str:
        """更新本插件已经创建并拥有的当前 workspace Skill。

        Args:
            skill_name(string): 要更新的 Skill 名称。
            skill_markdown(string): 更新后的完整 SKILL.md 内容，必须包含 YAML frontmatter 和正文。
            reason(string): 更新这个 Skill 的原因。
        """
        if not self._llm_tool_write_allowed(event):
            return "只有管理员可以更新自动 Skill。"
        try:
            resolved = self._resolve_current_skill_name(event, skill_name)
            if not resolved:
                raise PermissionError(f"Skill {skill_name} is not owned by current UMO")
            result = await self.skill_store.create_or_patch(
                self._umo(event),
                resolved,
                skill_markdown,
                "patch",
                reason,
            )
        except Exception as exc:
            return f"更新 workspace Skill {skill_name} 失败：{exc}"
        return f"已更新 workspace Skill：{result['name']}\n路径：{result['path']}"

    @filter.llm_tool(name="auto_skill_delete_request")
    async def auto_skill_delete_request(
        self,
        event: AstrMessageEvent,
        skill_name: str,
        reason: str,
    ) -> str:
        """请求删除本插件自动创建并拥有的当前 workspace Skill。

        Args:
            skill_name(string): 要删除的 Skill 名称。
            reason(string): 请求删除这个 Skill 的原因。
        """
        if not self._delete_allowed(event):
            return "只有管理员可以删除自动 Skill。"
        try:
            pending_key = self._umo(event)
            internal_name = self._resolve_current_skill_name(event, skill_name)
            confirmed = bool(
                internal_name and self._pending_deletes.get(pending_key) == internal_name
            )
            await self._handle_review_delete(event, skill_name, reason)
        except Exception as exc:
            return f"删除 workspace Skill {skill_name} 失败：{exc}"
        display = internal_name or skill_name
        if confirmed:
            return f"已删除 workspace Skill：{display}"
        return f"请再次确认是否删除 workspace Skill：{display}"

    @filter.command_group("autoskill")
    def autoskill(self):
        """管理 Auto Skills 自动创建的 workspace Skills。"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("status")
    async def autoskill_status(self, event: AstrMessageEvent):
        """查看 Auto Skills 插件状态、复盘频率和最近一次复盘结果。"""
        umo = self._umo(event)
        try:
            workspace_root = await self.skill_store.resolve_workspace_root(umo)
            skills_root = workspace_root / "skills"
        except Exception as exc:
            workspace_root = f"<error: {exc}>"
            skills_root = workspace_root
        yield event.plain_result(
            "Auto Skills (workspace mode):\n"
            f"enabled={self.config.enabled}\n"
            f"review_every_turns={self.config.review_every_turns}\n"
            f"umo={umo}\n"
            f"workspace={workspace_root}\n"
            f"skills_root={skills_root}\n"
            "note=workspace skills are injected by AstrBot only when computer_use_runtime=local\n"
            f"last={self.last_review_status}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("list")
    async def autoskill_list(self, event: AstrMessageEvent):
        """列出当前 workspace 中的 Skill，并标记本插件管理的项。"""
        umo = self._umo(event)
        names = await self.skill_store.list_workspace_skill_names(umo)
        if not names:
            yield event.plain_result("当前 workspace 没有 Skill。")
            return
        lines = []
        for name in names:
            record = self.state_store.get_skill(umo, name)
            if record and record.get("created_by") == PLUGIN_OWNER:
                lines.append(
                    f"- {name} [managed] v{record.get('version', 0)} "
                    f"{record.get('last_action', '')}"
                )
            else:
                lines.append(f"- {name} [untracked]")
        skills_root = await self.skill_store.skills_root(umo)
        yield event.plain_result(f"Workspace skills ({skills_root}):\n" + "\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("view")
    async def autoskill_view(self, event: AstrMessageEvent, name: str):
        """查看某个自动创建 Skill 的版本、更新时间和最近变更原因。"""
        internal_name = self._resolve_current_skill_name(event, name)
        if not internal_name:
            yield event.plain_result(f"Skill {name} 不属于当前 UMO 的 Auto Skills 管理范围。")
            return
        record = self.state_store.get_skill(self._umo(event), internal_name)
        if not record or record.get("created_by") != PLUGIN_OWNER:
            yield event.plain_result(f"Skill {name} is not owned by Auto Skills.")
            return
        yield event.plain_result(
            f"{internal_name}\n"
            f"version: {record.get('version')}\n"
            f"last_action: {record.get('last_action')}\n"
            f"updated_at: {record.get('updated_at')}\n"
            f"workspace_path: {record.get('workspace_path')}\n"
            f"reason: {record.get('last_reason')}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("rollback")
    async def autoskill_rollback(self, event: AstrMessageEvent, name: str):
        """将某个自动创建 Skill 回滚到最近一次备份。"""
        internal_name = self._resolve_current_skill_name(event, name)
        if not internal_name:
            yield event.plain_result(f"Rollback failed for {name}: 该 Skill 不属于当前 UMO。")
            return
        try:
            backup_path = await self.skill_store.rollback_latest(self._umo(event), internal_name)
        except Exception as exc:
            yield event.plain_result(f"Rollback failed for {name}: {exc}")
            return
        yield event.plain_result(f"Rolled back {internal_name} from {backup_path}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("delete")
    async def autoskill_delete(self, event: AstrMessageEvent, name: str):
        """直接删除本插件自动创建并拥有的 Skill、状态记录和对应备份。"""
        internal_name = self._resolve_current_skill_name(event, name)
        if not internal_name:
            yield event.plain_result(f"删除 {name} 失败：该 Skill 不属于当前 UMO。")
            return
        try:
            await self.skill_store.delete_owned(
                self._umo(event), internal_name, "admin command delete"
            )
        except Exception as exc:
            yield event.plain_result(f"删除 {name} 失败：{exc}")
            return
        yield event.plain_result(f"已删除 workspace Skill：{internal_name}")

    async def terminate(self) -> None:
        for task in list(self._review_tasks):
            task.cancel()
        logger.info("Auto Skills plugin unloaded")
