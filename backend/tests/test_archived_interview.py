"""Archived individual interviews require saved evidence and preserve identity."""
import json
from types import SimpleNamespace

from app.services import archived_interview as interview
from app.services.simulation_runner import RunnerStatus, SimulationRunner


def test_archived_interview_uses_saved_persona_and_recent_actions(monkeypatch, tmp_path):
    directory = tmp_path / 'sim_archive'
    directory.mkdir()
    (directory / 'reddit_profiles.json').write_text(json.dumps([
        {'user_id': 7, 'name': 'Driver', 'persona': 'Concerned about fare costs'},
        {'user_id': 8, 'name': 'Student', 'persona': 'Likes electric buses'},
    ]), encoding='utf-8')
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationRunner, 'get_run_state', lambda _: SimpleNamespace(runner_status=RunnerStatus.COMPLETED))
    monkeypatch.setattr(SimulationRunner, 'get_all_actions', lambda *args, **kwargs: [SimpleNamespace(round_num=60, action_type='CREATE_POST', action_args={'content':'I need another route'})])
    calls = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            calls['options'] = kwargs

        def chat(self, messages, **kwargs):
            calls['messages'] = messages
            return 'Tôi cần tuyến xe thay thế.'

    monkeypatch.setattr(interview, 'LLMClient', FakeLLM)
    result = interview.interview_archived('sim_archive', 'reddit', 7, 'Bạn cần gì?')
    assert result['result']['archived'] is True
    assert result['result']['response'] == 'Tôi cần tuyến xe thay thế.'
    assert 'Concerned about fare costs' in calls['messages'][0]['content']
    assert 'I need another route' in calls['messages'][0]['content']
    assert 'Likes electric buses' not in calls['messages'][0]['content']
    assert calls['messages'][1]['content'] == 'Bạn cần gì?'


def test_archived_interview_rejects_incomplete_run(monkeypatch, tmp_path):
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(SimulationRunner, 'get_run_state', lambda _: SimpleNamespace(runner_status=RunnerStatus.RUNNING))
    assert interview.archived_available('sim_archive') is False
