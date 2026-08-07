from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
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
    build_skill_creator_nudge,
    parse_review_decision,
)
from .auto_skills.skill_names import is_valid_skill_name, normalize_skill_name
from .auto_skills.suggestion_store import SuggestionStore
from .auto_skills.workspace_skills import WorkspaceSkillsReader


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutoSkillsPlugin(Star):
    """Review completed turns and remind the main agent to apply skill-creator."""

    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.raw_config = config or {}
        self.config = AutoSkillsConfig.from_mapping(self.raw_config)
        data_root = Path(get_astrbot_plugin_data_path()) / PLUGIN_OWNER
        self.suggestion_store = SuggestionStore(data_root / "state.json")
        self.workspace_skills = WorkspaceSkillsReader(context=context)
        self._review_tasks: set[asyncio.Task] = set()
        self._session_turns: dict[str, int] = {}
        self._review_semaphore: asyncio.Semaphore | None = None
        self.last_review_status: dict[str, Any] = {"action": "none", "error": ""}
        logger.info("Auto Skills plugin loaded (skill-creator reminder mode)")

    def _umo(self, event: AstrMessageEvent) -> str:
        return getattr(event, "unified_msg_origin", "") or "default"

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        return bool(hasattr(event, "is_admin") and event.is_admin())

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

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """Inject a pending skill-creator reminder into the next few turns."""
        if not self.config.enabled:
            return None
        pending = self.suggestion_store.consume_inject(self._umo(event))
        if not pending:
            return None
        if req.system_prompt is None:
            req.system_prompt = ""
        req.system_prompt += f"\n{build_skill_creator_nudge(pending)}\n"
        return None

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
                workspace_skills = await self.workspace_skills.list_skills(umo)
                user_prompt = build_review_user_prompt(
                    user_message=str(getattr(event, "message_str", "") or ""),
                    assistant_response=str(getattr(resp, "completion_text", "") or ""),
                    tool_summaries=[],
                    workspace_skills=workspace_skills,
                )
                provider_id = self.config.review_provider_id
                if not provider_id:
                    provider_id = await self.context.get_current_chat_provider_id(umo)
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
                status: dict[str, Any] = {
                    "action": decision.action,
                    "skill_name": decision.skill_name,
                    "reason": decision.reason,
                    "error": "",
                    "reviewed_at": _now_iso(),
                }

                if decision.action == "noop":
                    self.last_review_status = status
                    self.suggestion_store.record_review(status)
                    return

                skill_name = normalize_skill_name(decision.skill_name)
                if not is_valid_skill_name(skill_name):
                    status.update(
                        {
                            "action": "error",
                            "error": f"Invalid skill name from review: {decision.skill_name}",
                        }
                    )
                    self.last_review_status = status
                    self.suggestion_store.record_review(status)
                    return

                if decision.action in {"create", "patch"} and not str(
                    decision.skill_markdown or ""
                ).strip():
                    status.update(
                        {
                            "action": "error",
                            "error": "Review returned create/patch without skill_markdown draft",
                        }
                    )
                    self.last_review_status = status
                    self.suggestion_store.record_review(status)
                    return

                suggestion = {
                    "action": decision.action,
                    "skill_name": skill_name,
                    "reason": decision.reason,
                    "skill_markdown": decision.skill_markdown,
                    "patch_notes": decision.patch_notes,
                    "remaining_injects": self.config.pending_inject_turns,
                    "created_at": _now_iso(),
                }
                self.suggestion_store.set_pending(umo, suggestion)
                status["skill_name"] = skill_name
                status["pending"] = True
                status["remaining_injects"] = self.config.pending_inject_turns
                self.last_review_status = status
                self.suggestion_store.record_review(status)

                if self.config.notify_on_suggestion and hasattr(event, "send"):
                    await event.send(
                        event.plain_result(
                            "Auto Skills 建议通过 skill-creator "
                            f"{decision.action} workspace Skill：{skill_name}\n"
                            f"原因：{decision.reason or '（无）'}\n"
                            "将在接下来几轮对话中提醒主 Agent 处理。"
                        )
                    )
            except Exception as exc:
                self.last_review_status = {"action": "error", "error": str(exc)}
                self.suggestion_store.record_review(self.last_review_status)
                logger.warning("Auto Skills review failed: %s", exc)

    @filter.command_group("autoskill")
    def autoskill(self):
        """查看 Auto Skills 复盘提醒状态。"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("status")
    async def autoskill_status(self, event: AstrMessageEvent):
        """查看复盘配置、当前 workspace 和待处理建议。"""
        umo = self._umo(event)
        try:
            workspace_root = await self.workspace_skills.resolve_workspace_root(umo)
            skills_root = workspace_root / "skills"
        except Exception as exc:
            workspace_root = f"<error: {exc}>"
            skills_root = workspace_root
        pending = self.suggestion_store.get_pending(umo) or {}
        yield event.plain_result(
            "Auto Skills (skill-creator reminder mode):\n"
            f"enabled={self.config.enabled}\n"
            f"review_every_turns={self.config.review_every_turns}\n"
            f"pending_inject_turns={self.config.pending_inject_turns}\n"
            f"umo={umo}\n"
            f"workspace={workspace_root}\n"
            f"skills_root={skills_root}\n"
            "writer=skill-creator (this plugin does not write SKILL.md)\n"
            f"pending={pending or None}\n"
            f"last={self.last_review_status}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("list")
    async def autoskill_list(self, event: AstrMessageEvent):
        """列出当前 workspace 已有 Skills（只读，供对照复盘建议）。"""
        umo = self._umo(event)
        skills = await self.workspace_skills.list_skills(umo)
        skills_root = await self.workspace_skills.skills_root(umo)
        if not skills:
            yield event.plain_result(f"当前 workspace 没有 Skill。\nskills_root={skills_root}")
            return
        lines = [f"- {item['name']}: {item['description']}" for item in skills]
        yield event.plain_result(
            f"Workspace skills ({skills_root}):\n" + "\n".join(lines)
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("pending")
    async def autoskill_pending(self, event: AstrMessageEvent):
        """查看当前会话待处理的 skill-creator 建议。"""
        pending = self.suggestion_store.get_pending(self._umo(event))
        if not pending:
            yield event.plain_result("当前没有待处理的 Skill 建议。")
            return
        draft = str(pending.get("skill_markdown") or "").strip()
        preview = ""
        if draft:
            preview = "\n\nDraft preview:\n" + (
                draft if len(draft) <= 1200 else draft[:1200] + "\n... (truncated)"
            )
        yield event.plain_result(
            "Pending skill-creator suggestion:\n"
            f"action={pending.get('action')}\n"
            f"skill_name={pending.get('skill_name')}\n"
            f"reason={pending.get('reason')}\n"
            f"patch_notes={pending.get('patch_notes')}\n"
            f"remaining_injects={pending.get('remaining_injects')}\n"
            f"created_at={pending.get('created_at')}"
            f"{preview}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("clear")
    async def autoskill_clear(self, event: AstrMessageEvent):
        """清除当前会话待处理的 skill-creator 建议。"""
        cleared = self.suggestion_store.clear_pending(self._umo(event))
        if cleared:
            yield event.plain_result("已清除当前会话的待处理 Skill 建议。")
        else:
            yield event.plain_result("当前没有待处理的 Skill 建议。")

    async def terminate(self) -> None:
        for task in list(self._review_tasks):
            task.cancel()
        logger.info("Auto Skills plugin unloaded")
