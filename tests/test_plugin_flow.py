import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


VALID_MARKDOWN = """---
name: daily-report
description: Write structured daily reports from work notes.
---

# Daily Report

Body
"""


class _CommandGroup:
    def __call__(self, func):
        return self

    def command(self, _name):
        def decorator(func):
            return func

        return decorator


def _identity_decorator(*_args, **_kwargs):
    def decorator(func):
        return func

    return decorator


def _command_group(_name):
    return _CommandGroup()


class _Star:
    def __init__(self, context):
        self.context = context


class _SkillManager:
    def list_skills(self, active_only=False):
        _ = active_only
        return []

    def set_skill_active(self, name, active):
        _ = (name, active)

    def delete_skill(self, name):
        _ = name


def _install_astrbot_stubs(tmp_path):
    logger = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    filter_module = SimpleNamespace(
        on_agent_done=_identity_decorator,
        on_llm_request=_identity_decorator,
        llm_tool=_identity_decorator,
        permission_type=_identity_decorator,
        command_group=_command_group,
        PermissionType=SimpleNamespace(ADMIN="admin"),
    )
    modules = {
        "astrbot": types.ModuleType("astrbot"),
        "astrbot.api": types.ModuleType("astrbot.api"),
        "astrbot.api.event": types.ModuleType("astrbot.api.event"),
        "astrbot.api.provider": types.ModuleType("astrbot.api.provider"),
        "astrbot.api.star": types.ModuleType("astrbot.api.star"),
        "astrbot.core": types.ModuleType("astrbot.core"),
        "astrbot.core.agent": types.ModuleType("astrbot.core.agent"),
        "astrbot.core.agent.run_context": types.ModuleType("astrbot.core.agent.run_context"),
        "astrbot.core.astr_agent_context": types.ModuleType("astrbot.core.astr_agent_context"),
        "astrbot.core.computer": types.ModuleType("astrbot.core.computer"),
        "astrbot.core.computer.computer_client": types.ModuleType("astrbot.core.computer.computer_client"),
        "astrbot.core.config": types.ModuleType("astrbot.core.config"),
        "astrbot.core.config.astrbot_config": types.ModuleType("astrbot.core.config.astrbot_config"),
        "astrbot.core.skills": types.ModuleType("astrbot.core.skills"),
        "astrbot.core.skills.skill_manager": types.ModuleType("astrbot.core.skills.skill_manager"),
        "astrbot.core.utils": types.ModuleType("astrbot.core.utils"),
        "astrbot.core.utils.astrbot_path": types.ModuleType("astrbot.core.utils.astrbot_path"),
    }
    modules["astrbot.api"].logger = logger
    modules["astrbot.api.event"].AstrMessageEvent = object
    modules["astrbot.api.event"].filter = filter_module
    modules["astrbot.api.provider"].LLMResponse = object
    modules["astrbot.api.provider"].ProviderRequest = object
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = _Star
    modules["astrbot.core.agent.run_context"].ContextWrapper = object
    modules["astrbot.core.astr_agent_context"].AstrAgentContext = object
    modules["astrbot.core.computer.computer_client"].sync_skills_to_active_sandboxes = _sync_skills_to_active_sandboxes
    modules["astrbot.core.config.astrbot_config"].AstrBotConfig = dict
    modules["astrbot.core.skills.skill_manager"].SkillManager = _SkillManager
    modules["astrbot.core.skills.skill_manager"].SkillInfo = SimpleNamespace
    modules["astrbot.core.skills.skill_manager"].build_skills_prompt = _build_skills_prompt
    modules["astrbot.core.utils.astrbot_path"].get_astrbot_plugin_data_path = lambda: str(tmp_path / "data" / "plugin_data")
    modules["astrbot.core.utils.astrbot_path"].get_astrbot_skills_path = lambda: str(tmp_path / "data" / "skills")
    sys.modules.update(modules)


async def _sync_skills_to_active_sandboxes():
    return None


def _build_skills_prompt(skills):
    return "## Skills\n" + "\n".join(f"- {skill.name}: {skill.description}" for skill in skills)


def _load_plugin(tmp_path):
    _install_astrbot_stubs(tmp_path)
    package_name = "data.plugins.astrbot_plugin_auto_skills"
    for module_name in [
        "data",
        "data.plugins",
        package_name,
        f"{package_name}.main",
    ]:
        sys.modules.pop(module_name, None)
    data_module = types.ModuleType("data")
    data_module.__path__ = []
    plugins_module = types.ModuleType("data.plugins")
    plugins_module.__path__ = []
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(Path.cwd())]
    sys.modules["data"] = data_module
    sys.modules["data.plugins"] = plugins_module
    sys.modules[package_name] = package_module
    spec = importlib.util.spec_from_file_location(f"{package_name}.main", "main.py")
    plugin_main = importlib.util.module_from_spec(spec)
    sys.modules[f"{package_name}.main"] = plugin_main
    assert spec.loader is not None
    spec.loader.exec_module(plugin_main)
    return plugin_main.AutoSkillsPlugin


