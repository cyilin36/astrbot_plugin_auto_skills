import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


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


def _install_astrbot_stubs(tmp_path):
    logger = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    filter_module = SimpleNamespace(
        on_agent_done=_identity_decorator,
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
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = _Star
    modules["astrbot.core.agent.run_context"].ContextWrapper = object
    modules["astrbot.core.astr_agent_context"].AstrAgentContext = object
    modules["astrbot.core.computer.computer_client"].sync_skills_to_active_sandboxes = _sync_skills_to_active_sandboxes
    modules["astrbot.core.config.astrbot_config"].AstrBotConfig = dict
    modules["astrbot.core.skills.skill_manager"].SkillManager = _SkillManager
    modules["astrbot.core.utils.astrbot_path"].get_astrbot_plugin_data_path = lambda: str(tmp_path / "data" / "plugin_data")
    modules["astrbot.core.utils.astrbot_path"].get_astrbot_skills_path = lambda: str(tmp_path / "data" / "skills")
    sys.modules.update(modules)


async def _sync_skills_to_active_sandboxes():
    return None


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
    async def llm_generate(self, **kwargs):
        self.last_llm_kwargs = kwargs
        return SimpleNamespace(completion_text='{"action":"noop","reason":"none"}')

    def get_using_provider(self, umo=None):
        _ = umo
        return SimpleNamespace(id="provider-1")


class FakeEvent:
    unified_msg_origin = "platform:private:user"
    message_str = "write a daily report"

    def get_sender_id(self):
        return "admin"

    def plain_result(self, text):
        return text


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


def test_list_owned_skills_returns_names(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    AutoSkillsPlugin = _load_plugin(tmp_path)
    plugin = AutoSkillsPlugin(FakeContext(), {"admin_only": False})
    plugin.state_store.record_write("daily-report", "hash", "create", "reason", None)

    names = [item["name"] for item in plugin.state_store.list_skills()]

    assert names == ["daily-report"]
