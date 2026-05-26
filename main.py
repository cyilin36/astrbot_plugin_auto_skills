from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.computer.computer_client import sync_skills_to_active_sandboxes
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.skills.skill_manager import SkillInfo, SkillManager, build_skills_prompt
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


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PROTECTED_TOOL_NAMES = {
    "astrbot_execute_python",
    "astrbot_execute_ipython",
    "astrbot_execute_shell",
    "astrbot_file_write_tool",
    "astrbot_file_edit_tool",
}


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
            active_on_write=self.config.global_activate_generated_skills,
            delete_skill=lambda name: SkillManager().delete_skill(name),
        )
        self._review_tasks: set[asyncio.Task] = set()
        self._session_turns: dict[str, int] = {}
        self._review_semaphore: asyncio.Semaphore | None = None
        self._pending_deletes: dict[str, str] = {}
        self.last_review_status: dict[str, Any] = {"action": "none", "error": ""}
        logger.info("Auto Skills plugin loaded")

    def _umo(self, event: AstrMessageEvent) -> str:
        return getattr(event, "unified_msg_origin", "") or "default"

    def _normalize_display_name(self, skill_name: str) -> str:
        normalized = re.sub(r"[^a-z0-9._-]+", "-", skill_name.strip().lower()).strip(".-_")
        if not normalized:
            normalized = "skill"
        if not normalized[0].isalnum():
            normalized = f"skill-{normalized}"
        return normalized[:50].rstrip(".-_") or "skill"

    def _internal_skill_name(self, umo: str, display_name: str) -> str:
        umo_hash = hashlib.sha256(umo.encode("utf-8")).hexdigest()[:8]
        slug = self._normalize_display_name(display_name)
        internal = f"auto-{umo_hash}-{slug}"[:64].rstrip(".-_")
        return internal if _SKILL_NAME_RE.fullmatch(internal) else f"auto-{umo_hash}-skill"

    def _resolve_current_skill_name(self, event: AstrMessageEvent, skill_name: str) -> str | None:
        return self.state_store.resolve_skill_name(self._umo(event), skill_name)

    def _rewrite_frontmatter_name(self, markdown: str, skill_name: str) -> str:
        lines = markdown.splitlines()
        if not lines or lines[0].strip() != "---":
            return markdown
        end_idx = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end_idx = index
                break
        if end_idx is None:
            return markdown
        for index in range(1, end_idx):
            if lines[index].lstrip().startswith("name:"):
                lines[index] = f"name: {skill_name}"
                return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")
        lines.insert(1, f"name: {skill_name}")
        return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")

    def _skill_description(self, skill_name: str) -> str:
        skill_md = Path(get_astrbot_skills_path()) / skill_name / "SKILL.md"
        if not skill_md.exists():
            return "Read SKILL.md for details."
        lines = skill_md.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            return "Read SKILL.md for details."
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.lstrip().startswith("description:"):
                return line.split(":", 1)[1].strip().strip('"\'') or "Read SKILL.md for details."
        return "Read SKILL.md for details."

    def _current_umo_skill_infos(self, event: AstrMessageEvent) -> list[SkillInfo]:
        skills = []
        for record in self.state_store.list_skills(self._umo(event)):
            name = str(record.get("name") or "")
            if not name:
                continue
            path = Path(get_astrbot_skills_path()) / name / "SKILL.md"
            if not path.exists():
                continue
            skills.append(
                SkillInfo(
                    name=name,
                    description=self._skill_description(name),
                    path=str(path),
                    active=True,
                    source_type="local_only",
                    source_label="auto-skills-umo",
                )
            )
        return skills

    def _managed_skill_storage_policy(self) -> str:
        return (
            "## Managed Skill Storage Policy\n\n"
            "`data/skills/` is AstrBot managed Skill storage. You may read "
            "`data/skills/**/SKILL.md` to understand existing Skills, but you MUST NOT "
            "directly create, edit, overwrite, rename, move, or delete files or directories "
            "under `data/skills/` with generic filesystem tools, shell commands, Python code, "
            "or any other direct file operation.\n\n"
            "For AstrBot Skill lifecycle changes, use only the Auto Skills tools: "
            "`auto_skill_create` to create, `auto_skill_patch` to update, and "
            "`auto_skill_delete_request` to request deletion. If a user asks for direct "
            "modification or deletion of `data/skills`, refuse that method and offer to use "
            "the Auto Skills tools instead. Plugin-provided `skills/` directories are read-only."
        )

    def _mentions_managed_skills(self, value: Any) -> bool:
        text = str(value or "")
        if not text:
            return False
        normalized = text.replace("\\", "/")
        skills_root = str(Path(get_astrbot_skills_path()).resolve(strict=False)).replace("\\", "/")
        return (
            "data/skills" in normalized
            or skills_root in normalized
            or "get_astrbot_skills_path" in normalized
        )

    def _path_targets_managed_skills(self, value: Any) -> bool:
        path_text = str(value or "").strip()
        if not path_text:
            return False
        if self._mentions_managed_skills(path_text):
            return True
        try:
            candidate = Path(path_text).expanduser()
            if not candidate.is_absolute():
                return False
            skills_root = Path(get_astrbot_skills_path()).resolve(strict=False)
            resolved = candidate.resolve(strict=False)
            return resolved == skills_root or skills_root in resolved.parents
        except OSError:
            return False

    def _block_tool_args(self, tool_name: str, tool_args: dict) -> None:
        logger.warning("Auto Skills blocked %s from accessing data/skills", tool_name)
        if tool_name in {"astrbot_execute_python", "astrbot_execute_ipython"}:
            tool_args.clear()
            tool_args.update(
                {
                    "code": "raise PermissionError('Auto Skills blocked access to data/skills')",
                    "silent": False,
                    "timeout": 1,
                }
            )
        elif tool_name == "astrbot_execute_shell":
            tool_args.clear()
            tool_args.update(
                {
                    "command": "echo 'Auto Skills blocked access to data/skills' && exit 1",
                    "background": False,
                    "timeout": 1,
                    "env": {},
                }
            )
        elif tool_name == "astrbot_file_write_tool":
            tool_args.clear()
            tool_args.update({"path": "", "content": ""})
        elif tool_name == "astrbot_file_edit_tool":
            tool_args.clear()
            tool_args.update({"path": "", "old": "", "new": "", "replace_all": False})

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if req.system_prompt is None:
            req.system_prompt = ""
        req.system_prompt += f"\n{self._managed_skill_storage_policy()}\n"
        skills = self._current_umo_skill_infos(event)
        if not skills:
            return None
        req.system_prompt += f"\n{build_skills_prompt(skills)}\n"
        return None

    @filter.on_using_llm_tool()
    async def on_using_llm_tool(self, event: AstrMessageEvent, tool: Any, tool_args: dict | None) -> None:
        _ = event
        if not self.config.protect_skills_from_general_tools:
            return None
        if not tool_args:
            return None
        tool_name = str(getattr(tool, "name", "") or "")
        if tool_name not in _PROTECTED_TOOL_NAMES:
            return None
        blocked = False
        if tool_name in {"astrbot_execute_python", "astrbot_execute_ipython"}:
            blocked = self._mentions_managed_skills(tool_args.get("code"))
        elif tool_name == "astrbot_execute_shell":
            blocked = self._mentions_managed_skills(tool_args.get("command"))
        elif tool_name in {"astrbot_file_write_tool", "astrbot_file_edit_tool"}:
            blocked = self._path_targets_managed_skills(tool_args.get("path"))
        if blocked:
            self._block_tool_args(tool_name, tool_args)
        return None

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
                    owned_skills=self.state_store.list_skills(self._umo(event)),
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
                    display_name = self._normalize_display_name(decision.skill_name)
                    internal_name = self._resolve_current_skill_name(event, display_name) or self._internal_skill_name(
                        self._umo(event), display_name
                    )
                    self.skill_store.create_or_patch(
                        internal_name,
                        self._rewrite_frontmatter_name(decision.skill_markdown, internal_name),
                        decision.action,
                        decision.reason,
                        umo=self._umo(event),
                        display_name=display_name,
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
        if not self._delete_allowed(event):
            raise PermissionError("Only administrators can delete auto-created skills")
        internal_name = self._resolve_current_skill_name(event, skill_name)
        if not internal_name:
            raise PermissionError(f"Skill {skill_name} is not owned by Auto Skills")
        pending_key = getattr(event, "unified_msg_origin", "") or "default"
        if self._pending_deletes.get(pending_key) == internal_name:
            self.skill_store.delete_owned(internal_name, reason or "confirmed natural language delete")
            self._pending_deletes.pop(pending_key, None)
            if hasattr(event, "send"):
                await event.send(event.plain_result(f"已删除自动创建的 Skill：{skill_name}"))
            return
        self._pending_deletes[pending_key] = internal_name
        if hasattr(event, "send"):
            await event.send(event.plain_result(f"请再次确认是否删除自动创建的 Skill：{skill_name}"))

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        return bool(hasattr(event, "is_admin") and event.is_admin())

    def _llm_tool_write_allowed(self, event: AstrMessageEvent) -> bool:
        return not self.config.llm_tool_write_admin_only or self._is_admin(event)

    def _delete_allowed(self, event: AstrMessageEvent) -> bool:
        return not self.config.delete_admin_only or self._is_admin(event)

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
        if not self._llm_tool_write_allowed(event):
            return "只有管理员可以创建自动 Skill。"
        try:
            display_name = self._normalize_display_name(skill_name)
            internal_name = self._internal_skill_name(self._umo(event), display_name)
            self.skill_store.create_or_patch(
                internal_name,
                self._rewrite_frontmatter_name(skill_markdown, internal_name),
                "create",
                reason,
                umo=self._umo(event),
                display_name=display_name,
            )
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
        if not self._llm_tool_write_allowed(event):
            return "只有管理员可以更新自动 Skill。"
        try:
            internal_name = self._resolve_current_skill_name(event, skill_name)
            if not internal_name:
                raise PermissionError(f"Skill {skill_name} is not owned by current UMO")
            record = self.state_store.get_skill(internal_name) or {}
            self.skill_store.create_or_patch(
                internal_name,
                self._rewrite_frontmatter_name(skill_markdown, internal_name),
                "patch",
                reason,
                umo=self._umo(event),
                display_name=str(record.get("display_name") or skill_name),
            )
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
        if not self._delete_allowed(event):
            return "只有管理员可以删除自动 Skill。"
        try:
            pending_key = getattr(event, "unified_msg_origin", "") or "default"
            internal_name = self._resolve_current_skill_name(event, skill_name)
            confirmed = bool(internal_name and self._pending_deletes.get(pending_key) == internal_name)
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
        skills = self.state_store.list_skills(self._umo(event))
        if not skills:
            yield event.plain_result("No auto-created skills yet.")
            return
        lines = [f"- {item['name']} v{item.get('version', 0)}: {item.get('last_action', '')}" for item in skills]
        yield event.plain_result("Auto-created skills:\n" + "\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("view")
    async def autoskill_view(self, event: AstrMessageEvent, name: str):
        """查看某个自动创建 Skill 的版本、更新时间和最近变更原因。"""
        internal_name = self._resolve_current_skill_name(event, name)
        if not internal_name:
            yield event.plain_result(f"Skill {name} 不属于当前 UMO。")
            return
        record = self.state_store.get_skill(internal_name)
        if not record or record.get("created_by") != PLUGIN_OWNER:
            yield event.plain_result(f"Skill {name} is not owned by Auto Skills.")
            return
        yield event.plain_result(
            f"{internal_name}\n"
            f"display_name: {record.get('display_name')}\n"
            f"version: {record.get('version')}\n"
            f"last_action: {record.get('last_action')}\n"
            f"updated_at: {record.get('updated_at')}\n"
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
            backup_path = self.skill_store.rollback_latest(internal_name)
        except Exception as exc:
            yield event.plain_result(f"Rollback failed for {name}: {exc}")
            return
        yield event.plain_result(f"Rolled back {internal_name} from {backup_path}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @autoskill.command("delete")
    async def autoskill_delete(self, event: AstrMessageEvent, name: str):
        """直接删除本插件自动创建并拥有的 Skill，删除前会自动备份。"""
        internal_name = self._resolve_current_skill_name(event, name)
        if not internal_name:
            yield event.plain_result(f"删除 {name} 失败：该 Skill 不属于当前 UMO。")
            return
        try:
            backup_path = self.skill_store.delete_owned(internal_name, "admin command delete")
        except Exception as exc:
            yield event.plain_result(f"删除 {name} 失败：{exc}")
            return
        yield event.plain_result(f"已删除自动创建的 Skill：{name}，删除前备份：{backup_path}")

    async def terminate(self) -> None:
        for task in list(self._review_tasks):
            task.cancel()
        logger.info("Auto Skills plugin unloaded")