class FakeContext:
    def __init__(self, completion_text='{"action":"noop","reason":"none"}'):
        self.completion_text = completion_text

    async def llm_generate(self, **kwargs):
        self.last_llm_kwargs = kwargs
        return SimpleNamespace(completion_text=self.completion_text)

    def get_using_provider(self, umo=None):
        _ = umo
        return SimpleNamespace(id="provider-1")


class FakeEvent:
    unified_msg_origin = "platform:private:user"
    message_str = "write a daily report"
    sent_messages = None

    def is_admin(self):
        return True

    def get_sender_id(self):
        return "admin"

    def plain_result(self, text):
        return text

    async def send(self, result):
        if self.sent_messages is None:
            self.sent_messages = []
        self.sent_messages.append(result)


class FakeMemberEvent(FakeEvent):
    def is_admin(self):
        return False


class OtherUmoEvent(FakeEvent):
    unified_msg_origin = "platform:group:other"


async def _wait_for_tasks(plugin):
    tasks = list(plugin._review_tasks)
    if tasks:
        await asyncio.gather(*tasks)


async def _run_agent_done_and_wait(plugin, event, run_context, resp):
    await plugin.on_agent_done(event, run_context, resp)
    await _wait_for_tasks(plugin)


def test_on_agent_done_schedules_background_review(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"review_every_turns": 1, "admin_only": False})
    event = FakeEvent()
    resp = SimpleNamespace(completion_text="Here is the report.", role="assistant")
    run_context = SimpleNamespace()

    asyncio.run(_run_agent_done_and_wait(plugin, event, run_context, resp))

    assert plugin.last_review_status["action"] == "noop"


def test_plugin_imports_like_astrbot_package(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    AutoSkillsPlugin = _load_plugin(tmp_path)

    assert AutoSkillsPlugin.__name__ == "AutoSkillsPlugin"


def test_disabled_plugin_does_not_schedule_review(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"enabled": False, "admin_only": False})

    asyncio.run(plugin.on_agent_done(FakeEvent(), SimpleNamespace(), SimpleNamespace(completion_text="ok")))

    assert plugin._review_tasks == set()


def test_auto_review_requires_admin_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"review_every_turns": 1})

    asyncio.run(plugin.on_agent_done(FakeMemberEvent(), SimpleNamespace(), SimpleNamespace(completion_text="ok")))

    assert plugin._review_tasks == set()
    assert plugin.last_review_status == {"action": "none", "error": ""}


def test_list_owned_skills_returns_names(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    plugin.state_store.record_write("daily-report", "hash", "create", "reason", None)

    names = [item["name"] for item in plugin.state_store.list_skills()]

    assert names == ["daily-report"]


def test_delete_command_deletes_owned_skill_without_second_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    plugin.skill_store.create_or_patch("daily-report", VALID_MARKDOWN, "create", "initial")
    deleted = []
    plugin.skill_store.delete_skill = lambda name: deleted.append(name)

    async def run_command():
        results = []
        async for result in plugin.autoskill_delete(FakeEvent(), "daily-report"):
            results.append(result)
        return results

    results = asyncio.run(run_command())

    assert deleted == ["daily-report"]
    assert "已删除" in results[0]


def test_oral_delete_requires_admin_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    decision = '{"action":"delete","skill_name":"daily-report","reason":"用户要求删除"}'
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(decision), {"review_every_turns": 1, "admin_only": False})
    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "initial"))
    deleted = []
    plugin.skill_store.delete_skill = lambda name: deleted.append(name)
    event = FakeEvent()
    resp = SimpleNamespace(completion_text="请确认是否删除 daily-report。")

    asyncio.run(_run_agent_done_and_wait(plugin, event, SimpleNamespace(), resp))
    asyncio.run(_run_agent_done_and_wait(plugin, event, SimpleNamespace(), resp))

    assert len(deleted) == 1
    assert deleted[0].startswith("auto-")
    assert event.sent_messages is not None
    assert "请再次确认" in event.sent_messages[0]


def test_oral_delete_always_requires_admin_even_when_auto_review_allows_members(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    decision = '{"action":"delete","skill_name":"daily-report","reason":"用户要求删除"}'
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(decision), {"review_every_turns": 1, "admin_only": False})
    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "initial"))
    deleted = []
    plugin.skill_store.delete_skill = lambda name: deleted.append(name)
    event = FakeMemberEvent()
    resp = SimpleNamespace(completion_text="请删除 daily-report。")

    asyncio.run(_run_agent_done_and_wait(plugin, event, SimpleNamespace(), resp))

    assert deleted == []
    assert plugin.last_review_status["action"] == "error"


