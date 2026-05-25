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
from astrbot.core.computer.computer_client import sync_skills_to_active_sandboxes
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path, get_astrbot_skills_path

from .auto_skills.config import AutoSkillsConfig
from .auto_skills.models import PLUGIN_OWNER
from .auto_skills.review_runner import (
    build_review_system_prompt,
    build_review_user_prompt,
    parse_review_decision,
)
from .auto_skills.skill_store import SkillStore
from .auto_skills.state_store import StateStore


class AutoSkillsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.raw_config = config or {}
        self.config = AutoSkillsConfig.from_mapping(self.raw_config)
        data_root = Path(get_astrbot_plugin_data_path()) / PLUGIN_OWNER
        self.state_store = StateStore(data_root / "state.json")
        self.skill_store = SkillStore(
            get_astrbot_skills_path(),
            self.state_store,
            set_active=lambda name, active: SkillManager().set_skill_active(name, active),
            backup_root=data_root / "backups",
            max_skill_chars=self.config.max_skill_chars,
            max_description_chars=self.config.max_description_chars,
            max_backups_per_skill=self.config.max_backups_per_skill,
            delete_skill=lambda name: SkillManager().delete_skill(name),
        )
        self._review_tasks: set[asyncio.Task] = set()
        self._session_turns: dict[str, int] = {}
        self._review_semaphore: asyncio.Semaphore | None = None
        self._pending_deletes: dict[str, str] = {}
        self.last_review_status: dict[str, Any] = {"action": "none", "error": ""}
        logger.info("Auto Skills plugin loaded")

    def _should_review(self, event: AstrMessageEvent, resp: LLMResponse) -> bool:
        if not self.config.enabled:
            return False
        if self.config.admin_only and hasattr(event, "is_admin") and not event.is_admin():
            return False
        if not str(getattr(resp, "completion_text", "") or "").strip():
            return False
        umo = getattr(event, "unified_msg_origin", "") or "default"
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
                active_skills = [
                    {"name": skill.name, "description": skill.description}
                    for skill in SkillManager().list_skills(active_only=True)
                ]
                user_prompt = build_review_user_prompt(
                    user_message=str(getattr(event, "message_str", "") or ""),
                    assistant_response=str(getattr(resp, "completion_text", "") or ""),
                    tool_summaries=[],
                    active_skills=active_skills,
                    owned_skills=self.state_store.list_skills(),
                )
                provider_id = self.config.review_provider_id
                if not provider_id and hasattr(self.context, "get_using_provider"):
                    provider = self.context.get_using_provider(getattr(event, "unified_msg_origin", None))
                    provider_id = str(getattr(provider, "id", "") or "")
                llm_resp = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=user_prompt,
                        system_prompt=build_review_system_prompt(),
                    ),
                    timeout=self.config.review_timeout_seconds,
                )
                decision = parse_review_decision(str(getattr(llm_resp, "completion_text", "") or ""))
                if decision.action in {"create", "patch"}:
                    self.skill_store.create_or_patch(
                        decision.skill_name,
                        decision.skill_markdown,
                        decision.action,
                        decision.reason,
                    )
                    if self.config.auto_sync_sandbox:
                        try:
                            await sync_skills_to_active_sandboxes()
                        except Exception as exc:
                            logger.warning("Auto Skills sandbox sync failed: %s", exc)
                elif decision.action == "delete":
                    await self._handle_review_delete(event, decision.skill_name, decision.reason)
                self.last_review_status = {
                    "action": decision.action,
                    "skill_name": decision.skill_name,
                    "reason": decision.reason,
                    "error": "",
                }
            except Exception as exc:
                self.last_review_status = {"action": "error", "error": str(exc)}
                logger.warning("Auto Skills review failed: %s", exc)

    async def _handle_review_delete(self, event: AstrMessageEvent, skill_name: str, reason: str) -> None:
        if hasattr(event, "is_admin") and not event.is_admin():
            raise PermissionError("Only administrators can delete auto-created skills")
        if not self.state_store.is_owned(skill_name):
            raise PermissionError(f"Skill {skill_name} is not owned by Auto Skills")
        pending_key = getattr(event, "unified_msg_origin", "") or "default"
        if self._pending_deletes.get(pending_key) == skill_name:
            self.skill_store.delete_owned(skill_name, reason or "confirmed natural language delete")
            self._pending_deletes.pop(pending_key, None)
            if hasattr(event, "send"):
                await event.send(event.plain_result(f"已删除自动创建的 Skill：{skill_name}"))
            return
        self._pending_deletes[pending_key] = skill_name
        if hasattr(event, "send"):
            await event.send(event.plain_result(f"请再次确认是否删除自动创建的 Skill：{skill_name}"))

    def _admin_allowed(self, event: AstrMessageEvent) -> bool:
        return bool(hasattr(event, "is_admin") and event.is_admin())

    async def _sync_after_tool_write(self) -> None:
        if not self.config.auto_sync_sandbox:
            return
        try:
            await sync_skills_to_active_sandboxes()
        except Exception as exc:
            logger.warning("Auto Skills sandbox sync failed: %s", exc)

    @filter.llm_tool(name="auto_skill_create")
    async def auto_skill_create(
        self,
        event: AstrMessageEvent,
        skill_name: str,
        skill_markdown: str,
        reason: str,
    ) -> str:
        """创建一个新的 AstrBot Skill。

        Args:
            skill_name(string): Skill 名称，必须与 SKILL.md frontmatter 中的 name 一致。
            skill_markdown(string): 完整的 SKILL.md 内容，必须包含 YAML frontmatter 和正文。
            reason(string): 创建这个 Skill 的原因。
        """
        if not self._admin_allowed(event):
            return "只有管理员可以创建自动 Skill。"
        try:
            self.skill_store.create_or_patch(skill_name, skill_markdown, "create", reason)
            await self._sync_after_tool_write()
        except Exception as exc:
            return f"创建自动 Skill {skill_name} 失败：{exc}"
        return f"已创建并启用自动 Skill：{skill_name}"

    @filter.llm_tool(name="auto_skill_patch")
    async def auto_skill_patch(
        self,
        event: AstrMessageEvent,
        skill_name: str,
        skill_markdown: str,
        reason: str,
    ) -> str:
        """更新本插件已经创建并拥有的 AstrBot Skill。

        Args:
            skill_name(string): 要更新的 Skill 名称。
            skill_markdown(string): 更新后的完整 SKILL.md 内容，必须包含 YAML frontmatter 和正文。
            reason(string): 更新这个 Skill 的原因。
        """
        if not self._admin_allowed(event):
            return "只有管理员可以更新自动 Skill。"
        try:
            self.skill_store.create_or_patch(skill_name, skill_markdown, "patch", reason)
            await self._sync_after_tool_write()
        except Exception as exc:
            return f"更新自动 Skill {skill_name} 失败：{exc}"
        return f"已更新并启用自动 Skill：{skill_name}"

    @filter.llm_tool(name="auto_skill_delete_request")
    async def auto_skill_delete_request(
        self,
        event: AstrMessageEvent,
        skill_name: str,
        reason: str,
    ) -> str:
        """请求删除本插件自动创建并拥有的 AstrBot Skill。

        Args:
            skill_name(string): 要删除的 Skill 名称。
            reason(string): 请求删除这个 Skill 的原因。
        """
        if not self._admin_allowed(event):
            return "只有管理员可以删除自动 Skill。"
        try:
            pending_key = getattr(event, "unified_msg_origin", "") or "default"
            confirmed = self._pending_deletes.get(pending_key) == skill_name
            await self._handle_review_delete(event, skill_name, reason)
        except Exception as exc:
            return f"删除自动 Skill {skill_name} 失败：{exc}"
        if confirmed:
            return f"已删除自动创建的 Skill：{skill_name}"
        return f"请再次确认是否删除自动创建的 Skill：{skill_name}"

    @filter.command_group("autoskill")
    def autoskill(self):
        """管理 Auto Skills 自动创建的 AstrBot Skills。"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("status")
    async def autoskill_status(self, event: AstrMessageEvent):
        """查看 Auto Skills 插件状态、复盘频率和最近一次复盘结果。"""
        yield event.plain_result(
            "Auto Skills: "
            f"enabled={self.config.enabled}, "
            f"review_every_turns={self.config.review_every_turns}, "
            f"last={self.last_review_status}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("list")
    async def autoskill_list(self, event: AstrMessageEvent):
        """列出本插件自动创建并拥有的 Skill。"""
        skills = self.state_store.list_skills()
        if not skills:
            yield event.plain_result("No auto-created skills yet.")
            return
        lines = [f"- {item['name']} v{item.get('version', 0)}: {item.get('last_action', '')}" for item in skills]
        yield event.plain_result("Auto-created skills:\n" + "\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("view")
    async def autoskill_view(self, event: AstrMessageEvent, name: str):
        """查看某个自动创建 Skill 的版本、更新时间和最近变更原因。"""
        record = self.state_store.get_skill(name)
        if not record or record.get("created_by") != PLUGIN_OWNER:
            yield event.plain_result(f"Skill {name} is not owned by Auto Skills.")
            return
        yield event.plain_result(
            f"{name}\n"
            f"version: {record.get('version')}\n"
            f"last_action: {record.get('last_action')}\n"
            f"updated_at: {record.get('updated_at')}\n"
            f"reason: {record.get('last_reason')}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("rollback")
    async def autoskill_rollback(self, event: AstrMessageEvent, name: str):
        """将某个自动创建 Skill 回滚到最近一次备份。"""
        try:
            backup_path = self.skill_store.rollback_latest(name)
        except Exception as exc:
            yield event.plain_result(f"Rollback failed for {name}: {exc}")
            return
        yield event.plain_result(f"Rolled back {name} from {backup_path}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("delete")
    async def autoskill_delete(self, event: AstrMessageEvent, name: str):
        """直接删除本插件自动创建并拥有的 Skill，删除前会自动备份。"""
        try:
            backup_path = self.skill_store.delete_owned(name, "admin command delete")
        except Exception as exc:
            yield event.plain_result(f"删除 {name} 失败：{exc}")
            return
        yield event.plain_result(f"已删除自动创建的 Skill：{name}，删除前备份：{backup_path}")

    async def terminate(self) -> None:
        for task in list(self._review_tasks):
            task.cancel()
        logger.info("Auto Skills plugin unloaded")
