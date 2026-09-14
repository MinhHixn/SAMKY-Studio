import asyncio
import os
import threading
from types import SimpleNamespace

from app.services import simulation_config_generator as config_module

from app.services.simulation_config_generator import (
    EventConfig,
    SimulationConfigGenerator,
    TimeSimulationConfig,
)


def test_independent_config_requests_run_concurrently_and_keep_agent_order(monkeypatch):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    generator.model_name = "test-model"
    generator.base_url = "test-url"
    barrier = threading.Barrier(4)
    progress = []

    monkeypatch.setattr(generator, "_build_context", lambda **kwargs: "context")

    def time_request(*args):
        barrier.wait(timeout=3)
        return {"reasoning": "time"}

    def event_request(*args):
        barrier.wait(timeout=3)
        return {"reasoning": "event"}

    def agent_request(**kwargs):
        barrier.wait(timeout=3)
        start = kwargs["start_idx"]
        return list(range(start, start + len(kwargs["entities"])))

    monkeypatch.setattr(generator, "_generate_time_config", time_request)
    monkeypatch.setattr(generator, "_generate_event_config", event_request)
    monkeypatch.setattr(generator, "_generate_agent_configs_batch", agent_request)
    monkeypatch.setattr(generator, "_parse_time_config", lambda *args: TimeSimulationConfig())
    monkeypatch.setattr(generator, "_parse_event_config", lambda *args: EventConfig())
    monkeypatch.setattr(generator, "_assign_initial_post_agents", lambda event, agents: event)

    params = generator.generate_config(
        simulation_id="sim_test",
        project_id="project_test",
        graph_id="graph_test",
        simulation_requirement="test",
        document_text="test",
        entities=list(range(21)),
        progress_callback=lambda step, total, message: progress.append((step, total, message)),
    )

    assert params.agent_configs == list(range(21))
    assert progress[-1][0] == progress[-1][1] == 5
    assert [step for step, _, _ in progress] == list(range(6))
    assert any("Completed agents" in message for _, _, message in progress)


def test_online_config_requests_are_bounded_and_deepseek_responds_directly(monkeypatch):
    calls = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls['client'] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            calls['request'] = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"ok": true}'), finish_reason='stop',
            )])

    monkeypatch.setattr(config_module, 'OpenAI', FakeOpenAI)
    monkeypatch.setenv('SAM_RUNTIME_MODE', 'online')
    monkeypatch.delenv('OPENROUTER_REASONING_ENABLED', raising=False)
    generator = SimulationConfigGenerator(
        api_key='test-key', base_url='https://openrouter.ai/api/v1',
        model_name='deepseek/deepseek-v4-flash-0731',
    )
    assert generator._call_llm_with_retry('test', 'test') == {'ok': True}
    assert calls['client']['timeout'] == 120.0
    assert calls['client']['max_retries'] == 0
    assert calls['request']['extra_body'] == {'reasoning': {'enabled': False}}


def test_offline_config_request_keeps_existing_client_defaults(monkeypatch):
    calls = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls['client'] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            calls['request'] = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"ok": true}'), finish_reason='stop',
            )])

    monkeypatch.setattr(config_module, 'OpenAI', FakeOpenAI)
    monkeypatch.setenv('SAM_RUNTIME_MODE', 'offline')
    generator = SimulationConfigGenerator(
        api_key='sam-local', base_url='http://localhost:11434/v1', model_name='local-model',
    )
    assert generator._call_llm_with_retry('test', 'test') == {'ok': True}
    assert 'timeout' not in calls['client']
    assert 'max_retries' not in calls['client']
    assert 'extra_body' not in calls['request']


def test_slow_agent_timeout_does_not_block_next_agent(monkeypatch):
    from scripts import run_parallel_simulation as runner

    class FakeEnv:
        llm_semaphore = asyncio.Semaphore(1)

    class FakeAgent:
        def __init__(self, name, delay):
            self.name = name
            self.delay = delay

        async def perform_action_by_llm(self):
            await asyncio.sleep(self.delay)
            return self.name

    original_wait_for = asyncio.wait_for

    async def quick_wait_for(awaitable, timeout):
        return await original_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(runner.asyncio, "wait_for", quick_wait_for)
    logs = []
    env = FakeEnv()
    runner.install_bounded_llm_actions(env, "Reddit", logs.append)

    async def run_actions():
        return await asyncio.gather(
            env._perform_llm_action(FakeAgent("slow", 0.05)),
            env._perform_llm_action(FakeAgent("fast", 0)),
        )

    assert asyncio.run(run_actions()) == [None, "fast"]
    assert any("slow timed out" in message for message in logs)


def test_locked_database_keeps_run_state_and_actions_for_safe_retry(monkeypatch, tmp_path):
    from app.services.simulation_runner import SimulationRunner

    sim_dir = tmp_path / "sim_locked"
    (sim_dir / "reddit").mkdir(parents=True)
    database = sim_dir / "twitter_simulation.db"
    database.write_bytes(b"locked")
    run_state = sim_dir / "run_state.json"
    run_state.write_text("{}", encoding="utf-8")
    actions = sim_dir / "reddit" / "actions.jsonl"
    actions.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    real_remove = os.remove

    def locked_remove(path):
        if str(path) == str(database):
            raise PermissionError("database in use")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", locked_remove)
    result = SimulationRunner.cleanup_simulation_logs("sim_locked")

    assert result["success"] is False
    assert run_state.exists()
    assert actions.exists()