def test_llm_tool_create_skill_requires_admin_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})

    result = asyncio.run(
        plugin.auto_skill_create(
            FakeMemberEvent(),
            "daily-report",
            VALID_MARKDOWN,
            "用户要求保存流程",
        )
    )

    assert "只有管理员" in result
    assert not plugin.state_store.is_owned("daily-report")


def test_llm_tool_create_skill_can_allow_members_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"llm_tool_write_admin_only": False})

    result = asyncio.run(
        plugin.auto_skill_create(
            FakeMemberEvent(),
            "daily-report",
            VALID_MARKDOWN,
            "用户要求保存流程",
        )
    )

    assert "已创建" in result
    assert len(plugin.state_store.list_skills(FakeMemberEvent.unified_msg_origin)) == 1


def test_llm_tool_delete_request_requires_admin_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {})
    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "initial"))

    result = asyncio.run(plugin.auto_skill_delete_request(FakeMemberEvent(), "daily-report", "用户要求删除"))

    assert "只有管理员" in result


def test_llm_tool_delete_request_can_allow_members_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"delete_admin_only": False, "llm_tool_write_admin_only": False})
    asyncio.run(plugin.auto_skill_create(FakeMemberEvent(), "daily-report", VALID_MARKDOWN, "initial"))
    deleted = []
    plugin.skill_store.delete_skill = lambda name: deleted.append(name)

    first = asyncio.run(plugin.auto_skill_delete_request(FakeMemberEvent(), "daily-report", "用户要求删除"))
    second = asyncio.run(plugin.auto_skill_delete_request(FakeMemberEvent(), "daily-report", "用户确认删除"))

    assert "请再次确认" in first
    assert "已删除" in second
    assert len(deleted) == 1


def test_llm_tool_create_skill_writes_owned_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})

    result = asyncio.run(
        plugin.auto_skill_create(
            FakeEvent(),
            "daily-report",
            VALID_MARKDOWN,
            "用户要求保存流程",
        )
    )

    assert "已创建" in result
    skills = plugin.state_store.list_skills(FakeEvent.unified_msg_origin)
    assert len(skills) == 1
    assert skills[0]["display_name"] == "daily-report"
    assert skills[0]["name"].startswith("auto-")


def test_llm_tool_patch_skill_updates_owned_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "initial"))
    updated = VALID_MARKDOWN.replace("Body", "Updated Body")

    result = asyncio.run(
        plugin.auto_skill_patch(
            FakeEvent(),
            "daily-report",
            updated,
            "用户要求更新流程",
        )
    )

    assert "已更新" in result
    internal_name = plugin.state_store.resolve_skill_name(FakeEvent.unified_msg_origin, "daily-report")
    assert internal_name is not None
    record = plugin.state_store.get_skill(internal_name)
    assert record is not None
    assert record["last_action"] == "patch"
    assert len(record["backups"]) == 1


def test_llm_tool_delete_request_uses_confirmation_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "initial"))
    deleted = []
    plugin.skill_store.delete_skill = lambda name: deleted.append(name)
    event = FakeEvent()

    first = asyncio.run(plugin.auto_skill_delete_request(event, "daily-report", "用户要求删除"))
    second = asyncio.run(plugin.auto_skill_delete_request(event, "daily-report", "用户确认删除"))

    assert "请再次确认" in first
    assert "已删除" in second
    assert len(deleted) == 1
    assert deleted[0].startswith("auto-")


def test_llm_request_injects_only_current_umo_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "initial"))

    current_req = SimpleNamespace(system_prompt="base")
    other_req = SimpleNamespace(system_prompt="base")
    asyncio.run(plugin.on_llm_request(FakeEvent(), current_req))
    asyncio.run(plugin.on_llm_request(OtherUmoEvent(), other_req))

    assert "## Skills" in current_req.system_prompt
    assert "Write structured daily reports" in current_req.system_prompt
    assert other_req.system_prompt == "base"


def test_same_display_name_is_isolated_by_umo(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})

    asyncio.run(plugin.auto_skill_create(FakeEvent(), "daily-report", VALID_MARKDOWN, "current"))
    asyncio.run(plugin.auto_skill_create(OtherUmoEvent(), "daily-report", VALID_MARKDOWN, "other"))

    current = plugin.state_store.list_skills(FakeEvent.unified_msg_origin)
    other = plugin.state_store.list_skills(OtherUmoEvent.unified_msg_origin)
    assert len(current) == 1
    assert len(other) == 1
    assert current[0]["display_name"] == "daily-report"
    assert other[0]["display_name"] == "daily-report"
    assert current[0]["name"] != other[0]["name"]
