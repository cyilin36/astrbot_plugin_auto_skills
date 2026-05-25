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
        )
        self._review_tasks: set[asyncio.Task] = set()
        self._session_turns: dict[str, int] = {}
        self._review_semaphore: asyncio.Semaphore | None = None
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
                self.last_review_status = {
                    "action": decision.action,
                    "skill_name": decision.skill_name,
                    "reason": decision.reason,
                    "error": "",
                }
            except Exception as exc:
                self.last_review_status = {"action": "error", "error": str(exc)}
                logger.warning("Auto Skills review failed: %s", exc)

    @filter.command_group("autoskill")
    def autoskill(self):
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("status")
    async def autoskill_status(self, event: AstrMessageEvent):
        yield event.plain_result(
            "Auto Skills: "
            f"enabled={self.config.enabled}, "
            f"review_every_turns={self.config.review_every_turns}, "
            f"last={self.last_review_status}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("list")
    async def autoskill_list(self, event: AstrMessageEvent):
        skills = self.state_store.list_skills()
        if not skills:
            yield event.plain_result("No auto-created skills yet.")
            return
        lines = [f"- {item['name']} v{item.get('version', 0)}: {item.get('last_action', '')}" for item in skills]
        yield event.plain_result("Auto-created skills:\n" + "\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("view")
    async def autoskill_view(self, event: AstrMessageEvent, name: str):
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
        try:
            backup_path = self.skill_store.rollback_latest(name)
        except Exception as exc:
            yield event.plain_result(f"Rollback failed for {name}: {exc}")
            return
        yield event.plain_result(f"Rolled back {name} from {backup_path}")

    async def terminate(self) -> None:
        for task in list(self._review_tasks):
            task.cancel()
        logger.info("Auto Skills plugin unloaded")
